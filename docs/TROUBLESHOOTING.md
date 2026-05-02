# Galaxy 故障排除指南

## 目录

1. [节点启动失败 / 健康检查超时](#节点启动失败--健康检查超时)
2. [降级（Degraded）模式说明](#降级-degraded-模式说明)
3. [节点先决条件](#节点先决条件)
4. [常见错误与解决方案](#常见错误与解决方案)
5. [快速诊断命令](#快速诊断命令)

---

## 节点启动失败 / 健康检查超时

运行 `unified_launcher.py` 时，若控制台输出以下信息，说明对应节点启动失败：

```
节点 Node_XX_XXX 健康检查超时（10 次），视为启动失败
```

### 原因分类

| 原因 | 受影响节点 | 解决方案 |
|------|-----------|---------|
| 缺少 `.env` / API Key 未配置 | Node_01_OneAPI | 以降级模式运行，或配置 `.env` |
| 语言运行时未安装（Windows） | Node_09_Sandbox | 安装缺失的运行时，或接受受限模式 |
| LLM 路由不可达 | Node_110/111/112 | 先启动 Node_01，或接受降级模式 |
| 本地 `core/` 包遮蔽项目 `core` | Node_110/111/112 | 已在 v2.3.x 修复 |

---

## 降级（Degraded）模式说明

Galaxy 中的关键节点支持"降级模式"——即使依赖不满足，节点也会正常启动并通过健康检查，只是部分高级功能受限。

### 各节点降级行为

#### Node_01_OneAPI（端口 7995）

**前提条件（可选）：**
- `OPENROUTER_API_KEY`、`GROQ_API_KEY`、`ZHIPU_API_KEY`、`CLAUDE_API_KEY`、
  `TOGETHER_API_KEY`、`PERPLEXITY_API_KEY` 中至少配置一个
- 或 `LOCAL_LLM_ENABLED=true` 且 Node_79_LocalLLM 正在运行

**降级时行为：**
- 健康检查返回 `{"status": "degraded", ...}`，HTTP 200 ✅
- `/v1/chat/completions` 调用返回错误 `{"error": "No provider available"}`
- 启动日志输出警告：`未检测到任何 API Key，节点以降级模式运行`

**启用完整功能：**
```bash
cp .env.example .env
# 编辑 .env，填入至少一个 API Key
```

#### Node_09_Sandbox（端口 7996）

**前提条件（可选）：**
- `python3`（必须，基础功能）
- `node`（JavaScript）、`ruby`、`php`、`go`、`rustc`、`gcc`、`g++` 等（可选）

**降级时行为：**
- 健康检查始终返回 `{"status": "healthy", ...}`，HTTP 200 ✅
- `available_languages` 列表只包含已安装的运行时
- Windows 上通常只有 `python` 和 `bash` 可用
- 启动日志输出可用语言列表

**扩展语言支持（Windows）：**
- 安装 [Node.js](https://nodejs.org)、[Go](https://go.dev)、[Ruby](https://rubyinstaller.org) 等
- 重启节点，`available_languages` 会自动更新

#### Node_110_SmartOrchestrator（端口 7997）

**前提条件（可选）：**
- Node_01_OneAPI 或其他 LLM 路由正在运行
- 环境变量 `LLM_ROUTER_URL`（默认 `http://localhost:7995`）

**降级时行为：**
- 健康检查返回 `{"status": "healthy", "mode": "degraded", ...}`，HTTP 200 ✅
- 任务编排、工作流管理等核心功能仍可用
- LLM 推理请求返回 mock 响应
- 启动日志输出：`以降级 mock 模式启动`

#### Node_111_ContextManager（端口 7998）

**前提条件（可选）：**
- Node_01_OneAPI 或其他 LLM 路由正在运行
- 环境变量 `LLM_ROUTER_URL`（默认 `http://localhost:7995`）

**降级时行为：**
- 健康检查返回 `{"status": "healthy", "mode": "degraded", ...}`，HTTP 200 ✅
- 上下文管理（内存存储）仍可用
- 不依赖 LLM 的功能不受影响
- 启动日志输出：`以降级 mock 模式启动`

#### Node_112_SelfHealing（端口 7999）

**前提条件（可选）：**
- Node_01_OneAPI 或其他 LLM 路由正在运行
- 环境变量 `LLM_ROUTER_URL`（默认 `http://localhost:7995`）

**降级时行为：**
- 健康检查返回 `{"status": "healthy", "mode": "degraded", ...}`，HTTP 200 ✅
- 自愈引擎（规则模式）正常运行
- LLM 驱动的智能诊断暂不可用，回退到基于规则的诊断
- 启动日志输出：`以降级模式启动`

---

## 节点先决条件

### 最小化启动（无需任何配置）

所有上述节点在不配置 `.env` 的情况下均可启动，只是以降级模式运行：

```bash
# 直接启动，无需 .env
python unified_launcher.py
```

预期输出：
```
⚠️  Node_01_OneAPI 以 degraded 模式启动 — 部分功能可能受限，但不影响系统启动
✅  Node_09_Sandbox 健康检查通过
⚠️  Node_110_SmartOrchestrator 以 degraded 模式启动 — 部分功能可能受限，但不影响系统启动
⚠️  Node_111_ContextManager 以 degraded 模式启动 — 部分功能可能受限，但不影响系统启动
⚠️  Node_112_SelfHealing 以 degraded 模式启动 — 部分功能可能受限，但不影响系统启动
```

### 完整功能启动

```bash
cp .env.example .env
# 编辑 .env，配置所需 API Key
python unified_launcher.py
```

### 推荐的启动顺序

如果手动启动各节点，建议按以下顺序：

1. `Node_00_StateMachine`（状态机，核心依赖）
2. `Node_01_OneAPI`（LLM 路由，其他节点的依赖）
3. `Node_09_Sandbox`、`Node_110_SmartOrchestrator`、`Node_111_ContextManager`、`Node_112_SelfHealing`（可并行）

---

## 常见错误与解决方案

### `ModuleNotFoundError: No module named 'core.port_config'`

**原因：** Node_110/111/112 各自有 `core/` 子目录，运行时遮蔽了项目根目录的 `core` 包。

**解决方案（已在 v2.3.x 自动修复）：**
各节点 `main.py` 顶部已添加 `sys.path` 修正代码，确保项目根目录优先。

手动解决（如遇旧版本）：
```bash
PYTHONPATH=/path/to/project/root python3 nodes/Node_110_SmartOrchestrator/main.py
```

### 健康检查超时（旧版 Node_01_OneAPI）

**原因：** 旧版本在 `/health` 端点中使用同步 `requests.get()` 调用本地 LLM，阻塞事件循环。

**解决方案（已在 v2.3.x 修复）：**
- 本地 LLM 探测移至 `lifespan` 启动阶段（非阻塞异步）
- `/health` 端点直接返回缓存状态，无阻塞调用

### 健康检查超时（旧版 Node_09_Sandbox，Windows）

**原因：** 旧版本在 `/health` 端点中对每种语言运行 `subprocess.run(timeout=5)`，
在 Windows 上多语言检测可能累计耗时 60+ 秒，超过启动器的 30 秒超时。

**解决方案（已在 v2.3.x 修复）：**
- 语言可用性检测移至 `lifespan` 启动阶段（并行、1 秒超时）
- `/health` 端点直接返回缓存结果

---

## 快速诊断命令

```bash
# 检查节点状态
curl http://localhost:7995/health  # Node_01_OneAPI
curl http://localhost:7996/health  # Node_09_Sandbox
curl http://localhost:7997/health  # Node_110_SmartOrchestrator
curl http://localhost:7998/health  # Node_111_ContextManager
curl http://localhost:7999/health  # Node_112_SelfHealing

# 检查 Python 路径（排查 core 包遮蔽问题）
cd nodes/Node_110_SmartOrchestrator
python3 -c "import sys; print(sys.path[:3]); from core.port_config import get_node_port; print('OK')"

# 检查 .env 配置
python3 -c "
from dotenv import dotenv_values
cfg = dotenv_values('.env')
llm_keys = [k for k in cfg if 'API_KEY' in k and cfg[k]]
print(f'已配置 {len(llm_keys)} 个 API Key: {llm_keys}')
"
```
