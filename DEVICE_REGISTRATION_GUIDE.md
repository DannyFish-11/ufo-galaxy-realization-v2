# UFO Galaxy V2 - 设备注册指南

**版本**: v2.0.5
**更新时间**: 2026-02-15

---

## 📋 概述

UFO Galaxy V2 支持多种设备的注册和连接，包括：
- Android 设备 (手机/平板)
- Windows 电脑
- Linux 服务器
- macOS 设备
- 云服务器

---

## 🌐 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Galaxy Gateway (主节点)                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  WebSocket Server (端口 8765)                        │   │
│  │  HTTP API Server (端口 8080)                         │   │
│  │  设备注册服务                                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
         ▼                ▼                ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ Android  │     │ Windows  │     │  Linux   │
   │  客户端  │     │  客户端  │     │  客户端  │
   └──────────┘     └──────────┘     └──────────┘
```

---

## 📱 Android 设备注册

### 方式一：使用 APK 客户端

1. **下载 APK**
   ```bash
   # 从仓库构建
   git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
   cd ufo-galaxy-android
   ./gradlew assembleDebug
   ```

2. **安装到设备**
   ```bash
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```

3. **配置连接**
   - 打开 UFO Galaxy 应用
   - 进入设置页面
   - 输入服务器地址：
     - 本地：`ws://192.168.x.x:8765`
     - Tailscale：`ws://100.x.x.x:8765`
     - 云服务器：`wss://your-domain.com:8765`

4. **设备自动注册**
   - 应用启动后自动发送注册消息
   - 包含设备 ID、类型、能力等信息

### 方式二：通过 ADB 控制（无需安装客户端）

```bash
# 确保设备已连接
adb devices

# 系统自动发现设备
# Node_33_ADB 会自动注册连接的 Android 设备
```

---

## 💻 Windows 设备注册

### 方式一：使用 Windows 客户端

1. **克隆仓库**
   ```bash
   git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
   cd ufo-galaxy-realization-v2/windows_client
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置连接**
   ```bash
   # 设置环境变量
   set NODE_50_URL=ws://192.168.x.x:8050
   set DEVICE_ID=Windows_PC_001
   
   # 或创建配置文件
   echo NODE_50_URL=ws://192.168.x.x:8050 > .env
   echo DEVICE_ID=Windows_PC_001 >> .env
   ```

4. **启动客户端**
   ```bash
   python main.py --node50_url ws://192.168.x.x:8050 --client_id Windows_PC_001
   ```

### 方式二：通过 HTTP API 注册

```bash
# 使用 curl 注册设备
curl -X POST http://192.168.x.x:8080/api/devices/register \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "Windows_PC_001",
    "device_name": "我的电脑",
    "device_type": "windows",
    "aliases": ["电脑", "PC"],
    "capabilities": ["execute_script", "send_notification", "status_update"],
    "ip_address": "192.168.x.x"
  }'
```

### 方式三：通过 Node_36_UIAWindows 控制

```bash
# Node_36 会自动注册本地 Windows 设备
# 只需启动节点即可
cd nodes/Node_36_UIAWindows
python main.py
```

---

## 🐧 Linux 设备注册

### 方式一：使用 SSH 连接

```bash
# Node_39_SSH 可以远程控制 Linux 设备
# 在主节点配置 SSH 连接

# 1. 确保 SSH 服务运行
sudo systemctl start sshd

# 2. 在主节点添加设备
curl -X POST http://localhost:8080/api/devices/register \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "Linux_Server_001",
    "device_name": "Linux 服务器",
    "device_type": "linux",
    "aliases": ["服务器", "Linux"],
    "capabilities": ["ssh", "execute_command", "file_transfer"],
    "ip_address": "192.168.x.x"
  }'
```

### 方式二：运行客户端

```bash
# 克隆仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 配置
export NODE_50_URL=ws://192.168.x.x:8050
export DEVICE_ID=Linux_Server_001

# 启动客户端
python windows_client/client.py  # 同样的客户端可用于 Linux
```

### 方式三：通过 Node_37_LinuxDBus 控制

```bash
# Node_37 使用 D-Bus 控制 Linux 桌面
cd nodes/Node_37_LinuxDBus
python main.py
```

---

## ☁️ 云服务器注册

### 作为主节点

```bash
# 1. 部署主系统
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2
./deploy.sh

# 2. 配置公网访问
# 编辑 .env
PUBLIC_URL=https://your-domain.com
WEBSOCKET_PORT=8765

# 3. 启动服务
./start.sh
```

### 作为工作节点

```bash
# 1. 部署客户端
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# 2. 配置连接主节点
export UFO_NODE_ID="cloud-worker-001"
export UFO_NODE_ROLE="worker"
export MASTER_URL="ws://main-server:8765"

# 3. 启动
python main.py --worker
```

---

## 📋 注册 API 参考

### HTTP API

```http
POST /api/devices/register
Content-Type: application/json

{
  "device_id": "unique_device_id",
  "device_name": "设备名称",
  "device_type": "android|windows|linux|macos",
  "aliases": ["别名1", "别名2"],
  "capabilities": ["capability1", "capability2"],
  "ip_address": "192.168.x.x"
}
```

### WebSocket 消息

```json
{
  "protocol": "AIP/2.0",
  "type": "device_register",
  "source_node": "device_id",
  "target_node": "gateway",
  "timestamp": 1234567890,
  "payload": {
    "device_type": "windows",
    "device_name": "我的电脑",
    "capabilities": ["execute_script", "send_notification"]
  }
}
```

---

## 🔧 配置文件示例

### 主节点配置 (config.json)

```json
{
  "node_id": "master",
  "role": "coordinator",
  "websocket": {
    "host": "0.0.0.0",
    "port": 8765
  },
  "http": {
    "host": "0.0.0.0",
    "port": 8080
  },
  "discovery": {
    "mdns_enabled": true,
    "upnp_enabled": true,
    "broadcast_enabled": true
  }
}
```

### 客户端配置 (.env)

```bash
# 设备信息
DEVICE_ID=Windows_PC_001
DEVICE_NAME=我的电脑
DEVICE_TYPE=windows

# 连接配置
NODE_50_URL=ws://192.168.1.100:8050
GATEWAY_URL=ws://192.168.1.100:8765

# 能力
CAPABILITIES=execute_script,send_notification,status_update
```

---

## 🌐 Tailscale 网络配置

### 安装 Tailscale

```bash
# Windows
# 下载安装: https://tailscale.com/download

# Linux
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Android
# 从 Play Store 安装 Tailscale
```

### 配置连接

```bash
# 获取 Tailscale IP
tailscale ip

# 使用 Tailscale IP 连接
export GATEWAY_URL=ws://100.x.x.x:8765
```

---

## ✅ 验证注册

### 检查设备列表

```bash
# HTTP API
curl http://localhost:8080/api/devices

# 返回示例
{
  "devices": [
    {
      "device_id": "Android_Phone_001",
      "device_name": "我的手机",
      "device_type": "android",
      "status": "online",
      "capabilities": ["tap", "swipe", "screenshot"]
    },
    {
      "device_id": "Windows_PC_001",
      "device_name": "我的电脑",
      "device_type": "windows",
      "status": "online",
      "capabilities": ["execute_script", "send_notification"]
    }
  ]
}
```

### 测试设备控制

```bash
# 发送命令到设备
curl -X POST http://localhost:8080/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "Android_Phone_001",
    "command": "tap",
    "params": {"x": 500, "y": 800}
  }'
```

---

## 🚀 快速开始

### 最简单的注册方式

1. **启动主节点**
   ```bash
   ./start.sh
   ```

2. **其他设备自动发现**
   - 同一局域网内的设备会自动发现
   - 通过 mDNS/UPnP/广播协议

3. **手动注册（可选）**
   ```bash
   curl -X POST http://localhost:8080/api/devices/register \
     -H "Content-Type: application/json" \
     -d '{"device_id":"test","device_name":"测试设备","device_type":"other","ip_address":"127.0.0.1"}'
   ```

---

**设备注册完成后，即可通过系统控制所有已注册的设备！** 🎉
