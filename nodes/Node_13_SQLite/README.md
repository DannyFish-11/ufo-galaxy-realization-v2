# Node_13_SQLite

SQLite 数据库节点，提供轻量级本地数据库操作。

## 端口
8013

## 环境变量
- `SQLITE_DB_PATH`: 数据库文件路径（默认 ./galaxy.db）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /query` - 执行 SQL 查询
- `GET /tables` - 列出表
- `GET /schema/{table}` - 获取表结构
