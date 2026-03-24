# Node_01_OneAPI

> **System position:** External aggregator integration layer — see
> [`docs/ONEAPI_SYSTEM_POSITION.md`](../../docs/ONEAPI_SYSTEM_POSITION.md)
> for the canonical definition.

LLM 统一接入网关，支持 OpenAI、Azure OpenAI、Anthropic、Google Gemini 等多个大模型提供商。

## System Role

`Node_01_OneAPI` is the Galaxy integration point for an **external OneAPI-compatible
aggregator gateway**.  It is **not** a direct/native-multimodal vendor provider.

Key properties:

- **Aggregator integration layer** — wraps multiple upstream LLM vendors behind a single
  OpenAI-compatible endpoint.  Galaxy treats it as `ProviderCategory.ONEAPI`, which is
  distinct from `ProviderCategory.DIRECT` (direct vendor APIs).
- **System-wide configuration** — `ONEAPI_BASE_URL` / `ONEAPI_API_KEY` propagate to the
  global provider registry (`MultiLLMRouter`, `ProviderInventory`) and routing graph
  (`TopologyRouter`).  They are **not** dashboard-local settings.
- **Separate lower-layer row** — in the model supply topology, OneAPI appears as a distinct
  lower-layer row below the top-layer direct/native-multimodal providers.  It must not be
  interleaved with direct vendor rows in status-board displays.
- **Routing role** — assigned `TopologyRole.ROUTING` by the config bridge, reflecting its
  aggregator nature rather than that of a native multimodal primary provider.

## 端口
8001

## 环境变量

### OneAPI 聚合端点（外部聚合器接入位）
- `ONEAPI_BASE_URL`: OneAPI 聚合网关地址（设置后系统全局生效）
- `ONEAPI_API_KEY`: OneAPI 访问密钥（设置后系统全局生效）

### 直供云端 LLM 提供商
- `OPENROUTER_API_KEY`: OpenRouter API Key
- `ZHIPU_API_KEY`: 智谱 AI API Key
- `GROQ_API_KEY`: Groq API Key
- `CLAUDE_API_KEY`: Anthropic Claude API Key
- `TOGETHER_API_KEY`: Together AI API Key
- `PERPLEXITY_API_KEY`: Perplexity API Key

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态（含云端提供商列表和本地 LLM 可用性）
- `POST /chat` - 对话请求（兼容 OpenAI 格式）
- `GET /models` - 列出可用模型
