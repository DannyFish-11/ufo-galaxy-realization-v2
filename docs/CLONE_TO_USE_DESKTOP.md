# UFO Galaxy — 桌面原生 AI 助手使用指南

> **版本**: v10.0 | **更新日期**: 2026-05-31

---

## 系统简介

UFO Galaxy 是一个**桌面原生 AI 助手系统**。通过 Electron 三态覆盖层直接在桌面上与 AI 对话，不需要浏览器。

核心特点：
- **本地模型**: Google Gemma 4 E4B (128K 上下文，~5GB 显存)
- **模型回退**: 本地宕机自动切云端 (DeepSeek → OpenRouter → Groq)
- **持久对话**: 上下文压缩 + 记忆召回，理论上无限长度
- **远程操作**: 通过 SSH 管理你的云服务器
- **沙箱安全**: 危险命令自动阻止

---

## 系统架构

```
用户桌面
    │
    │ Ctrl+Space 唤醒
    ▼
┌─────────────────┐
│ Electron 覆盖层 │  三态: SILENT → LIMINAL → MANIFEST
│ (全屏透明窗口)   │  快捷键: F12 控制面板, Esc 关闭
└────────┬────────┘
         │ WebSocket
         ▼
┌─────────────────┐     ┌──────────────────┐
│ Galaxy Gateway  │────►│ Ollama (Gemma 4) │
│ (FastAPI :8765) │     └──────────────────┘
└────────┬────────┘     ┌──────────────────┐
         │              │ DeepSeek (兜底)   │
         ├──────────────┼──────────────────┤
         │              │ OpenRouter (兜底) │
         │              └──────────────────┘
    ┌────┴────┐
    │  节点层  │
    └─────────┘
```

---

## 前提条件

- Python 3.10+
- Node.js 18+
- Ollama (本地模型运行时)

---

## 安装步骤

### 1. 克隆仓库

```bash
git clone <你的仓库地址> ufo-galaxy
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
```

编辑 `.env`，至少配置：

```bash
# 至少一个 LLM API Key（云端兜底用）
OPENAI_API_KEY=sk-your-key
# 或
DEEPSEEK_API_KEY=your-key

# 本地模型（默认 Gemma 4 E4B，适合普通电脑）
OLLAMA_MODEL=gemma4:latest

# 系统模式
de GALAXY_SYSTEM_MODE=desktop-local
```

可选配置：

```bash
# AI 搜索
TAVILY_API_KEY=tvly-your-key

# 远程服务器 SSH 密钥
SSH_KEY_PATH=/home/you/.ssh/id_rsa
```

### 5. 启动

```bash
python launch_desktop.py
```

---

## 启动方式

### 方式一：一体化启动（推荐）

```bash
python launch_desktop.py
```

自动完成：环境检查 → 依赖安装 → 模型下载 → Gateway 启动 → Electron 启动

选项：
- `--check` — 只检查环境，不启动
- `--backend` — 只启动 Gateway
- `--frontend` — 只启动 Electron（后端需已运行）
- `--docker` — Docker 模式启动后端

### 方式二：Docker Compose

```bash
docker compose up -d
```

启动：Gateway、Ollama、Neo4j、Qdrant、Redis、MongoDB、NATS

### 方式三：手动分别启动

```bash
# 终端1：Gateway
python main.py

# 终端2：Electron
cd electron && npm start
```

---

## 三态操作

| 状态 | 视觉表现 | 触发 | 快捷键 |
|------|----------|------|--------|
| **SILENT** | 静默，边缘呼吸灯 | 系统空闲 | — |
| **LIMINAL** | 半透明覆盖层，白色脉冲 | AI 处理中 | Ctrl+Space |
| **MANIFEST** | 完全显形，CRT 扫描线 | AI 返回结果 | — |

- `Ctrl+Space` — 唤醒 AI
- `F12` — 打开/关闭控制面板
- `Esc` — 关闭结果面板

---

## 远程服务器操作

注册你的云服务器后，通过对话即可远程操作。

### 注册服务器

```bash
curl -X POST http://localhost:8765/api/v1/agents/linux/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "华为云",
    "host": "你的IP地址",
    "port": 22,
    "user": "root",
    "key_path": "/home/you/.ssh/id_rsa",
    "tags": ["huaweicloud"]
  }'
```

返回 `server_id`（如 `a1b2c3d4`），后续操作使用这个 ID。

### 执行命令

```bash
curl -X POST http://localhost:8765/api/v1/agents/linux/servers/a1b2c3d4/execute \
  -d '{"command": "uname -a && df -h"}'
```

### 查看系统信息

```bash
curl http://localhost:8765/api/v1/agents/linux/servers/a1b2c3d4/info
```

### API 端点列表

| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/api/v1/agents/linux/servers` | 注册服务器 |
| GET | `/api/v1/agents/linux/servers` | 列出服务器 |
| GET | `/api/v1/agents/linux/servers/{id}` | 查看详情 |
| DELETE | `/api/v1/agents/linux/servers/{id}` | 注销服务器 |
| POST | `/api/v1/agents/linux/servers/{id}/execute` | 执行命令 |
| POST | `/api/v1/agents/linux/servers/{id}/file/read` | 读文件 |
| POST | `/api/v1/agents/linux/servers/{id}/file/write` | 写文件 |
| GET | `/api/v1/agents/linux/servers/{id}/info` | 系统信息 |
| POST | `/api/v1/agents/linux/servers/{id}/probe` | 探测连通性 |

---

## 故障排除

### Gateway 启动失败

| 症状 | 原因 | 解决 |
|------|------|------|
| `ImportError` | 依赖未安装 | `pip install -r requirements.txt` |
| 端口占用 | 8765 被占用 | `lsof -i :8765` 杀掉进程 |
| `.env` 缺失 | 环境变量未配置 | `cp .env.example .env` 后编辑 |

### Electron 启动失败

| 症状 | 原因 | 解决 |
|------|------|------|
| 白屏 | node_modules 缺失 | `cd electron && npm install` |
| WebSocket OFFLINE | Gateway 未启动 | 先启动 `python main.py` |
| `Cannot find module` | Electron 未安装 | `cd electron && npm install` |

### 模型下载

首次启动会自动 `ollama pull gemma4:latest`（约 2-5GB）。

手动下载：
```bash
ollama pull gemma4:latest
```

---

## 模型配置

### 默认：Gemma 4 E4B

| 版本 | 参数量 | 显存(4-bit) | 适用 |
|------|--------|-------------|------|
| **E4B（默认）** | 4B | ~5GB | 普通笔记本，16GB RAM |
| 26B MoE | 26B | ~15GB | 高配桌面机 |
| 31B | 31B | ~17GB | 工作站 |

上下文窗口：128K tokens

通过上下文压缩机制，对话长度理论上无上限。

切换模型：
```bash
# .env 中修改
OLLAMA_MODEL=gemma4:26b
ollama pull gemma4:26b
```

---

## 相关文档

| 文档 | 说明 |
|------|------|
| `README.md` | 系统介绍和架构 |
| `docs/CLONE_TO_USE_REALITY.md` | 运行时真相 |
| `docs/MAINTAINER_RUNBOOK.md` | 维护者参考 |
| `docs/DEPLOYMENT_SURFACES.md` | Docker 部署 |
| `SOUL.md` | 人格与能力边界 |

---

*最后更新: 2026-05-31 | 版本: v10.0*
