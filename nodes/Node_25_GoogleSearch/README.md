# Node_25_GoogleSearch

Google 搜索集成节点，支持 Google Custom Search API 和 googlesearch-python 库。

## 端口
8026

## 环境变量
- `GOOGLE_API_KEY`: Google Custom Search API Key（可选）
- `GOOGLE_CSE_ID`: Custom Search Engine ID（可选）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /search` - Google 搜索
- `POST /search/images` - 图片搜索（需要 API Key）
