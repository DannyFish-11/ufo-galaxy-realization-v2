# Galaxy — 桌面原生 AI 助手系统

> **版本**: v10.0 | **模型**: Google Gemma 4 E4B (128K 上下文) | **日期**: 2026-05-31

---

## 一句话介绍

**Galaxy** 是一个桌面原生 AI 助手系统。通过 Electron 三态覆盖层（SILENT/LIMINAL/MANIFEST）直接在桌面上与 AI 对话，本地运行 Google Gemma 4 多模态模型，支持远程服务器操作、AI 搜索、持久记忆、Skill 扩展。

---

## 系统架构

```
用户桌面
    │
    │ Ctrl+Space 唤醒
    │
    ▼
┌─────────────────────────────────────────────┐
│          Electron 桌面覆盖层                 │
│  ┌──────────────────┐  ┌──────────────────┐ │
│  │ mainWindow       │  │ panelWindow      │ │
│  │ (全屏透明覆盖层)  │  │ (F12 控制面板)   │ │
│  │                  │  │                  │ │
│  │ SILENT ──LIMINAL │  │ 维态/星元/设置    │ │
│  │   ──── MANIFEST  │  │ STANDBY + 三态点  │ │
│  │                  │  │                  │ │
│  │ WebSocket        │  │                  │ │
│  │ ws://localhost   │  │                  │ │
│  └────────┬─────────┘  └──────────────────┘ │
└───────────┼─────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────┐
│          Galaxy Gateway (FastAPI)            │
│  端口: 8765                                  │
│                                              │
│  REST API: /api/v1/*                         │
│  WebSocket: /ws/desktop-presence             │
│                                              │
│  路由:                                       │
│    /api/v1/agents/linux/*  (远程服务器操作)   │
│    /api/v1/agents/sandbox/* (沙箱安全执行)    │
│    /api/v1/devices/*       (设备管理)         │
│    /api/v1/tasks/*         (任务调度)         │
│    /api/v1/llm/*           (LLM 调用)         │
│    ... 37 个端点                             │
└───────────┬─────────────────────────────────┘
            │
            ├── 本地模型: Ollama (Gemma 4 E4B)
            ├── 云端兜底: DeepSeek → OpenRouter → Groq
            ├── 持久记忆: SQLite (/app/data/)
            ├── 上下文压缩: 突破 128K 限制
            └── Skill 系统: 动态加载扩展
```

---

## 三态交互

| 状态 | 视觉 | 触发 | 操作 |
|------|------|------|------|
| **SILENT** | 静默，边缘呼吸灯 | 系统空闲 | 监听语音/快捷键，鼠标穿透 |
| **LIMINAL** | 半透明覆盖层，白色脉冲 | AI 处理中 | 显示 "THINKING..."，按 F12 看面板 |
| **MANIFEST** | 完全显形，结果显示 | AI 返回结果 | CRT 扫描线效果 + 结果面板 |

快捷键：
- `Ctrl+Space` — 唤醒 AI (SILENT → LIMINAL)
- `F12` — 打开/关闭控制面板
- `Esc` — 关闭结果 (MANIFEST → SILENT)

---

## 核心能力

### 1. 本地多模态 AI (Gemma 4 E4B)
- **模型**: Google Gemma 4 E4B (默认), 可选 26B MoE / 31B
- **显存**: E4B 约 5GB (4-bit 量化)
- **上下文**: 128K tokens
- **突破**: 通过上下文压缩 + 记忆召回，对话长度理论上无限

### 2. 模型宕机保护 (四级级联回退)
```
用户请求
  │
  ▼
[本地 Ollama Gemma 4] ──失败──┐
  │ 成功                      ▼
返回结果              [DeepSeek API]
                        │ 失败
                        ▼
                [OpenRouter API]
                        │ 失败
                        ▼
                  [Groq API]
                        │
                        ▼
                  返回结果 (标记 fallback)
```

### 3. 远程服务器操作 (Linux Agent)
注册你的服务器（华为云/阿里云/任何 Linux），通过对话远程操作：
```bash
# 注册服务器
curl -X POST http://localhost:8765/api/v1/agents/linux/servers \
  -H "Content-Type: application/json" \
  -d '{"name":"华为云","host":"IP","port":22,"user":"root","key_path":"~/.ssh/id_rsa"}'

# 远程执行命令
curl -X POST http://localhost:8765/api/v1/agents/linux/servers/ID/execute \
  -d '{"command":"uname -a && df -h"}'
```
支持：SSH 密钥/密码认证、远程文件读写、系统信息查看、批量操作。

### 4. AI 搜索 (Tavily)
AI 原生搜索引擎，basic/advanced 深度搜索，结果自动注入对话上下文。

### 5. 混合知识库 (Node_80)
- **向量层**: sentence-transformers 语义搜索
- **图层**: 实体关系网络，多跳遍历
- **持久化**: SQLite 磁盘存储

### 6. 沙箱安全执行
- 危险命令黑名单 (`rm -rf`, `dd`, `mkfs` 等 16 种)
- 资源限制 (内存 256MB, CPU 30秒超时)
- **OpenClawd PolicyGate**: 应用启动白名单 + 命令注入检测

### 7. Skill 系统
动态加载自定义技能包：
```
skills/
└── my_skill/
    ├── skill.json      # 技能描述
    └── handler.py      # 执行逻辑
```
通过 `skill__<id>` 工具调用。

### 8. DAG 动态编排
- **StarSplit**: 自动检测并行任务，最大拆分 8 个子任务
- **预测性调度**: Welford 在线算法学习历史执行时间
- **不变量验证**: I1(依赖存在) I2(无环) I3(参数一致)

---

## 启动方式

### 方式一：一体化启动（推荐）
```bash
python launch_desktop.py
```
自动完成：环境检查 → 依赖安装 → 模型下载 → Gateway 启动 → Electron 启动

选项：
```bash
python launch_desktop.py --check      # 只检查环境
python launch_desktop.py --backend    # 只启动 Gateway
python launch_desktop.py --frontend   # 只启动 Electron
```

### 方式二：Docker Compose（后端服务）
```bash
docker compose up -d
```
启动：Galaxy Gateway、Ollama、Neo4j、Qdrant、Redis、MongoDB、NATS

### 方式三：手动分别启动
```bash
# 终端1：Gateway
python main.py

# 终端2：Electron 桌面覆盖层
cd electron && npm install && npm start
```

---

## 安装步骤

### 前提
- Python 3.10+
- Node.js 18+
- Ollama (本地模型)

### 1. 克隆仓库
```bash
git clone <仓库地址> ufo-galaxy
cd ufo-galaxy
```

### 2. 安装 Python 依赖
```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### 3. 安装 Electron 依赖
```bash
cd electron && npm install
```

### 4. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，至少配置一个 LLM API Key（云端兜底用）
```

### 5. 启动
```bash
python launch_desktop.py
```

---

## 环境变量配置 (.env)

```bash
# === 必需 ===
# 至少一个 LLM API Key（云端兜底）
OPENAI_API_KEY=sk-your-key-here
# 或
DEEPSEEK_API_KEY=your-key-here

# === 本地模型 ===
OLLAMA_MODEL=gemma4:latest          # Google Gemma 4 E4B (默认, ~5GB)
# OLLAMA_MODEL=gemma4:26b           # MoE 版本 (~15GB)

# === 系统配置 ===
GALAXY_SYSTEM_MODE=desktop-local
GALAXY_LOG_LEVEL=INFO
PORT=8765

# === AI 搜索 ===
TAVILY_API_KEY=tvly-your-key

# === 持久记忆 ===
MEMORY_DB_PATH=/app/data/galaxy_memory.db

# === 远程服务器 (Linux Agent) ===
SSH_HOST=your-server-ip
SSH_USER=root
SSH_KEY_PATH=/home/you/.ssh/id_rsa

# === 其他按需配置 ===
```

---

## API 路由 (37 个端点)

| 路由 | 端点数 | 说明 |
|------|--------|------|
| `/api/v1/health/*` | 6 | 健康检查 |
| `/api/v1/devices/*` | 7 | 设备管理 |
| `/api/v1/tasks/*` | 5 | 任务调度 |
| `/api/v1/sessions/*` | 4 | Session 管理 |
| `/api/v1/chat/*` | 2 | 对话 |
| `/api/v1/llm/*` | 1 | LLM 调用 |
| `/api/v1/agents/linux/*` | 9 | **远程服务器操作** (新增) |
| `/api/v1/agents/sandbox/*` | 3 | **沙箱安全执行** (新增) |

WebSocket: `ws://localhost:8765/ws/desktop-presence`

---

## 节点列表 (135+)

### R9 新增节点

| 节点 | 功能 | 类名 |
|------|------|------|
| Node_Linux_Agent | 远程 Linux 服务器操作 (SSH) | LinuxAgent |
| Node_Tavily_Search | AI 原生搜索 | TavilySearchManager |
| Node_80_KnowledgeBase | 混合知识库 (向量+图) | HybridKnowledgeStore |

### 核心节点

| 类别 | 节点 |
|------|------|
| 本地计算 | Node_06_Filesystem, Node_36_LocalCompute, Node_45_SystemAgent, Node_Linux_Agent |
| 移动设备 | Node_33_AndroidBridge, Node_34_Scrcpy, Node_113_AndroidVLM |
| 数据库 | Node_12_Postgres, Node_13_SQLite, Node_20_Qdrant, Node_80_KnowledgeBase |
| 搜索 | Node_08_BraveSearch, Node_22_Search, Node_25_GoogleSearch, Node_Tavily_Search |
| 通信 | Node_10_Slack, Node_16_Email, Node_26_Discord |
| 智能家居 | Node_27_SmartHome, Node_38_BLE, Node_41_MQTT, Node_42_CANbus, Node_43_MAVLink |
| 媒体处理 | Node_14_FFmpeg, Node_15_OCR, Node_17_EdgeTTS, Node_46_Camera, Node_86_VideoProc |
| 开发工具 | Node_07_Git, Node_09_Sandbox, Node_100_MemorySystem, Node_118_NodeFactory, Node_122_Shell |
| AI/ML | Node_01_OneAPI, Node_50_Transformer, Node_79_LocalLLM, Node_99_EmbedService |
| 3D打印 | Node_49_OctoPrint, Node_127_BambuLab |
| 监控运维 | Node_23_Time, Node_24_Weather, Node_65_LoggerCentral, Node_76_AlertManager |

完整节点列表见 `nodes/` 目录。

---

## 关键文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 主入口 | `main.py` | 系统编排器 |
| 桌面启动器 | `launch_desktop.py` | 前后端一体启动 |
| Gateway | `galaxy_gateway/app.py` | FastAPI 应用 |
| Electron 入口 | `electron/main.js` | 桌面主进程 |
| 三态管理 | `electron/renderer/app.js` | SILENT/LIMINAL/MANIFEST |
| NLU 引擎 | `galaxy_gateway/enhanced_nlu_v2.py` | Gemma 4 + 级联回退 |
| 上下文压缩 | `core/context_compressor.py` | 突破 128K 限制 |
| 沙箱 | `galaxy_gateway/routes/sandbox.py` | 安全检查 |
| Linux Agent | `galaxy_gateway/routes/linux_agent.py` | 远程服务器 |
| 事件总线 | `core/state_event_bus.py` | 三态事件发布订阅 |
| 记忆系统 | `nodes/Node_100_MemorySystem/main.py` | SQLite 持久化 |
| 环境模板 | `.env.example` | 复制为 `.env` 后配置 |

---

## 相关仓库

| 仓库 | 代码规模 | 职责 |
|------|----------|------|
| [ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android) | ~28万行 Kotlin | Android 客户端 (APK) — AIP v3 协议、本地 MobileVLM 推理、SeeClick 视觉定位 |
| ufo-galaxy-realization-v2（本仓库） | ~66万行 Python | 服务端 + Galaxy Gateway + Electron 桌面覆盖层 |

**Android 客户端快速开始**：
```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
cd ufo-galaxy-android
./build_apk.sh
adb install app/build/outputs/apk/debug/app-debug.apk
```

完整 Android 文档：`docs/ANDROID_COMPAT.md`

---

## 安全

- **沙箱**: 危险命令黑名单 + 资源限制
- **PolicyGate**: OpenClawd 应用启动白名单
- **SSH 密钥**: Linux Agent 优先使用密钥认证
- **CodeQL**: GitHub 自动安全扫描

---

## 许可证

MIT License
