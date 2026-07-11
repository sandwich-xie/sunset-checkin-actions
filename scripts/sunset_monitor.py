#!/usr/bin/env python3
# sunsetbot 火烧云监控 + 全量日报，通过环境变量配置，适配 GitHub Actions
import json, os, re, sys, urllib.parse, urllib.request
from datetime import datetime, date, timezone, timedelta

# --- 配置来自环境变量 ---
CITIES = os.getenv("SUNSET_CITIES", "长沙,衡阳").split(",")
THRESHOLD = float(os.getenv("SUNSET_THRESHOLD", "0.33"))
EVENT = os.getenv("SUNSET_EVENT", "set_1")
MODELS = os.getenv("SUNSET_MODELS", "GFS,EC").split(",")
PUSH_CHANNEL = os.getenv("PUSH_CHANNEL", "serverchan")
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")
TIMEOUT = int(os.getenv("TIMEOUT_SEC", "20"))
TZ_CST = timezone(timedelta(hours=8))

API_BASE = "https://sunsetbot.top/?intend=select_city&query_city={city}&event={event}&model={model}"

# --- 模型更新时间表（北京时间） ---
MODEL_SCHEDULE = {
    "GFS": ["07:30 (大更新)", "13:30 (小更新)", "19:30 (大更新)", "01:30 (小更新)"],
    "EC":  ["04:00", "10:00", "16:00", "22:00"],
}

def parse_float(s):
    if not s: return None
    m = re.search(r"([\d.]+)", str(s))
    return float(m.group(1)) if m else None

def level_label(q):
    if q is None: return "未知"
    for th, lb in [(0.05,"微微烧"),(0.2,"小烧"),(0.33,"中小烧"),(0.4,"中小烧偏上"),(0.6,"中等烧"),(0.8,"中大烧"),(1.0,"大烧(不完美)"),(1.5,"典型大烧"),(2.0,"优质大烧")]:
        if q < th: return lb
    return "世纪大烧"

def parse_model_ts(times_str):
    """解析 display_times_str 如 '2026071100z' → datetime (UTC)"""
    try:
        s = times_str.strip().rstrip("z").rstrip("Z")
        return datetime.strptime(s, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fmt_elapsed(times_str):
    """返回距模型时次的耗时描述，如 '2h ago'"""
    ts = parse_model_ts(times_str)
    if not ts: return ""
    delta = datetime.now(timezone.utc) - ts
    hours = int(delta.total_seconds() / 3600)
    mins = int((delta.total_seconds() % 3600) / 60)
    if hours >= 1:
        return f"（{hours}h{mins}m ago）"
    else:
        return f"（{mins}m ago）"

def query_city(city, event, model):
    url = API_BASE.format(city=urllib.parse.quote(city), event=event, model=model)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sunset-monitor/2.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "ok": return None
        return {"quality": parse_float(data.get("tb_quality")), "aod": parse_float(data.get("tb_aod")),
                "time": data.get("tb_event_time"),
                "model_ts": data.get("display_times_str", ""),
                "model_ts_name": data.get("display_times_name", ""),
                "raw": data}
    except Exception as e:
        print(f"[WARN] {city}/{model} failed: {e}", file=sys.stderr)
        return None

def query_all(event):
    out = {}
    for city in CITIES:
        md = {}
        for m in MODELS:
            rd = query_city(city, event, m)
            if rd: md[m] = rd
        if not md: out[city] = None; continue
        q = max(rv["quality"] for rv in md.values() if rv["quality"] is not None)
        aod = max((rv["aod"] for rv in md.values() if rv["aod"] is not None), default=None)
        t = next((rv["time"] for rv in md.values() if rv["time"]), None)
        out[city] = {"models": md, "quality": q, "aod": aod, "time": t}
    return out

def http_post(url, data=None, is_json=False, timeout=20):
    if is_json:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    else:
        body = urllib.parse.urlencode(data).encode() if data else b""
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")

def push(title, content):
    if PUSH_CHANNEL == "serverchan" and SERVERCHAN_SENDKEY:
        return http_post(f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send", {"title": title, "desp": content})
    elif PUSH_CHANNEL == "pushplus" and PUSHPLUS_TOKEN:
        return http_post(f"http://www.pushplus.plus/send?token={PUSHPLUS_TOKEN}&title={urllib.parse.quote(title)}&content={urllib.parse.quote(content)}&template=markdown")
    elif PUSH_CHANNEL == "wecom" and WECOM_WEBHOOK:
        return http_post(WECOM_WEBHOOK, {"msgtype": "markdown", "markdown": {"content": content}}, is_json=True)
    return "no push channel configured"

# --- 公用尾部：模型更新时差 + 更新时间表 ---
def build_footer(model_ts_map):
    """model_ts_map: {model: times_str}"""
    lines = [""]
    for m in MODELS:
        ts = model_ts_map.get(m, "")
        if ts:
            lines.append(f"⏱ {m} 数据时次 `{ts}` {fmt_elapsed(ts)}")
        else:
            lines.append(f"⏱ {m} 数据时次：查询失败")
    lines.append("")
    lines.append("---")
    lines.append("📡 **模型更新时间表（北京时间）**")
    for m in MODELS:
        if m in MODEL_SCHEDULE:
            lines.append(f"  **{m}**：{' · '.join(MODEL_SCHEDULE[m])}")
    lines.append("")
    lines.append("🔗 https://sunsetbot.top/")
    return "\n".join(lines)

# --- 公用：构建城市数据表 ---
def build_city_table(results):
    """results: {city: {model: {quality, aod, due}}} → Markdown 表格"""
    lines = []
    lines.append("| 城市 | 模型 | 鲜艳度 | 等级 | 气溶胶 | 状态 |")
    lines.append("|------|------|--------|------|--------|------|")
    for city in CITIES:
        r = results.get(city)
        if not r:
            lines.append(f"| {city} | — | — | — | — | 查询失败 |")
            continue
        first = True
        for m in MODELS:
            if m in r:
                d = r[m]
                q_s = f"{d['quality']:.3f}"
                lbl = level_label(d["quality"])
                aod_s = f"{d['aod']:.2f}" if isinstance(d['aod'],(int,float)) else "—"
                status = "🔥 达标" if d["due"] else "—"
                city_col = f"**{city}**" if first else ""
                lines.append(f"| {city_col} | {m} | {q_s} | {lbl} | {aod_s} | {status} |")
                first = False
            else:
                city_col = f"**{city}**" if first else ""
                lines.append(f"| {city_col} | {m} | — | — | — | 查询失败 |")
                first = False
    return "\n".join(lines)

# --- digest mode ---
EVENT_LABELS = {"set_1":"🌅 今日日落","set_2":"🌇 明日日落","rise_1":"🌄 今日日出","rise_2":"🌅 明日日出"}

def run_digest():
    today = date.today().strftime("%Y-%m-%d")
    events = os.getenv("DIGEST_EVENTS", "set_1,set_2").split(",")
    sections = []
    model_ts_map = {}
    for ev in events:
        data = query_all(ev)
        rows = []
        for city, r in data.items():
            if not r: rows.append(f"| {city} | - | - | - | - | - | 查询失败 |"); continue
            gfs = r["models"].get("GFS",{}).get("quality"); ec = r["models"].get("EC",{}).get("quality")
            gfs_s = f"{gfs:.2f}" if isinstance(gfs,(int,float)) else "-"
            ec_s = f"{ec:.2f}" if isinstance(ec,(int,float)) else "-"
            q_s = f"{r['quality']:.2f}"; aod_s = f"{r['aod']:.2f}" if isinstance(r['aod'],(int,float)) else "-"
            t_s = (r['time'].split(" ")[-1][:5]) if r['time'] else "-"
            rows.append(f"| {city} | {gfs_s} | {ec_s} | {q_s} | {aod_s} | {t_s} | {level_label(r['quality'])} |")
            for m in MODELS:
                if m in r["models"] and m not in model_ts_map:
                    model_ts_map[m] = r["models"][m].get("model_ts", "")
        table = (f"### {EVENT_LABELS.get(ev,ev)}\n\n"
                 "| 城市 | GFS | EC | 综合 | 气溶胶 | 日落 | 等级 |\n"
                 "|------|-----|-----|------|--------|------|------|\n" + "\n".join(rows))
        sections.append(table)
    content = f"📊 **火烧云全量数据 · {today}**\n\n> 每日 10:00 / 15:00 定时推送（数据留痕，不受阈值限制）\n\n" + "\n\n".join(sections)
    content += build_footer(model_ts_map)
    title = f"📊 火烧云日报 · {today}"
    print(content)
    resp = push(title, content)
    print(f"[PUSH] {title} -> {resp[:200]}")

# --- monitor mode（每次必推） ---
def run_monitor():
    today = date.today().strftime("%Y-%m-%d")
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = {}; any_due = False; model_ts_map = {}
    for city in CITIES:
        md = {}
        for m in MODELS:
            rd = query_city(city, EVENT, m)
            if rd:
                md[m] = rd
                if m not in model_ts_map:
                    model_ts_map[m] = rd.get("model_ts", "")
        if not md: continue
        results[city] = {}
        for m, rd in md.items():
            due = rd["quality"] >= THRESHOLD
            if due: any_due = True
            results[city][m] = {"quality": rd["quality"], "aod": rd["aod"], "due": due}
    title = f"📡 火烧云实时数据 · {today}"
    lines = [f"📍 **{today} 晚霞火烧云实时查询**", "", f"阈值：鲜艳度 ≥ {THRESHOLD}（{level_label(THRESHOLD)}）", ""]
    lines.append(build_city_table(results))
    lines.append(build_footer(model_ts_map))
    content = "\n".join(lines)
    print(content)
    resp = push(title, content)
    print(f"[PUSH] {title} -> {resp[:200]}")
    # 写日志
    log_entry = {"ts": ts_str, "alert": any_due}
    for city, r in results.items():
        log_entry[city] = {}
        for m in MODELS:
            if m in r: log_entry[city][m] = round(r[m]["quality"], 3)
    with open(os.path.join(os.path.dirname(__file__), "sunset_monitor.log"), "a") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False)+"\n")

# --- force mode ---
def run_force():
    today = date.today().strftime("%Y-%m-%d")
    results = {}; any_due = False; model_ts_map = {}
    for city in CITIES:
        md = {}
        for m in MODELS:
            rd = query_city(city, EVENT, m)
            if rd:
                md[m] = rd
                if m not in model_ts_map:
                    model_ts_map[m] = rd.get("model_ts", "")
        if not md: continue
        results[city] = {}
        for m, rd in md.items():
            due = rd["quality"] >= THRESHOLD
            if due: any_due = True
            results[city][m] = {"quality": rd["quality"], "aod": rd["aod"], "due": due}
    title = f"📡 火烧云实时数据 · {today}"
    lines = [f"📍 **{today} 晚霞火烧云实时查询**", "", f"阈值：鲜艳度 ≥ {THRESHOLD}（{level_label(THRESHOLD)}）", ""]
    lines.append(build_city_table(results))
    lines.append(build_footer(model_ts_map))
    content = "\n".join(lines)
    print(content)
    resp = push(title, content)
    print(f"[PUSH] {title} -> {resp[:200]}")

if __name__ == "__main__":
    if "--digest" in sys.argv:
        run_digest()
    elif "--force" in sys.argv:
        run_force()
    else:
        run_monitor()
