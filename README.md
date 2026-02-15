# UFO Galaxy V2

**L4 级自主性智能系统 - 多设备协调星系**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-green)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🚀 快速开始

### 方式一：一键部署

```bash
# 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 一键部署
chmod +x deploy.sh
./deploy.sh

# 配置 API Key
nano .env

# 启动系统
./start.sh
```

### 方式二：Docker 部署

```bash
# 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# Docker 启动
./docker-start.sh
```

### 方式三：手动部署

```bash
# 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境
cp .env.example .env
nano .env  # 填写 API Key

# 启动系统
python main.py --minimal
```

---

## 📊 系统架构

```
UFO Galaxy V2
├── 核心层 (Core Layer)
│   ├── NodeRegistry - 节点注册中心
│   ├── NodeCommunication - 节点通信
│   ├── CacheManager - 缓存管理
│   ├── MonitoringManager - 监控管理
│   ├── SafeEval - 安全表达式求值
│   └── SecureConfig - 安全配置
│
├── 节点层 (Node Layer)
│   ├── 108 个功能节点
│   ├── 设备控制节点 (ADB/Scrcpy/AppleScript/UIA)
│   ├── 工具节点 (Git/OCR/FFmpeg/Search)
│   └── AI 节点 (OneAPI/Router/Transformer)
│
├── 协调层 (Coordination Layer)
│   ├── Node_71 - 多设备协调引擎
│   ├── 设备发现 (mDNS/UPnP)
│   ├── 状态同步 (向量时钟)
│   └── 任务调度 (多策略)
│
└── 网关层 (Gateway Layer)
    ├── GalaxyGateway - 统一网关
    ├── CrossDeviceCoordinator - 跨设备协调
    └── MCPAdapter - MCP 协议适配
```

---

## ✨ 核心功能

### 1. 多设备互控

- ✅ Android 设备控制 (ADB/Scrcpy)
- ✅ iOS/Mac 控制 (AppleScript)
- ✅ Windows 控制 (UI Automation)
- ✅ 蓝牙设备控制 (BLE)
- ✅ 远程设备控制 (SSH)
- ✅ IoT 设备控制 (MQTT)

### 2. 跨设备协调

- ✅ 剪贴板同步
- ✅ 文件传输
- ✅ 媒体控制同步
- ✅ 通知同步

### 3. AI 能力

- ✅ 多 LLM 支持 (OpenAI/Anthropic/DeepSeek/Gemini)
- ✅ 智能路由
- ✅ 意图理解
- ✅ 任务分解

### 4. MCP Skill 支持

- ✅ 24+ MCP 服务集成
- ✅ 工具注册和调用
- ✅ 健康检查

---

## 📋 配置说明

### 必需配置

```bash
# 至少配置一个 LLM API Key
OPENAI_API_KEY=sk-xxxxx
# 或
DEEPSEEK_API_KEY=sk-xxxxx
```

### 可选配置

```bash
# 数据库
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333

# 安全
JWT_SECRET=your-secret-key
```

---

## 🔧 常用命令

```bash
# 最小启动
python main.py --minimal

# 完整启动
python main.py

# 查看状态
python main.py --status

# 运行测试
python verify_system.py
```

---

## 📁 项目结构

```
ufo-galaxy-realization-v2/
├── core/                   # 核心模块
├── nodes/                  # 功能节点
├── galaxy_gateway/         # 网关层
├── enhancements/           # 增强模块
├── tests/                  # 测试文件
├── main.py                 # 主入口
├── unified_launcher.py     # 统一启动器
├── deploy.sh               # 一键部署
├── start.sh                # 快速启动
└── docker-start.sh         # Docker 启动
```

---

## 🔗 相关仓库

- [ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android) - Android 客户端

---

## 📄 许可证

MIT License

---

## 🙏 致谢

感谢所有贡献者和开源社区的支持！
