# Memory Freshness — PR-G6

> **模块**: `core/task_memory.py`  
> **API 路由**: `core/routes/c_stage.py`  
> **测试**: `tests/test_g6_memory_freshness.py`

---

## 概述

PR-G6 在原有 C 阶段任务记忆（4B）的基础上增加：

| 特性 | 说明 |
|------|------|
| **task_type 字段** | `TaskSummary` 新增可选类型标签，用于过滤和分组 |
| **TTL** | 热区记录超时后自动排除，`ttl_seconds=0` 禁用（默认，向后兼容） |
| **冷热分层** | 最近 `hot_limit` 条为热区（驻内存），超出部分为冷区（可按需查询） |
| **task_type 过滤** | `get_recent_summaries(task_type=...)` / `query_cold_storage(task_type=...)` |
| **漂移检测** | `check_consistency()` 对比新结果与缓存摘要；触发动作可配置 |

所有新增参数均有默认值，**不破坏已有调用方式**。

---

## TaskSummary — 新增字段

```python
@dataclass
class TaskSummary:
    # ... 原有字段不变 ...
    task_type: str = ""   # G6 新增；旧记录反序列化时默认为空字符串
```

`task_type` 已写入 `to_dict()` / `from_dict()`；从不含该字段的旧文件加载时自动填 `""`。

---

## TaskMemory — 构造函数

```python
TaskMemory(
    data_dir: str = None,        # 持久化目录（默认 data/）
    hot_limit: int = 200,        # 热区最大条数（默认与旧版 _MAX_IN_MEMORY 一致）
    ttl_seconds: float = 0.0,    # 热区 TTL（0 = 不过期，向后兼容默认值）
)
```

### 示例

```python
from core.task_memory import TaskMemory

# 最小化（与旧版行为完全一致）
mem = TaskMemory()

# 热区最多 50 条，记录 1 小时后过期
mem = TaskMemory(hot_limit=50, ttl_seconds=3600)
```

---

## 新增方法

### record_task — 新增 task_type 参数

```python
mem.record_task(
    task="搜索 Python 教程",
    result_summary="找到 5 篇",
    task_type="search",   # 新增，可选，默认 ""
)
```

### get_recent_summaries — 新增 task_type 过滤

```python
# 不过滤（与旧版一致）
summaries = mem.get_recent_summaries(n=5)

# 只返回 "search" 类型的最近 10 条
summaries = mem.get_recent_summaries(n=10, task_type="search")
```

热区不足时，自动补充冷区结果。

### query_cold_storage

```python
# 获取最近 50 条冷区记录
cold = mem.query_cold_storage(n=50)

# 按类型过滤冷区记录
cold = mem.query_cold_storage(n=20, task_type="analysis")
```

- 返回热区以外的持久化历史，按时间降序（最新在前）
- 尊重 TTL：过期记录不会出现在结果中
- 冷区即 `data/task_memory.jsonl` 中超出热区 `hot_limit` 的部分

### evict_expired

```python
removed_count = mem.evict_expired()
```

从热区内存中移除已过期的记录（它们仍保留在文件中）。`ttl_seconds=0` 时为空操作。

---

## 漂移检测

### configure_drift

```python
mem.configure_drift(
    threshold=0.5,          # Jaccard 相似度阈值（0.0–1.0）
    action="human_review",  # "rerun" | "human_review" | "none"
)
```

默认值：`threshold=0.5`，`action="human_review"`。

### check_consistency

```python
result = mem.check_consistency(
    task_key="搜索 Python 教程",   # 任务标识
    new_result="找到 3 篇",         # 本次结果
    task_type="search",            # 可选：优先匹配此类型的缓存
    threshold=0.6,                 # 可选：覆盖实例级阈值
    action="rerun",                # 可选：覆盖实例级动作
)

print(result.is_drift)       # True / False
print(result.similarity)     # 0.0–1.0
print(result.action)         # "none" | "rerun" | "human_review"
print(result.cached_summary) # 匹配到的缓存摘要（未找到时为 None）
```

**相似度算法**：词级 Jaccard 相似度（大小写不敏感）。

```
similarity = |words(A) ∩ words(B)| / |words(A) ∪ words(B)|
```

**查找策略**（按优先级）：
1. 若指定 `task_type`，优先在热区中匹配同类型的最近记录
2. 按 `task_key` 文本在热区中模糊匹配（子串包含）
3. 未找到缓存 → `is_drift=False, action="none"`

**处理流程**：

```
新结果
  └─> check_consistency()
        └─> 找到缓存摘要?
              ├─ 否 → is_drift=False, action="none"（无法比较）
              └─ 是 → 计算 Jaccard 相似度
                        ├─ similarity >= threshold → is_drift=False
                        └─ similarity < threshold  → is_drift=True
                                                      action = "rerun" | "human_review"
                                                      (调用方决定如何处理)
```

> ⚠️ `check_consistency` **只返回结果**，不自动重跑任务。重跑逻辑由调用方实现。

---

## API 端点

所有端点返回 `{"success": true, ...}` / `{"success": false, "error": "..."}` 格式。

### GET /api/v1/memory/tasks

获取最近 N 条热区摘要。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `n` | int | 10 | 返回条数（最大 100） |
| `task_type` | string | — | 按类型过滤（可选） |

```json
{
  "success": true,
  "count": 2,
  "task_type_filter": "search",
  "summaries": [...]
}
```

### GET /api/v1/memory/stats

统计信息（新增 `task_type_distribution`、`hot_limit`、`ttl_seconds`）。

```json
{
  "success": true,
  "total": 42,
  "successful": 40,
  "failed": 2,
  "strategy_distribution": {"single": 30, "specialized": 12},
  "task_type_distribution": {"search": 20, "analysis": 22},
  "hot_limit": 200,
  "ttl_seconds": 0.0
}
```

### GET /api/v1/memory/cold

查询冷区历史记录（热区外的持久化记录）。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `n` | int | 50 | 返回条数（最大 500） |
| `task_type` | string | — | 按类型过滤（可选） |

```json
{
  "success": true,
  "count": 8,
  "task_type_filter": null,
  "records": [...]
}
```

### GET /api/v1/memory/drift/config

获取当前漂移检测配置。

```json
{
  "success": true,
  "threshold": 0.5,
  "action": "human_review"
}
```

### PUT /api/v1/memory/drift/config

更新漂移检测配置（字段均可选）。

```json
// 请求
{ "threshold": 0.7, "action": "rerun" }

// 响应
{ "success": true, "threshold": 0.7, "action": "rerun" }
```

`action` 只接受 `"rerun"`、`"human_review"`、`"none"`；其他值返回 400。

### POST /api/v1/memory/drift/check

对比新结果与缓存摘要。

```json
// 请求
{
  "task_key": "搜索 Python 教程",
  "new_result": "找到 2 篇",
  "task_type": "search",    // 可选
  "threshold": 0.6,         // 可选，覆盖配置值
  "action": "rerun"         // 可选，覆盖配置值
}

// 响应（无漂移）
{
  "success": true,
  "is_drift": false,
  "similarity": 0.85,
  "action": "none",
  "threshold": 0.6,
  "cached_summary": "找到 5 篇",
  "task_key": "搜索 Python 教程"
}

// 响应（漂移）
{
  "success": true,
  "is_drift": true,
  "similarity": 0.12,
  "action": "rerun",
  "threshold": 0.6,
  "cached_summary": "找到 5 篇",
  "task_key": "搜索 Python 教程"
}
```

`task_key` 为必填字段；缺失返回 400。

---

## 配置说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `hot_limit` | 200 | 热区最大记录数；与旧版 `_MAX_IN_MEMORY` 完全一致 |
| `ttl_seconds` | 0.0 | 0 = 禁用 TTL（向后兼容）；正数 = 过期秒数 |
| `drift_threshold` | 0.5 | Jaccard 相似度阈值；低于此值视为漂移 |
| `drift_action` | `"human_review"` | 漂移时的建议动作 |

---

## 向后兼容保证

- `TaskMemory()` 无参构造与旧版行为完全一致
- `record_task()` 新增的 `task_type=""` 参数为可选
- `get_recent_summaries(n)` 无 `task_type` 时与旧版一致
- 旧版 `.jsonl` 文件（无 `task_type` 字段）可正常加载，`task_type` 默认为 `""`
- `get_stats()` 新增字段不影响已有字段
- 所有新 API 端点为新增，不修改已有端点路径和响应结构（`/api/v1/memory/tasks` 仅新增可选 `task_type` 参数，原有响应字段不变）
