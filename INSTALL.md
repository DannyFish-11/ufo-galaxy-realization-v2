# Galaxy UFO V2 — 完整安装和使用指南

> **目标**：从克隆到完全使用，只需 5-10 分钟

## 📋 系统要求

- **Python**: 3.10 或更高
- **操作系统**: Linux, macOS, Windows (WSL2 推荐)
- **内存**: 4GB 最小 (8GB+ 推荐)
- **磁盘**: 5GB 可用空间

### 依赖工具

- `git` — 版本控制
- `docker` (可选) — 用于 NATS、PostgreSQL 等服务
- `docker-compose` (可选) — 用于完整部署

---

## 🚀 快速开始 (5 分钟)

### 1️⃣ 克隆仓库

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2
```

### 2️⃣ 自动初始化脚本

运行一键初始化脚本，它会自动处理所有依赖和配置：

```bash
# Linux / macOS
bash scripts/bootstrap.sh

# Windows (PowerShell)
.\scripts\bootstrap.ps1

# 或者使用 Python 版本（跨平台）
python scripts/bootstrap.py
```

**脚本会自动完成**：
- ✅ 校验 Python 版本 (>= 3.10)
- ✅ 创建虚拟环境 (`.venv`)
- ✅ 安装 Python 依赖 (`requirements.txt`)
- ✅ 从 `.env.example` 生成 `.env`（若缺失）
- ✅ 确保 `config/` 目录存在

> NATS / Docker 基础设施 / 系统预检由 `python main.py` 在运行时自动处理（见
> 启动时的 Phase 3.5 基础设施 与 Phase 4 消息总线），无需在初始化阶段单独执行。

### 3️⃣ 启动系统

```bash
# 官方启动方式（推荐）
python main.py

# 或使用脚本
bash start.sh          # Linux/macOS
.\start.bat           # Windows
```

停止：

```bash
bash stop.sh           # Linux/macOS
.\stop.bat            # Windows
```

> 两个停止脚本都会先核对 PID 文件里的进程**确实属于本仓库**再终止 ——
> 陈旧的 PID 文件里那个号码可能早已被系统回收并分配给别的进程，
> 不校验就直接 kill 等于在杀无关进程。

系统启动后访问：
- 🌐 **API 文档**: http://localhost:9000/docs
- 📊 **状态板**: http://localhost:9000/api/status
- 💬 **聊天 API**: http://localhost:9000/api/v1/chat

---

## 🧠 选主脑档位（首次启动会问你）

第一次 `python main.py` 时，终端会按**实际探测到的硬件**推荐一档并列出全部档位：

| 档 | 组成 | 看 / 听 / 说 | 硬件门槛 |
|----|------|-------------|---------|
| **A** | Gemma 4 系（单模型，档内按显存再挑一个） | 原生 / 原生 / TTS 桥 | 无独显也能跑 |
| **B** | MiniCPM-o 4.5（单模型，全模态） | 全原生 | 约 11 GB 显存（**跑起来**的量，不是 6 GB 的权重量） |
| **C** | **双模型**：推理位 Qwen3.6-35B-A3B 常驻独显 + 感知位（Gemma 4 系 / MiniCPM-o 四选一，可随时换）走核显 | 全原生 | 见下 |

三点值得先知道：

- **档位和云端 API 不是二选一。** 本地两位、云端 API 三者同时存在、同时可用；
  只要其中任意一个在，系统都跑得下来。云端 API 是给特定任务专门用的，不是"兜底"。
- **感知位可以随时换人**，推理位相对常驻 —— 换感知位（换到 Gemma 4 还是 MiniCPM-o）
  不会动独显上那一位。面板「模型」tab 或 `POST /api/v1/models/slot` 都能换。
- **跑过 `install.sh` 也照样会问。** 生成的 `.env` 里 `OLLAMA_MODEL` 刻意留空；
  一旦它有值，选档界面就会被跳过（`resolve_main_brain` 的第一条判据就是它）。

### C 档：把推理位真正架起来

推理位登记的驻留量是 7.3 GB，而权重有 18 GB —— 这个差额**完全来自专家卸载**
（MoE 每 token 只激活约 3B，把专家 FFN 留在内存、注意力留显存）。而 PyPI 上的
`llama-cpp-python`（实测至 0.3.34）既不透出 `n_cpu_moe` 也不透出 `override_tensor`，
**进程内这条路做不到这次卸载**。所以推理位走 llama.cpp 的 server：

```bash
# 体检：算出 --n-cpu-moe 的层数、检查权重和二进制在不在，并给出完整命令
python scripts/setup_reasoning_slot.py

# 顺带把权重下下来（约 18 GB）、把三个环境变量写进 .env
python scripts/setup_reasoning_slot.py --download --write-env

# 直接把 llama-server 拉起来（前台运行）
python scripts/setup_reasoning_slot.py --start
```

`llama-server` 二进制需要**你自己装**（脚本不会替你下载并执行二进制）：

```bash
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_CUDA=ON && cmake --build build -j --target llama-server
```

装在非标准位置就用 `GALAXY_LLAMA_SERVER_BIN=/绝对/路径` 指过来。接进路由的三个键：

```bash
GALAXY_LOCAL_OPENAI_URL=http://127.0.0.1:18080/v1
GALAXY_LOCAL_OPENAI_MODEL=qwen3.6:35b-a3b
GALAXY_LOCAL_OPENAI_SERVES=qwen3.6:35b-a3b   # 声明这个 server 伺候的是哪一位
```

若你的 server 按自己那套命名报模型 id（不是目录里的 tag），把 `_SERVES` 设成目录
tag 即可 —— 路由靠它把请求投准槽位。

> **少跑一个模型会明说。** 某一位的加载后端没装、或者装了也做不到目录声称的落位时，
> 每次启动的终端上都会打出具体是哪一位、缺什么、怎么装；面板的 `/api/v1/models/tier`
> 与 `/slot` 响应里也带同一份 `runtime_gaps`。不会出现"以为两个都在跑、其实只有一个"。

---

## 🔧 详细配置步骤

### 方案 A：交互式配置向导（推荐新手）

```bash
python setup_wizard.py --interactive
```

向导会引导你：
1. 检测已有的 API Key
2. 配置 OpenAI、Anthropic、Gemini 等 LLM
3. 配置数据库连接
4. 测试所有服务可用性

### 方案 B：快速配置（环境变量已设）

```bash
python setup_wizard.py --quick
```

从环境变量自动检测并生成 `.env` 文件。

### 方案 C：手动配置

1. **复制模板**
   ```bash
   cp .env.example .env
   ```

2. **编辑 `.env` 文件**，至少设置一个 LLM API Key：
   ```bash
   # 选择以下任意一个
   OPENAI_API_KEY=sk-...
   ANTHROPIC_API_KEY=sk-ant-...
   GEMINI_API_KEY=...
   DEEPSEEK_API_KEY=...
   ```

3. **验证配置**
   ```bash
   python -m core.config_preflight --mode all
   ```

---

## 🗄️ 数据库初始化

### 自动初始化（推荐）

```bash
python scripts/init_databases.py
```

自动检测并初始化：
- ✅ PostgreSQL (主数据库)
- ✅ Redis (缓存/消息队列)
- ✅ Qdrant (向量数据库)

### 使用 Docker Compose

如果已安装 Docker，可以一键启动所有基础设施：

```bash
# 启动核心基础设施（PostgreSQL、Redis、Qdrant）
docker-compose -f deploy/compose/core.yml up -d

# 查看所有服务
docker-compose -f deploy/compose/core.yml ps

# 停止所有服务
docker-compose -f deploy/compose/core.yml down
```

### 手动配置

在 `.env` 中设置数据库 URL：

```bash
# PostgreSQL
DATABASE_URL=postgresql://postgres:password@localhost:5432/ufogalaxy

# Redis
REDIS_URL=redis://localhost:6379

# Qdrant
QDRANT_URL=http://localhost:6333
```

---

## 🔌 NATS 服务配置

### 自动启动（推荐）

`bootstrap.sh` / `start.sh` 会自动启动 NATS：

```bash
# 检查 NATS 状态
curl http://localhost:4222/varz

# 或在日志中查看
grep "NATS" *.log
```

### 手动安装

**Linux/macOS**：
```bash
# Ubuntu/Debian
apt install nats-server

# macOS
brew install nats-server

# 启动
nats-server -p 4222
```

**Windows**：
```powershell
# 使用 Chocolatey
choco install nats-server

# 或 Docker
docker run -p 4222:4222 nats:latest
```

### 配置 NATS URL

在 `.env` 中设置：
```bash
GALAXY_NATS_URL=nats://localhost:4222
GALAXY_NATS_ENABLED=true
```

---

## ✅ 验证安装

### 1. 检查依赖

```bash
python scripts/check_dependencies.py
```

### 2. 运行系统检查

```bash
python main.py --check-only
```

### 3. 测试 API

```bash
# 健康检查
curl http://localhost:9000/health

# 获取系统状态
curl http://localhost:9000/api/status

# 测试聊天 API
curl -X POST http://localhost:9000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, Galaxy!"}'
```

### 4. 查看日志

```bash
# 最后 50 行日志
tail -50 logs/galaxy.log

# 实时跟踪日志
tail -f logs/galaxy.log
```

---

## 🐛 常见问题

### ❌ "NATS is not running"

**解决方案**：
```bash
# 启动 NATS
nats-server -p 4222

# 或通过 Docker
docker run -d -p 4222:4222 --name galaxy-nats nats:latest

# 或禁用 NATS（只用于开发）
export GALAXY_NATS_ENABLED=false
python main.py
```

### ❌ "No LLM API configured"

**解决方案**：
```bash
# 设置至少一个 LLM API Key
export OPENAI_API_KEY=sk-...
python setup_wizard.py --quick
```

### ❌ "Port 9000 already in use"

**解决方案**：
```bash
# 指定其他端口
python main.py --port 8300

# 或查找并停止占用该端口的进程
lsof -i :9000        # 查看占用进程
kill -9 <PID>        # 停止进程
```

### ❌ "PostgreSQL connection refused"

**解决方案**：
```bash
# 启动 PostgreSQL（Docker）
docker run -d -p 5432:5432 \
  -e POSTGRES_PASSWORD=ufo123 \
  -e POSTGRES_DB=ufogalaxy \
  --name galaxy-postgres \
  postgres:15

# 验证连接
psql postgresql://postgres:ufo123@localhost:5432/ufogalaxy -c "SELECT 1"
```

### ❌ "ImportError: No module named 'core.xyz'"

**解决方案**：
```bash
# 重新安装依赖
pip install -r requirements.txt

# 或清空 Python 缓存
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
python main.py
```

---

## 📦 完整部署（所有 130 个节点）

如果要启动完整的 Galaxy 节点生态：

```bash
# 启动所有 130 个节点 + 基础设施
docker-compose -f deploy/compose/full.yml --profile full up -d

# 查看运行的容器
docker-compose -f deploy/compose/full.yml ps

# 查看日志
docker-compose -f deploy/compose/full.yml logs -f galaxy

# 停止所有服务
docker-compose -f deploy/compose/full.yml --profile full down
```

---

## 🔄 更新和维护

### 更新代码

```bash
git pull origin main
pip install -r requirements.txt --upgrade
python main.py
```

### 清空缓存和日志

```bash
# 清空 Python 缓存
find . -type d -name __pycache__ -exec rm -rf {} +

# 清空 Redis 缓存
redis-cli FLUSHALL

# 清空日志
rm -rf logs/*.log
```

### 重置配置

```bash
# 备份现有配置
cp .env .env.backup

# 重新运行配置向导
python setup_wizard.py --interactive
```

---

## 📚 后续资源

- 📖 **Architecture**: 查看 `docs/UNIFIED_SUBJECT_ARCHITECTURE.md`
- 🔌 **API 文档**: 启动后访问 http://localhost:9000/docs
- 📝 **贡献指南**: 见 `CONTRIBUTING.md`
- 🚀 **部署指南**: 见 `deploy/README.md`
- 🐛 **故障排查**: 见 `docs/TROUBLESHOOTING.md`

---

## 🆘 需要帮助？

```bash
# 查看所有可用命令
python main.py --help

# 检查系统状态
python main.py --status

# 运行诊断检查
python -m core.config_preflight --mode all

# 查看日志
tail -f logs/galaxy.log
```

---

**祝你使用愉快！🎉**
