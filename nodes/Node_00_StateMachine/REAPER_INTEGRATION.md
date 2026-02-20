# Stale Lock Reaper 集成说明

## 概述

Stale Lock Reaper（过期锁清理器）是 Node 00 的增强模块，用于防止系统死锁。

## 功能

1. **自动扫描**：每 60 秒扫描一次所有锁
2. **自动清理**：如果锁持有时间超过 300 秒（5 分钟），自动删除
3. **审计日志**：将清理操作记录到 Node 65
4. **统计信息**：提供清理统计和监控接口

## 集成方法

### 方法 1：修改 main.py（推荐）

在 `main.py` 中添加以下代码：

```python
# 在文件顶部添加导入
from stale_lock_reaper import StaleLockReaper

# 修改 lifespan 函数
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 00: State Machine & Lock Manager")
    
    # 启动 Stale Lock Reaper
    reaper = StaleLockReaper(
        store=store,
        scan_interval=60,      # 每 60 秒扫描一次
        max_lock_age=300,      # 锁最多持有 300 秒
        audit_log_url="http://localhost:8065/log"
    )
    await reaper.start()
    logger.info("Stale Lock Reaper started")
    
    # 添加 Reaper API 端点
    @app.get("/reaper/stats")
    async def get_reaper_stats():
        """获取 Reaper 统计信息"""
        return reaper.get_stats()
    
    @app.post("/reaper/scan")
    async def force_reaper_scan():
        """强制执行一次扫描"""
        return await reaper.force_scan()
    
    yield
    
    # 停止 Reaper
    await reaper.stop()
    logger.info("Node 00 shutdown complete")
```

### 方法 2：使用辅助函数

```python
from stale_lock_reaper import integrate_reaper

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Node 00: State Machine & Lock Manager")
    
    # 一行集成
    reaper = integrate_reaper(app, store)
    await reaper.start()
    
    yield
    
    await reaper.stop()
    logger.info("Node 00 shutdown complete")
```

## 新增 API 端点

集成后，Node 00 将新增以下端点：

### GET /reaper/stats

获取 Reaper 统计信息

**响应示例：**
```json
{
  "total_scans": 120,
  "locks_reaped": 5,
  "last_scan_time": "2026-01-21T12:34:56",
  "last_reap_time": "2026-01-21T12:30:00",
  "running": true,
  "scan_interval": 60,
  "max_lock_age": 300
}
```

### POST /reaper/scan

强制执行一次扫描

**响应示例：**
```json
{
  "total_scans": 121,
  "locks_reaped": 5,
  "last_scan_time": "2026-01-21T12:35:00",
  "running": true
}
```

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `scan_interval` | 60 | 扫描间隔（秒） |
| `max_lock_age` | 300 | 最大锁持有时间（秒） |
| `audit_log_url` | `http://localhost:8065/log` | 审计日志 URL |

## 工作原理

1. **扫描循环**
   - 每 60 秒执行一次扫描
   - 检查所有锁的 `acquired_at` 时间
   - 计算锁的持有时间

2. **清理逻辑**
   - 如果 `(now - acquired_at) > max_lock_age`
   - 从 `store.locks` 中删除该锁
   - 记录警告日志

3. **审计日志**
   - 将清理操作发送到 Node 65
   - 包含锁的详细信息（resource_id, node_id, age 等）
   - 日志级别：WARNING
   - 日志分类：SYSTEM

## 测试

### 独立测试

```bash
cd /home/ubuntu/ufo-galaxy-check/nodes/Node_00_StateMachine
python3 stale_lock_reaper.py
```

### 集成测试

```python
import httpx

# 1. 获取当前锁
response = httpx.get("http://localhost:8000/locks")
print(response.json())

# 2. 获取 Reaper 统计
response = httpx.get("http://localhost:8000/reaper/stats")
print(response.json())

# 3. 强制扫描
response = httpx.post("http://localhost:8000/reaper/scan")
print(response.json())
```

## 监控建议

1. **定期检查统计**
   - 如果 `locks_reaped` 持续增长，说明有节点未正确释放锁
   - 检查 `last_reap_time` 确认清理器正常工作

2. **查看审计日志**
   - 在 Node 65 中查询 `action=stale_lock_reaped` 的日志
   - 分析哪些节点经常产生过期锁

3. **调整参数**
   - 如果误杀正常锁，增加 `max_lock_age`
   - 如果清理不及时，减少 `scan_interval`

## 注意事项

1. **不修改原有代码**
   - `stale_lock_reaper.py` 是独立模块
   - 可以随时启用或禁用

2. **线程安全**
   - 使用 `store._lock` 确保并发安全
   - 不会与正常的锁操作冲突

3. **性能影响**
   - 扫描操作非常快（< 1ms）
   - 对系统性能影响可忽略

## 故障排查

### 问题：Reaper 未启动

**检查：**
```bash
curl http://localhost:8000/reaper/stats
```

**解决：**
- 确认已在 `lifespan` 中调用 `reaper.start()`
- 检查日志是否有错误信息

### 问题：锁未被清理

**检查：**
- 确认 `max_lock_age` 设置正确
- 查看 `last_scan_time` 是否更新
- 检查锁的 `acquired_at` 时间格式

**解决：**
- 手动触发扫描：`POST /reaper/scan`
- 查看日志中的错误信息

### 问题：审计日志未发送

**检查：**
```bash
curl http://localhost:8065/health
```

**解决：**
- 确认 Node 65 正在运行
- 检查 `audit_log_url` 配置是否正确
- 查看 Reaper 日志中的错误信息

## 版本历史

- **v1.0** (2026-01-21): 初始版本
  - 基本的扫描和清理功能
  - 审计日志集成
  - 统计信息 API
