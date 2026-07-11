#!/usr/bin/env python3
# sunsetbot 火烧云监控 + 全量日报，通过环境变量配置，适配 GitHub Actions
import json, os, re, sys, urllib.parse, urllib.request
from datetime import datetime, date

# --- 配置来自环境变量 ---
CITIES = os.getenv("SUNSET_CITIES", "长沙,衡阳").split(",")
THRESHOLD = float(os.getenv("SUNSET_THRESHOLD", "0.4"))
REALERT_DELTA = float(os.getenv("SUNSET_REALERT_DELTA", "0.3"))
EVENT = os.getenv("SUNSET_EVENT", "set_1")
MODELS = os.getenv("SUNSET_MODELS", "GFS,EC").split(",")
PUSH_CHANNEL = os.getenv("PUSH_CHANNEL", "serverchan")
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")
TIMEOUT = int(os.getenv("TIMEOUT_SEC", "20"))

API_BASE = "https://sunsetbot.top/?intend=select_city&query_city={city}&event={event}&model={model}"

def parse_float(s):
    if not s: return None
    m = re.search(r"([\d.]+)", str(s))
    return float(m.group(1)) if m else None

def level_label(q):
    if q is None: return "未知"
    for th, lb in [(0.05,"微微烧"),(0.2,"小烧"),(0.4,"中小烧"),(0.6,"中等烧"),(0.8,"中大烧"),(1.0,"大烧(不完美)"),(1.5,"典型大烧"),(2.0,"优质大烧")]:
        if q < th: return lb
    return "世纪大烧"

def query_city(city, event, model):
    url = API_BASE.format(city=urllib.parse.quote(city), event=event, model=model)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sunset-monitor/2.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "ok": return None
        return {"quality": parse_float(data.get("tb_quality")), "aod": parse_float(data.get("tb_aod")),
                "time": data.get("tb_event_time"), "raw": data}
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

def load_state():
    p = os.path.join(os.path.dirname(__file__), ".sunset_state.json")
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return {}

def save_state(st):
    with open(os.path.join(os.path.dirname(__file__), ".sunset_state.json"), "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

# --- digest mode ---
EVENT_LABELS = {"set_1":"🌅 今日日落","set_2":"🌇 明日日落","rise_1":"🌄 今日日出","rise_2":"🌅 明日日出"}

def run_digest():
    today = date.today().strftime("%Y-%m-%d")
    events = os.getenv("DIGEST_EVENTS", "set_1,set_2").split(",")
    sections = []
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
        table = (f"### {EVENT_LABELS.get(ev,ev)}\n\n"
                 "| 城市 | GFS | EC | 综合 | 气溶胶 | 日落 | 等级 |\n"
                 "|------|-----|-----|------|--------|------|------|\n" + "\n".join(rows))
        sections.append(table)
    content = f"📊 **火烧云全量数据 · {today}**\n\n> 每日 10:00 / 15:00 定时推送（数据留痕，不受阈值限制）\n\n" + "\n\n".join(sections) + "\n\n🔗 https://sunsetbot.top/"
    title = f"📊 火烧云日报 · {today}"
    print(content)
    resp = push(title, content)
    print(f"[PUSH] {title} -> {resp[:200]}")

# --- monitor mode ---
def run_monitor():
    today = date.today().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state = load_state()
    results = {}; due = []
    for city in CITIES:
        md = {}
        for m in MODELS:
            rd = query_city(city, EVENT, m)
            if rd: md[m] = rd
        if not md: continue
        q = max(rv["quality"] for rv in md.values() if rv["quality"] is not None)
        aod = max((rv["aod"] for rv in md.values() if rv["aod"] is not None), default=None)
        t = next((rv["time"] for rv in md.values() if rv["time"]), None)
        results[city] = {"quality": q, "aod": aod, "time": t, "models": md}
        key = f"{city}|{EVENT}"
        st = state.get(key, {})
        notified = (st.get("date") == today) and st.get("notified", False)
        nq = st.get("notified_quality", 0.0)
        is_due = False
        if q >= THRESHOLD:
            if not notified: is_due = True
            elif REALERT_DELTA > 0 and (q - nq) >= REALERT_DELTA: is_due = True
        if is_due: due.append(city)
        state[key] = {"date": today, "notified": notified or is_due,
                       "notified_quality": nq if (notified and not is_due) else q, "last_quality": q}
    save_state(state)
    if due:
        top = max(due, key=lambda c: results[c]["quality"])
        title = f"🔥 火烧云提醒 · {top} {results[top]['quality']:.2f}"
        lines = [f"📍 **{today} 晚霞火烧云预报**", "", f"阈值：鲜艳度 ≥ {THRESHOLD}（{level_label(THRESHOLD)}）", ""]
        for city, r in results.items():
            lbl = level_label(r["quality"])
            md_s = " / ".join(f"{m} {rv['quality']:.2f}" for m, rv in r["models"].items())
            prefix = "🔥" if city in due else "🌆"
            lines.append(f"{prefix} **{city}** {lbl}：{r['quality']:.2f}（{md_s}）｜气溶胶 {r['aod']:.2f}｜日落 {r['time']}")
        lines.append(""); lines.append("🔗 https://sunsetbot.top/")
        content = "\n".join(lines)
        print(content)
        resp = push(title, content)
        print(f"[PUSH] {title} -> {resp[:200]}")
    else:
        print(f"[{ts}] OK — 无达标城市")
    # 写日志
    with open(os.path.join(os.path.dirname(__file__), "sunset_monitor.log"), "a") as f:
        f.write(json.dumps({"ts": ts, "alert": bool(due), "qualities": {c:round(r["quality"],3) for c,r in results.items()}}, ensure_ascii=False)+"\n")

if __name__ == "__main__":
    if "--digest" in sys.argv:
        run_digest()
    else:
        run_monitor()
