# Node_23_Time

时间服务节点，提供时间查询、时区转换、定时器功能。

## 端口
8024

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /current` - 获取当前时间
- `POST /convert` - 时区转换
- `GET /timezones` - 列出时区
