# Node_64_Telemetry

预测性遥测与异常检测服务节点，负责采集节点指标、检测异常并生成预测报告。

## 端口
8064

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /report` - 上报遥测数据
- `GET /metrics/{node_id}/{metric_type}` - 获取指标历史
- `GET /anomalies` - 获取异常列表
- `GET /predictions/{node_id}` - 获取预测结果
