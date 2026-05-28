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
- ✅ 创建虚拟环境 (`venv`)
- ✅ 安装 Python 依赖 (`requirements.txt`)
- ✅ 初始化 `.env` 配置文件
- ✅ 生成/初始化 `config/` 目录
- ✅ 启动 NATS 服务（Docker 或本地）
- ✅ 运行系统预检检查

### 3️⃣ 启动系统

```bash
# 官方启动方式（推荐）
python main.py

# 或使用脚本
bash start.sh          # Linux/macOS
.\start.bat           # Windows
```

系统启动后访问：
- 🌐 **API 文档**: http://localhost:8299/docs
- 📊 **状态板**: http://localhost:8299/api/status
- 💬 **聊天 API**: http://localhost:8299/api/v1/chat

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
python unified_launcher.py --check-only
```

### 3. 测试 API

```bash
# 健康检查
curl http://localhost:8299/health

# 获取系统状态
curl http://localhost:8299/api/status

# 测试聊天 API
curl -X POST http://localhost:8299/api/v1/chat \
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

### ❌ "Port 8299 already in use"

**解决方案**：
```bash
# 指定其他端口
python main.py --port 8300

# 或查找并停止占用该端口的进程
lsof -i :8299        # 查看占用进程
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
- 🔌 **API 文档**: 启动后访问 http://localhost:8299/docs
- 📝 **贡献指南**: 见 `CONTRIBUTING.md`
- 🚀 **部署指南**: 见 `deploy/README.md`
- 🐛 **故障排查**: 见 `docs/TROUBLESHOOTING.md`

---

## 🆘 需要帮助？

```bash
# 查看所有可用命令
python main.py --help

# 检查系统状态
python unified_launcher.py --status

# 运行诊断检查
python -m core.config_preflight --mode all

# 查看日志
tail -f logs/galaxy.log
```

---

**祝你使用愉快！🎉**
