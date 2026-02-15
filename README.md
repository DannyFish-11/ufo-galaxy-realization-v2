# Galaxy - L4 级自主性智能系统

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

**Galaxy** 是一个完整的 L4 级自主性智能系统。克隆后运行安装脚本，系统将自动配置并 7×24 小时运行，每次开机自动启动。

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

# 完成！Galaxy 现在正在后台运行，并且已设置开机自启动
```

### Windows

```cmd
# 1. 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 2. 双击运行 install.bat
# 或在命令行中运行:
install.bat

# 完成！Galaxy 现在正在后台运行，并且已设置开机自启动
```

---

## ✨ 安装后自动完成

运行安装脚本后，系统会自动：

1. ✅ 创建虚拟环境
2. ✅ 安装所有依赖
3. ✅ 创建配置文件
4. ✅ 配置 API Key (交互式)
5. ✅ 设置开机自启动
6. ✅ 启动后台服务

**安装完成后，Galaxy 将：**
- 在后台 7×24 小时运行
- 每次开机自动启动
- 按 F12 键唤醒交互界面

---

## 🎮 交互方式

### 唤醒界面

```
按 F12 键 → 交互界面从右侧滑出
```

### 使用界面

```
┌────────────────────────────────────┐
│  Galaxy                       ● 在线│
│  ─────────────────────────────    │
│                                    │
│  用户: 帮我截图                     │
│  系统: 正在执行...                  │
│                                    │
│  [输入命令...]          [发送]     │
│  [🎤 语音]                          │
└────────────────────────────────────┘
```

---

## 📊 访问地址

安装完成后，访问以下地址：

| 界面 | 地址 |
|------|------|
| **配置中心** | http://localhost:8080/config |
| **设备管理** | http://localhost:8080/devices |
| **API 文档** | http://localhost:8080/docs |

---

## 🔧 管理命令

```bash
# 查看状态
./galaxy.sh status

# 启动服务
./galaxy.sh start

# 停止服务
./galaxy.sh stop

# 重启服务
./galaxy.sh restart

# 启动交互界面
./galaxy.sh ui

# 查看日志
./galaxy.sh logs

# 打开配置
./galaxy.sh config
```

---

## 🔑 API Key 配置

安装时会提示配置 API Key，也可以稍后编辑 `.env` 文件：

```bash
# 编辑配置文件
nano .env   # Linux/macOS
notepad .env  # Windows
```

**至少配置一个 API Key：**

```bash
# OpenAI (推荐)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx

# 或 DeepSeek (性价比高)
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

---

## 📱 Android 客户端

### 构建 APK

```bash
# 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
cd ufo-galaxy-android

# 配置服务器地址 (编辑 app/build.gradle)
# buildConfigField "String", "GALAXY_SERVER_URL", '"ws://你的服务器IP:8765"'

# 构建 APK
./gradlew assembleDebug

# 安装到设备
adb install app/build/outputs/apk/debug/app-debug.apk
```

### 使用方式

1. 打开 Galaxy 应用
2. 授予权限 (悬浮窗、麦克风、通知)
3. 从屏幕右侧边缘滑动唤醒灵动岛
4. 点击麦克风说话 或 打字输入

---

## 🌐 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Galaxy 系统                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  7×24 后台运行                                       │   │
│  │  - 开机自启动                                        │   │
│  │  - 自动重启                                          │   │
│  │  - 健康检查                                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  交互界面 (F12 唤醒)                                 │   │
│  │  - 卷轴式展开                                        │   │
│  │  - 打字/语音交互                                     │   │
│  │  - 摄像头/视觉理解                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  LLM 智能路由                                        │   │
│  │  - 三级优先模型                                      │   │
│  │  - 负载均衡                                          │   │
│  │  - 故障转移                                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 快速开始清单

- [ ] 克隆仓库
- [ ] 运行 install.sh / install.bat
- [ ] 配置 API Key
- [ ] 按 F12 测试交互界面
- [ ] 访问 http://localhost:8080/config
- [ ] 完成！

---

## 🔗 相关仓库

- [Galaxy Android](https://github.com/DannyFish-11/ufo-galaxy-android) - Android 客户端

---

## 📄 许可证

MIT License

---

**Galaxy - 克隆、安装、使用，就这么简单！** 🌌

---

## 🧠 记忆系统

Galaxy 拥有完整的记忆系统，可以记住对话历史、用户偏好和重要信息。

### 访问记忆中心

```
http://localhost:8080/memory
```

### 记忆类型

| 类型 | 说明 |
|------|------|
| **对话历史** | 自动保存所有对话，支持上下文理解 |
| **长期记忆** | 记住重要事实、偏好、事件、知识 |
| **用户偏好** | 学习并记住你的偏好设置 |

### 功能

- 💬 **对话历史**: 自动保存，支持上下文理解
- 🧠 **长期记忆**: 记住重要的事情
- 🔍 **记忆搜索**: 快速查找历史信息
- ⚙️ **用户偏好**: 自动学习你的偏好

### 使用示例

```
用户: 记住我喜欢喝咖啡
Galaxy: 好的，我已经记住了你喜欢喝咖啡。

用户: 我喜欢什么？
Galaxy: 根据我的记忆，你喜欢喝咖啡。

用户: 记住我明天下午3点有会议
Galaxy: 好的，我已经记住了你明天下午3点有会议。
```

### 数据存储

所有记忆数据存储在 `data/memory/` 目录：

```
data/memory/
├── sessions/           # 对话会话
├── long_term_memory.json  # 长期记忆
└── user_preferences.json  # 用户偏好
```

