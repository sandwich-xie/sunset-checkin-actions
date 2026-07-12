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

results = []  # 每条: (平台, 结果) 或 (平台, 结果, 图片URL)

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

# --- 库街区（鸣潮） ---
if KURO_ENABLED and KURO_TOKEN:
    try:
        headers = {
            "token": KURO_TOKEN,
            "source": "android",
            "User-Agent": "Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.15 Mobile Safari/537.36 Kuro/2.2.0 KuroGameBox/2.2.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "devcode": "2fba3859fe9bfe9099f2696b8648c2c6",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://web-static.kurobbs.com",
        }

        # Step 1: 获取 userId
        req = urllib.request.Request("https://api.kurobbs.com/user/mineV2",
                                     data=urllib.parse.urlencode({"type":"1"}).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            mine = json.loads(resp.read())
        uid = (mine.get("data") or {}).get("mine", {}).get("userId")
        if not uid:
            results.append(("库街区", f"获取userId失败: {mine.get('msg')}"))
        else:
            # Step 2: 获取角色列表，找鸣潮 gameId=3
            req2 = urllib.request.Request("https://api.kurobbs.com/gamer/role/default",
                                          data=urllib.parse.urlencode({"queryUserId":str(uid)}).encode(),
                                          headers=headers, method="POST")
            with urllib.request.urlopen(req2, timeout=TIMEOUT) as resp:
                roles = json.loads(resp.read())
            rl = (roles.get("data") or {}).get("defaultRoleList") or []
            role = next((r for r in rl if r.get("gameId") == 3), None)
            if not role:
                results.append(("库街区", "未绑定鸣潮角色"))
            else:
                MC_SERVER_ID = "76402e5b20be2c39f095a152090afddc"
                rid = str(role.get("roleId", 0))

                # Step 3: 获取签到物品映射表（goodsId → goodsName）
                goods_map = {}
                try:
                    info_data = urllib.parse.urlencode({
                        "gameId": "3", "serverId": MC_SERVER_ID,
                        "roleId": rid, "userId": str(uid),
                    }).encode()
                    req_info = urllib.request.Request("https://api.kurobbs.com/encourage/signIn/initSignInV2",
                                                      data=info_data, headers=headers, method="POST")
                    with urllib.request.urlopen(req_info, timeout=TIMEOUT) as resp:
                        info_js = json.loads(resp.read())
                    for c in (info_js.get("data") or {}).get("signInGoodsConfigs", []):
                        gid = c.get("goodsId")
                        if gid and gid not in goods_map:
                            goods_map[str(gid)] = c.get("goodsName", "")
                except Exception:
                    pass  # 映射表获取失败不影响签到

                # Step 4: 鸣潮签到 V2
                sd = urllib.parse.urlencode({
                    "gameId": "3", "serverId": MC_SERVER_ID,
                    "roleId": rid, "userId": str(uid),
                    "reqMonth": datetime.now().strftime("%m"),
                }).encode()
                req3 = urllib.request.Request("https://api.kurobbs.com/encourage/signIn/v2",
                                              data=sd, headers=headers, method="POST")
                with urllib.request.urlopen(req3, timeout=TIMEOUT) as resp:
                    js = json.loads(resp.read())
                if js.get("success"):
                    goods_list = (js.get("data") or {}).get("todayList", [])
                    # 汇总物品描述
                    parts = []
                    img_url = ""
                    for g in goods_list:
                        gid = str(g.get("goodsId", ""))
                        gnum = g.get("goodsNum", "")
                        gname = goods_map.get(gid) or g.get("goodsName") or f"ID:{gid}"
                        parts.append(f"+{gnum} {gname}")
                        if not img_url:
                            img_url = g.get("goodsUrl", "")
                    desc = "签到成功 " + " ".join(parts)
                    results.append(("库街区·鸣潮", desc, img_url))
                else:
                    msg = js.get("msg", "失败")
                    if js.get("code") == 1511:
                        results.append(("库街区·鸣潮", "今日已签到"))
                    else:
                        results.append(("库街区·鸣潮", msg))
    except Exception as e:
        results.append(("库街区", f"ERROR: {e}"))
else:
    results.append(("库街区", "未启用或缺少token"))

# --- 战报 ---
today = date.today().strftime("%Y-%m-%d")
title = f"签到战报 · {today}"

# Markdown 表格
lines = [f"📋 **每日签到战报 · {today}**", "", "| 项目 | 结果 |", "|------|------|"]
for item in results:
    name = item[0]
    msg = item[1]
    lines.append(f"| {name} | {msg} |")
lines.append("")

# HTML 图片展示（仅对有图片的项）
has_images = any(len(item) >= 3 and item[2] for item in results)
if has_images:
    lines.append("---")
    lines.append("### 🎁 签到物品")
    lines.append("")
    for item in results:
        if len(item) >= 3 and item[2]:
            name = item[0]
            msg = item[1]
            img_url = item[2]
            lines.append(f"**{name}**：{msg}")
            lines.append(f"![]({img_url})")
            lines.append("")

lines.append("🔗 GitHub Actions 自动执行")
content = "\n".join(lines)
print(content)
resp = push(title, content)
print(f"[PUSH] -> {resp[:200]}")
