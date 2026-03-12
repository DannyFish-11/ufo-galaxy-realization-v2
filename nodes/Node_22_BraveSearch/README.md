# Node_22_BraveSearch

Brave 搜索引擎集成节点。

## 端口
8022

## 环境变量
- `BRAVE_API_KEY`: Brave Search API Key（必填）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /search` - 搜索查询
- `POST /search/news` - 新闻搜索
- `POST /search/images` - 图片搜索
