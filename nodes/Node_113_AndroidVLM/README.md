# Node 113: AndroidVLM - Android GUI 理解引擎

**版本**: 1.0.0  
**日期**: 2026-01-24  
**作者**: Manus AI

---

## 功能概述

Node_113_AndroidVLM 是一个专门为 Android 设备设计的 GUI 理解引擎，结合了**无障碍服务截图**和**多模态 VLM 分析**，实现智能的界面理解和操作。

### 核心能力

1. **截图获取** - 调用 Android 无障碍服务截取屏幕
2. **VLM 分析** - 使用 Gemini/Qwen 等多模态模型分析界面
3. **智能查找** - 根据自然语言描述查找界面元素
4. **智能点击** - 自动定位并点击目标元素
5. **任务规划** - 根据任务描述生成操作步骤
6. **任务执行** - 自动执行生成的操作计划

---

## 依赖节点

| 节点 | 功能 | 必需 |
| :--- | :--- | :---: |
| **Node_90_MultimodalVision** | VLM 分析 | ✅ |
| **Node_33 (Android)** | 截图和操作 | ✅ |

---

## 环境变量

```bash
# Node_90 地址
NODE_90_MULTIMODAL_VISION_URL=http://localhost:8090

# Android Agent 地址
ANDROID_AGENT_URL=http://192.168.1.100:8033

# VLM 提供商（auto, gemini, qwen）
VLM_PROVIDER=auto

# 端口
NODE_113_PORT=8113
```

---

## API 端点

### 1. 截取屏幕

**POST** `/capture_screen`

```json
{
  "use_cache": true
}
```

**响应**:
```json
{
  "success": true,
  "image": "base64...",
  "width": 1080,
  "height": 2400,
  "timestamp": 1706083200000
}
```

---

### 2. 分析屏幕

**POST** `/analyze_screen`

```json
{
  "query": "这个界面是什么应用？主要功能是什么？",
  "image_base64": null,
  "provider": "auto"
}
```

**响应**:
```json
{
  "success": true,
  "analysis": "这是微信的聊天界面...",
  "provider": "gemini",
  "model": "gemini-2.0-flash-exp"
}
```

---

### 3. 查找元素

**POST** `/find_element`

```json
{
  "description": "发送按钮",
  "image_base64": null,
  "confidence": 0.8
}
```

**响应**:
```json
{
  "success": true,
  "found": true,
  "element": "发送",
  "position": {
    "x": 980,
    "y": 2200,
    "width": 100,
    "height": 80
  },
  "confidence": 0.95
}
```

---

### 4. 智能点击

**POST** `/smart_click`

```json
{
  "description": "发送按钮",
  "confidence": 0.8
}
```

**响应**:
```json
{
  "success": true,
  "clicked": true,
  "element": "发送",
  "position": {
    "x": 980,
    "y": 2200
  },
  "confidence": 0.95
}
```

---

### 5. 生成操作计划

**POST** `/generate_action_plan`

```json
{
  "task_description": "打开设置，找到 Wi-Fi，连接到 'Home' 网络",
  "max_steps": 10
}
```

**响应**:
```json
{
  "success": true,
  "steps": [
    {
      "step": 1,
      "action": "click",
      "target": "设置图标",
      "description": "打开设置应用"
    },
    {
      "step": 2,
      "action": "click",
      "target": "Wi-Fi",
      "description": "进入 Wi-Fi 设置"
    },
    {
      "step": 3,
      "action": "click",
      "target": "Home 网络",
      "description": "选择 Home 网络"
    }
  ],
  "provider": "gemini",
  "model": "gemini-2.0-flash-exp"
}
```

---

### 6. 执行操作计划

**POST** `/execute_action_plan`

```json
{
  "steps": [
    {
      "step": 1,
      "action": "click",
      "target": "设置图标",
      "description": "打开设置应用"
    }
  ],
  "verify_each_step": true
}
```

**响应**:
```json
{
  "success": true,
  "completed_steps": 1,
  "results": [
    {
      "step": 1,
      "action": "click",
      "target": "设置图标",
      "result": {
        "success": true,
        "clicked": true
      }
    }
  ]
}
```

---

### 7. 智能任务执行

**POST** `/smart_task_execution`

```json
{
  "task_description": "打开微信，找到'张三'，发送消息'你好'",
  "max_steps": 10
}
```

**响应**:
```json
{
  "success": true,
  "plan": {
    "steps": [...]
  },
  "execution": {
    "completed_steps": 3,
    "results": [...]
  }
}
```

---

## 使用示例

### Python 示例

```python
import httpx
import asyncio

async def smart_android_task():
    # 1. 智能任务执行
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8113/smart_task_execution",
            json={
                "task_description": "打开设置，找到 Wi-Fi，连接到 'Home' 网络",
                "max_steps": 10
            }
        )
        result = response.json()
        
        if result["success"]:
            print(f"任务完成！共执行 {result['execution']['completed_steps']} 步")
        else:
            print(f"任务失败：{result.get('error')}")

asyncio.run(smart_android_task())
```

### cURL 示例

```bash
# 智能点击
curl -X POST http://localhost:8113/smart_click \
  -H "Content-Type: application/json" \
  -d '{"description": "发送按钮", "confidence": 0.8}'

# 分析屏幕
curl -X POST http://localhost:8113/analyze_screen \
  -H "Content-Type: application/json" \
  -d '{"query": "这个界面是什么应用？", "provider": "gemini"}'
```

---

## 工作原理

### 智能任务执行流程

```
用户任务描述
    ↓
1. 截取 Android 屏幕（Node_33）
    ↓
2. VLM 分析界面（Node_90）
    ↓
3. 生成操作步骤
    ↓
4. 逐步执行操作
    ├─ 截图
    ├─ VLM 查找元素
    ├─ 计算坐标
    └─ 执行点击/滑动
    ↓
5. 验证结果（可选）
    ↓
任务完成
```

### 技术栈

- **截图**: Android 无障碍服务（API 30+）
- **VLM**: Gemini 2.0 Flash / Qwen3-VL
- **通信**: HTTP + JSON
- **异步**: asyncio + httpx

---

## 与豆包手机对比

| 功能 | 豆包手机 | UFO³ Node_113 | 说明 |
| :--- | :---: | :---: | :--- |
| **GUI 理解** | ✅ (VLM) | ✅ (VLM) | 都使用多模态模型 |
| **智能查找** | ✅ | ✅ | 都支持自然语言描述 |
| **任务规划** | ✅ | ✅ | 都能生成操作步骤 |
| **自动执行** | ✅ | ✅ | 都能自动执行任务 |
| **跨设备** | ❌ | ✅ | UFO³ 支持跨设备协同 |
| **开放架构** | ❌ | ✅ | UFO³ 可自由扩展 |

**结论**: Node_113 + Android 无障碍服务 = **豆包手机的开源替代方案**

---

## 性能指标

| 指标 | 数值 | 说明 |
| :--- | :---: | :--- |
| **截图延迟** | ~200ms | 无障碍服务截图 |
| **VLM 分析** | ~1-3s | 取决于模型和网络 |
| **元素查找** | ~1-3s | VLM 分析 + 坐标计算 |
| **智能点击** | ~1.5-3.5s | 截图 + 查找 + 点击 |
| **任务执行** | ~5-30s | 取决于步骤数量 |

---

## 限制和注意事项

1. **Android 版本**: 截图功能需要 Android 11+ (API 30+)
2. **无障碍服务**: 必须启用 UFO Galaxy 无障碍服务
3. **网络依赖**: VLM 分析需要网络连接
4. **API 成本**: Gemini/Qwen 调用可能产生费用
5. **准确性**: VLM 分析准确性取决于模型和界面复杂度

---

## 未来计划

- [ ] 支持更多 VLM 模型（Claude, GPT-4V）
- [ ] 添加本地 VLM（ScreenAI, Ferret-UI）
- [ ] 优化截图缓存策略
- [ ] 添加步骤验证机制
- [ ] 支持更复杂的操作（长按、双击）
- [ ] 添加错误恢复机制

---

## 许可证

MIT License

---

**维护者**: Manus AI  
**最后更新**: 2026-01-24
