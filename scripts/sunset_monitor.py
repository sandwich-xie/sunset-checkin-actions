#!/usr/bin/env python3
# sunsetbot 火烧云监控，通过环境变量配置，适配 GitHub Actions
import json, os, re, sys, urllib.parse, urllib.request
from datetime import datetime, date, timezone, timedelta

CITIES = os.getenv("SUNSET_CITIES", "长沙,衡阳").split(",")
THRESHOLD = float(os.getenv("SUNSET_THRESHOLD", "0.33"))
MODELS = os.getenv("SUNSET_MODELS", "GFS,EC").split(",")
PUSH_CHANNEL = os.getenv("PUSH_CHANNEL", "serverchan")
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")
TIMEOUT = int(os.getenv("TIMEOUT_SEC", "20"))
TZ_CST = timezone(timedelta(hours=8))

API_BASE = "https://sunsetbot.top/?intend=select_city&query_city={city}&event={event}&model={model}"

MODEL_SCHEDULE = {
    "GFS": ["07:30 (大更新)", "13:30 (小更新)", "19:30 (大更新)", "01:30 (小更新)"],
    "EC":  ["04:00", "10:00", "16:00", "22:00"],
}

EVENT_LABELS = {"set_1": "今日日落", "set_2": "明日日落"}

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
    try:
        s = times_str.strip().rstrip("z").rstrip("Z")
        return datetime.strptime(s, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fmt_elapsed(times_str):
    ts = parse_model_ts(times_str)
    if not ts: return ""
    delta = datetime.now(timezone.utc) - ts
    hours = int(delta.total_seconds() / 3600)
    mins = int((delta.total_seconds() % 3600) / 60)
    return f"{hours}h{mins}m ago" if hours >= 1 else f"{mins}m ago"

def extract_time_hhmm(s):
    """从字符串提取 HH:MM 时间"""
    if not s: return ""
    m = re.search(r"(\d{1,2}:\d{2})", str(s))
    return m.group(1) if m else ""

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

def query_city(city, event, model):
    url = API_BASE.format(city=urllib.parse.quote(city), event=event, model=model)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sunset-monitor/3.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "ok": return None
        # display_event_date_str = 日落开始时刻, tb_event_time = 日落结束时刻
        start = extract_time_hhmm(data.get("display_event_date_str", ""))
        end = extract_time_hhmm(data.get("tb_event_time", ""))
        return {
            "quality": parse_float(data.get("tb_quality")),
            "aod": parse_float(data.get("tb_aod")),
            "sunset_start": start,
            "sunset_end": end,
            "model_ts": data.get("display_times_str", ""),
            "model_ts_name": data.get("display_times_name", ""),
            "event_date": data.get("display_event_date_str", ""),
        }
    except Exception as e:
        print(f"[WARN] {city}/{model}/{event} failed: {e}", file=sys.stderr)
        return None

def build_footer(model_ts_map):
    lines = [""]
    for m in MODELS:
        ts = model_ts_map.get(m, "")
        if ts:
            lines.append(f"⏱ {m} 数据时次 `{ts}`（{fmt_elapsed(ts)}）")
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

def build_event_section(event, all_results):
    """构建某个 event 的完整 section：日落时间段 + 数据表"""
    label = EVENT_LABELS.get(event, event)
    lines = [f"### 🌅 {label}", ""]

    # 提取日落时间段（同一城市不同模型时间相同，取第一个即可）
    sunset_times = {}
    for city in CITIES:
        r = all_results.get(event, {}).get(city)
        if not r: continue
        for m in MODELS:
            if m in r:
                s = r[m].get("sunset_start", "")
                e = r[m].get("sunset_end", "")
                if s and e:
                    sunset_times[city] = f"{s} → {e}"
                break  # 只取第一个模型的即可

    if sunset_times:
        parts = []
        for city in CITIES:
            if city in sunset_times:
                parts.append(f"**{city}** {sunset_times[city]}")
        lines.append("🕐 " + "　|　".join(parts))
        lines.append("")

    # 数据表
    lines.append("| 城市 | 模型 | 鲜艳度 | 等级 | 气溶胶 | 状态 |")
    lines.append("|------|------|--------|------|--------|------|")

    for city in CITIES:
        r = all_results.get(event, {}).get(city)
        if not r:
            lines.append(f"| {city} | — | — | — | — | 查询失败 |")
            continue
        first = True
        for m in MODELS:
            if m in r:
                d = r[m]
                q_s = f"{d['quality']:.3f}" if d["quality"] is not None else "—"
                lbl = level_label(d["quality"])
                aod_s = f"{d['aod']:.2f}" if isinstance(d["aod"], (int, float)) else "—"
                status = "🔥 达标" if d.get("due") else "—"
                city_col = f"**{city}**" if first else ""
                lines.append(f"| {city_col} | {m} | {q_s} | {lbl} | {aod_s} | {status} |")
                first = False
            else:
                city_col = f"**{city}**" if first else ""
                lines.append(f"| {city_col} | {m} | — | — | — | 查询失败 |")
                first = False
    return "\n".join(lines)

def run_monitor():
    today = date.today().strftime("%Y-%m-%d")
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    events = ["set_1", "set_2"]
    all_results = {}
    model_ts_map = {}
    any_due = False

    for ev in events:
        all_results[ev] = {}
        for city in CITIES:
            md = {}
            for m in MODELS:
                rd = query_city(city, ev, m)
                if rd:
                    md[m] = rd
                    if m not in model_ts_map:
                        model_ts_map[m] = rd.get("model_ts", "")
            if not md:
                all_results[ev][city] = None
                continue
            all_results[ev][city] = {}
            for m, rd in md.items():
                due = (rd["quality"] or 0) >= THRESHOLD
                if due: any_due = True
                all_results[ev][city][m] = {
                    "quality": rd["quality"],
                    "aod": rd["aod"],
                    "sunset_start": rd["sunset_start"],
                    "sunset_end": rd["sunset_end"],
                    "due": due,
                }

    title = f"📡 火烧云 · {today}"
    lines = [
        f"📍 **{today} 晚霞火烧云实时查询**",
        "",
        f"> 阈值：鲜艳度 ≥ {THRESHOLD}（{level_label(THRESHOLD)}）",
        f"> 查询时间：{ts_str}",
        "",
    ]

    for ev in events:
        lines.append(build_event_section(ev, all_results))
        lines.append("")

    lines.append(build_footer(model_ts_map))
    content = "\n".join(lines)
    print(content)
    resp = push(title, content)
    print(f"[PUSH] {title} -> {resp[:200]}")

    log_entry = {"ts": ts_str, "alert": any_due}
    with open(os.path.join(os.path.dirname(__file__), "sunset_monitor.log"), "a") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    run_monitor()
