# Node_21_Notion

Notion 集成节点，提供页面、数据库、块的管理功能。

## 端口
8021

## 环境变量
- `NOTION_API_KEY`: Notion Integration Token（必填）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /mcp/call` - 调用 Notion API 操作（search、create_page、update_page 等）
