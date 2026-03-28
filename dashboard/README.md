# Galaxy Dashboard

> **⚠️ LEGACY HEADLESS BACKEND (PR-1 — frontend fully retired)**
> `dashboard/frontend/` has been **permanently deleted** as of PR-1.
> There is no longer any web operator-facing UI surface here.
> `dashboard/backend/main.py` is retained **headless** for migration/compatibility only.
>
> - **Active operator surface**: `windows_client/status_board_v2/`
> - Canonical REST API: `core/api_routes.py`, `core/routes/`
> - Canonical status truth: `GET /api/v1/projection/runtime` (RuntimeProjection / DesktopStatusProjection)
>
> Do not add new status-authority endpoints here.  See `core/ui_surface_authority.py`
> for the canonical UI surface authority registry.

legacy headless backend — API compatibility surface only (frontend retired PR-1)

## 功能特性

### 1. 系统概览
- 总节点数统计
- 运行/停止/错误节点数
- 系统健康率
- 实时状态更新

### 2. 节点管理
- 节点状态监控
- 节点健康检查
- 节点重启控制
- 节点详情查看

### 3. 日志查看
- 实时日志流
- 日志级别过滤
- 日志搜索
- 日志导出

### 4. 任务管理
- 任务创建和编排
- 任务执行状态
- 任务历史记录

### 5. 记忆系统
- 对话历史查看
- 记忆统计
- 用户画像

### 7. 自动 Agent 创建（P1 新增）

OpenClawd 现在能够**自动理解任务意图并创建合适的 Agent 执行任务**，无需用户发出任何特殊指令。

#### 默认执行流程（动态自组织）

```
用户消息 → IntentRouter (规则分类，<5ms)
               │
               ├─ chat_only  → 直接 LLM 对话
               │
               └─ task_execute / hybrid（默认路径）
                               │
                               ▼
                    ExecutionPlanner（策略选择）
                               │
                    ┌──────────┴──────────┐
                    │ 策略选择（自动）      │
                    ├──────────────────────┤
                    │ single_agent         │ 低复杂度默认
                    │ team_specialized     │ 中高复杂度 / 多模型协同
                    │ team_swarm           │ 高并发（上限 20）
                    │ fractal              │ 极高复杂度（深度 3）
                    └──────────────────────┘
                               │
                    AgentFactory（LLM 优先）
                               │
                    ┌──────────┴──────────┐
                    │ LLM 动态生成（主路径） │
                    │ 模板兜底（失败时）     │
                    └──────────────────────┘
                               │
                    TwinModel（孪生指挥层）
                               │ 自动创建孪生 Agent（默认 LOOSE）
                               ▼
                    Multi-LLM Router（任务类型 + 成本策略）
                               │
                    Agents 执行 → ExecutionResult
                               │
                    返回 auto_agent_id + chosen_strategy
                         + chosen_providers + twin_id
```

#### 设计原则

| 原则 | 说明 |
|------|------|
| **默认执行** | 所有任务类请求优先进入执行链，保留 chat_only 仅用于纯问答 |
| **LLM 优先生成** | AgentFactory 优先调用 LLM 动态生成 Agent；模板作为结构蓝图兜底 |
| **模板 = 蓝图** | 模板不是静态产物，而是 LLM 生成的结构约束 |
| **孪生指挥** | 每个主控 Agent 自动创建数字孪生（默认 LOOSE 耦合，可随时解耦/耦合） |
| **策略护栏** | Multi-LLM Router 规则选择具有最高权威；LLM 只能微调，不可覆盖规则 |

#### 策略选择逻辑

| 条件 | 策略 | 说明 |
|------|------|------|
| swarm/批量/高并发 关键词 | `team_swarm` | 并发上限 20 |
| 复杂度 ≥ 0.75 / 递归/分型 关键词 | `fractal` | 最大深度 3，最大子任务 20 |
| 复杂度 ≥ 0.65 / team/并行 关键词 | `team_specialized` | 异构 Agent Team |
| 默认 | `single_agent` | 单 LLM 驱动 Agent |

#### 自动模板选择逻辑（兜底）

| 关键词（中英文） | 选中模板 |
|-----------------|---------|
| 代码、编程、code、script、写代码 | `code_executor` |
| 分析、数据、统计、analyze、data、图表 | `data_analyst` |
| 设备、控制、手机、device、截图 | `device_controller` |
| 搜索、调研、research、查找 | `research` |
| 计划、规划、plan、策略、步骤 | `planner` |
| 其他（默认） | `coordinator` |

#### API 响应中的新字段

任务执行成功后，`/api/v1/chat` 响应的 `data` 字段中包含以下可选字段：

```json
{
  "success": true,
  "response": "分析完成：...",
  "data": {
    "auto_agent_id": "agent_abc123456",
    "auto_agent_template": "data_analyst",
    "chosen_strategy": "single_agent",
    "chosen_providers": ["deepseek:deepseek-chat"],
    "twin_id": "twin_xyz789",
    "twin_coupling": "loose",
    "task_result": { ... }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `auto_agent_id` | string? | 自动创建的主控 Agent ID |
| `auto_agent_template` | string? | 使用的模板蓝图名（LLM 生成时为 null） |
| `chosen_strategy` | string? | 执行策略：single_agent / team_specialized / team_swarm / fractal |
| `chosen_providers` | string[]? | 本次执行使用的 LLM provider:model 列表 |
| `twin_id` | string? | 孪生 Agent ID |
| `twin_coupling` | string? | 孪生耦合模式：tight / loose / decoupled / shadow |

> ⚠️ 所有字段均为**可选的** — 纯聊天消息不包含这些字段，向后兼容。

#### Dashboard UI 展示

在 **🧪 测试** 标签页的「简单对话测试」中，当系统自动为任务创建了 Agent，对话回复上方会显示两个标签栏：

1. **紫色标签栏**（`auto_agent_template` 存在时）：
   ```
   ┌─────────────────────────────────────────┐
   │ 🤖 自动创建 Agent  [data_analyst]  agent_abc123  │
   └─────────────────────────────────────────┘
   ```

2. **绿色标签栏**（`chosen_strategy` 存在时）：
   ```
   ┌───────────────────────────────────────────────────┐
   │ ⚡ 执行策略  [fractal]  deepseek:deepseek-chat  🔗 twin:loose  │
   └───────────────────────────────────────────────────┘
   ```

#### 注意事项

- 仅在 `AGENT_FACTORY_AVAILABLE` 为 `True` 时才会触发自动 Agent 路径。
- 意图路由使用**规则引擎**（`use_llm=False`），延迟极低（<5ms）。
- 如果 Agent 执行失败，系统会自动降级到直接 LLM 对话。
- Swarm 并发上限：**20**；Fractal 最大递归深度：**3**（硬编码）。



在 **🤖 Agent** 标签页的「创建 Agent」面板中，新增了 4 个能力权限开关：

| 权限 | 图标 | 说明 |
|------|------|------|
| `filesystem` | 📁 | 允许 Agent 读写本地文件系统 |
| `terminal` | ⌨️ | 允许 Agent 执行终端 / Shell 命令 |
| `network` | 🌐 | 允许 Agent 访问外部网络（HTTP / API） |
| `browser` | 🖥️ | 允许 Agent 控制浏览器进行 Web 自动化 |

**默认全部关闭**，仅勾选确实需要的权限后再创建 Agent，以最小化执行风险。

权限信息在创建时随请求体一同发送至后端，持久化存储在 `AgentConfig.permissions` 字段中，并可通过 `GET /api/v1/agents/{id}` 接口中的 `agent.permissions` 字段读回。

## 快速开始

### 1. 启动后端

```bash
cd dashboard/backend
pip install -r requirements.txt
python main.py
```

后端将在 `http://localhost:8085` 启动（**无头模式** — 不提供任何前端 UI）。

### ~~2. 访问前端~~ — RETIRED

> **⚠️ `dashboard/frontend/` 已在 PR-1 中完全删除。**
> 不再有任何面向运维人员的 Web UI 可访问。
> 运维界面请使用 `windows_client/status_board_v2/`。

### ~~3. 构建 TypeScript 前端（可选）~~ — RETIRED

> **⚠️ TypeScript 前端代码（`dashboard/frontend/ts/`）已在 PR-1 中完全删除。**
> 请勿尝试执行 `npm install` 或 `npm run build`。

## WebSocket 实时连接

后端 WebSocket 端点：`ws://localhost:8085/ws`

> **⚠️ 前端 TypeScript 客户端（`dashboard/frontend/ts/api.ts`）已在 PR-1 中删除。**
> 如需通过 WebSocket 连接，请直接使用标准 WebSocket 客户端或从 `core/` 层调用。

## 配置

### 环境变量

```bash
# 节点基础 URL
NODE_BASE_URL=http://localhost

# 节点端口起始值
NODE_PORT_START=8000

# 日志级别
LOG_LEVEL=INFO
```

## API 文档

### 系统信息
```
GET /api/v1/system/info
GET /api/v1/ascii
```

### 设备管理
```
GET  /api/v1/devices              # 获取设备列表
POST /api/v1/devices/register     # 注册设备
POST /api/v1/devices/{id}/command # 发送设备命令（新增 trace 记录）
```

### Agent 管理
```
GET /api/v1/agents                # 获取 Agent 列表
GET /api/v1/llm/providers         # 获取 LLM 提供商列表（含多模态标记）
```

### 支持的模型 / Provider 表格

`GET /api/v1/llm/providers` 返回以下 provider 列表。响应字段：
`provider`, `model`（默认模型）, `models`（全部可用模型）, `available`（是否配置了 API Key）,
`multimodal`（是否支持多模态）, `missing_env_key`（不可用时提示需配置的环境变量）。

| Provider ID | 显示名 | 默认模型（API ID） | 全部支持模型 | 多模态 | 所需环境变量 |
|-------------|--------|-------------------|-------------|-------|-------------|
| `openai` | OpenAI | `gpt-5.4` | `gpt-5.4`, `gpt-5.4-thinking`, `gpt-5.4-pro`, `gpt-4.1`, `gpt-4o`, `gpt-4o-mini` | ✅ | `OPENAI_API_KEY` |
| `anthropic` | Anthropic | `claude-sonnet-4.6` | `claude-opus-4.6`, `claude-sonnet-4.6`, `claude-haiku-4-5-20251001` | ✅ | `ANTHROPIC_API_KEY` |
| `google` | Google | `gemini-3.1-pro` | `gemini-3.1-pro`, `gemini-3.1-flash`, `gemini-3.1-deep-think`, `gemini-2.5-pro` | ✅ | `GOOGLE_API_KEY` 或 `GEMINI_API_KEY` |
| `xai` | xAI / Grok | `grok-4.20` | `grok-4.20`, `grok-4.20-beta` | ✅ | `XAI_API_KEY` |
| `mistral` | Mistral | `mistral-large-3` | `mistral-large-3`, `mistral-medium-3`, `mistral-large-2` | ✅ | `MISTRAL_API_KEY` |
| `deepseek` | DeepSeek | `deepseek-ai/DeepSeek-V3.2` | `deepseek-ai/DeepSeek-V3.2`, `deepseek-ai/DeepSeek-V3`, `deepseek-chat`, `deepseek-reasoner` | ❌ | `DEEPSEEK_API_KEY` |
| `qwen` | 通义千问 | `Qwen/Qwen3.5-397B-A17B` | `Qwen/Qwen3.5-397B-A17B`, `Qwen/Qwen3.5-397B-A17B-Coder`, `Qwen/Qwen3-235B-A22B` | ❌ | `QWEN_API_KEY` 或 `TOGETHER_API_KEY` |
| `zhipu` | 智谱 AI | `glm-4.6` | `glm-4.6`, `glm-4-flash` | ✅ | `ZHIPU_API_KEY` |
| `moonshot` | Moonshot Kimi | `moonshot-v1-128k` | `moonshot-v1-32k`, `moonshot-v1-128k`, `moonshot-v1-256k` | ❌ | `MOONSHOT_API_KEY` |
| `perplexity` | Perplexity | `sonar-pro` | `sonar-pro`, `sonar-deep-research`, `sonar-reasoning-pro`, `sonar` | ❌ | `PERPLEXITY_API_KEY` |
| `groq` | Groq | `llama-3.3-70b-versatile` | `llama-3.3-70b-versatile` | ❌ | `GROQ_API_KEY` |
| `openrouter` | OpenRouter | `openrouter/auto` | `openrouter/auto` | ❌ | `OPENROUTER_API_KEY` |

> **多模态（MM）**：Provider 原生接受图像、音频或视频作为输入（不仅限于文本）。  
> **通过 Together AI 访问 Qwen**：`QWEN_API_KEY` 和 `TOGETHER_API_KEY` 均可，系统自动检测。

### 聊天
```
POST /api/v1/chat                 # 统一聊天入口
POST /api/v1/dashboard/chat       # 仪表盘聊天（与上同功能）
```

### 多设备并行执行
```
POST /api/v1/execute/parallel     # 并行执行多设备命令（新增 trace + 编排记录）
                                  # 可选字段: task_id, description
```

---

## P2 新增 API（设备执行链路 / 协同视图 / 编排可视化）

### 设备执行 Trace
```
GET  /api/v1/devices/traces                # 所有设备执行记录（?limit=100）
GET  /api/v1/devices/{device_id}/traces    # 指定设备执行记录（?limit=50）
```

每条 trace 包含：`trace_id`, `device_id`, `command`, `params`, `result`, `success`,
`error`, `agent_id`, `task_id`, `duration_ms`, `timestamp`。

trace 持久化到 `data/device_traces.json`（最多 500 条滚动保留）。

### Agent–Device 协同映射
```
GET   /api/v1/agent-device/mapping            # 查询所有 Agent 控制的设备及任务状态
POST  /api/v1/agent-device/assign             # 记录 Agent→Device 分配
      Body: { agent_id, device_id, task, status }
PATCH /api/v1/agent-device/{agent_id}/status  # 更新 Agent 任务状态
      Body: { status }
```

响应中每条映射附带 `trace_summary`（最近一条 trace 摘要）。

### 多设备任务编排
```
GET   /api/v1/orchestration/tasks           # 获取编排任务列表（?limit=50）
POST  /api/v1/orchestration/tasks           # 手动记录编排任务
      Body: { task_id?, description, device_assignments, status? }
PATCH /api/v1/orchestration/tasks/{task_id} # 更新任务状态 / 归并结果
      Body: { status?, results? }
```

每条任务包含 `device_assignments` 和 `device_traces`（关联的 trace 列表），
便于前端渲染任务时间线和结果归并状态。

---

### Dashboard UI 新增标签页

| 标签 | 功能 |
|------|------|
| 📋 执行链路 | 展示设备执行记录，支持按设备过滤，显示命令/耗时/错误 |
| 🔗 协同视图 | 展示 Agent–Device 映射，含任务状态和 trace 摘要 |
| 🗂️ 编排 | 展示多设备任务编排，含分配列表、步骤时间线和结果归并状态 |

### WebSocket 实时更新
```
WS /ws
```

消息格式：
```json
{ "type": "ping" }                         // 心跳
{ "type": "chat", "content": "你好" }      // 发送聊天
{ "type": "chat_response", "content": "..." } // 聊天回复（服务端推送）
{ "type": "status_update", "data": {} }    // 状态更新（服务端推送）
```

## 技术栈

### 后端
- FastAPI - Web 框架（端口 8085，无头运行）
- httpx - HTTP 客户端
- WebSocket - 实时通信

### ~~前端~~ — RETIRED (PR-1)

> `dashboard/frontend/` 已完全删除。不再有任何面向运维人员的 Web 前端。

## 开发

### 添加新功能

1. 在 `backend/main.py` 添加 API 端点（仅限迁移兼容性用途）
2. 新的运维界面功能请在 `windows_client/status_board_v2/` 中实现

### 调试

后端日志：
```bash
tail -f dashboard.log
```

前端调试：
- 打开浏览器开发者工具
- 查看 Console 和 Network 标签

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t galaxy-dashboard .

# 运行容器
docker run -d -p 8080:8080 galaxy-dashboard
```

### 生产环境

```bash
# 使用 Gunicorn + Uvicorn workers
gunicorn -w 4 -k uvicorn.workers.UvicornWorker dashboard.backend.main:app --bind 0.0.0.0:8085
```

## 故障排查

### 节点无法连接
1. 检查节点是否启动
2. 检查端口是否正确
3. 检查防火墙设置

### WebSocket 断开
1. 检查网络连接
2. 检查后端日志
3. 刷新页面重新连接

---

## 实时状态面板（PR-95 新增）

### 数据来源

实时状态面板由前端 `LiveStatusPanel` 组件驱动，每 5 秒轮询一次后端聚合端点：

| 端点 | 说明 |
|------|------|
| `GET /api/v1/observability/live-status` | 聚合四项状态，一次请求返回所有面板数据 |
| `GET /api/v1/observability/model-route` | 活跃 LLM 路由及 Fallback 提供商 |
| `GET /api/v1/observability/gateway` | 网关 / 设备在线状态汇总 |
| `GET /api/v1/observability/recent-calls` | 近期工具 / 设备调用记录（最多 50 条） |
| `GET /api/v1/observability/stats` | GatewayTraceStore 统计 |
| `GET /api/v1/observability/trace/{id}` | 按 task_id 或 command_id 查询追踪记录 |

### 面板四大区块

1. **⚡ 能力加载**（`capability_load`）  
   显示 `CapabilityRegistry` 已注册的工具总数及列表（最多展示 5 条）。

2. **🌐 网关追踪**（`gateway_trace`）  
   显示 `CommandRouter` 路由总数及最近 3 条调用记录（`command_id` + `status`）。

3. **📱 设备健康**（`device_health`）  
   显示 `DeviceRegistry` 中注册设备数 / 在线设备数，以及各设备的在线状态。

4. **🤖 模型路由**（`model_route`）  
   显示当前活跃 LLM 提供商、默认模型名称及 Fallback 列表。

### 前端使用

```typescript
import { LiveStatusPanel } from './ts/components';

const panel = new LiveStatusPanel(
  document.getElementById('live-status')!,
  5000  // 轮询间隔（毫秒）
);
panel.start();   // 启动轮询
// panel.stop();  // 停止轮询
```

---

## 节点打包标准（PR-95 新增）

所有节点（`nodes/Node_XX_*`）必须包含：

| 文件 | 说明 |
|------|------|
| `requirements.txt` | pip 依赖声明。若无外部依赖，保留注释行而非空文件。 |
| `Dockerfile` | 基于 `python:3.11-slim`，使用非 root `galaxy` 用户。 |

### 检查覆盖率

从仓库根目录运行：

```bash
bash tools/check_node_packaging.sh
# Exit 0 = 所有节点均已完成打包（110/110）
```

### Dockerfile 模板

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE <端口号>

RUN addgroup --system --gid 1000 galaxy \
    && adduser --system --uid 1000 --ingroup galaxy --no-create-home galaxy \
    && chown -R galaxy:galaxy /app
USER galaxy

CMD ["python", "main.py"]
```

### requirements.txt 规范

- 列出所有非标准库依赖（`fastapi`、`uvicorn`、`pydantic` 等）。
- 若节点无第三方依赖，添加注释行：  
  `# No external dependencies beyond the Python standard library`
- 禁止引用不存在的包名。
- 建议锁定大版本：`fastapi>=0.109.0`、`uvicorn>=0.27.0`、`pydantic>=2.5.3`。

---

## 端到端集成测试（PR-95 新增）

正式集成测试位于 `tests/test_e2e_stack.py`，覆盖四个测试套件：

| 套件 | 覆盖范围 |
|------|---------|
| `TestDeviceRegistrationAndCapabilitySync` | 设备注册 → 设备列表 → CapabilityRegistry 查询 |
| `TestCommandRoutingWithTrace` | 命令提交 → 路由统计 → 网关可观测性 |
| `TestObservabilityEndpoints` | 模型路由 / 近期调用 / 统计 / Trace 查询 |
| `TestDashboardLiveStatusEndpoint` | 聚合实时状态端点（四区块 JSON 契约验证） |

### P2 新增测试（`tests/test_p2_dashboard_endpoints.py`）

25 个测试，覆盖 P2 三大功能模块：

| 测试类 | 覆盖范围 |
|--------|---------|
| `TestDeviceTraceStore` | DeviceTraceStore 单元测试（增、查、持久化、上限） |
| `TestDeviceTraceEndpoints` | `/api/v1/devices/traces` 及 `/{id}/traces` |
| `TestAgentDeviceMapping` | `/api/v1/agent-device/mapping`、`/assign`、`/{id}/status` |
| `TestOrchestrationEndpoints` | `/api/v1/orchestration/tasks` CRUD |
| `TestParallelExecuteP2Integration` | `execute/parallel` 的 trace + orch 联动写入 |

### 本地运行

```bash
# 从仓库根目录运行（无需外部服务）
pip install pytest httpx fastapi
pytest tests/test_e2e_stack.py tests/test_p2_dashboard_endpoints.py -v
```

---

## 执行链路可视化（P1 新增）

在 **🧪 测试** 标签页的「简单对话测试」中，每次发送消息后将自动展示响应中的执行链路信息：

| 字段 | 展示方式 |
|------|----------|
| `agent_steps` | 紫色左边框时间线，每步显示动作名称、状态和输出 |
| `tool_calls`  | 蓝色左边框列表，显示工具名称和参数 |
| `error`       | 红色警告框，展示错误信息 |

当 Agent 返回这些字段时（如 task_execute / hybrid 意图），用户可直观看到整个执行过程。

---

## 权限管理中心（P1 新增）

### UI：🔐 权限 标签页

- **全局权限策略**：统一管理 `filesystem / terminal / network / browser` 四类权限的默认开关
- **Agent 覆盖策略**：为特定 Agent（按 ID）单独设置权限，覆盖全局默认值
- **策略持久化**：保存到 `data/permissions_policy.json`

### 后端端点

```
GET  /api/v1/permissions/policy   # 获取当前策略（global + agent_overrides）
POST /api/v1/permissions/policy   # 更新策略（局部更新，支持 global 和 agent_overrides 字段）
```

**请求体示例（POST）：**
```json
{
  "global": { "filesystem": false, "terminal": false, "network": true, "browser": false },
  "agent_overrides": { "agent_001": { "filesystem": true, "terminal": true } }
}
```

### Policy Loader（执行上下文注入）

`core/policy_loader.py` 提供以下接口，供 Agent 执行链路读取权限：

```python
from core.policy_loader import get_global_permissions, get_agent_permissions, inject_policy_into_context

# 获取全局默认权限
perms = get_global_permissions()

# 获取指定 Agent 的有效权限（覆盖优先于全局）
perms = get_agent_permissions("agent_001")

# 注入到执行上下文
context = inject_policy_into_context({"task": "..."}, agent_id="agent_001")
# context["permissions"] 即为该 Agent 的有效权限
```

---

## 集成管理（P1 新增）

### UI：🔗 集成 标签页

支持管理以下 4 个平台的接入配置：

| 平台 | 字段 |
|------|------|
| ✈️ Telegram | Bot Token, Webhook URL |
| 🎮 Discord  | Bot Token, Webhook URL |
| 💬 Slack    | Bot Token, Webhook URL |
| 📱 WhatsApp | API Token, Phone Number ID |

- **Token 脱敏**：Token 字段保存后不再明文展示（仅显示"已配置 Token ✓"）
- **启用/禁用**：每个集成独立开关
- **配置持久化**：保存到 `data/integrations_config.json`

> P1 阶段仅存储配置，不执行实际 API 调用。

### 后端端点

```
GET  /api/v1/integrations/config   # 获取集成配置（Token 脱敏）
POST /api/v1/integrations/config   # 更新集成配置（支持局部更新各平台字段）
```

**请求体示例（POST）：**
```json
{
  "telegram": { "enabled": true, "bot_token": "xxx", "webhook_url": "https://..." },
  "slack":    { "enabled": false }
}
```

---

## 许可证

MIT License


---

## C阶段功能扩展（C Stage Features）

### 1A — SOUL 人格继承增强

**原则**: 主控 Agent 的 SOUL 约束向下继承给子 Agent（Team/Swarm/Fractal 分裂路径），子 Agent 可追加自己的 `soul_supplement`，但 `inherited_soul` 不可被覆盖。

**新增字段（AgentConfig）**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `inherited_soul` | `str` | 从主控继承的 SOUL 约束（子代只读） |
| `soul_supplement` | `str` | 子 Agent 可追加的补充人格说明 |

**新增函数**:
- `core.agent_factory.get_effective_soul(config)` → 返回 `inherited_soul + soul_supplement` 合并字符串

---

### 2C — 工具/MCP 调用守护与回滚

**新增模块**: `core/tool_guardian.py`

**功能**:
- **风险评分**（B）：对工具名进行 SAFE/MODERATE/DANGEROUS/CRITICAL 评级，分数 0~1
- **拦截**（B）：`score >= block_score`（默认 0.95）时抛出 `ToolGuardianBlockedError`
- **重试**（A）：失败时按 `max_retries` 次重试
- **回滚**（A）：最终失败后调用用户传入的 `rollback_fn(tool_name, args, kwargs, exc)`
- **审计日志**：内存 ring-buffer，最近 200 条，可通过 API 查询

**向后兼容**: `GuardedCallConfig(enabled=False)`（默认）时完全透传，不影响现有代码路径。

**新增 API**:
```
GET /api/v1/guardian/audit?n=50   # 获取最近 N 条工具调用守护审计日志
```

**使用示例**:
```python
from core.tool_guardian import call_with_guardian, GuardedCallConfig

cfg = GuardedCallConfig(enabled=True, max_retries=2, rollback_fn=my_rollback)
result = await call_with_guardian(fn=my_tool_fn, fn_args=(arg1,), tool_name="file_write", config=cfg)
```

---

### 3B — 协同策略规则扩展

**新增**: `TASK_TYPE_STRATEGY_MAP`（`core/agent/execution_planner.py`）

任务类型 → 执行策略映射表（优先级最高，融合到原有复杂度/关键词规则中）：

| 任务类型 | 推荐策略 |
|---------|---------|
| `fast_response`, `chat`, `question`, `coding`, `device_control` | `single` |
| `reasoning`, `planning`, `analysis`, `research` | `specialized` |
| `swarm`, `batch` | `swarm` |
| `fractal`, `deep_planning` | `fractal` |

原有复杂度/关键词规则保留不变，映射表优先级最高。

**新增 API**:
```
GET /api/v1/strategy/mappings   # 获取完整映射表 + 可用策略列表
```

---

### 4B — 任务记忆/长期记忆

**新增模块**: `core/task_memory.py`

**功能**:
- 每次任务执行完成后自动将摘要持久化到 `data/task_memory.jsonl`
- 下次执行时自动将最近 3 条任务摘要注入 `context`（可配置条数）
- 提供统计接口

**新增 API**:
```
GET /api/v1/memory/tasks?n=10   # 获取最近 N 条任务记忆摘要
GET /api/v1/memory/stats        # 获取统计（总数/成功率/策略分布）
```

**TaskSummary 字段**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `summary_id` | `str` | 唯一 ID |
| `timestamp` | `float` | Unix 时间戳 |
| `task` | `str` | 任务描述（最多 500 字符） |
| `result_summary` | `str` | 执行结果摘要（最多 300 字符） |
| `success` | `bool` | 是否成功 |
| `strategy` | `str` | 执行策略 |
| `duration_ms` | `float` | 执行时长（毫秒） |

---

### 5C — 执行链路可视化细化

**新增字段（ExecutionResult，均为可选，默认 None，向后兼容）**:
| 字段 | 类型 | 说明 |
|------|------|------|
| `total_latency_ms` | `float \| None` | 整条链路总延迟（毫秒） |
| `total_tokens` | `int \| None` | 本次执行消耗 LLM Token 总量 |
| `total_cost_usd` | `float \| None` | 本次执行估算费用（USD） |

**API 响应变化**（`/api/v1/chat` 等）：
```json
{
  "data": {
    "chosen_strategy": "single",
    "total_latency_ms": 1234.5,
    "total_tokens": 800,
    "total_cost_usd": 0.000456
  }
}
```
> 所有字段均为可选，缺失时不影响现有客户端解析。

