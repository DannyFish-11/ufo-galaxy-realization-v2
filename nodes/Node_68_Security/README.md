# Node_68_Security

安全策略执行服务节点，提供访问控制检查、安全事件记录与规则管理。

## 端口
8068

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /check` - 安全策略检查
- `GET /events` - 获取安全事件列表
- `GET /rules` - 获取当前安全规则
