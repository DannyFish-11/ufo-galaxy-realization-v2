# Node_08_Fetch

HTTP 请求服务节点，支持同步/异步 HTTP 请求、批量请求、代理等功能。

## 端口
8008

## 环境变量
- `FETCH_TIMEOUT`: 请求超时秒数（默认 30）
- `FETCH_MAX_REDIRECTS`: 最大重定向次数（默认 10）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /fetch` - 发送 HTTP 请求
- `POST /fetch/batch` - 批量 HTTP 请求
- `GET /fetch/ping?url=...` - 连通性检查
