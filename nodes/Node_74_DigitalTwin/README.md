# Node_74_DigitalTwin

数字孪生服务节点，维护系统实体的数字镜像，支持状态更新、历史查询与仿真。

## 端口
8074

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /twin` - 获取数字孪生当前状态
- `POST /twin/update` - 更新孪生状态
- `GET /twin/history` - 查询孪生历史
- `POST /twin/simulate` - 执行仿真推演
