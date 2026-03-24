# Node_123_Calendar

日历服务节点，提供事件创建、查询、更新、删除与提醒管理功能。

## 端口
8123

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /events` - 创建日历事件
- `GET /events` - 获取事件列表
- `GET /events/{event_id}` - 获取事件详情
- `PUT /events/{event_id}` - 更新事件
- `DELETE /events/{event_id}` - 删除事件
