# Node_96_SmartTransportRouter

## 功能

智能传输路由节点，根据任务类型、网络状况和设备状态，自动选择最佳的屏幕内容传输方式。

## 支持的传输方式

| 传输方式 | 适用场景 | 优势 | 劣势 |
|---------|---------|------|------|
| **WebRTC** | 动态内容、实时交互 | 低延迟、高质量、双向 | 功耗较高、需要信令服务器 |
| **Scrcpy** | 动态内容、高帧率 | 高帧率、低延迟 | 需要 ADB、功耗较高 |
| **ADB 截图** | 静态内容、低功耗 | 低功耗、通用 | 延迟高、不适合动态内容 |
| **HTTP 截图** | 静态内容、简单场景 | 简单、通用 | 延迟高、功能有限 |

## 路由逻辑

```
任务类型 + 需求 -> 传输方式
├─ 动态内容 + 实时 -> WebRTC（回退到 Scrcpy）
├─ 动态内容 + 非实时 -> Scrcpy
├─ 静态内容 + 高质量 -> Scrcpy
├─ 静态内容 + 中低质量 -> ADB 截图
└─ 交互式内容 -> WebRTC
```

## API 接口

### 1. 健康检查

```bash
GET /health
```

### 2. 智能路由

```bash
POST /route
Content-Type: application/json

{
  "device_id": "phone_a",
  "task_type": "dynamic",  # static/dynamic/interactive
  "quality": "high",       # low/medium/high
  "realtime": true,
  "preferred_method": "webrtc"  # 可选
}
```

响应：

```json
{
  "success": true,
  "method": "webrtc",
  "network": "tailscale",
  "signal": "websocket",
  "endpoint": "http://localhost:8095/capture?device_id=phone_a",
  "metadata": {
    "device_id": "phone_a",
    "task_type": "dynamic",
    "quality": "high",
    "realtime": true
  }
}
```

### 3. 列出支持的方式

```bash
GET /methods
```

## 环境变量

| 变量 | 说明 | 默认值 |
|-----|------|--------|
| `NODE_95_URL` | WebRTC 节点地址 | `http://localhost:8095` |
| `NODE_34_URL` | Scrcpy 节点地址 | `http://localhost:8034` |
| `NODE_33_URL` | ADB 节点地址 | `http://localhost:8033` |
| `NODE_41_URL` | MQTT 节点地址 | `http://localhost:8041` |
| `TAILSCALE_ENABLED` | 是否启用 Tailscale | `false` |
| `TAILSCALE_DOMAIN` | Tailscale 域名 | `` |

## 启动

```bash
cd /home/ubuntu/ufo-galaxy/nodes/Node_96_SmartTransportRouter
python3 main.py
```

## 使用示例

### Python 客户端

```python
import httpx
import asyncio

async def main():
    async with httpx.AsyncClient() as client:
        # 请求智能路由
        response = await client.post(
            "http://localhost:8096/route",
            json={
                "device_id": "phone_a",
                "task_type": "dynamic",
                "quality": "high",
                "realtime": True
            }
        )
        
        result = response.json()
        print(f"选择的传输方式: {result['method']}")
        print(f"端点: {result['endpoint']}")

asyncio.run(main())
```

### cURL

```bash
curl -X POST http://localhost:8096/route \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "phone_a",
    "task_type": "dynamic",
    "quality": "high",
    "realtime": true
  }'
```

## 集成到 Gateway

在 `gateway_service_v3.py` 中集成：

```python
from smart_transport_router import SmartTransportRouter, TransportRequest

router = SmartTransportRouter()

async def capture_screen(device_id: str, task_type: str):
    # 请求智能路由
    request = TransportRequest(
        device_id=device_id,
        task_type=task_type,
        quality="high",
        realtime=True
    )
    
    response = await router.route(request)
    
    # 使用选择的端点进行屏幕捕获
    async with httpx.AsyncClient() as client:
        result = await client.get(response.endpoint)
        return result.content
```

## 版本

- **1.0.0** (2026-01-22): 初始版本，支持 WebRTC/Scrcpy/ADB/HTTP 四种传输方式
