# Node_83_NewsAggregator

新闻聚合服务节点，提供多来源新闻抓取、全文搜索与文章管理功能。

## 端口
8083

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /articles` - 获取新闻列表
- `POST /search` - 搜索新闻
- `GET /article/{article_id}` - 获取文章详情
