# Node_18_DeepL

DeepL 翻译服务节点，支持 DeepL Python SDK 和直接 HTTP API 调用。

## 端口
8018

## 环境变量
- `DEEPL_API_KEY`: DeepL API Key（必填，支持 Free 和 Pro 版本）

## 依赖
- `deepl>=1.16.0`（推荐，使用官方 SDK）
- `requests>=2.31.0`（回退方式）

## API
- `GET /health` - 健康检查（含 SDK 可用状态）
- `GET /status` - 节点状态
- `POST /translate` - 文本翻译
- `GET /languages` - 获取支持的语言列表

## 注意
- DeepL Free API 使用 `https://api-free.deepl.com/v2/`
- DeepL Pro API 使用 `https://api.deepl.com/v2/`
- API Key 为空时返回 503 错误
