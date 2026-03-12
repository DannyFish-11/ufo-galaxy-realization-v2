# Node_10_Slack

Slack 集成服务节点，提供消息发送、频道管理、用户查询等功能。

## 端口
8010

## 环境变量
- `SLACK_BOT_TOKEN`: Slack Bot OAuth Token（必填，格式 xoxb-...）
- `SLACK_DEFAULT_CHANNEL`: 默认频道（默认 #general）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /messages/send` - 发送消息
- `GET /messages/history` - 获取频道历史
- `POST /channels/create` - 创建频道
- `GET /channels/list` - 列出频道
- `POST /users/info` - 获取用户信息
- `POST /reactions/add` - 添加表情反应
