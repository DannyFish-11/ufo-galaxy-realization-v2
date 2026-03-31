# Galaxy 通信层说明 — 统一入口 Gateway + AIP v3

## 概述

Galaxy 系统通信层的唯一标准入口是 **Galaxy Gateway（默认端口 9000）+ AIP v3 协议**。

```
设备 / 客户端
    ↓ WebSocket / HTTP (AIP v3)
Galaxy Gateway (:9000)
    ↓
Core 路由 / CommandRouter
    ↓ （可选）
NATS 分布式调度总线
```

所有 Windows 客户端、Android 客户端、以及第三方集成均应连接 Gateway，
**不应直接连接任何 Node（如 Node_50:8050）**。

---

## AIP v3 协议

AIP v3 是 Galaxy 的消息格式规范，在 `core/schemas/protocol.py` 中定义。

**最小消息示例：**
```json
{
  "version": "3.0",
  "type": "device_register",
  "device_id": "my-device-001",
  "timestamp": 1741234567,
  "payload": {
    "device_type": "windows",
    "capabilities": ["execute_script", "send_notification"]
  }
}
```

### WebSocket 入口（推荐）

| 路径 | 说明 |
|------|------|
| `/ws/device/{device_id}` | 主推荐入口，所有设备类型 |
| `/ws/android/{device_id}` | Android 设备专用（AIP v3） |

### 旧路径（默认禁用）

| 路径 | 状态 |
|------|------|
| `/ws/ufo3/{device_id}` | **默认禁用**，设置 `GALAXY_ENABLE_LEGACY_PROTOCOLS=true` 可重新开启 |

---

## 环境变量汇总

### 核心入口

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GALAXY_GATEWAY_URL` | `ws://localhost:9000` | Windows 客户端连接的 Gateway WS 地址 |
| `GALAXY_API_BASE` | `http://localhost:9000` | HTTP API 基础地址 |

### 旧协议兼容开关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GALAXY_ENABLE_LEGACY_PROTOCOLS` | `false` | 设为 `true` 启用 `/ws/ufo3` 等旧 WS 路径 |

> ⚠️ 旧路径仅供过渡期兼容使用，生产环境请保持关闭。

### NATS 控制面

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GALAXY_NATS_URL` | —（未设置则 no-op）| NATS 服务地址，如 `nats://localhost:4222` |

**启用 NATS：**
1. 启动 NATS 服务（Docker 示例）：
   ```bash
   docker run -d --name nats -p 4222:4222 nats:latest
   ```
2. 设置环境变量并重启 Galaxy：
   ```bash
   export GALAXY_NATS_URL=nats://localhost:4222
   python unified_launcher.py
   ```
3. NATS 启用后提供：跨节点任务派发、Worker 心跳、分布式调度。

### Tailscale 网络穿透

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GALAXY_TAILSCALE_ENABLED` | `false` | 是否启用 Tailscale 网络层 |
| `GALAXY_TAILSCALE_HOST` | — | Tailscale 域名或 IP（可选） |

**启用 Tailscale：**
1. 安装并登录 Tailscale（[官网](https://tailscale.com/download)）。
2. 在 `.env` 中设置：
   ```bash
   GALAXY_TAILSCALE_ENABLED=true
   GALAXY_TAILSCALE_HOST=100.x.y.z   # 你的 Tailscale IP
   ```
3. 在 `.env` 中设置 `GALAXY_GATEWAY_URL` 为 Tailscale IP：
   ```bash
   GALAXY_GATEWAY_URL=ws://100.x.y.z:9000
   ```
   > **Note:** `start_galaxy_client.bat` was fully deleted in PR-8.  Set the gateway
   > URL via the `.env` file or the `GALAXY_GATEWAY_URL` environment variable instead.

### 可选传输通道

默认只有 Gateway WS（AIP v3）路由生效。以下通道需要明确启用：

| 变量 | 节点 | 说明 |
|------|------|------|
| `GALAXY_ENABLE_WEBRTC=true` | Node_95:8095 | WebRTC 实时视频流 |
| `GALAXY_ENABLE_SCRCPY=true` | Node_34:8034 | Scrcpy 屏幕镜像 |
| `GALAXY_ENABLE_MQTT=true` | Node_41:8041 | MQTT 轻量级控制信令 |

---

## SmartTransportRouter 路由逻辑

`galaxy_gateway/smart_transport_router.py` 的路由规则：

1. **默认**：返回 Gateway WS 端点 `ws(s)://<gateway>/ws/device/{device_id}`
2. **WebRTC**：仅在 `GALAXY_ENABLE_WEBRTC=true` 且 Node_95 可达时返回 Node_95 直连
3. **Scrcpy**：仅在 `GALAXY_ENABLE_SCRCPY=true` 且 Node_34 可达时返回 Node_34 直连
4. **其他**：回退到 Gateway WS

---

## 通信状态可视化

Dashboard 的"实时状态面板"（`/api/v1/observability/live-status`）包含 `channel_status` 字段，展示：

- NATS 是否配置且已连接
- Tailscale 是否启用
- WebRTC / MQTT / Scrcpy 通道是否启用且节点可达
- Legacy 协议开关状态

---

## Windows 客户端配置

> ⚠️ **RETIRED (PR-8):** `windows_client/start_galaxy_client.bat` has been fully deleted.
> Configure the Gateway URL via the `GALAXY_GATEWAY_URL` environment variable or `.env` file.

Set the Gateway URL by exporting the environment variable before starting:

```bash
# Windows PowerShell
$env:GALAXY_GATEWAY_URL = "ws://localhost:9000"
python unified_launcher.py

# Windows Command Prompt
set GALAXY_GATEWAY_URL=ws://localhost:9000
python unified_launcher.py
```

---

## 迁移指南（旧 Node_50 客户端）

| 旧配置 | 新配置 |
|--------|--------|
| `NODE_50_URL=ws://localhost:8050` | `GALAXY_GATEWAY_URL=ws://localhost:9000` |
| `--node50_url` 参数 | `--gateway_url` 参数 |
| `/ws/ufo3/{id}` | `/ws/device/{id}` |
| `AIP/1.0` 消息 | `AIP/3.0` 消息（`version: "3.0"`, `type: "device_register"` 等） |
