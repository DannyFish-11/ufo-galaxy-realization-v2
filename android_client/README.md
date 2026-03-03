# UFO Galaxy Android 客户端

> ⚠️ **已迁移通知**：Android 客户端已迁移至独立仓库，本目录不再维护 Android 源码。

## 独立仓库（唯一真相源）

Android 客户端 APK 的唯一来源：

👉 **https://github.com/DannyFish-11/ufo-galaxy-android**

## 如何克隆和构建 APK

```bash
# 1. 克隆独立仓库
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
cd ufo-galaxy-android

# 2. 配置服务端地址（编辑 app/build.gradle）
#    buildConfigField "String", "GALAXY_SERVER_URL", '"ws://YOUR_SERVER_IP:8765"'

# 3. 构建 Debug APK
./gradlew assembleDebug

# 4. 安装到设备
adb install app/build/outputs/apk/debug/app-debug.apk
```

## 服务端 WebSocket 端点（AIP v3.0）

本仓库 (`ufo-galaxy-realization-v2`) 为服务端 + 桥接 + VLM，接收 APK 的连接。

| 端点 | 说明 |
|------|------|
| `ws://<host>:8765/ws/android` | Android 设备主连接端点 |
| `ws://<host>:8765/ws/device/{device_id}` | 设备专属通道 |

### 协议版本

AIP v3.0（Android Integration Protocol v3.0）

消息格式：
```json
{
  "version": "3.0",
  "type": "<message_type>",
  "message_id": "<uuid>",
  "device_id": "<device_id>",
  "timestamp": 1234567890000
}
```

完整协议文档见：[docs/ANDROID_PROTOCOL_ALIGNMENT.md](../docs/ANDROID_PROTOCOL_ALIGNMENT.md)

## 架构关系图

```
独立仓库(APK)
  DannyFish-11/ufo-galaxy-android
        │
        │  WebSocket (AIP v3.0)
        │  ws://<host>:8765/ws/android
        ▼
galaxy_gateway/android_bridge.py   ← 桥接层（本仓库）
        │
        │  HTTP
        ▼
Node_113_AndroidVLM                ← VLM 分析节点（本仓库）
```

## 相关文档

- [docs/ANDROID_PROTOCOL_ALIGNMENT.md](../docs/ANDROID_PROTOCOL_ALIGNMENT.md) - AIP v3.0 完整协议文档
- [galaxy_gateway/android_bridge.py](../galaxy_gateway/android_bridge.py) - 桥接层源码
