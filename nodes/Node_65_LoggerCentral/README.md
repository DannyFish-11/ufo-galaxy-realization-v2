# Node_65_LoggerCentral

集中式审计与取证日志服务节点，提供结构化日志记录、查询与完整性验证。

## 端口
8065

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /log` - 写入日志
- `POST /query` - 查询日志
- `GET /recent` - 获取最近日志
- `GET /stats` - 日志统计信息
- `GET /verify/{log_id}` - 验证日志完整性
