# Node_01_OneAPI

> **System position:** External aggregator integration layer —
> **OneAPI Aggregator Horizon** in the model supply topology.
> See [`docs/ONEAPI_SYSTEM_POSITION.md`](../../docs/ONEAPI_SYSTEM_POSITION.md)
> for the canonical definition and
> [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](../../docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md)
> §3 Layer 5 for the visual grammar.

LLM 统一接入网关，支持 OpenAI、Azure OpenAI、Anthropic、Google Gemini 等多个大模型提供商。

## System Role

`Node_01_OneAPI` is the Galaxy integration point for an **external OneAPI-compatible
aggregator gateway**.  It is **not** a direct/native-multimodal vendor provider.

Key properties:

- **Aggregator Horizon** — wraps multiple upstream LLM vendors behind a single
  OpenAI-compatible endpoint.  Galaxy treats it as `ProviderCategory.ONEAPI`, which is
  distinct from `ProviderCategory.DIRECT` (direct vendor APIs).
- **Always a lower architectural tier** — OneAPI must never be placed at the same
  visual or architectural level as direct/native-multimodal top-layer providers
  (OpenAI, Anthropic, Gemini, xAI, etc.).  Any such placement is architecturally
  incorrect.  This is a non-negotiable constraint established in PR-1.
- **System-wide configuration** — `ONEAPI_BASE_URL` / `ONEAPI_API_KEY` propagate to the
  global provider registry (`MultiLLMRouter`, `ProviderInventory`) and routing graph
  (`TopologyRouter`).  They are **not** dashboard-local settings.
- **Separate Aggregator Horizon row** — in the model supply topology, OneAPI appears as
  a distinct lower-layer row below the top-layer direct/native-multimodal providers,
  separated by a mandatory horizontal rule.
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
