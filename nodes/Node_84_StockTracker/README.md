# Node_84_StockTracker

股票追踪服务节点，提供实时行情查询、历史数据获取与技术指标计算。

## 端口
8084

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /quote/{symbol}` - 获取实时报价
- `GET /historical/{symbol}` - 获取历史行情
- `GET /indicators/{symbol}` - 获取技术指标
