# Galaxy — 桌面原生 AI 助手系统

> **版本** `v2.3.21` · **L4 Autonomous Intelligence System** · 本地优先 / 桌面原生

Galaxy 是一个桌面原生的 AI 助手：通过 Electron 三态覆盖层（SILENT / LIMINAL / MANIFEST）直接在桌面与 AI 对话，本地运行模型（Ollama），云端 API 兜底，支持远程服务器操作、AI 搜索、持久记忆与 Skill 扩展。

---

## 快速开始（克隆 → 运行 → 使用）

```bash
# 1. 克隆
git clone <仓库地址> ufo-galaxy && cd ufo-galaxy

# 2. 一键启动（自动完成环境检查 → 依赖 → 后端 → 9000 网关 → Electron 覆盖层 → 托盘）
python main.py
```

启动完成后：

| 快捷键 | 作用 |
|--------|------|
| **`Ctrl+Alt+Space`** | 唤醒覆盖层（避开被输入法占用的 `Ctrl+Space`） |
| **`Ctrl+Alt+H`** | 隐藏覆盖层 |
| **`F12`** | 打开 / 关闭控制面板 |

> 右下角系统托盘会常驻一颗彩色渐变球（与启动横幅同色调）：正常运行=干净渐变球，告警/错误/离线时右下角叠加状态色圆点。

### 前提

- Python 3.10+ · Node.js 18+ · [Ollama](https://ollama.com)（本地模型，可选）
- 首次运行前复制环境模板并至少配置一个云端 LLM Key（兜底用）：
  ```bash
  cp .env.example .env   # 然后编辑 .env
  ```

> 完整安装、数据库 / NATS 配置与故障排查见 [INSTALL.md](INSTALL.md)。

### 常用入口

```bash
python main.py            # 启动完整系统（推荐）
python main.py --setup    # 配置向导
python main.py --status   # 查看系统状态
python main.py --help     # 全部启动选项
```

---

## 三态交互

| 状态 | 视觉 | 触发 | 行为 |
|------|------|------|------|
| **SILENT** | 边缘呼吸灯，鼠标穿透 | 系统空闲 | 监听快捷键 / 语音 |
| **LIMINAL** | 半透明覆盖层，白色脉冲 | AI 处理中 | 显示 "THINKING…"，`F12` 看面板 |
| **MANIFEST** | 完全显形 + 结果面板 | AI 返回结果 | `Ctrl+Alt+H` 收起 |

---

## 系统架构

```
用户桌面 ──Ctrl+Alt+Space──▶ Electron 覆盖层 ──▶ Galaxy Gateway (FastAPI, :9000)
                            mainWindow 全屏透明        │
                            panelWindow F12 面板        ├── 本地模型: Ollama
                                                        ├── 云端兜底: DeepSeek → OpenRouter → Groq
                                                        ├── 持久记忆: SQLite
                                                        └── Skill 系统: 动态扩展
```

请求生命周期沿规范链路流动：

```
main.py → unified_launcher.py → DesktopPresenceRuntime.handle_request → OpenClawd.process → CommandRouter.route_envelope
```

`DesktopPresenceRuntime`（运行时外壳）与 `OpenClawd`（认知核心）是同一主体的两层。
详见 [docs/UNIFIED_SUBJECT_ARCHITECTURE.md](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)。

---

## 核心能力

- **本地多模态 AI** — Ollama 本地模型，128K 上下文，云端四级级联兜底（本地 → DeepSeek → OpenRouter → Groq）。
- **远程服务器操作** — 注册任意 Linux 服务器（SSH 密钥/密码），通过对话远程执行命令、读写文件。
- **AI 搜索** — Tavily 原生搜索，结果自动注入对话上下文。
- **混合知识库** — 向量语义检索 + 实体关系图，多跳遍历，SQLite 持久化。
- **沙箱安全执行** — 危险命令黑名单 + 资源限制 + OpenClawd PolicyGate 白名单。
- **Skill 系统** — `skills/<id>/{skill.json, handler.py}` 动态加载，经 `skill__<id>` 调用。
- **DAG 动态编排** — StarSplit 并行拆分、预测性调度、不变量校验。

完整节点清单见 `nodes/` 目录；API 路由见运行后的 `http://localhost:9000/docs`。

---

## 环境变量（.env）

```bash
# 至少一个云端 LLM Key（本地模型不可用时兜底）
DEEPSEEK_API_KEY=your-key            # 或 OPENAI_API_KEY=sk-...

# 本地模型（Ollama）
OLLAMA_MODEL=gemma:latest

# 系统
GALAXY_SYSTEM_MODE=desktop-local
GALAXY_LOG_LEVEL=INFO

# 可选：AI 搜索 / 远程服务器
TAVILY_API_KEY=tvly-...
SSH_HOST=...   SSH_USER=root   SSH_KEY_PATH=~/.ssh/id_rsa

# 可选：节点的 Docker 基础设施自动拉起（默认 auto = 装了 Docker 就自动起）
GALAXY_AUTO_DOCKER=auto               # 0 关闭
```

完整可配置项见 `.env.example`。

> **节点 / Docker**：`main.py` 会在「Phase 3.5 基础设施」自动检测 Docker —— 装了就后台
> 拉起 `nats/redis/qdrant/neo4j/mongodb` 并把依赖它们的节点带上线（首次下载镜像在后台，
> 进度见 `logs/docker.log`）。没装 Docker 也能用，依赖基础设施的节点会被清晰标注「跳过」，
> 不影响桌面功能。`GALAXY_AUTO_DOCKER=0` 可关闭。

---

## 其他启动方式

```bash
# 仅后端服务（Docker Compose）
docker compose up -d

# 手动分别启动
python main.py                        # 后端 + 网关
cd electron && npm install && npm start   # 桌面覆盖层
```

---

## 相关仓库

| 仓库 | 职责 |
|------|------|
| [ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android) | Android 客户端（APK）— AIP v3 协议、本地 MobileVLM、SeeClick 视觉定位 |
| ufo-galaxy-realization-v2（本仓库） | 服务端 + Galaxy Gateway + Electron 桌面覆盖层 |

Android 快速开始见 `docs/ANDROID_COMPAT.md`。

---

## 关键文件

| 用途 | 路径 |
|------|------|
| 主入口（编排器） | `main.py` |
| 启动器 | `unified_launcher.py` |
| Electron 主进程 | `electron/main.js` |
| 三态渲染 | `electron/renderer/app.js` |
| 事件总线 | `core/state_event_bus.py` |
| 系统托盘 | `windows_service/tray_icon.py` |
| 启动横幅 / 配色 | `core/ascii_art.py` |
| 环境模板 | `.env.example` |

---

## 文档导航

| 文档 | 内容 |
|------|------|
| [INSTALL.md](INSTALL.md) | 完整安装、数据库 / NATS 配置、故障排查 |
| [docs/guides/QUICKSTART.md](docs/guides/QUICKSTART.md) | 10 分钟本地验证、烟雾测试、手机跨设备联通 |
| [docs/guides/L4_QUICK_START_GUIDE.md](docs/guides/L4_QUICK_START_GUIDE.md) | L4 自主性、物理设备控制、systemd 部署 |
| [docs/ANDROID_COMPAT.md](docs/ANDROID_COMPAT.md) | Android 客户端对接 |
| [docs/UNIFIED_SUBJECT_ARCHITECTURE.md](docs/UNIFIED_SUBJECT_ARCHITECTURE.md) | 统一主体架构（规范源） |
| `docs/reports/` | 历史审计 / 集成报告归档 |

---

## 安全

危险命令黑名单 + 资源限制 · OpenClawd PolicyGate 白名单 · Linux Agent 优先密钥认证 · GitHub CodeQL 自动扫描。

## 许可证

MIT License
