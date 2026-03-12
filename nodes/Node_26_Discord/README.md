# Node_26_Discord

Discord 集成服务节点，通过 Discord REST API v10 提供消息发送、频道管理等功能。

## 端口
8023

## 环境变量
- `DISCORD_BOT_TOKEN`: Discord Bot Token（大部分 API 必填）
- `DISCORD_DEFAULT_CHANNEL_ID`: 默认频道 ID
- `DISCORD_DEFAULT_GUILD_ID`: 默认服务器 ID

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /messages/send` - 发送消息
- `GET /messages/list` - 获取消息列表
- `POST /channels/info` - 获取频道信息
- `GET /guilds/list` - 列出服务器
- `POST /guilds/info` - 获取服务器信息
- `POST /reactions/add` - 添加表情反应
- `POST /webhooks/send` - 通过 Webhook 发送消息（无需 Token）
