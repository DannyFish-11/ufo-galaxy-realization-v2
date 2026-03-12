# Node_12_Postgres

PostgreSQL 数据库节点，提供连接池管理、SQL 查询、事务执行等功能。

## 端口
8012

## 环境变量
- `POSTGRES_HOST`: 主机（默认 localhost）
- `POSTGRES_PORT`: 端口（默认 5432）
- `POSTGRES_USER`: 用户名（默认 postgres）
- `POSTGRES_PASSWORD`: 密码（必填）
- `POSTGRES_DATABASE`: 数据库名（默认 postgres）
- `POSTGRES_POOL_SIZE`: 连接池大小（默认 10）

## 依赖
需要安装 `asyncpg`：`pip install asyncpg`

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /query` - 执行 SQL 查询
- `POST /transaction` - 执行事务（多条语句）
- `GET /tables` - 列出所有表
- `GET /schema/{table_name}` - 获取表结构
- `GET /stats/{table_name}` - 获取表统计信息
