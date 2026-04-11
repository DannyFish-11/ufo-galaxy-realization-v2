# Galaxy - 快速上手指南

> ⚠️ **先看真实运行路径**：请先阅读
> [`docs/CLONE_TO_USE_REALITY.md`](docs/CLONE_TO_USE_REALITY.md)。
> 该文档定义了当前仓库的 canonical clone-to-use 路径、
> 桌面状态板唤醒方式、交互入口与跨设备边界。

## 🎯 系统概览 (Round 2 - R-4)

Galaxy 是一个 **L4 级自主性智能系统**，集成了：

- ✨ **能力注册与发现** (OpenClaw 风格) - 统一能力索引和调度
- 🔗 **稳定连接管理** (向日葵风格) - 心跳保活、自动重连
- 🏗️ **完整系统群型架构** - 贯穿启动→注册→通信→监控的闭环

### 核心流程

```mermaid
graph LR
    A[配置加载] --> B[能力注册]
    B --> C[节点启动]
    C --> D[连接初始化]
    D --> E[健康监控]
    E --> B
```

---

## ⚡ 10分钟本地快速验证 (PR-G7)

> **一条命令** 启动最小节点集（Tasker + Gateway + VLM stub）并跑通  
> WS → HTTP → result 烟雾路径，全程约 1–2 分钟。

### 前提条件

| 工具 | 版本要求 |
|------|---------|
| Python | ≥ 3.9 |
| pip 依赖 | `fastapi uvicorn[standard] websockets httpx`（脚本自动安装） |
| bash | Linux / macOS 原生；Windows 请用 WSL2 或 Git Bash |

### 一条命令运行

```bash
# 克隆仓库后，在项目根目录执行：
bash scripts/quick_verify.sh
```

或者使用 Make 目标：

```bash
make quick-verify
```

正常输出示例：

```
  [INFO] Starting VLM stub on :8199 ...
  [INFO] Starting Galaxy Gateway on :8888 ...
  [INFO] Starting Tasker stub on :8299 ...
  [PASS] VLM stub is up
  [PASS] Gateway is up
  [PASS] Tasker stub is up
  [PASS] GET /health → 200
  [PASS] WS /ws/status → ping echoed
  [PASS] POST /api/v1/vlm/infer → result:stub_ok
  [PASS] Tasker /health → gateway_reachable:true
  [PASS] POST /api/v1/task/submit → task_id present
  ✅  All smoke checks passed — minimal stack healthy
```

### 自定义端口

```bash
VLM_PORT=9199 GATEWAY_PORT=9888 TASKER_PORT=9299 bash scripts/quick_verify.sh
```

### Make 工具链

项目根目录提供了常用的 Make 目标：

```bash
make fmt          # black + isort 自动格式化
make lint         # flake8 静态检查
make test:fast    # pytest -m "not slow"（快速 CI 门）
make contract     # 生成 protobuf stubs + proto lint
make quick-verify # 10分钟本地最小栈烟雾验证
```

> **Windows 用户**：Make 目标在 WSL2 / Git Bash 下可直接使用。
> 原生 CMD/PowerShell 可直接运行对应的 `python -m` 命令：
> ```powershell
> python -m black core/ tests/
> python -m isort core/ tests/
> python -m flake8 core/ tests/ --max-line-length=120
> python -m pytest tests/ -m "not slow"
> ```

### 仅跑烟雾测试（无需启动进程）

```bash
python -m pytest -m g7_smoke tests/test_g7_smoke.py -v --tb=short
```

---

## 🔧 常见故障排查 / Troubleshooting（快速路径）

| 症状 | 原因 | 解决方法 |
|------|------|---------|
| `[FAIL] Gateway is up` | Gateway 端口被占用 | `GATEWAY_PORT=9888 bash scripts/quick_verify.sh` |
| `ImportError: fastapi` | 缺少依赖 | `pip install -r requirements.txt` |
| `[FAIL] WS /ws/status → ping echoed` | Gateway 未完全启动 | 脚本已内置 15 s 重试；若仍失败请检查 Python 路径 |
| `Permission denied: quick_verify.sh` | 脚本未加执行权限 | `chmod +x scripts/quick_verify.sh` |
| Windows 下 `bash` 报错 | 缺少 bash 环境 | 安装 [WSL2](https://learn.microsoft.com/zh-cn/windows/wsl/install) 或 [Git Bash](https://git-scm.com/downloads) |
| `flake8` / `black` 报错 | 缺少开发依赖 | `pip install -r requirements-dev.txt` |

---

## 🚀 一键启动

### 方式 1: Docker Compose (推荐)

```bash
# 1. 克隆仓库
git clone https://github.com/DannyFish-11/galaxy-realization.git
cd galaxy-realization

# 2. 一键启动
docker-compose up -d

# 3. 查看状态
docker-compose ps
```

### 方式 2: 本地安装

```bash
# 1. 克隆仓库
git clone https://github.com/DannyFish-11/galaxy-realization.git
cd galaxy-realization

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动系统
python -m launcher start --groups core

# 4. 查看状态
python -m launcher status
```

## 📱 手机跨设备联通

### Android App 配置

1. **下载 APK**
   ```bash
   # 从 GitHub Releases 下载
   wget https://github.com/DannyFish-11/galaxy-android/releases/latest/download/app-release.apk
   ```

2. **配置服务器地址**
   - 打开 App → Settings
   - 输入服务器地址: `ws://your-server-ip:9000`
   - 点击 Connect

3. **授权设备**
   - 在服务器端确认设备注册
   - 设备将自动同步

### 自然语言控制

从手机发送语音/文字命令:

```
"打开客厅的灯"                    → 控制智能家居
"让无人机起飞到10米"              → 控制无人机
"开始打印文件test.gcode"          → 控制3D打印机
"截图保存"                        → 控制浏览器
"发送邮件给xxx说你好"              → 发送邮件
"创建一个明天下午3点的会议"        → 创建日程
```

## 🎯 支持的设备和平台

| 平台/设备 | 节点ID | 示例命令 |
|-----------|--------|----------|
| **iOS** | Node_26 | "打开iPhone上的微信" |
| **Android** | Node_33 | "连接Android设备" |
| **Windows** | Node_36 | "点击Windows上的按钮" |
| **macOS** | Node_35 | "执行AppleScript" |
| **Linux** | Node_37 | "执行Linux命令" |
| **智能家居** | Node_27 | "打开客厅的灯" |
| **无人机** | Node_43 | "让无人机起飞" |
| **3D打印机** | Node_49 | "开始打印文件" |
| **浏览器** | Node_98 | "打开网站example.com" |
| **邮件** | Node_16 | "发送邮件" |
| **日历** | Node_23 | "创建日程" |
| **GitHub** | Node_11 | "列出仓库" |
| **量子计算** | Node_51 | "提交量子任务" |

## 🔧 常用命令

### 节点管理

```bash
# 启动所有核心节点
python -m launcher start --groups core

# 启动特定节点
python -m launcher start --nodes 26 27 43

# 查看节点状态
python -m launcher status

# 停止所有节点
python -m launcher stop
```

### 自然语言执行

```python
from enhancements.nlu.unified_nlu import NLUCommandExecutor

executor = NLUCommandExecutor(gateway)

# 从任意节点执行自然语言命令
result = await executor.execute_text("打开客厅的灯")
```

### 跨节点通信

```python
from core.node_communication import wakeup_node, execute_command

# 从服务器唤醒Android设备
await wakeup_node("server_01", "android_01", "new_task")

# 从Android控制服务器
await execute_command("android_01", "server_50", "process_data", args=["data"])

# 节点自激活
await activate_self("server_01", "restart_service")
```

## 🌐 Web 控制台

启动后访问:
- **控制台**: http://localhost:3000 (Grafana)
- **API 文档**: http://localhost:9000/docs
- **节点状态**: http://localhost:9000/status

## 📊 监控面板

```bash
# 查看日志
docker-compose logs -f

# 查看指标
curl http://localhost:9090/metrics

# 查看节点健康
curl http://localhost:9000/health
```

## 🔐 安全配置

```bash
# 设置 API Key
export GALAXY_API_KEY="your-secret-key"

# 配置 JWT Secret
export JWT_SECRET="your-jwt-secret"

# 启用 HTTPS
export GALAXY_HTTPS_ENABLED=true
export GALAXY_SSL_CERT=/path/to/cert.pem
export GALAXY_SSL_KEY=/path/to/key.pem
```

## 🐛 故障排查

### 常见问题

1. **节点无法启动**
   ```bash
   # 检查日志
   python -m launcher status
   
   # 重启节点
   python -m launcher restart --nodes <node_id>
   ```

2. **Android 无法连接**
   ```bash
   # 检查网络
   ping your-server-ip
   
   # 检查防火墙
   sudo ufw allow 9000
   ```

3. **自然语言识别失败**
   ```bash
   # 测试 NLU
   python enhancements/nlu/unified_nlu.py
   ```

## 📚 更多文档

- [完整文档](docs/README.md)
- [API 参考](docs/API.md)
- [节点开发指南](docs/NODE_DEVELOPMENT.md)
- [部署指南](docs/DEPLOYMENT.md)
- [能力注册系统](docs/CAPABILITY_SYSTEM.md)

## 🔧 能力注册与连接管理 (New in R-4)

### 验证系统状态

```bash
# 验证能力注册系统
python scripts/verify_capability_registry.py

# 运行集成测试
python tests/test_capability_integration.py
```

### 能力查询

系统启动后，能力信息保存在 `config/capabilities.json`：

```json
{
  "version": "1.0.0",
  "capabilities": [
    {
      "name": "http_get",
      "description": "HTTP GET 请求",
      "node_id": "08",
      "node_name": "Fetch",
      "category": "http",
      "status": "online"
    }
  ]
}
```

### 连接状态

连接信息保存在 `config/connection_state.json`：

```json
{
  "timestamp": "2026-02-11T08:00:00",
  "connections": [
    {
      "connection_id": "node_08",
      "url": "http://localhost:8008",
      "state": "connected",
      "last_heartbeat": "2026-02-11T08:00:30"
    }
  ]
}
```

### 健康监控集成

健康监控现在包括能力和连接状态：

```bash
# 查看完整系统状态
python system_manager.py status
```

输出包括：
- 节点健康状态
- 能力在线/离线统计
- 连接状态和重连次数

## 💬 获取帮助

- GitHub Issues: https://github.com/DannyFish-11/galaxy-realization/issues
- Discord: https://discord.gg/galaxy

---

## 🤖 OpenClawd Agent 心跳调度器

OpenClawd 内置 **自主心跳调度器（OpenClaw 3.x 风格）**，让智能体每隔固定时间自动"唤醒"并执行维护任务。

### 配置方式

心跳配置分两部分：

#### 1. `config/agent.yaml` — 系统配置

```yaml
agent:
  name: core_agent

heartbeat:
  enabled: true          # 是否启用（可通过 .env 覆盖）
  interval: 30m          # 触发间隔（s/m/h，默认 30 分钟）
  task_file: agent/HEARTBEAT.md   # 任务清单文件
  ack_token: HEARTBEAT_OK         # 无任务时的 ACK 令牌
  max_output_chars: 160           # ACK 判定最大长度
  tier1_model: local_small        # 默认轻量模型（节省 token）
  tier2_model: gpt-4o             # 复杂任务升级模型
  tier2_trigger:
    - "complex_reasoning"
    - "multi_step_plan"
    - "code_generation"
```

#### 2. `.env` — 仅存放密钥，不做系统配置

```dotenv
# 可选：在运行时覆盖 agent.yaml 中的设置
# HEARTBEAT_ENABLED=true
# HEARTBEAT_INTERVAL=30m
```

### 任务清单 `agent/HEARTBEAT.md`

心跳触发时，智能体读取 `agent/HEARTBEAT.md` 并逐项执行：

```markdown
# Heartbeat Tasks

## system check
- check device status
- check pending tasks
- update memory if needed

## scheduled jobs
- every 30m: check notifications
- every 2h: check device health

## autonomous tasks
- optimize skills if possible
- summarize logs
```

### ACK 抑制机制

当智能体没有任何任务要执行时，它返回 `HEARTBEAT_OK`（短文本）。
心跳调度器检测到 ACK 后，**只写日志，不向用户输出**，避免垃圾消息。

### 分级模型路由

| 场景 | 模型 |
|------|------|
| 普通维护任务 | `tier1_model`（轻量/廉价） |
| 包含 `complex_reasoning` / `code_generation` 等关键词 | `tier2_model`（强模型） |

### 禁用心跳

```yaml
# config/agent.yaml
heartbeat:
  enabled: false
```

或在 `.env` 中设置：

```dotenv
HEARTBEAT_ENABLED=false
```

---

**现在你可以从手机控制所有设备了！** 🎉
