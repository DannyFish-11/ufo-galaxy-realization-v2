# Galaxy - L4 级自主性智能系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

**Galaxy** 是一个完整的 L4 级自主性智能系统。克隆后运行安装脚本，系统将自动配置并运行。

---

## 🚀 一键安装

### Linux / macOS

```bash
# 1. 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 2. 运行安装脚本
chmod +x install.sh
./install.sh

# 完成！
```

### Windows

```cmd
# 1. 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 2. 双击运行 windows\install.bat

# 完成！
```

---

## ✨ 功能特性

### 核心功能

| 功能 | 说明 |
|------|------|
| 🔧 **配置中心** | 可视化配置所有 API Key |
| 📱 **设备管理** | 管理所有连接的设备 |
| 🧠 **记忆系统** | 对话历史、长期记忆、用户偏好 |
| 🔀 **AI 智能路由** | 自动选择最佳 LLM 模型 |
| 🔑 **API Key 管理** | 统一管理所有 API Key |

### 系统特性

| 特性 | 说明 |
|------|------|
| ✅ 一键安装 | 自动配置环境 |
| ✅ 开机自启 | Windows/Linux 自动启动 |
| ✅ 系统托盘 | 右下角显示实时状态 |
| ✅ 远程访问 | 支持 Tailscale 远程连接 |

---

## 📊 访问地址

安装完成后，访问以下地址：

| 界面 | 地址 |
|------|------|
| 控制面板 | http://localhost:8080 |
| 配置中心 | http://localhost:8080/config |
| 设备管理 | http://localhost:8080/devices |
| 记忆中心 | http://localhost:8080/memory |
| AI 路由 | http://localhost:8080/router |
| API Key | http://localhost:8080/api-keys |
| API 文档 | http://localhost:8080/docs |

---

## 🔧 管理命令

### Linux / macOS

```bash
./galaxy.sh start     # 启动
./galaxy.sh stop      # 停止
./galaxy.sh restart   # 重启
./galaxy.sh status    # 状态
./galaxy.sh logs      # 日志
./galaxy.sh check     # 系统检查
```

### Windows

```cmd
# 快速启动
双击 windows\quick_start.bat

# 托盘模式
双击 windows\start_galaxy.bat

# 系统托盘
右下角图标 → 右键菜单
```

---

## 🔑 API Key 配置

### 方式一：OneAPI 统一网关（推荐）

```
ONEAPI_URL=http://localhost:3000
ONEAPI_API_KEY=your-oneapi-key
```

配置 OneAPI 后，所有 LLM 请求通过统一网关，无需单独配置各 LLM API Key。

### 方式二：单独配置

```bash
# 编辑 .env 文件
OPENAI_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx
# ...
```

### 可视化配置

访问 http://localhost:8080/api-keys 在界面中配置。

---

## 📱 远程访问

### 使用 Tailscale

1. 安装 Tailscale: https://tailscale.com
2. 登录并连接网络
3. 获取 Tailscale IP: `tailscale ip`
4. 手机/平板访问: `http://[Tailscale-IP]:8080`

---

## 🖥️ 系统托盘（Windows）

启动后右下角显示图标：

| 颜色 | 状态 |
|------|------|
| 🟢 青色 | 运行中 |
| 🟡 黄色 | 部分异常 |
| 🔴 红色 | 已停止 |
| ⚪ 灰色 | 待机中 |

**右键菜单：**
- 打开控制面板
- 打开配置
- 重启/停止服务
- 开机自启动开关
- 退出

---

## 📁 项目结构

```
galaxy/
├── core/                    # 核心模块
│   ├── memory.py           # 记忆系统
│   ├── ai_router.py        # AI 智能路由
│   ├── llm_router.py       # LLM 路由
│   └── api_key_manager.py  # API Key 管理
├── galaxy_gateway/          # 服务网关
│   ├── main_app.py         # 主应用
│   ├── config_service.py   # 配置服务
│   ├── memory_service.py   # 记忆服务
│   ├── router_service.py   # 路由服务
│   └── static/             # 界面文件
├── windows/                 # Windows 支持
│   ├── install.bat         # 安装脚本
│   ├── quick_start.bat     # 快速启动
│   └── galaxy_tray.py      # 托盘程序
├── nodes/                   # 功能节点 (108个)
├── install.sh              # Linux/macOS 安装
├── galaxy.sh               # 管理脚本
├── run_galaxy.py           # 启动入口
└── .env.example            # 配置模板
```

---

## 📊 代码统计

| 类型 | 数量 |
|------|------|
| Python 代码 | 368,000+ 行 |
| Kotlin 代码 | 15,000+ 行 |
| 功能节点 | 108 个 |
| 界面文件 | 6 个 |

---

## 🔗 相关仓库

- **Galaxy 主系统**: https://github.com/DannyFish-11/ufo-galaxy-realization-v2
- **Android 客户端**: https://github.com/DannyFish-11/ufo-galaxy-android

---

## 📄 License

MIT License

---

**Galaxy v2.1.6 - 完整的 L4 级自主性智能系统** 🌌
