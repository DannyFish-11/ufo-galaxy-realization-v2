# Galaxy — 桌面原生 AI 助手系统

> **官方文档 v10.0** | **更新日期**: 2026-05-31 | **代码规模**: ~74万行 Python (1,683 文件) | **节点**: 133 个

---

## 目录

1. [系统概述](#1-系统概述)
2. [架构总览](#2-架构总览)
3. [核心子系统](#3-核心子系统)
4. [节点系统](#4-节点系统)
5. [Electron 桌面覆盖层](#5-electron-桌面覆盖层)
6. [API 参考](#6-api-参考)
7. [配置参考](#7-配置参考)
8. [部署指南](#8-部署指南)
9. [故障排除](#9-故障排除)
10. [版本历史](#10-版本历史)

---

## 1. 系统概述

### 1.1 简介

Galaxy 是一个**桌面原生 AI 助手操作系统**，通过 Electron 三态覆盖层直接在用户桌面上提供 AI 交互能力。系统围绕 **OpenClawd**（认知核心）和 **DesktopPresenceRuntime**（桌面运行时）构建，形成统一的主体架构。

### 1.2 核心特征

| 特征 | 说明 |
|------|------|
| **本地多模态 AI** | Google Gemma 4 E4B (128K 上下文)，显存 ~5GB |
| **模型宕机保护** | 四级级联回退：Ollama → DeepSeek → OpenRouter → Groq |
| **持久对话** | 上下文压缩 + SQLite 记忆召回，理论上无限对话长度 |
| **三态交互** | SILENT (静默) → LIMINAL (处理中) → MANIFEST (结果展示) |
| **远程服务器** | SSH 远程操作，支持华为云/阿里云等任意 Linux 服务器 |
| **沙箱安全** | 危险命令黑名单 + PolicyGate 应用白名单 |
| **133 个节点** | 覆盖数据库、搜索、媒体、智能家居、物理设备等 |
| **Skill 系统** | 动态加载自定义技能包 |
| **DAG 编排** | StarSplit + 预测性调度 + 不变量验证 |

### 1.3 代码规模

| 指标 | 数值 |
|------|------|
| 核心代码 (core+gateway+nodes+enhancements+skills+launcher) | ~663,105 行 (1,530 文件) |
| **Android 客户端** | **~283,378 行 Kotlin (200+ 文件)** |
| 节点数量 | 133 个 |
| 路由端点总数 | ~300+ 个 |
| 文档数量 | 206 个 Markdown |
| Docker 服务 | 17 个 |
| 核心子系统 | 50+ 个 |

### 1.4 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Electron + Three.js + WebGL (CRT 扫描线效果) |
| 后端 | FastAPI + Uvicorn + WebSocket |
| AI 模型 | Google Gemma 4 / DeepSeek / OpenRouter / Groq |
| 数据库 | PostgreSQL + SQLite + Qdrant (向量) + Neo4j (图) + MongoDB |
| 缓存 | Redis |
| 消息队列 | NATS JetStream |
| 容器 | Docker + Docker Compose |
| 工作流 | Temporal |
| 监控 | Grafana |

---

## 2. 架构总览

### 2.1 系统架构图

```
                                用户桌面
                                   │
                    ┌──────────────┴──────────────┐
                    │     Electron 桌面覆盖层      │
                    │                              │
                    │  ┌──────────────────────┐   │
                    │  │   mainWindow         │   │
                    │  │   (全屏透明覆盖层)    │   │
                    │  │                      │   │
                    │  │   SILENT  ──► LIMINAL │  │   Ctrl+Space 唤醒
                    │  │             ──► MANIFEST│ │   Esc 关闭
                    │  │                      │   │
                    │  │   WebSocket          │   │
                    │  │   ws://localhost:8765│   │
                    │  └──────────────────────┘   │
                    │                              │
                    │  ┌──────────────────────┐   │
                    │  │   panelWindow (F12)  │   │
                    │  │   维态/星元/设置      │   │
                    │  │   STANDBY + 三态点    │   │
                    │  └──────────────────────┘   │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │     Galaxy Gateway          │
                    │     (FastAPI :8765)         │
                    │                             │
                    │  REST API: /api/v1/*        │
                    │  WebSocket: /ws/*           │
                    │                             │
                    │  ┌─────────────────────┐    │
                    │  │   OpenClawd 认知核心 │    │
                    │  │   (Continuum 编排)   │    │
                    │  └─────────────────────┘    │
                    │                             │
                    │  ┌─────────────────────┐    │
                    │  │   能力注册中心        │    │
                    │  │   (133 个节点)       │    │
                    │  └─────────────────────┘    │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼─────────┐ ┌───▼──────────┐ ┌──▼─────────────┐
    │   本地模型         │ │   云端兜底    │ │   基础设施      │
    │                    │ │              │ │                │
    │   Ollama           │ │   DeepSeek   │ │   PostgreSQL   │
    │   Gemma 4 E4B      │ │   OpenRouter │ │   Redis        │
    │   (128K 上下文)    │ │   Groq       │ │   Qdrant       │
    │                    │ │              │ │   Neo4j        │
    └────────────────────┘ └──────────────┘ └────────────────┘
```

### 2.2 统一主体架构

Galaxy 的核心哲学是**统一主体**：

```
UFO Galaxy 主体 = DesktopPresenceRuntime (外壳) + OpenClawd (内核)

DesktopPresenceRuntime  ← Windows 桌面运行时壳 / "衣服"
    ├─ 持有三态生命周期: silent → liminal → manifest
    ├─ 持有 runtime_session_id (全链路关联 ID)
    ├─ 持有原生多模态输入 (MultimodalIngressBus)
    └─ 在 LIMINAL 内调用 OpenClawd

OpenClawd  ← 主体认知/执行核心
    ├─ 阶段 1: Ingest (多模态上下文融合)
    ├─ 阶段 2: Continuum/认知 (ContinuumOrchestrator)
    ├─ 阶段 3: Branch (local / cross_device / hybrid / none)
    └─ 阶段 4: Manifest (DecisionExecutor / CommandRouter)
```

**三套状态系统**（不可混淆）：

1. **三态生命周期** `silent/liminal/manifest` → DesktopPresenceRuntime (主体状态)
2. **Continuum 姿态** `tri_state_phase + runtime_domain` → OpenClawd 内部协议
3. **UI 壳展开模式** `DORMANT/ISLAND/SIDESHEET/FULLAGENT` → 桌面呈现

### 2.3 目录结构

```
ufo-galaxy/
│
├── main.py                          # 系统主入口/编排器
├── unified_launcher.py              # 统一启动器 (L4增强)
├── launch_desktop.py                # 桌面一体化启动器
├── requirements.txt                 # Python 依赖
├── .env.example                     # 环境变量模板
├── docker-compose.yml               # Docker 编排
├── SOUL.md                          # 人格与能力边界策略
│
├── core/                            # 核心引擎 (~50 子系统)
│   ├── ai_intent.py                 # AI 意图解析
│   ├── context_compressor.py        # 上下文压缩(突破128K)
│   ├── desktop_presence_runtime.py  # 桌面运行时
│   ├── state_event_bus.py           # 状态事件总线
│   ├── skill_loader.py              # Skill 加载器
│   ├── skill_registry.py            # Skill 注册表
│   ├── dag_starsplit.py             # DAG StarSplit
│   ├── dag_predictive_scheduler.py  # DAG 预测调度
│   ├── dag_invariant_verifier.py    # DAG 不变量验证
│   ├── hidden_context_visible_action_surface.py  # 隐蔽上下文
│   ├── execution/                   # 执行引擎
│   │   └── decision_executor.py     # 决策执行器(PolicyGate)
│   ├── routes/                      # 核心路由 (43 模块)
│   ├── schemas/                     # 数据模型 (21 文件)
│   ├── llm/                         # LLM 路由拓扑
│   ├── multimodal/                  # 多模态处理 (19 文件)
│   ├── mesh/                        # 设备网格 (15 文件)
│   ├── model_topology/              # 模型拓扑 (13 文件)
│   ├── unified/                     # 统一运行时 (20 文件)
│   ├── orchestration/               # 编排 (10 文件)
│   ├── cognitive/                   # 认知引擎 (11 文件)
│   ├── continuum/                   # Continuum (12 文件)
│   └── ... (50+ 子系统)
│
├── galaxy_gateway/                  # API 网关
│   ├── app.py                       # FastAPI 应用
│   ├── gateway_service.py           # 网关服务入口
│   ├── enhanced_nlu_v2.py          # NLU引擎(Gemma4+回退)
│   ├── routes/                      # 网关路由
│   │   ├── health.py               # 健康检查 (6端点)
│   │   ├── devices.py              # 设备管理 (7端点)
│   │   ├── tasks.py                # 任务调度 (5端点)
│   │   ├── sessions.py             # Session (4端点)
│   │   ├── chat.py                 # 对话 (2端点)
│   │   ├── llm.py                  # LLM调用 (1端点)
│   │   ├── linux_agent.py          # Linux Agent (9端点) [新增]
│   │   ├── sandbox.py              # 沙箱 (3端点) [新增]
│   │   └── android_vlm.py          # Android VLM (4端点)
│   ├── websocket.py                # WebSocket处理器
│   └── bootstrap/                  # 启动引导
│
├── electron/                        # 桌面应用
│   ├── main.js                      # Electron主进程
│   ├── preload.js                   # 预加载脚本
│   ├── package.json                 # 依赖配置
│   └── renderer/                    # 渲染进程
│       ├── index.html               # 主入口
│       ├── app.js                   # 三态管理核心
│       ├── silent-state.js          # SILENT态
│       ├── liminal-state.js         # LIMINAL态
│       ├── manifest-state.js        # MANIFEST态
│       ├── three-scene.js           # Three.js 3D场景
│       ├── style.css                # 样式
│       ├── shaders/                 # WebGL着色器
│       │   ├── crt.frag            # CRT扫描线
│       │   ├── liminal.frag        # LIMINAL效果
│       │   └── liminal.vert        # LIMINAL顶点
│       └── panel/                   # 控制面板(v38)
│           ├── index.html           # Vite入口
│           ├── glass_panel_bg.png  # 雨滴背景
│           └── assets/              # 编译产物
│
├── nodes/                           # 133 个节点
│   ├── Node_Linux_Agent/           # [新增]远程Linux
│   ├── Node_Tavily_Search/         # [新增]AI搜索
│   ├── Node_80_KnowledgeBase/      # [新增]混合知识库
│   ├── Node_01_OneAPI/             # API网关
│   ├── Node_02_Tasker/             # 任务调度
│   ├── Node_03_SecretVault/        # 密钥管理
│   ├── Node_05_Auth/               # 认证
│   ├── Node_06_Filesystem/         # 文件系统
│   ├── Node_09_Sandbox/            # 沙箱执行
│   ├── Node_10_Slack/              # Slack
│   ├── Node_12_Postgres/           # PostgreSQL
│   ├── Node_14_FFmpeg/             # 视频处理
│   ├── Node_20_Qdrant/             # 向量数据库
│   ├── Node_22_BraveSearch/        # Brave搜索
│   ├── Node_24_Weather/            # 天气
│   ├── Node_33_ADB/                # Android ADB
│   ├── Node_34_Scrcpy/             # Scrcpy投屏
│   ├── Node_100_MemorySystem/      # 记忆系统
│   ├── Node_112_SelfHealing/       # 自愈
│   ├── Node_113_AndroidVLM/        # AndroidVLM
│   ├── Node_118_NodeFactory/       # 节点工厂
│   └── ... (133个)
│
├── skills/                          # Skill系统
│   └── examples/                    # 示例Skill
│
├── docs/                            # 文档 (206个Markdown)
│   ├── CLONE_TO_USE_REALITY.md
│   ├── CLONE_TO_USE_DESKTOP.md
│   ├── UNIFIED_SUBJECT_ARCHITECTURE.md
│   ├── DEPLOYMENT_SURFACES.md
│   ├── MAINTAINER_RUNBOOK.md
│   └── ...
│
├── tests/                           # 测试
├── deploy/                          # 部署脚本
├── config/                          # 配置
├── data/                            # 数据目录
├── external/                        # 外部集成
├── mcp_bridge/                      # MCP桥接
└── enhancements/                    # 增强模块
```

---

## 3. 核心子系统

### 3.1 OpenClawd 认知核心

OpenClawd 是系统的认知和执行核心，采用 Continuum 编排模式：

| 阶段 | 职责 | 关键文件 |
|------|------|----------|
| **Ingest** | 多模态上下文融合 | `core/multimodal/` |
| **Continuum** | 认知编排 | `core/continuum/` |
| **Branch** | 执行分支决策 | `core/orchestration/` |
| **Manifest** | 结果呈现 | `core/execution/decision_executor.py` |

### 3.2 DesktopPresenceRuntime

桌面运行时，管理三态生命周期：

| 状态 | 视觉 | 触发 | 文件 |
|------|------|------|------|
| **SILENT** | 静默，边缘呼吸灯 | 系统空闲 | `silent-state.js` |
| **LIMINAL** | 半透明覆盖层，白色脉冲 | AI处理中 | `liminal-state.js` |
| **MANIFEST** | CRT扫描线+结果面板 | AI返回结果 | `manifest-state.js` |

### 3.3 能力注册中心

133 个节点通过统一能力注册中心自动发现和调用：

```
能力注册 → 能力发现 → 状态跟踪 → 持久化存储
    ↓          ↓           ↓            ↓
config/    名称/分类    在线/离线   capabilities.json
```

### 3.4 上下文压缩系统

突破模型 128K 上下文窗口限制：

| 机制 | 说明 | 代码 |
|------|------|------|
| 滑动窗口 | 保留最近 6 轮对话 | `ContextCompressor` |
| 自动摘要 | 超过 60K tokens 自动压缩 | `_generate_summary()` |
| 记忆召回 | 从 SQLite 检索相关历史 | `_recall_from_memory()` |
| 记忆上限 | 短期 100 条，长期受限于硬盘 | `MAX_SHORT_TERM_SIZE=100` |

### 3.5 DAG 动态编排

| 组件 | 功能 | 文件 |
|------|------|------|
| **StarSplit** | 自动检测并行任务，最大拆分 8 个子任务 | `dag_starsplit.py` |
| **预测性调度** | Welford 在线算法学习历史执行时间 | `dag_predictive_scheduler.py` |
| **不变量验证** | I1(依赖存在) I2(无环) I3(参数一致) | `dag_invariant_verifier.py` |

### 3.6 沙箱安全系统

双层安全：

**第一层 — PolicyGate（应用启动）**
- 白名单: `chrome`, `firefox`, `code`, `terminal`
- 危险命令模式黑名单: 16 种模式
- Shell 元字符检测: `;|&$(){}[]<>#!`

**第二层 — 沙箱执行**
- 危险命令黑名单: `rm -rf`, `dd`, `mkfs`, `fdisk`, fork bomb 等
- 资源限制: 内存 256MB, CPU 30 秒超时
- 子进程隔离: 临时目录 + preexec_fn

### 3.7 隐蔽上下文

记忆和推理在 BACKGROUND_SEMANTIC 层，默认对用户不可见：

| 层级 | 内容 | 可见性 |
|------|------|--------|
| BACKGROUND_SEMANTIC | working_memory, long_term_memory, internal_reasoning | **默认隐藏** |
| FOREGROUND_PRESENCE_ACTION | 三态显示, action_state, result_artifacts | 用户可见 |
| OPERATOR_AUDIT_TRUTH | decision_reasoning, truth_source | 仅审计 |

---

## 4. 节点系统

### 4.1 节点分类

系统包含 **133 个节点**，按功能分类：

#### 基础服务 (0-9)

| 编号 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_00 | StateMachine | — | 状态机引擎 |
| Node_01 | OneAPI | 3000 | API 网关聚合 |
| Node_02 | Tasker | 8002 | 任务队列、定时任务 |
| Node_03 | SecretVault | 8003 | 密钥管理、加密解密 |
| Node_04 | Router | — | 智能路由 |
| Node_05 | Auth | 8005 | 用户认证、JWT |
| Node_06 | Filesystem | 8006 | 文件读写、目录管理 |
| Node_07 | Git | — | Git 操作 |
| Node_08 | Fetch | — | HTTP 请求 |
| Node_09 | Sandbox | — | 沙箱代码执行 |

#### 通信与工具 (10-19)

| 编号 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_10 | Slack | — | Slack 消息 |
| Node_11 | GitHub | — | GitHub API |
| Node_12 | Postgres | 8012 | PostgreSQL 数据库 |
| Node_13 | SQLite | 8013 | SQLite 数据库 |
| Node_14 | FFmpeg | 8014 | 视频转码、剪辑 |
| Node_15 | OCR | — | 文字识别 |
| Node_16 | Email | 8016 | SMTP 邮件发送 |
| Node_17 | EdgeTTS | 8017 | 文本转语音 |
| Node_18 | DeepL | 8018 | 文本翻译 |
| Node_19 | Crypto | 8019 | 加密解密、哈希 |

#### 搜索与数据 (20-29)

| 编号 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_20 | Qdrant | 8020 | 向量存储、相似度搜索 |
| Node_21 | Notion | — | Notion API |
| Node_22 | BraveSearch | 8022 | Brave 搜索 |
| Node_23 | Time | 8123 | 时间查询、时区转换 |
| Node_24 | Weather | 8024 | 天气查询 |
| Node_25 | GoogleSearch | 8025 | Google 搜索 |
| Node_26 | Discord | — | Discord 消息 |

#### 设备控制 (27-49)

| 编号 | 名称 | 功能 |
|------|------|------|
| Node_27 | SmartHome | 智能家居 |
| Node_33 | ADB | Android ADB |
| Node_34 | Scrcpy | 屏幕投射 |
| Node_35 | AppleScript | macOS 自动化 |
| Node_36 | UIAWindows | Windows UI 自动化 |
| Node_37 | LinuxDBus | Linux DBus |
| Node_38 | BLE | 蓝牙低功耗 |
| Node_39 | SSH | SSH 连接 |
| Node_40 | SFTP | SFTP 文件传输 |
| Node_41 | MQTT | MQTT 消息队列 |
| Node_42 | CANbus | CAN 总线 |
| Node_43 | MAVLink | 无人机通信 |
| Node_44 | NFC | NFC 近场通信 |
| Node_45 | DesktopAuto | 桌面自动化 |
| Node_46 | Camera | 摄像头 |
| Node_47 | Audio | 音频处理 |
| Node_48 | Serial | 串口通信 |
| Node_49 | OctoPrint | 3D 打印 |

#### AI/ML 引擎 (50-63)

| 编号 | 名称 | 功能 |
|------|------|------|
| Node_50 | Transformer | Transformer 模型 |
| Node_51 | QuantumDispatcher | 量子调度器 |
| Node_52 | QiskitSimulator | IBM Qiskit 模拟 |
| Node_53 | GraphLogic | 图逻辑推理 |
| Node_54 | SymbolicMath | 符号数学 |
| Node_55 | MultiModal | 多模态处理 |
| Node_56 | Planning | 规划引擎 |
| Node_57 | QuantumCloud | 量子云 (IBM/AWS) |
| Node_58 | ModelRouter | 模型路由 |
| Node_59 | CausalInference | 因果推断 |
| Node_60 | ReinforcementLearning | 强化学习 |
| Node_61 | GeometricReasoning | 几何推理 |
| Node_62 | ProbabilisticProgramming | 概率编程 |
| Node_63 | FuzzyLogicEngine | 模糊逻辑 |

#### 运维监控 (64-78)

| 编号 | 名称 | 功能 |
|------|------|------|
| Node_64 | Telemetry | 遥测数据 |
| Node_65 | LoggerCentral | 日志中心 |
| Node_66 | ConfigManager | 配置管理 |
| Node_67 | HealthMonitor | 健康监控 |
| Node_68 | Security | 安全审计 |
| Node_69 | BackupRestore | 备份恢复 |
| Node_70 | AutonomousLearning | 自主学习 |
| Node_71 | MultiDeviceCoordination | 多设备协调 |
| Node_72 | KnowledgeBase | 知识库 |
| Node_73 | Learning | 学习引擎 |
| Node_74 | DigitalTwin | 数字孪生 |
| Node_75 | DataPipeline | 数据管道 |
| Node_76 | AlertManager | 告警管理 |
| Node_77 | TaskScheduler | 任务调度器 |
| Node_78 | DataValidator | 数据验证 |

#### 本地 LLM 与嵌入 (79-99)

| 编号 | 名称 | 端口 | 功能 |
|------|------|------|------|
| Node_79 | LocalLLM | — | 本地 LLM |
| Node_80 | KnowledgeBase | 8080 | 混合知识库 (向量+图) |
| Node_81 | Orchestrator | — | 编排器 |
| Node_82 | NetworkGuard | — | 网络守卫 |
| Node_83 | NewsAggregator | — | 新闻聚合 |
| Node_84 | StockTracker | — | 股票追踪 |
| Node_85 | PromptLibrary | — | 提示词库 |
| Node_86 | SpeechProcessor | — | 语音处理 |
| Node_87 | ImageAnalysis | — | 图像分析 |
| Node_88 | WorkflowEngine | — | 工作流引擎 |
| Node_89 | APIGateway | — | API 网关 |
| Node_90 | MultimodalVision | — | 多模态视觉 |
| Node_91 | MultimodalAgent | — | 多模态智能体 |
| Node_92 | AutoControl | — | 自动控制 |
| Node_93 | VideoProcessor | — | 视频处理 |
| Node_94 | AudioAnalysis | — | 音频分析 |
| Node_95 | WebRTC_Receiver | — | WebRTC 接收 |
| Node_96 | SmartTransportRouter | — | 智能传输路由 |
| Node_97 | AcademicSearch | — | 学术搜索 |
| Node_98 | MultimodalFusion | — | 多模态融合 |
| Node_99 | EmbeddingService | — | 嵌入服务 |

#### 高级功能 (100-130)

| 编号 | 名称 | 功能 |
|------|------|------|
| Node_100 | MemorySystem | 记忆系统 (SQLite) |
| Node_101 | CodeEngine | 代码引擎 |
| Node_102 | DebugOptimize | 调试优化 |
| Node_103 | KnowledgeGraph | 知识图谱 |
| Node_104 | AgentCPM | Agent CPM |
| Node_105 | UnifiedKnowledgeBase | 统一知识库 |
| Node_106 | GitHubFlow | GitHub 工作流 |
| Node_107 | FunctionCalling | 函数调用 |
| Node_108 | MetaCognition | 元认知 |
| Node_109 | ProactiveSensing | 主动感知 |
| Node_110 | SmartOrchestrator | 智能编排器 |
| Node_111 | ContextManager | 上下文管理 |
| Node_112 | SelfHealing | 自愈系统 |
| Node_113 | AndroidVLM | Android VLM |
| Node_114 | DocumentIntelligence | 文档智能 |
| Node_115 | PluginManager | 插件管理 |
| Node_116 | ExternalToolWrapper | 外部工具包装 |
| Node_117 | OpenCode | 开放代码 |
| Node_118 | NodeFactory | 节点工厂 |
| Node_119 | BenchmarkEval | 基准评估 |
| Node_120 | File | 文件操作 |
| Node_121 | Web | Web 操作 |
| Node_122 | Shell | Shell 执行 |
| Node_123 | Calendar | 日历服务 |
| Node_124 | LinuxDesktopAuto | Linux 桌面自动化 |
| Node_125 | MediaGen | 媒体生成 |
| Node_126 | AgentSwarm | 智能体集群 |
| Node_127 | BambuLab | BambuLab 3D打印 |
| Node_128 | MediaGen | 媒体生成 (扩展) |
| Node_130 | AutonomousCoding | 自主编码 |

#### R9 新增节点

| 编号 | 名称 | 端口 | 类名 | 功能 |
|------|------|------|------|------|
| Node_Linux_Agent | Linux Agent | — | LinuxAgent | SSH远程操作Linux服务器 |
| Node_Tavily_Search | Tavily Search | — | TavilySearchManager | AI原生搜索 |
| Node_80_KnowledgeBase | KnowledgeBase | 8080 | HybridKnowledgeStore | 混合知识库(向量+图) |

### 4.2 节点目录结构

```
Node_XX_Name/
├── main.py              # 主要业务逻辑 (必需)
├── fusion_entry.py      # 融合入口文件 (必需)
├── README.md            # 节点说明 (必需)
├── requirements.txt     # Python 依赖 (活跃节点必需)
├── Dockerfile           # 容器化支持 (活跃节点必需)
├── config.json          # 节点配置 (可选)
└── tests/               # 节点测试 (可选)
```

---

## 5. Electron 桌面覆盖层

### 5.1 窗口架构

| 窗口 | 职责 | 触发 |
|------|------|------|
| **mainWindow** | 全屏透明覆盖层，三态显示 | Ctrl+Space 唤醒 |
| **panelWindow** | 控制面板 (维态/星元/设置) | F12 切换 |

### 5.2 三态实现

| 状态 | 文件 | 效果 |
|------|------|------|
| SILENT | `silent-state.js` | 边缘呼吸灯，鼠标穿透 |
| LIMINAL | `liminal-state.js` | 半透明覆盖，WebGL脉冲 |
| MANIFEST | `manifest-state.js` | CRT扫描线，结果展示 |

### 5.3 WebGL 效果

| 着色器 | 文件 | 效果 |
|--------|------|------|
| CRT | `shaders/crt.frag` | 扫描线、RGB分离 |
| LIMINAL | `shaders/liminal.frag/vert` | 边缘脉冲光效 |

### 5.4 通信

```
Electron (WebSocket客户端)
    ws://localhost:8765/ws/desktop-presence
        ↓
Galaxy Gateway (WebSocket服务器)
    galaxy_gateway/routes/websocket.py
```

---

## 6. API 参考

### 6.1 Gateway 路由 (galaxy_gateway/routes/)

| 路由模块 | 端点数 | 前缀 | 说明 |
|----------|--------|------|------|
| health.py | 6 | `/health` | 健康检查 |
| devices.py | 7 | `/devices` | 设备管理 |
| tasks.py | 5 | `/tasks` | 任务调度 |
| sessions.py | 4 | `/sessions` | Session管理 |
| chat.py | 2 | `/chat` | 对话接口 |
| llm.py | 1 | `/llm` | LLM调用 |
| android_vlm.py | 4 | `/android` | Android VLM |
| **linux_agent.py** | **9** | `/api/v1/agents/linux` | **远程Linux操作** |
| **sandbox.py** | **3** | `/api/v1/agents/sandbox` | **沙箱安全执行** |

### 6.2 核心路由 (core/routes/) — 43 模块

| 路由模块 | 端点数 | 说明 |
|----------|--------|------|
| operator.py | 32 | 操作员控制台 |
| projection.py | 29 | 投影输出 |
| hybrid.py | 15 | 混合执行 |
| observability.py | 15 | 可观测性 |
| protocols.py | 14 | 协议管理 |
| system.py | 13 | 系统管理 |
| federation.py | 10 | 联邦管理 |
| nodes.py | 9 | 节点管理 |
| tasks.py | 8 | 任务调度 |
| c_stage.py | 8 | C阶段编排 |
| command.py | 7 | 命令协议 |
| governance.py | 7 | 治理 |
| diagnostics.py | 7 | 诊断 |
| sessions.py | 7 | Session管理 |
| github.py | 6 | GitHub集成 |
| channels.py | 6 | 通道管理 |
| audit.py | 6 | 审计 |
| twin.py | 11 | 数字孪生 |
| vault.py | 10 | 密钥管理 |
| monitoring.py | 9 | 监控 |
| ai.py | 10 | AI Agent |
| ... | ... | ... |

### 6.3 Linux Agent API (9 端点)

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/api/v1/agents/linux/servers` | 注册服务器 |
| GET | `/api/v1/agents/linux/servers` | 列出服务器 |
| GET | `/api/v1/agents/linux/servers/{id}` | 查看详情 |
| DELETE | `/api/v1/agents/linux/servers/{id}` | 注销服务器 |
| POST | `/api/v1/agents/linux/servers/{id}/execute` | 执行命令(带沙箱预检) |
| POST | `/api/v1/agents/linux/servers/{id}/file/read` | 读文件 |
| POST | `/api/v1/agents/linux/servers/{id}/file/write` | 写文件 |
| GET | `/api/v1/agents/linux/servers/{id}/info` | 系统信息 |
| POST | `/api/v1/agents/linux/servers/{id}/probe` | 探测连通性 |

### 6.4 沙箱 API (3 端点)

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/api/v1/agents/sandbox/status` | 沙箱状态 |
| POST | `/api/v1/agents/sandbox/validate` | 验证命令安全性 |
| POST | `/api/v1/agents/sandbox/execute` | 沙箱执行代码 |

### 6.5 WebSocket 端点

| 端点 | 方向 | 说明 |
|------|------|------|
| `/ws/desktop-presence` | 双向 | 桌面三态通信 |
| `/ws/operator` | 双向 | 操作员控制台 |
| `/ws/android` | 双向 | Android客户端 (AIP v3) |
| `/ws/cross-device` | 双向 | 跨设备控制 |

---

## 7. 配置参考

### 7.1 环境变量 (.env)

#### 系统模式

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GALAXY_SYSTEM_MODE` | `desktop-local` | 桌面本地模式 |
| `GALAXY_MODE` | `development` | 开发/生产模式 |
| `GALAXY_LOG_LEVEL` | `INFO` | 日志级别 |
| `PORT` | `8765` | Gateway端口 |
| `HOST` | `127.0.0.1` | 绑定地址 |

#### LLM API Key (至少配一个，云端兜底用)

| 变量 | 用途 |
|------|------|
| `OPENAI_API_KEY` | OpenAI GPT 系列 |
| `DEEPSEEK_API_KEY` | DeepSeek (级联回退第一选择) |
| `OPENROUTER_API_KEY` | OpenRouter (级联回退第二选择) |
| `GROQ_API_KEY` | Groq (级联回退第三选择) |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `GEMINI_API_KEY` | Google Gemini |
| `XAI_API_KEY` | xAI Grok |

#### 本地模型

| 变量 | 默认值 | 选项 |
|------|--------|------|
| `OLLAMA_MODEL` | `gemma4:latest` | E4B (~5GB) |
| | | `gemma4:26b` | MoE (~15GB) |
| | | `gemma4:31b` | (~17GB) |

#### 持久记忆

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_DB_PATH` | `/app/data/galaxy_memory.db` | SQLite路径 |

#### 其他服务

| 变量 | 说明 |
|------|------|
| `TAVILY_API_KEY` | Tavily AI搜索 |
| `ONEAPI_BASE_URL` | OneAPI网关 |
| `NATS_URL` | NATS消息队列 |

#### 安全

| 变量 | 说明 |
|------|------|
| `GALAXY_AUTH_ENABLED` | 启用认证 |
| `GALAXY_REQUIRE_API_TOKEN` | 要求API Token |
| `GALAXY_API_TOKEN` | API Token |
| `PICKLE_SECRET_KEY` | Pickle序列化密钥 |

### 7.2 Docker Compose 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| galaxy | — | 主应用 |
| galaxy-gateway | 8765 | API网关 |
| ollama | 11434 | 本地LLM |
| neo4j | 7474/7687 | 图数据库 |
| qdrant | 6333 | 向量数据库 |
| redis | 6379 | 缓存 |
| mongodb | 27017 | 文档数据库 |
| nats | 4222 | 消息队列 |
| temporal | 7233 | 工作流引擎 |
| minio | 9000 | 对象存储 |
| coturn | 3478 | TURN服务器 |
| oneapi | — | API网关 |
| memos | — | 备忘录 |
| galaxy-worker | — | 工作进程 |

---

## 8. 部署指南

### 8.1 前提条件

- Python 3.10+
- Node.js 18+
- Ollama (本地模型)
- (可选) Docker + Docker Compose

### 8.2 安装步骤

```bash
# 1. 克隆仓库
git clone <仓库地址> ufo-galaxy
cd ufo-galaxy

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装 Electron 依赖
cd electron && npm install

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，配置至少一个 LLM API Key

# 6. 启动
python launch_desktop.py
```

### 8.3 启动方式

**方式一：一体化启动（推荐）**

```bash
python launch_desktop.py              # 完整启动
python launch_desktop.py --check      # 仅环境检查
python launch_desktop.py --backend    # 仅 Gateway
python launch_desktop.py --frontend   # 仅 Electron
python launch_desktop.py --docker     # Docker模式
```

**方式二：Docker Compose**

```bash
docker compose up -d
```

启动 17 个服务：Gateway、Ollama、Neo4j、Qdrant、Redis、MongoDB、NATS、Temporal 等。

**方式三：手动分别启动**

```bash
# 终端1：Gateway
python main.py

# 终端2：Electron
cd electron && npm start
```

### 8.4 模型下载

首次启动自动下载：
```bash
ollama pull gemma4:latest    # ~5GB
```

可选版本：
```bash
ollama pull gemma4:26b       # ~15GB (MoE)
ollama pull gemma4:31b       # ~17GB
```

---

## 9. 故障排除

### 9.1 Gateway 启动失败

| 症状 | 原因 | 解决 |
|------|------|------|
| `ImportError` | 依赖未安装 | `pip install -r requirements.txt` |
| 端口 8765 占用 | 其他进程占用 | `lsof -i :8765` 杀掉进程 |
| `.env` 缺失 | 环境变量未配置 | `cp .env.example .env` 后编辑 |
| `time` 未定义 | api_routes.py 导入问题 | 已修复 (PR-v10) |
| `dataclass` 未定义 | ai_intent.py 导入问题 | 已修复 (PR-v10) |
| `subscribe` 不存在 | state_event_bus.py 缺失 | 已修复 (PR-v10) |

### 9.2 Electron 启动失败

| 症状 | 原因 | 解决 |
|------|------|------|
| 白屏 | node_modules 缺失 | `cd electron && npm install` |
| WebSocket OFFLINE | Gateway 未启动 | 先启动 `python main.py` |
| Cannot find module | Electron 未安装 | `cd electron && npm install` |

### 9.3 模型问题

| 症状 | 原因 | 解决 |
|------|------|------|
| Ollama 未连接 | Ollama 未运行 | `ollama serve &` |
| 模型未下载 | 首次使用 | `ollama pull gemma4:latest` |
| 显存不足 | GPU 内存不够 | 换 E4B 版本或减少量化位数 |
| 本地模型宕机 | Ollama 崩溃 | 自动级联回退到云端 |

### 9.4 WebSocket 连接问题

```bash
# 检查 Gateway 是否运行
curl http://localhost:8765/health

# 检查 WebSocket 端点
python3 -c "
import asyncio, websockets
async def test():
    async with websockets.connect('ws://localhost:8765/ws/desktop-presence') as ws:
        print('WebSocket连接成功')
asyncio.run(test())
"
```

---

## 10. 版本历史

### v10.0 (2026-05-31)

| 改动 | 文件 |
|------|------|
| 新增统一启动器 | `launch_desktop.py` |
| 新增 Linux Agent 路由 | `galaxy_gateway/routes/linux_agent.py` |
| 新增沙箱路由 | `galaxy_gateway/routes/sandbox.py` |
| 新增上下文压缩 | `core/context_compressor.py` |
| Gemma 4 E4B 默认模型 | `galaxy_gateway/enhanced_nlu_v2.py` |
| 四级级联回退 | `galaxy_gateway/enhanced_nlu_v2.py` |
| 持久化路径修复 | `nodes/Node_100_MemorySystem/main.py` |
| PolicyGate 安全扩展 | `core/execution/decision_executor.py` |
| 修复 dataclass 导入 | `core/ai_intent.py` |
| 修复 subscribe 函数 | `core/state_event_bus.py` |
| 修复 time 导入 | `core/api_routes.py` |
| 修复 aiohttp 延迟导入 | `galaxy_gateway/enhanced_nlu_v2.py` |

---

## 附录

### A. 相关文档索引

| 文档 | 说明 |
|------|------|
| `SOUL.md` | 人格与能力边界策略 |
| `docs/UNIFIED_SUBJECT_ARCHITECTURE.md` | 统一主体架构 |
| `docs/CLONE_TO_USE_REALITY.md` | 运行时真相 |
| `docs/MAINTAINER_RUNBOOK.md` | 维护者参考 |
| `docs/DEPLOYMENT_SURFACES.md` | Docker部署 |
| `docs/ANDROID_PROTOCOL_ALIGNMENT.md` | Android协议 |
| `docs/TEST_STRATEGY.md` | 测试策略 |
| `CONTRIBUTING.md` | 贡献指南 |

### B. 相关仓库

| 仓库 | 代码规模 | 职责 |
|------|----------|------|
| [ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android) | ~28万行 Kotlin | Android客户端 — AIP v3协议、MobileVLM本地推理、SeeClick视觉定位 |
| ufo-galaxy-realization（本仓库） | ~66万行 Python | 服务端 + Galaxy Gateway + Electron桌面覆盖层 |

### C. 许可证

MIT License
