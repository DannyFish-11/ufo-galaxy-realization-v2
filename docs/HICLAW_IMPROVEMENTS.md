# HiClaw 改进 + 多语言 MCP Bridge 文档

> 版本：v2.4.0  
> 日期：2026-03-04

本文档说明 UFO Galaxy 新增的 6 大特性的使用方式与 API 参考。

---

## 目录

1. [集中凭证管理（Credential Vault）](#1-集中凭证管理credential-vault)
2. [Worker 独立记忆隔离（Memory Namespace）](#2-worker-独立记忆隔离memory-namespace)
3. [外部渠道插件框架（Channel Plugins）](#3-外部渠道插件框架channel-plugins)
4. [多实例联邦协作（Galaxy Federation）](#4-多实例联邦协作galaxy-federation)
5. [成本可观测性（Cost Tracking）](#5-成本可观测性cost-tracking)
6. [多语言 MCP Bridge（Node.js 示例）](#6-多语言-mcp-bridgenodejs-示例)

---

## 1. 集中凭证管理（Credential Vault）

### 功能概述

`core/credential_vault.py` 提供统一的 API Key 管理服务：

- 统一读写 API Key（OpenAI / Anthropic / DeepSeek / Groq / OneAPI / Ollama）
- 按 Worker/Device 发放短期 token（内存 token + 过期时间）
- 访问审计（记录谁在何时请求了哪个凭证）
- `multi_llm_router.py` 优先从 Vault 获取密钥；若 Vault 无值则回退环境变量

### Python 代码示例

```python
from core.credential_vault import get_vault

vault = get_vault()

# 管理端写入凭证
vault.set_credential("openai", "sk-your-openai-key")
vault.set_credential("anthropic", "sk-ant-your-key")

# 读取凭证（优先 Vault，回退 env）
key = vault.get_credential("openai")

# 列出所有凭证键名
keys = vault.list_credential_keys()
# -> ["anthropic", "deepseek", "openai", ...]

# 为 Worker 颁发短期 token（有效 5 分钟，仅允许访问 openai）
token = vault.issue_token("device-001", ttl=300, scopes=["openai"])

# Worker 用 token 拉取凭证
key = vault.get_credential_by_token(token, "openai")

# 查看审计日志
log = vault.get_audit_log(limit=20)
```

### REST API

#### 写入凭证

```http
POST /api/v1/vault/credentials
Content-Type: application/json

{"key_name": "openai", "value": "sk-xxx"}
```

#### 列出凭证键名

```http
GET /api/v1/vault/credentials
```

响应：
```json
{"keys": ["anthropic", "openai", "deepseek"]}
```

#### 删除凭证

```http
DELETE /api/v1/vault/credentials/openai
```

#### 颁发 Worker Token

```http
POST /api/v1/vault/tokens
Content-Type: application/json

{
  "device_id": "device-001",
  "ttl": 300,
  "scopes": ["openai", "anthropic"]
}
```

响应：
```json
{"success": true, "token": "abc123...", "ttl": 300}
```

#### Worker 用 Token 拉取凭证

```http
POST /api/v1/vault/fetch
Content-Type: application/json

{"token": "abc123...", "key_name": "openai"}
```

#### 审计日志

```http
GET /api/v1/vault/audit?limit=50
```

---

## 2. Worker 独立记忆隔离（Memory Namespace）

### 功能概述

`core/rag_memory.py` 新增命名空间隔离：

- 不传 `namespace` 时使用全局行为（完全向后兼容）
- 传入 `namespace` 后，经验数据存储在独立子目录，互不干扰
- 提供按 `device_id` / `worker_id` 推导 namespace 的便捷函数

### Python 代码示例

```python
from core.rag_memory import get_rag_memory, get_rag_memory_for_device, get_rag_memory_for_worker

# 全局实例（兼容现有代码）
rag = get_rag_memory()

# 按 device 隔离
rag_device = get_rag_memory_for_device("pixel-001")

# 按 worker 隔离
rag_worker = get_rag_memory_for_worker("worker-42")

# 手动指定命名空间
rag_custom = get_rag_memory(namespace="project_alpha")

# 记录经验（仅写入到 device-001 的隔离空间）
rag_device.log_experience(
    agent_name="TaskAgent",
    instruction="打开微信发消息",
    steps=[{"thought": "点击图标", "action": "click", "observation": "微信已打开"}],
    final_output="消息已发送",
    success=True,
    device_id="pixel-001",
)

# 检索（只在该 device 的隔离空间内检索）
similar = rag_device.recall_similar("发微信消息给好友")

# 推导 namespace
ns = rag_device.namespace_for(device_id="pixel-001")
# -> "device_pixel-001"
```

---

## 3. 外部渠道插件框架（Channel Plugins）

### 功能概述

`core/channel_plugins.py` 提供统一的 `ChannelAdapter` 接口：

- 内置 `ConsoleChannelAdapter`（开箱即用，打印到 stdout）
- 外部插件放在 `external/channels/<plugin_name>/channel.py`，其中定义 `Plugin(ChannelAdapter)` 类
- 支持运行时动态加载/卸载，类似 `skill_loader`

### 创建自定义插件

在 `external/channels/my_plugin/channel.py` 中：

```python
from core.channel_plugins import ChannelAdapter

class Plugin(ChannelAdapter):
    name = "my_plugin"
    description = "My custom channel"
    version = "1.0.0"

    async def send(self, message: str, **kwargs):
        # 实现发送逻辑
        return {"success": True, "message_id": "xxx"}

    async def receive(self):
        return None  # 非阻塞，无消息时返回 None

    async def health(self):
        return {"healthy": True, "details": "OK"}
```

### Python 代码示例

```python
from core.channel_plugins import get_channel_loader

loader = get_channel_loader()

# 加载内置 Console 插件
await loader.load_plugin("console")

# 加载外部插件
await loader.load_plugin("my_plugin", path="external/channels/my_plugin")

# 配置插件
await loader.load_plugin("mock_http", path="external/channels/mock_http",
                          config={"webhook_url": "http://localhost:9999/hook"})

# 发送消息
result = await loader.send("console", "Hello, World!", target="broadcast")

# 自动扫描并加载 external/channels/ 目录
await loader.auto_load_plugins()

# 健康检查
health = await loader.health_check_all()
```

### REST API

```http
# 列出已加载插件
GET /api/v1/channels

# 加载内置插件
POST /api/v1/channels/load
{"plugin_id": "console"}

# 加载外部插件
POST /api/v1/channels/load
{"plugin_id": "mock_http", "path": "external/channels/mock_http"}

# 发送消息
POST /api/v1/channels/console/send
{"message": "Hello!", "target": "user-001"}

# 健康检查
GET /api/v1/channels/health
```

---

## 4. 多实例联邦协作（Galaxy Federation）

### 功能概述

`core/galaxy_federation.py` 实现轻量"实例互联"层：

- 实例注册、心跳（HTTP 定时 POST）
- 远程任务转发（HTTP POST）
- 配置项：`FEDERATION_ENABLED`、`FEDERATION_PEERS`、`FEDERATION_INSTANCE_ID`

### 环境变量配置

```bash
FEDERATION_ENABLED=true
FEDERATION_INSTANCE_ID=galaxy-01   # 可选，默认自动生成
FEDERATION_PEERS=http://127.0.0.1:8001,http://peer2:8000
FEDERATION_HEARTBEAT_INTERVAL=15   # 心跳间隔秒数
FEDERATION_LOCAL_HOST=http://127.0.0.1
GATEWAY_PORT=8000
```

### 单机模拟两实例互联

**实例 A（端口 8000）：**

```bash
FEDERATION_ENABLED=true \
FEDERATION_INSTANCE_ID=galaxy-A \
FEDERATION_PEERS=http://127.0.0.1:8001 \
GATEWAY_PORT=8000 \
python start_galaxy.py
```

**实例 B（端口 8001）：**

```bash
FEDERATION_ENABLED=true \
FEDERATION_INSTANCE_ID=galaxy-B \
FEDERATION_PEERS=http://127.0.0.1:8000 \
GATEWAY_PORT=8001 \
python start_galaxy.py
```

启动后，两实例会互相发送心跳，可通过以下 API 验证互联状态。

### Python 代码示例

```python
from core.galaxy_federation import get_federation

fed = get_federation()
await fed.start()

# 列出在线 peer
peers = fed.list_peers()

# 手动注册 peer
fed.register_peer("http://127.0.0.1:8001", instance_id="galaxy-B", name="Node B")

# 转发任务
result = await fed.forward_task("http://127.0.0.1:8001", {
    "command": "ping",
    "params": {"data": "hello from A"}
})
```

### REST API

```http
# 本实例联邦信息
GET /api/v1/federation/info

# 列出 peer
GET /api/v1/federation/peers

# 注册 peer
POST /api/v1/federation/peers
{"url": "http://127.0.0.1:8001", "instance_id": "galaxy-B", "name": "Node B"}

# 接收心跳（供其他实例调用）
POST /api/v1/federation/heartbeat
{"instance_id": "galaxy-B", "url": "http://127.0.0.1:8001"}

# 转发任务给指定 peer
POST /api/v1/federation/forward
{"target": "http://127.0.0.1:8001", "task": {"command": "ping", "params": {}}}
```

---

## 5. 成本可观测性（Cost Tracking）

### 功能概述

`core/cost_tracker.py` 为每次 LLM 调用记录：

- provider、model、input_tokens、output_tokens
- 估算成本（USD）、延迟、是否成功
- 持久化到 `data/cost_records.jsonl`
- `multi_llm_router.py` 调用成功后自动记录

### Python 代码示例

```python
from core.cost_tracker import get_cost_tracker

tracker = get_cost_tracker()

# 手动记录（通常由 multi_llm_router 自动调用）
tracker.record(
    provider="openai",
    model="gpt-4o",
    input_tokens=500,
    output_tokens=200,
    task_type="coding",
    device_id="device-001",
    latency_ms=1234.5,
)

# 读取最近 50 条
records = tracker.get_recent(50)

# 获取汇总统计
summary = tracker.get_summary()
# {
#   "total_calls": 42,
#   "total_input_tokens": 15000,
#   "total_output_tokens": 8000,
#   "total_cost_usd": 0.00234,
#   "by_provider": {"openai": {...}, "deepseek": {...}}
# }
```

### REST API

```http
# 最近 50 条成本记录
GET /api/v1/cost/records?limit=50

# 汇总统计
GET /api/v1/cost/summary
```

---

## 6. 多语言 MCP Bridge（Node.js 示例）

### 功能概述

`mcp_bridge/` 目录提供多语言 MCP Server 桥接层：

- 任何语言实现的 MCP Server（符合 JSON-RPC over stdio 规范）均可被加载
- 通过 `mcp_bridge/bridge.py` 管理子进程生命周期
- 加载后自动注册到 `core/mcp_loader`，与现有系统无缝集成
- 支持通过 `/api/v1/mcp/load` 加载（复用现有 MCP API）

### MCP Server 规范

外部 MCP Server 须满足：

1. **通信协议**：JSON-RPC 2.0 over stdio（每行一个 JSON 对象）
2. **必须实现的方法**：
   - `initialize` → 返回 `{protocolVersion, capabilities, serverInfo}`
   - `tools/list` → 返回 `{tools: [{name, description, inputSchema}]}`
   - `tools/call` → 接收 `{name, arguments}`，返回 `{content: [{type, text}]}`
3. **启动方式**：通过命令行参数传递配置（如 `node server.js --port 0`）

### Node.js 示例服务器

位置：`mcp_bridge/examples/node_demo/server.js`

提供两个演示工具：
- `echo`：回显输入消息
- `timestamp`：返回当前时间戳

#### 直接运行

```bash
cd mcp_bridge/examples/node_demo
node server.js
# 然后在 stdin 输入 JSON-RPC 消息：
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | node server.js
```

#### 通过 UFO Galaxy 加载

**方法 1：使用 Python mcp_bridge API**

```python
from mcp_bridge import MCPBridgeSpec, load_bridge_server

spec = MCPBridgeSpec(
    server_id="node-demo",
    command="node /path/to/mcp_bridge/examples/node_demo/server.js",
    description="Node.js demo MCP server",
)
result = await load_bridge_server(spec)
# {"success": true, "server_id": "node-demo", "tools": ["echo", "timestamp"]}

# 调用工具
from mcp_bridge import get_bridge_loader
bridge = get_bridge_loader()
result = await bridge.call_tool("node-demo", "echo", {"message": "Hello from Python!"})
# {"content": [{"type": "text", "text": "Echo: Hello from Python!"}]}
```

**方法 2：通过 REST API（复用现有 `/api/v1/mcp/load`）**

```bash
curl -X POST http://localhost:8000/api/v1/mcp/load \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "node-demo",
    "command": "node /abs/path/to/mcp_bridge/examples/node_demo/server.js"
  }'

# 调用工具
curl -X POST http://localhost:8000/api/v1/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "node-demo",
    "tool_name": "timestamp",
    "arguments": {"format": "iso"}
  }'
```

### 使用 TypeScript 编写 MCP Server

可基于官方 `@modelcontextprotocol/sdk` npm 包：

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server({ name: "my-ts-server", version: "1.0.0" }, {
  capabilities: { tools: {} },
});

// 注册工具、添加处理器...

const transport = new StdioServerTransport();
await server.connect(transport);
```

加载方式与上述相同，将 `command` 改为 `"node dist/server.js"` 或 `"npx ts-node server.ts"`。

---

## 变更日志

- `core/credential_vault.py` — 新增
- `core/cost_tracker.py` — 新增
- `core/channel_plugins.py` — 新增
- `core/galaxy_federation.py` — 新增
- `core/rag_memory.py` — 新增命名空间支持（`namespace` 参数、`get_rag_memory_for_device/worker`）
- `core/multi_llm_router.py` — 集成 Vault 密钥读取、自动记录调用成本
- `core/api_routes.py` — 新增 vault/cost/channel/federation 路由
- `mcp_bridge/` — 新增多语言 MCP Bridge 框架
- `mcp_bridge/examples/node_demo/` — Node.js MCP Server 示例
- `external/channels/mock_http/` — 外部渠道插件示例
