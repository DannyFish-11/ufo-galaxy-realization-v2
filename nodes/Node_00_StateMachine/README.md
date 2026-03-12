# Node_00_StateMachine

分布式状态机与锁管理节点，提供分布式锁、节点注册、心跳管理功能。

## 端口
8000

## 环境变量
- `REDIS_URL`: Redis 连接 URL（可选，默认使用内存模式）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /lock/acquire` - 获取分布式锁
- `POST /lock/release` - 释放分布式锁
- `GET /locks` - 查看所有锁
- `POST /node/register` - 节点注册
- `POST /node/heartbeat/{node_id}` - 节点心跳
- `GET /nodes` - 查看所有节点
- `GET /state/{key}` - 获取状态
- `POST /state/{key}` - 设置状态
