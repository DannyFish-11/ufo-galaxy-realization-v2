# Galaxy 多设备并发架构深度分析

> 分析时间：2026-05-31
> 基于：V2 仓源码逆向分析

---

## 一、设备并发上限（代码层面无上限，实际有瓶颈）

### 1.1 代码架构 — 无硬限制

```python
# galaxy_gateway/android_bridge.py:340
self._devices: Dict[str, AndroidDevice] = {}
# 就是一个普通 Python dict，没有 maxlen，没有计数器
```

```python
# core/cross_device_sync.py:96
for device_id, device in _bridge._devices.items():
    if device.websocket is not None and getattr(device, "connected", False):
        for attempt in range(MAX_RETRIES):
            try:
                await device.websocket.send_json(msg)
```

**关键发现**：同步推送是**串行 for 循环**，不是并发广播。N 个设备 = N 次顺序 send_json。

### 1.2 实际瓶颈

| 瓶颈层 | 理论上限 | 实际建议 | 原因 |
|--------|---------|---------|------|
| **WebSocket 连接** | OS fd 上限 (~65535) | < 5000 | 每个设备一个 WebSocket |
| **asyncio 事件循环** | 单线程 | 同左 | 所有设备共享一个 loop |
| **串行推送延迟** | N × 5ms | N > 100 时明显 | for 循环逐个发送 |
| **内存（device 对象）** | ~2KB/设备 | 10万≈200MB | 对象+WebSocket句柄 |
| **Python GIL** | 单核 | 同左 | 无法利用多核 |

### 1.3 实际并发建议

| 场景 | 建议设备数 | 推送延迟 |
|------|-----------|---------|
| 开发测试 | < 10 | < 50ms |
| 个人使用 | < 20 | < 100ms |
| 小规模家庭 | 20-50 | 100-250ms |
| 上限（需优化） | 100-200 | 250-500ms |

**超过 100 台设备时，串行推送会变成明显瓶颈。**

---

## 二、发起顺序 — 目前是无序广播，缺乏优先级

### 2.1 当前实现

```python
# cross_device_sync.py — 串行 for 循环，无优先级
for device_id, device in _bridge._devices.items():
    await device.websocket.send_json(msg)  # 逐个等待
```

**问题**：
- 无设备优先级（Wear OS 手表应该比手机更快收到状态变化）
- 无拓扑排序（近处设备应该比远处设备优先）
- 无负载隔离（一个设备慢会拖慢所有后续设备）

### 2.2 设备类型与发起顺序现状

当前所有设备类型共享同一个 `_devices` dict，按**插入顺序**遍历：

```
devices = {
    "android_001": AndroidDevice(phone),      # 插入 #1
    "android_002": AndroidDevice(phone),      # 插入 #2
    "wear_001": AndroidDevice(watch),         # 插入 #3
    "linux_001": ...,
}
# 推送顺序：001 → 002 → wear_001 → linux_001
```

**没有根据设备类型、网络延迟、重要性排序。**

### 2.3 应该的发起顺序（建议）

```
优先级 1: Wear OS 手表（屏幕小，需要最快反馈）
优先级 2: Android 手机（主交互设备）
优先级 3: Android 平板（次要交互）
优先级 4: Home Assistant（智能家居，可容忍延迟）
优先级 5: Linux Agent（无 UI，纯日志）
```

---

## 三、共同发起 — 多设备协调机制分析

### 3.1 当前：广播模式（所有设备收到相同消息）

```
Windows Phase: SILENT → LIMINAL
    ↓
    ├──→ Android Phone #1: 收到 state_event(LIMINAL)
    ├──→ Android Phone #2: 收到 state_event(LIMINAL)
    ├──→ Wear OS Watch: 收到 state_event(LIMINAL)
    └──→ Home Assistant: 收到 state_event(LIMINAL)
```

**所有设备同时收到完全相同的 phase 状态。**

### 3.2 缺乏的协调机制

| 协调需求 | 当前状态 | 说明 |
|---------|---------|------|
| **设备互斥** | ❌ 无 | 两个手机不能同时执行冲突任务 |
| **任务分片** | ❌ 无 | 不能把一个大任务拆给多个设备 |
| **投票/共识** | ❌ 无 | 多设备不能对某个操作投票 |
| **主从选举** | ❌ 无 | 没有"主设备"概念 |
| **负载均衡** | ❌ 无 | 任务不能按设备能力分配 |

### 3.3 Mesh 生命周期（仅有的多设备协调）

```
mesh_join    → 设备请求加入协作会话
mesh_result  → 设备提交执行结果
mesh_leave   → 设备离开会话
```

这是**会话级别的生命周期追踪**，不是实时状态同步。用于审计和验证设备是否完整参与了某个任务会话。

---

## 四、实时状态同步的更好表示方式

### 4.1 当前表示的问题

| 问题 | 说明 |
|------|------|
| 无全局视图 | 无法一眼看到所有设备的当前状态 |
| 无历史轨迹 | 无法回放状态变化的时间线 |
| 无拓扑关系 | 不知道设备之间的从属/优先级关系 |
| 无延迟指标 | 不知道每个设备的状态延迟 |
| 日志散落 | 状态变化记录在各自模块的日志中 |

### 4.2 建议方案：统一状态拓扑图

```
┌─────────────────────────────────────────────────────────────────┐
│                     Galaxy 全局状态拓扑 (v2.0)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────────┐                                              │
│   │   Windows    │ ◄── 状态源 (Source of Truth)                  │
│   │   DESKTOP    │      Phase: MANIFEST                          │
│   │   ⚪⚪⚪      │      Last: 2s ago                             │
│   └──────┬───────┘                                              │
│          │                                                      │
│          ▼ broadcast (state_event)                              │
│   ┌──────┴──────┬──────────────┬──────────────┐               │
│   │             │              │              │                 │
│   ▼             ▼              ▼              ▼                 │
│ ┌──────┐   ┌──────┐    ┌──────────┐   ┌──────────┐           │
│ │Phone │   │Phone │    │ Wear OS  │   │  Home    │           │
│ │#1    │   │#2    │    │ Watch    │   │ Assistant│           │
│ │⚪⚪⚪ │   │⚪⚪⚪ │    │  ⚪⚪⚪   │   │  ⚪⚪⚪   │           │
│ │2ms  │   │15ms │    │  5ms    │   │  120ms   │           │
│ └──────┘   └──────┘    └──────────┘   └──────────┘           │
│                                                                 │
│   延迟图例: 2ms ✅  15ms ✅  5ms ✅  120ms ⚠️                   │
│                                                                 │
│   状态时间线:                                                   │
│   14:32:01  SILENT  ──→  LIMINAL  (Windows 发起)               │
│   14:32:01  LIMINAL ──→  Phone#1 (2ms)                         │
│   14:32:01  LIMINAL ──→  Watch (5ms)                           │
│   14:32:01  LIMINAL ──→  Phone#2 (15ms)                        │
│   14:32:02  LIMINAL ──→  HA (120ms)                            │
│   14:32:05  LIMINAL ──→  MANIFEST (Windows 发起)               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 建议实现

**方案 A：Web Dashboard（推荐）**

在 Galaxy Gateway 上加一个 `/status` 页面：

```python
# galaxy_gateway/routes/status_dashboard.py
@app.get("/status")
async def status_dashboard():
    return {
        "topology": {
            "source": {"device_id": "v2_desktop", "phase": "manifest", "timestamp": ...},
            "receivers": [
                {"device_id": "android_001", "phase": "manifest", "latency_ms": 2, "connected": True},
                {"device_id": "wear_001", "phase": "manifest", "latency_ms": 5, "connected": True},
                {"device_id": "ha_001", "phase": "manifest", "latency_ms": 120, "connected": True},
            ]
        },
        "timeline": [
            {"ts": ..., "from": "silent", "to": "liminal", "source": "desktop"},
            {"ts": ..., "from": "liminal", "to": "manifest", "source": "desktop"},
        ]
    }
```

**方案 B：CLI 实时拓扑**

```bash
$ galaxy status --topology

Galaxy 设备拓扑 (2026-05-31 14:32:05)
═══════════════════════════════════════════════════════

SOURCE        DEVICE           PHASE      LATENCY   STATUS
───────────────────────────────────────────────────────
[v2_desktop]  Windows Desktop  MANIFEST   0ms       ✅ ONLINE
  ├─→         Android Phone#1  MANIFEST   2ms       ✅ ONLINE
  ├─→         Wear OS Watch    MANIFEST   5ms       ✅ ONLINE
  ├─→         Android Phone#2  MANIFEST   15ms      ✅ ONLINE
  └─→         Home Assistant   MANIFEST   120ms     ⚠️ SLOW

状态时间线:
14:32:01  SILENT  → LIMINAL   (source: desktop, synced: 4/4)
14:32:05  LIMINAL → MANIFEST  (source: desktop, synced: 4/4)

最近 60 秒: 2 次 phase 转换, 平均同步延迟 35ms
```

**方案 C：状态同步质量指标（Prometheus 风格）**

```python
# 在 cross_device_sync.py 中收集
METRICS = {
    "galaxy_sync_total": 42,           # 总同步次数
    "galaxy_sync_success": 40,         # 成功次数
    "galaxy_sync_latency_ms": 35,      # 平均延迟
    "galaxy_devices_connected": 4,     # 在线设备数
    "galaxy_devices_total": 5,         # 注册设备数
    "galaxy_phase_current": 2,         # 0=silent, 1=liminal, 2=manifest
}
```

---

## 五、核心问题与改进建议

### 5.1 推送延迟优化（串行 → 并发）

```python
# 当前：串行 for 循环（慢）
for device_id, device in _bridge._devices.items():
    await device.websocket.send_json(msg)  # 逐个等

# 改进：并发 gather（快 N 倍）
import asyncio
tasks = []
for device_id, device in _bridge._devices.items():
    if device.connected and device.websocket:
        tasks.append(device.websocket.send_json(msg))
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 5.2 添加设备优先级

```python
# 建议：按设备类型优先级排序
DEVICE_PRIORITY = {
    "wear_os": 0,      # 最高：手表需要最快反馈
    "android_phone": 1,
    "android_tablet": 2,
    "home_assistant": 3,
    "linux_agent": 4,   # 最低：纯日志
}

sorted_devices = sorted(
    _bridge._devices.items(),
    key=lambda x: DEVICE_PRIORITY.get(x[1].device_type, 99)
)
```

### 5.3 添加同步质量追踪

```python
# 建议：记录每个设备的同步延迟
class SyncMetrics:
    def __init__(self):
        self.device_latencies: Dict[str, List[float]] = {}  # ms
        self.phase_transitions: List[Dict] = []
        self.sync_failures: int = 0

    def record_sync(self, device_id: str, latency_ms: float, success: bool):
        if device_id not in self.device_latencies:
            self.device_latencies[device_id] = []
        self.device_latencies[device_id].append(latency_ms)
        if not success:
            self.sync_failures += 1
```

---

## 六、总结

| 问题 | 现状 | 建议 |
|------|------|------|
| **并发上限** | 代码无限制，实际 ~100-200 | 加并发 gather + 设备上限保护 |
| **发起顺序** | 无序（dict 插入顺序） | 按设备类型优先级排序 |
| **共同发起** | 纯广播，无协调 | 加设备互斥 + 任务分片 + 主从选举 |
| **状态表示** | 无全局视图 | 加 Web Dashboard / CLI 拓扑图 |
| **同步质量** | 无延迟指标 | 加 Prometheus 风格指标收集 |

**最关键的改进**：
1. 串行推送 → 并发 `asyncio.gather`（延迟降低 N 倍）
2. 添加 `/status` 端点返回全局拓扑
3. 按设备类型排序（手表优先）
