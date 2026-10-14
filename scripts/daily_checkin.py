#!/usr/bin/env python3
"""每日签到聚合 — GitHub Actions 版，配置来自环境变量

v2 变更（2026-10-14）：
  * 库街区块：不再调用已失效的 /user/mineV2（该接口对所有 token 都回 220，
    无法用于判断 token 是否有效）；改为直接从 JWT 的 payload 里解出 userId。
  * 库街区块：补全官方文档要求的 App 端请求头，并在结果里回显 code/msg，
    出问题时一眼能看出是"token 失效(220)"还是"网络/风控(其它 code)"。
  * 库街区块：支持 KURO_DISTINCT_ID / KURO_DEVCODE /
    KURO_USER_ID / KURO_ROLE_ID 覆盖，缺省时随机生成或自动推断。
  * 新增 KURO_DRYRUN=true：只查询不签到，用于安全验证 token。
"""
import base64, json, os, sys, urllib.error, urllib.parse, urllib.request, uuid
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
KURO_DISTINCT_ID = os.getenv("KURO_DISTINCT_ID", "")
KURO_DEVCODE = os.getenv("KURO_DEVCODE", "")
KURO_USER_ID = os.getenv("KURO_USER_ID", "")
KURO_ROLE_ID = os.getenv("KURO_ROLE_ID", "")
KURO_DRYRUN = os.getenv("KURO_DRYRUN", "false").lower() == "true"

MC_SERVER_ID = "76402e5b20be2c39f095a152090afddc"
KURO_UA = ("Mozilla/5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.230804.001; wv) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.15 "
           "Mobile Safari/537.36 Kuro/2.2.0 KuroGameBox/2.2.0")


def http_post(url, data=None, is_json=False, timeout=20, headers=None):
    """POST 并返回响应文本。

    推送服务返回 4xx 时会抛 HTTPError，而它的响应体里通常带着有用的原因
    （例如 Server酱 的 {"code":40001,"info":"错误的Key"}）。这里把响应体读出来
    返回，保证调用方能看到"服务端原话"，也让脚本正常结束而不是崩掉。
    """
    if is_json:
        body = json.dumps(data).encode()
        h = {"Content-Type": "application/json"}
    else:
        body = urllib.parse.urlencode(data).encode() if data else b""
        h = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return "HTTP %s %s" % (e.code, e.read().decode("utf-8", "ignore")[:400])
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


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
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def jwt_user_id(token):
    """库街区 token 是 JWT，payload 里直接带 userId —— 比打已失效的 /user/mineV2 可靠"""
    try:
        seg = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        return str(payload.get("userId") or "")
    except Exception:
        return ""


def kuro_headers():
    """官方文档要求签到类接口使用类似 App/浏览器的完整请求头"""
    return {
        "token": KURO_TOKEN,
        "source": "android",
        "version": "2.2.0",
        "versionCode": "2200",
        "osVersion": "Android",
        "countryCode": "CN",
        "model": "23127PN0CC",
        "lang": "zh-Hans",
        "channelId": "2",
        "devCode": KURO_DEVCODE or "073A9EFAC18FC50616DD15808DAE719DBCB904B7",
        "distinct_id": KURO_DISTINCT_ID or str(uuid.uuid4()),
        "User-Agent": KURO_UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://web-static.kurobbs.com",
    }


def kuro_post(path, data, timeout=None):
    url = "https://api.kurobbs.com" + path
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=kuro_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


GAME_MAP = {"原神": "genshin", "星穹铁道": "starrail", "绝区零": "zzz", "崩坏3": "honkai3rd", "未定事件簿": "tot"}

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
                results.append(("米游社·" + name, "签到成功"))
            except genshin.errors.AlreadyClaimed:
                results.append(("米游社·" + name, "今日已签到"))
            except Exception as e:
                results.append(("米游社·" + name, f"ERROR: {e}"))
    except Exception as e:
        results.append(("米游社", f"初始化失败: {e}"))
else:
    results.append(("米游社", "未启用或缺少cookie"))

# --- 库街区（鸣潮） ---
if KURO_ENABLED and KURO_TOKEN:
    try:
        uid = KURO_USER_ID or jwt_user_id(KURO_TOKEN)
        if not uid:
            results.append(("库街区", "无法从 token 解析 userId（token 格式不对？）"))
            raise StopIteration

        # 角色列表（该接口不校验 token，仅用于拿 roleId）
        rid = KURO_ROLE_ID
        if not rid:
            roles = kuro_post("/gamer/role/default", {"queryUserId": uid})
            rl = (roles.get("data") or {}).get("defaultRoleList") or []
            role = next((r for r in rl if r.get("gameId") == 3), None)
            if not role:
                results.append(("库街区", f"未绑定鸣潮角色 (code={roles.get('code')})"))
                raise StopIteration
            rid = str(role.get("roleId", 0))

        sign_data = {"gameId": "3", "serverId": MC_SERVER_ID, "roleId": rid, "userId": uid}

        # 先查状态：这一步直接反映 token 是否被接受
        info = kuro_post("/encourage/signIn/initSignInV2", sign_data)
        if info.get("code") != 200:
            results.append(("库街区·鸣潮", f"token 不可用: code={info.get('code')} {info.get('msg')}"))
            raise StopIteration

        d = info.get("data") or {}
        goods_map = {}
        for c in d.get("signInGoodsConfigs") or []:
            gid = c.get("goodsId")
            if gid and str(gid) not in goods_map:
                goods_map[str(gid)] = c.get("goodsName", "")

        if KURO_DRYRUN:
            results.append(("库街区·鸣潮", f"[DRYRUN] token 有效，今天已签={d.get('isSigIn')}"))
            raise StopIteration

        if d.get("isSigIn"):
            results.append(("库街区·鸣潮", f"今日已签到（累计 {d.get('sigInNum')} 天）"))
            raise StopIteration

        js = kuro_post("/encourage/signIn/v2", sign_data)
        if js.get("success"):
            parts, img_url = [], ""
            for g in (js.get("data") or {}).get("todayList", []):
                gid = str(g.get("goodsId", ""))
                gname = goods_map.get(gid) or g.get("goodsName") or f"ID:{gid}"
                parts.append(f"+{g.get('goodsNum')} {gname}")
                if not img_url:
                    img_url = g.get("goodsUrl", "")
            results.append(("库街区·鸣潮", "签到成功 " + " ".join(parts), img_url))
        elif js.get("code") == 1511:
            results.append(("库街区·鸣潮", "今日已签到"))
        else:
            results.append(("库街区·鸣潮", f"签到失败: code={js.get('code')} {js.get('msg')}"))
    except StopIteration:
        pass
    except Exception as e:
        results.append(("库街区", f"ERROR: {type(e).__name__}: {e}"))
else:
    results.append(("库街区", "未启用或缺少token"))

# --- 战报 ---
today = date.today().strftime("%Y-%m-%d")
title = f"签到战报 · {today}"

lines = [f"📋 **每日签到战报 · {today}**", "", "| 项目 | 结果 |", "|------|------|"]
for item in results:
    lines.append(f"| {item[0]} | {item[1]} |")
lines.append("")

has_images = any(len(item) >= 3 and item[2] for item in results)
if has_images:
    lines.append("---")
    lines.append("### 🎁 签到物品")
    lines.append("")
    for item in results:
        if len(item) >= 3 and item[2]:
            lines.append(f"**{item[0]}**：{item[1]}")
            lines.append(f"![]({item[2]})")
            lines.append("")

lines.append("🔗 GitHub Actions 自动执行")
content = "\n".join(lines)
print(content)
resp = push(title, content)
print(f"[PUSH] -> {str(resp)[:300]}")

# 推送失败只告警，不让整个工作流变红：签到本身已经完成，不该被通知问题拖累
try:
    _js = json.loads(resp)
    _ok = (_js.get("code") == 0) or (_js.get("error") == "SUCCESS") or (_js.get("errno") == 0)
except Exception:
    _ok = not (str(resp).startswith("HTTP ") or str(resp).startswith("no push channel"))

if not _ok:
    print("")
    print("[WARN] 推送失败，但签到已完成，签到结果不受影响。")
    print("[WARN] 请检查推送凭据：")
    print("       · Server酱   -> SERVERCHAN_SENDKEY 是否为 https://sct.ftqq.com/ 上的有效 SendKey")
    print("       · PushPlus  -> PUSHPLUS_TOKEN")
    print("       · 企业微信   -> WECOM_WEBHOOK")
    print("[WARN] 服务端返回原文：" + str(resp)[:300])
