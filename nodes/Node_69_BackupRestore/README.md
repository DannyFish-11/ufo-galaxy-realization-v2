# Node_69_BackupRestore

备份与灾难恢复服务节点，提供数据备份、恢复及完整性验证功能。

## 端口
8069

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /backup` - 创建备份
- `POST /restore` - 恢复备份
- `GET /backups` - 列出所有备份
- `GET /backups/{backup_id}` - 获取备份详情
- `GET /verify/{backup_id}` - 验证备份完整性
