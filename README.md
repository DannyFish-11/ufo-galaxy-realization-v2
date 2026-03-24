# Galaxy 节点实现

本目录包含Galaxy系统的P0级优先节点实现。

---

## ✅ 快速验证 / Quick Validation (PR-9)

After the PR-1 through PR-8 structural cleanup, use these commands to confirm
the authoritative runtime system is coherent:

```bash
# Validate startup path, authority chain, node registry, legacy isolation, docs
python scripts/validate_runtime.py

# JSON output (for CI integration)
python scripts/validate_runtime.py --json

# Run the integration validation test suite
pytest tests/test_pr9_integration_validation.py -v
```

For the authoritative maintainer reference see:
**[docs/MAINTAINER_RUNBOOK.md](docs/MAINTAINER_RUNBOOK.md)**

---

## 🧠 统一主体架构 (Unified Subject Architecture)

> **核心原则**: `DesktopPresenceRuntime` 和 `OpenClawd` **不是**两个并列主体，而是**同一个主体的两层**。

```
UFO Galaxy 主体 = DesktopPresenceRuntime (外壳) + OpenClawd (内核)

DesktopPresenceRuntime  ← Windows 桌面运行时壳 / "衣服"
    ├─ 持有三态生命周期: silent → liminal → manifest → silent
    ├─ 持有 runtime_session_id (全链路关联 ID)
    ├─ 持有原生多模态输入 (MultimodalIngressBus → PerceptionFrame)
    └─ 在 LIMINAL 内调用 OpenClawd

OpenClawd  ← 主体认知/执行核心
    ├─ 阶段 1: Ingest (多模态上下文融合)
    ├─ 阶段 2: Continuum/认知 (ContinuumOrchestrator)
    ├─ 阶段 3: Branch (local / cross_device / hybrid / none)
    └─ 阶段 4: Manifest (DecisionExecutor / CommandRouter)
```

**三套状态系统（不可混淆）**:
1. 三态生命周期 `silent/liminal/manifest` → `DesktopPresenceRuntime` (主体状态)
2. Continuum 姿态 `tri_state_phase + runtime_domain` → `OpenClawd` 内部协议
3. UI 壳展开模式 `DORMANT/ISLAND/SIDESHEET/FULLAGENT` → `system_integration/` (桌面"衣服"呈现)

详见: [`docs/UNIFIED_SUBJECT_ARCHITECTURE.md`](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)

---

## 🎯 系统架构 (Round 2 - R-4)

### 能力注册与发现系统 (OpenClaw 风格)

Galaxy 现已集成**统一能力注册和发现系统**，提供：

- **能力注册**：节点启动时自动注册能力到中央索引
- **能力发现**：通过名称、分类或节点查询可用能力
- **状态跟踪**：实时监控能力状态（在线/离线/错误）
- **持久化存储**：能力信息保存到 `config/capabilities.json`

### 稳定连接管理 (向日葵风格)

系统内置**连接管理器**，确保节点间通信稳定：

- **心跳保活**：自动心跳机制，检测连接健康
- **自动重连**：断线后指数退避重连策略
- **健康监控**：实时连接状态报告
- **故障恢复**：智能重试和故障转移

### 统一运行时流程

```
配置加载 → 能力注册 → 节点启动 → 连接初始化 → 健康监控
    ↓           ↓           ↓            ↓            ↓
  环境变量   能力索引   进程管理    心跳/重连    状态报告
```

**核心组件**：
- `core/capability_manager.py` - 能力管理器
- `core/connection_manager.py` - 连接管理器  
- `core/node_registry.py` - 节点注册表（已增强）
- `system_manager.py` - 系统管理器（已集成）
- `health_monitor.py` - 健康监控（已集成）

### 三闭环自治能力（已打通）

系统已实现并打通以下三条自治闭环：

1. **自愈 → 自编程 → 验证**
   - Node_112 检测异常并诊断问题
   - AutoFixer 触发 `FixAction.CODE_FIX`
   - AutonomousCoder 生成修复并在沙箱测试
   - 通过后自动提交并由 Node_112 验证修复

2. **学习 → 决策权重反馈**
   - LearningOptimizer 产出性能洞察
   - Planner 通过 `update_decision_weights` 调整策略权重
   - 下一次路由优先使用新的策略

3. **能力缺口 → 自动扩展**
   - AutonomousCoder 生成新节点代码
   - 自动注册到 NodeFactory 与 CapabilityManager
   - 能力索引更新后可自动路由新节点

**验证工具**：
```bash
# 验证能力注册系统
python scripts/verify_capability_registry.py

# 运行集成测试
python tests/test_capability_integration.py
```

---

## 🧠 B 阶段：SOUL 全局约束 + 模板蓝图双层约束

### SOUL 全局生效（1B）

SOUL（`SOUL.md` 中定义的人格与能力边界策略）现在在**全执行链路中全局生效**：

| 执行路径 | SOUL 注入位置 |
|---------|-------------|
| 单 Agent（`_run_single_agent`） | `create_from_llm` prompt 前置注入 + `task_dict.context.soul` |
| Team / Swarm（`_run_team`） | 每个成员 LLM 调用的 `system` 消息前缀 |
| Fractal（`_run_fractal`） | 根 Agent 原子执行 system prompt + 子任务 context 继承 |

主控 Agent 的 SOUL 通过 `ExecutionPlan.soul_policy` 传递到 `context["soul"]`，
子 Agent（Team 成员 / Fractal 子 Agent）从 `context` 中读取并注入自身 system prompt，
实现 **planner → agent_factory → agent_team → fractal** 全链路 SOUL 约束。

### 模板蓝图双层约束（2C）

Agent 配置生成时采用**前置提示约束 + 后置 schema 校验**双层机制：

**第一层 — 生成前（pre-generation）**  
在 `AgentFactory._build_agent_generation_prompt` 中，将 SOUL 约束和模板 schema 硬规则
以结构化文本注入 LLM prompt，要求 LLM 严格遵守输出格式。

**第二层 — 生成后（post-generation）**  
`AgentFactory._validate_agent_config(result)` 对 LLM 输出做结构校验：
- `role` 必须是以下之一：`coordinator` / `executor` / `analyst` / `planner` / `monitor` / `communicator` / `specialist`
- `name` / `system_prompt` 必须是非空字符串
- `capabilities` 数组中每项必须含 `name`，`strength` 须在 [0.0, 1.0]
- `max_subtasks` 须在 [1, 50]，`max_depth` 须在 [1, 5]

校验失败时**自动回退到模板兜底**，维持现有 LLM-first 逻辑不变。

### 路由器保持自由（3B）

不新增角色-工具-模型白名单。Multi-LLM Router 继续使用"任务类型 + 成本"规则护栏进行自由路由。

### ExecutionResult 调试字段

`ExecutionResult` 新增可选字段 `soul_enforced: Optional[bool]`：
- 执行时有 SOUL 策略 → `True`
- 执行时无 SOUL 策略 → `False`
- 旧代码不提供该字段 → 默认 `None`（向后兼容）

### 验证测试

```bash
# 运行 B 阶段所有验证测试
python -m pytest tests/test_soul_blueprint_b_stage.py -v
```

涵盖：schema 校验单元测试 · SOUL prompt 注入 · 校验失败回退 · Team/Swarm/Fractal SOUL 传播 · `soul_enforced` 字段向后兼容性

---

## 🔄 三大自主循环 (Three Autonomous Loops)

Galaxy 内置三条端到端自主循环，实现系统自愈、持续学习和能力扩展：

### Loop 1 — 自愈 → 代码修复 → 验证 (Self-Heal → Code-Fix → Verify)

**关键文件**：`nodes/Node_112_SelfHealing/main.py`

```
异常检测
   ↓
自动诊断
   ↓
确定修复动作 → FixAction.CODE_FIX
                      ↓
       AutonomousCoder.generate_and_execute()
                      ↓
            沙箱测试执行 → 自动提交(通过时)
                      ↓
                   验证完成
```

- `FixAction.CODE_FIX` 枚举值：当诊断建议包含代码修复关键词时触发
- `AutoFixer._determine_action()` 根据推荐内容中的关键词（`_CODE_FIX_KEYWORDS`）决策
- `AutoFixer._code_fix()` 调用 `AutonomousCoder.generate_and_execute()` 执行代码修复
- `psutil` 使用可选导入（`try/except ImportError`），不影响测试收集

### Loop 2 — 学习 → 决策权重更新 → 路由优化 (Learning → Weight Update → Routing)

**关键文件**：`enhancements/reasoning/autonomous_planner.py`、`galaxy_main_loop_l4.py`

```
执行结果记录
      ↓
LearningOptimizer.analyze_performance()
      ↓
generate_optimization_plan()
      ↓
apply_optimization()
      ↓
AutonomousPlanner.update_decision_weights(performance_metrics)
      ↓
资源 availability 调整
      ↓
影响下一次路由决策
```

- `AutonomousPlanner.update_decision_weights(metrics)` 根据平均成功率调整资源可用性
  - 成功率 > 0.8：availability × 1.05（上限 1.0）
  - 成功率 < 0.5：availability × 0.9（下限 0.1）
- `GalaxyMainLoopL4._perform_optimization()` 在每次优化周期末调用该方法，形成闭环

### Loop 3 — 能力缺口 → 自动扩展 → 即时路由 (Capability Gap → Auto-Expand → Route)

**关键文件**：`enhancements/reasoning/autonomous_coder.py`

```
检测能力缺口
      ↓
AutonomousCoder.generate_and_execute(task, target_type='node')
      ↓
_deploy_as_node(code, task)
      ↓                         ↓
NodeFactory.register_node()   CapabilityManager.register_capability()
      ↓                         ↓
节点索引更新               能力索引更新（可被路由发现）
      ↓
新节点无需人工干预即可被路由
```

- 生成代码后自动调用 `get_node_factory().register_node()`
- 同步调用 `get_capability_manager().register_capability()` 更新能力索引
- 两步注册均为非致命操作（失败时仅记录警告，不中断流程）

### 运行三循环测试

```bash
python -m pytest tests/test_autonomous_loops.py -v
# 预期输出: 17 passed
```

---

## 已实现的节点列表

### 第一优先级 - 基础服务节点

| 节点 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_02_Tasker | 任务调度器 | 8002 | 任务队列、定时任务、状态跟踪 |
| Node_03_SecretVault | 密钥管理 | 8003 | 密钥存储、加密解密、密钥轮换 |
| Node_05_Auth | 认证服务 | 8005 | 用户认证、JWT令牌、权限控制 |
| Node_06_Filesystem | 文件系统 | 8006 | 文件读写、目录管理、压缩解压 |

### 第二优先级 - 数据库节点

| 节点 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_12_Postgres | PostgreSQL | 8012 | PostgreSQL连接、查询、事务 |
| Node_13_SQLite | SQLite | 8013 | SQLite数据库操作 |
| Node_20_Qdrant | 向量数据库 | 8020 | 向量存储、相似度搜索 |

### 第三优先级 - 工具节点

| 节点 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_14_FFmpeg | 视频处理 | 8014 | 视频转码、剪辑、截图 |
| Node_16_Email | 邮件服务 | 8016 | SMTP邮件发送、模板 |
| Node_17_EdgeTTS | 语音合成 | 8017 | 文本转语音 |
| Node_18_DeepL | 翻译服务 | 8018 | 文本翻译 |
| Node_19_Crypto | 加密服务 | 8019 | 加密解密、哈希、签名 |

### 第四优先级 - 搜索节点

| 节点 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_22_BraveSearch | Brave搜索 | 8022 | 网页搜索、图片搜索 |
| Node_25_GoogleSearch | Google搜索 | 8025 | Google搜索 |

### 第五优先级 - 时间和天气节点

| 节点 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_123_Calendar | 日历服务 | 8123 | 日历管理、事件创建 |
| Node_23_Time | 时间服务 | 8123 | 时间查询、时区转换 |
| Node_24_Weather | 天气查询 | 8024 | 天气查询、预报 |

### 第六优先级 - 设备控制节点

| 节点 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_39_SSH | SSH连接 | 8039 | SSH连接、命令执行 |
| Node_41_MQTT | MQTT消息队列 | 8041 | MQTT发布订阅 |

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行节点

```bash
# 进入节点目录
cd nodes/Node_02_Tasker

# 运行节点
python main.py
```

### 环境变量配置

```bash
# Node 03: SecretVault
export SECRETVAULT_MASTER_KEY="your-master-key"

# Node 05: Auth
export AUTH_JWT_SECRET="your-jwt-secret"

# Node 12: PostgreSQL
export POSTGRES_HOST="localhost"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD="your-password"
export POSTGRES_DATABASE="postgres"

# Node 16: Email
export SMTP_HOST="smtp.gmail.com"
export SMTP_USER="your-email@gmail.com"
export SMTP_PASSWORD="your-password"

# Node 18: DeepL
export DEEPL_API_KEY="your-api-key"

# Node 22: BraveSearch
export BRAVE_API_KEY="your-api-key"

# Node 24: Weather
export OPENWEATHER_API_KEY="your-api-key"

# Node 25: GoogleSearch
export GOOGLE_API_KEY="your-api-key"
export GOOGLE_CSE_ID="your-cse-id"

# Node 41: MQTT
export MQTT_BROKER="localhost"
export MQTT_PORT="1883"
```

## API文档

每个节点都提供以下标准端点：

- `GET /health` - 健康检查
- 各节点特有的功能端点

启动节点后，访问 `http://localhost:{port}/docs` 查看完整的API文档（Swagger UI）。

## 节点结构

每个节点包含以下文件：

```
Node_XX_Name/
├── main.py          # 主要业务逻辑 (required)
├── fusion_entry.py  # 融合入口文件 (required)
├── README.md        # 节点说明 (required)
├── requirements.txt # Python 依赖 (required for active nodes)
└── Dockerfile       # 容器化支持 (required for active nodes)
```

A ready-to-copy template is provided at `templates/node_template/`.
The full node contract (baseline vs active requirements, port registration,
health/status surface) is documented in `CONTRIBUTING.md § Canonical Node Contract`
and `docs/MAINTAINER_RUNBOOK.md § 8a`.

## 依赖说明

- **必需依赖**: fastapi, uvicorn, pydantic
- **数据库节点**: asyncpg (PostgreSQL), qdrant-client (Qdrant)
- **加密节点**: cryptography
- **语音节点**: edge-tts
- **SSH节点**: asyncssh
- **MQTT节点**: paho-mqtt

## 相关仓库

| 仓库 | 职责 | 说明 |
|------|------|------|
| [galaxy-android](https://github.com/DannyFish-11/galaxy-android) | **唯一 Android 真相源** | 打包 APK，实现 Android 客户端 UI 和 Agent |
| galaxy-realization-v2（本仓库） | **服务端 + 桥接 + VLM** | 接收 APK 连接，提供 AI 推理和节点调度 |

### 架构示意图

```
独立仓库(APK)
  DannyFish-11/galaxy-android
        │
        │  WebSocket (AIP v3.0)
        │  ws://<host>:8765/ws/android
        ▼
galaxy_gateway/android_bridge.py   ← 桥接层（本仓库）
        │
        │  HTTP
        ▼
Node_113_AndroidVLM                ← VLM 分析节点（本仓库）
```

协议详细说明见 [docs/ANDROID_PROTOCOL_ALIGNMENT.md](docs/ANDROID_PROTOCOL_ALIGNMENT.md)。

## 安全扫描 / Security Scanning

项目已集成 **GitHub CodeQL** 静态安全分析（见 `.github/workflows/codeql.yml`），
在每次推送 `main` 分支及 PR 时自动运行 Python 代码安全扫描。

**本地运行静态检查：**

```bash
# 安装开发依赖
pip install -r requirements-dev.txt

# Flake8 代码风格与错误检查
flake8 core/ --max-line-length=120

# Black 格式化检查
black --check core/ tests/

# isort 导入顺序检查
isort --check-only core/ tests/
```

详细 UI 资产来源与入口路径说明见 [UI_ASSETS.md](UI_ASSETS.md)。

## 许可证

MIT License
