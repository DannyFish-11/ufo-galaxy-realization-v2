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

---

## 📱 设备注册

### 快速注册设备

```bash
# 自动检测并注册当前设备
python register_device.py --gateway http://192.168.x.x:8080
```

### 各平台注册方式

| 平台 | 注册方式 |
|------|----------|
| **Android** | 安装 APK 客户端，输入服务器地址 |
| **Windows** | 运行 `register_device.py` 或启动客户端 |
| **Linux** | 运行 `register_device.py` 或 SSH 连接 |
| **macOS** | 运行 `register_device.py` 或 AppleScript |
| **云服务器** | 作为主节点或工作节点部署 |

### 详细文档

参见 [设备注册指南](DEVICE_REGISTRATION_GUIDE.md)


---

## 🖥️ 可视化界面

### 控制面板

启动系统后，访问以下地址：

| 界面 | 地址 | 说明 |
|------|------|------|
| 控制面板 | http://localhost:8080 | 系统状态概览 |
| **设备管理** | http://localhost:8080/devices | 可视化设备注册和管理 |
| API 文档 | http://localhost:8080/docs | FastAPI 自动文档 |

### 设备管理界面

```
功能:
├── 📱 设备注册 - 可视化表单注册新设备
├── 📋 设备列表 - 查看所有已注册设备
├── 🟢 状态监控 - 实时显示设备在线/离线状态
├── 📊 统计概览 - 设备数量、在线率统计
├── 🔍 搜索过滤 - 按名称、类型搜索设备
├── ⚡ 命令发送 - 向设备发送控制命令
└── 🗑️ 设备注销 - 移除不需要的设备
```

### 启动方式

```bash
# 方式一：启动完整系统
./start.sh

# 方式二：仅启动设备管理服务
./start_device_manager.sh

# 访问设备管理界面
open http://localhost:8080/devices
```


---

## 🎮 交互系统

### 主仓库交互方式

| 功能 | 说明 |
|------|------|
| **按键唤醒** | 按 F12 键唤醒/隐藏界面 |
| **卷轴 UI** | 书法卷轴式展开动画 |
| **侧边栏** | 从右侧滑入的极客风界面 |
| **打字交互** | 输入命令与 AI 对话 |
| **摄像头** | 截图、视频流 |
| **视觉理解** | VLM 分析屏幕内容 |

### 启动交互界面

```bash
# 方式一：启动交互系统
./start_ui.sh

# 方式二：指定 UI 风格
python start_interactive.py --style geek_scroll   # 卷轴式
python start_interactive.py --style geek_sidebar  # 侧边栏

# 方式三：自定义热键
python start_interactive.py --hotkey f12
```

### UI 风格

#### 卷轴式 (geek_scroll)
```
┌────────────────────────────────────┐
│  ███████╗   ██╗   ██╗   ███████╗  │
│  ██╔════╝   ██║   ██║   ██╔════╝  │
│  ███████╗   ██║   ██║   ███████╗  │
│  ╚════██║   ██║   ██║   ╚════██║  │
│  ███████║   ╚██████╔╝   ███████║  │
│  ╚══════╝    ╚═════╝    ╚══════╝  │
│                                    │
│  UFO³ Galaxy                       │
│  ─────────────────────────────    │
│                                    │
│  用户: 帮我截图                     │
│  系统: 正在执行...                  │
│                                    │
│  [输入命令...]          [发送]     │
└────────────────────────────────────┘
```

#### 侧边栏式 (geek_sidebar)
```
                    ┌────────────────────┐
                    │ UFO³ Galaxy  ● 在线 │
                    │ ────────────────── │
                    │                    │
                    │ 对话历史           │
                    │ ┌────────────────┐ │
                    │ │ 用户: 帮我截图  │ │
                    │ │ 系统: 已完成    │ │
                    │ └────────────────┘ │
                    │                    │
                    │ 快捷操作           │
                    │ [📸截图][📋剪贴板] │
                    │                    │
                    │ ┌────────────────┐ │
                    │ │ 输入命令...     │ │
                    │ └────────────────┘ │
                    │ [🎤语音]    [发送] │
                    └────────────────────┘
```

### Android 交互方式

| 功能 | 说明 |
|------|------|
| **边缘滑动** | 从屏幕右侧边缘滑动唤醒 |
| **灵动岛** | 灵动岛式悬浮窗 |
| **语音输入** | 点击麦克风按钮说话 |
| **悬浮交互** | 随时随地唤起 |

### Android 使用方法

1. **安装 APK**
   ```bash
   ./gradlew assembleDebug
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```

2. **授予权限**
   - 悬浮窗权限
   - 麦克风权限
   - 通知权限

3. **唤醒方式**
   - 从屏幕右侧边缘向左滑动
   - 点击灵动岛展开

4. **交互方式**
   - 点击麦克风按钮说话
   - 或在输入框打字

