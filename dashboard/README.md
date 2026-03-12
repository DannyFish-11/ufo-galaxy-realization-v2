# Galaxy Dashboard

可视化管理界面 - 监控、管理和控制整个 Galaxy 系统

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

### 6. Agent 权限管理（P0 新增）

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

后端将在 `http://localhost:8085` 启动。

### 2. 访问前端

直接在浏览器中打开：
```
http://localhost:8085/
```

前端 `index.html` 由后端静态文件路由直接提供服务，无需单独的 HTTP 服务器。

> 如果仅需本地预览，也可通过简单 HTTP 服务器：
> ```bash
> cd dashboard/frontend/public
> python -m http.server 8081
> ```
> 然后访问 `http://localhost:8081`（此模式下 API 调用需后端同时运行）。

### 3. 构建 TypeScript 前端（可选）

TypeScript 源码位于 `dashboard/frontend/ts/`，编译产物输出到 `dist/`。

```bash
cd dashboard/frontend
npm install       # 安装依赖（vue、axios、typescript 等）
npm run build     # 编译 TypeScript
```

## WebSocket 实时连接

后端 WebSocket 端点：`ws://localhost:8085/ws`

前端 TypeScript 客户端示例（`dashboard/frontend/ts/api.ts`）：

```typescript
import { GalaxyAPI } from './api';

const api = new GalaxyAPI('http://localhost:8085');
api.connectWebSocket((msg) => {
  console.log('WS message:', msg);
});
api.sendWSMessage({ type: 'ping' });
```

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
POST /api/v1/devices/{id}/command # 发送设备命令
```

### Agent 管理
```
GET /api/v1/agents                # 获取 Agent 列表
GET /api/v1/llm/providers         # 获取 LLM 提供商列表
```

### 聊天
```
POST /api/v1/chat                 # 统一聊天入口
POST /api/v1/dashboard/chat       # 仪表盘聊天（与上同功能）
```

### 多设备并行执行
```
POST /api/v1/execute/parallel     # 并行执行多设备命令
```

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
- FastAPI - Web 框架（端口 8085）
- httpx - HTTP 客户端
- WebSocket - 实时通信

### 前端
- Vue 3 - 前端框架（CDN 加载）
- Tailwind CSS - UI 样式（CDN 加载）
- Axios - HTTP 客户端（CDN 加载）
- TypeScript - 类型安全客户端（`ts/` 目录）

## 开发

### 添加新功能

1. 在 `backend/main.py` 添加 API 端点
2. 在 `frontend/ts/types.ts` 更新类型定义
3. 在 `frontend/ts/api.ts` 更新客户端方法
4. 在 `frontend/public/index.html` 添加 UI 组件
5. 测试并提交

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

### 本地运行

```bash
# 从仓库根目录运行（无需外部服务）
pip install pytest httpx fastapi
pytest tests/test_e2e_stack.py -v
```

## 许可证

MIT License

