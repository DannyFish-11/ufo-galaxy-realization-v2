# Node_20_Qdrant

向量数据库节点，使用 Qdrant 提供向量存储、相似度搜索功能。

## 端口
8020

## 环境变量
- `QDRANT_HOST`: Qdrant 主机（默认 localhost）
- `QDRANT_PORT`: Qdrant 端口（默认 6333）
- `QDRANT_API_KEY`: Qdrant API Key（可选）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /collections` - 创建集合
- `DELETE /collections/{name}` - 删除集合
- `GET /collections` - 列出集合
- `POST /points` - 插入向量点
- `POST /search` - 向量相似搜索
- `DELETE /points/{collection}/{id}` - 删除向量点
- `GET /points/{collection}/{id}` - 获取向量点
