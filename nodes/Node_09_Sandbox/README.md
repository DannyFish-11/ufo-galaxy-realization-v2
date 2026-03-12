# Node_09_Sandbox

沙箱执行环境节点，提供安全的代码执行环境。

## 端口
8009

## 环境变量
- `SANDBOX_TIMEOUT`: 执行超时秒数（默认 30）
- `SANDBOX_MAX_MEMORY`: 最大内存（默认 256MB）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /execute` - 执行代码
- `GET /sandboxes` - 列出沙箱
