# 火烧云监控 + 每日签到

GitHub Actions 自动化：

- **火烧云监控**：每 30 分钟查 sunsetbot 长沙/衡阳日落鲜艳度，≥0.4 推微信
- **火烧云日报**：每天 10:00 / 15:00 (CST) 全量数据推送
- **每日签到**：每天 8:30 (CST) 米游社原神签到

## Secrets 配置

| Secret | 说明 |
|--------|------|
| `SERVERCHAN_SENDKEY` | Server酱 SendKey |
| `MIYO_COOKIE` | 米游社完整 Cookie |
| `KURO_TOKEN` | 库街区 user_token |

## Variables 配置

| Variable | 默认值 | 说明 |
|----------|--------|------|
| `SUNSET_CITIES` | 长沙,衡阳 | 监控城市 |
| `SUNSET_THRESHOLD` | 0.4 | 鲜艳度阈值 |
| `MIYO_ENABLED` | true | 启用米游社签到 |
| `MIYO_GAMES` | 原神 | 签到游戏 |
| `KURO_ENABLED` | false | 启用库街区签到 |
