# Node_24_Weather

天气服务节点，提供实时天气查询、预报功能。

## 端口
8025

## 环境变量
- `WEATHER_API_KEY`: OpenWeatherMap API Key（必填）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /current` - 查询当前天气
- `POST /forecast` - 天气预报
