#!/usr/bin/env python3
"""每日签到聚合 — GitHub Actions 版，配置来自环境变量"""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime, date

SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")
PUSH_CHANNEL = os.getenv("PUSH_CHANNEL", "serverchan")
TIMEOUT = int(os.getenv("TIMEOUT_SEC", "20"))
MIYO_COOKIE = os.getenv("MIYO_COOKIE", "")
MIYO_ENABLED = os.getenv("MIYO_ENABLED", "false").lower() == "true"
MIYO_GAMES = os.getenv("MIYO_GAMES", "原神").split(",")
KURO_TOKEN = os.getenv("KURO_TOKEN", "")
KURO_ENABLED = os.getenv("KURO_ENABLED", "false").lower() == "true"

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
    return "no push channel"

def parse_cookie(s):
    d = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part: k, v = part.split("=", 1); d[k.strip()] = v.strip()
    return d

GAME_MAP = {"原神":"genshin","星穹铁道":"starrail","绝区零":"zzz","崩坏3":"honkai3rd","未定事件簿":"tot"}

results = []

# --- 米游社 ---
if MIYO_ENABLED and MIYO_COOKIE:
    try:
        import asyncio, genshin
        client = genshin.Client(region=genshin.Region.CHINESE)
        client.set_cookies(cookies=parse_cookie(MIYO_COOKIE))
        for name in MIYO_GAMES:
            game = getattr(genshin.Game, GAME_MAP.get(name, "genshin").upper(), genshin.Game.GENSHIN)
            try:
                asyncio.run(client.claim_daily_reward(game=game))
                results.append(("米游社·"+name, "签到成功"))
            except genshin.errors.AlreadyClaimed:
                results.append(("米游社·"+name, "今日已签到"))
            except Exception as e:
                results.append(("米游社·"+name, f"ERROR: {e}"))
    except Exception as e:
        results.append(("米游社", f"初始化失败: {e}"))
else:
    results.append(("米游社", "未启用或缺少cookie"))

# --- 库街区 ---
if KURO_ENABLED and KURO_TOKEN:
    try:
        headers = {"token": KURO_TOKEN, "osversion": "Android", "devcode": "2fba3859fe9bfe9099f2696b8648c2c6",
                   "countrycode": "CN", "ip": "10.0.2.233", "model": "2211133C", "source": "android",
                   "lang": "zh-Hans", "version": "1.0.9",
                   "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        req = urllib.request.Request("https://api.kurobbs.com/user/mineV2",
                                     data=urllib.parse.urlencode({"type":"1"}).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            mine = json.loads(resp.read())
        uid = (mine.get("data") or {}).get("mine", {}).get("userId")
        if not uid:
            results.append(("库街区", f"获取userId失败: {mine.get('msg')}"))
        else:
            req2 = urllib.request.Request("https://api.kurobbs.com/gamer/role/default",
                                          data=urllib.parse.urlencode({"queryUserId":str(uid)}).encode(),
                                          headers=headers, method="POST")
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp:
                roles = json.loads(resp.read())
            rl = (roles.get("data") or {}).get("defaultRoleList") or []
            role = next((r for r in rl if r.get("gameId")==1), rl[0] if rl else None)
            if not role:
                results.append(("库街区", "无默认角色"))
            else:
                # 社区签到
                sd = urllib.parse.urlencode({"gameId":str(role.get("gameId",1)),"serverId":str(role.get("serverId","")),
                     "roleId":str(role.get("roleId",0)),"userId":str(role.get("userId",uid)),
                     "reqMonth":datetime.now().strftime("%m")}).encode()
                req3 = urllib.request.Request("https://api.kurobbs.com/encourage/signIn/v2", data=sd, headers=headers, method="POST")
                with urllib.request.urlopen(req3, timeout=TIMEOUT) as resp:
                    js = json.loads(resp.read())
                results.append(("库街区·社区", "成功" if js.get("success") else js.get("msg","失败")))
                # 游戏签到
                gd = urllib.parse.urlencode({"gameId":str(role.get("gameId",1))}).encode()
                req4 = urllib.request.Request("https://api.kurobbs.com/user/signIn", data=gd, headers=headers, method="POST")
                with urllib.request.urlopen(req4, timeout=TIMEOUT) as resp:
                    js2 = json.loads(resp.read())
                results.append(("库街区·鸣潮", "成功" if js2.get("success") else js2.get("msg","失败")))
    except Exception as e:
        results.append(("库街区", f"ERROR: {e}"))
else:
    results.append(("库街区", "未启用或缺少token"))

# --- 战报 ---
today = date.today().strftime("%Y-%m-%d")
lines = [f"📋 **每日签到战报 · {today}**", "", "| 项目 | 结果 |", "|------|------|"]
for n, m in results: lines.append(f"| {n} | {m} |")
lines.append(""); lines.append("🔗 GitHub Actions 自动执行")
content = "\n".join(lines)
title = f"签到战报 · {today}"
print(content)
resp = push(title, content)
print(f"[PUSH] -> {resp[:200]}")
