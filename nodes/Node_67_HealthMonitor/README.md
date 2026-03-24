# Node_67_HealthMonitor

智能健康监控与自愈服务节点，实时检测系统和各节点的健康状态并触发自愈恢复。

## 端口
8067

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /system` - 系统健康总览
- `GET /nodes` - 所有节点健康状态
- `GET /nodes/{node_id}` - 指定节点健康状态
- `POST /check/{node_id}` - 主动检查指定节点
- `POST /recover` - 触发节点自愈
