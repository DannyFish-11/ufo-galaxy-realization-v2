# Node_01_OneAPI

LLM 统一接入网关，支持 OpenAI、Azure OpenAI、Anthropic、Google Gemini 等多个大模型提供商。

## 端口
8001

## 环境变量
- `OPENAI_API_KEY`: OpenAI API Key
- `AZURE_OPENAI_API_KEY`: Azure OpenAI API Key
- `ANTHROPIC_API_KEY`: Anthropic API Key
- `GEMINI_API_KEY`: Google Gemini API Key

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /chat` - 对话请求（兼容 OpenAI 格式）
- `GET /models` - 列出可用模型
