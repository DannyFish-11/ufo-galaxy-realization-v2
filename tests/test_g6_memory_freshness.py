"""
tests/test_g6_memory_freshness.py
===================================
PR-G6 "记忆与数据新鲜度" 测试套件

覆盖:
  - TaskSummary.task_type 字段（新增 + 向后兼容反序列化）
  - TaskMemory TTL：热区过期逻辑
  - TaskMemory 冷热分层：hot_limit 控制热区大小；冷区查询
  - 按 task_type 过滤：get_recent_summaries / query_cold_storage
  - 漂移检测：_text_similarity / check_consistency / configure_drift
  - API 路由（FastAPI TestClient）：
      GET  /api/v1/memory/tasks?task_type=...
      GET  /api/v1/memory/cold?task_type=...
      GET  /api/v1/memory/drift/config
      PUT  /api/v1/memory/drift/config
      POST /api/v1/memory/drift/check
  - 旧版向后兼容：无 task_type 字段的记录能正常反序列化
"""

import json
import os
import tempfile
import time

import pytest


# ============================================================================
# 辅助工厂
# ============================================================================

def _make_memory(hot_limit=200, ttl_seconds=0.0):
    """每个测试使用独立的临时目录。"""
    from core.task_memory import TaskMemory
    tmp = tempfile.mkdtemp()
    return TaskMemory(data_dir=tmp, hot_limit=hot_limit, ttl_seconds=ttl_seconds)


# ============================================================================
# 1. TaskSummary 新字段 + 向后兼容
# ============================================================================

class TestTaskSummaryTaskType:
    def test_new_record_has_task_type(self):
        mem = _make_memory()
        entry = mem.record_task(task="test", task_type="search")
        assert entry.task_type == "search"

    def test_default_task_type_empty(self):
        mem = _make_memory()
        entry = mem.record_task(task="test")
        assert entry.task_type == ""

    def test_from_dict_without_task_type_defaults_empty(self):
        """旧格式记录（无 task_type 字段）反序列化时默认为空字符串。"""
        from core.task_memory import TaskSummary
        old_data = {
            "summary_id": "abc123",
            "timestamp": 1000.0,
            "task": "old task",
            "result_summary": "ok",
            "success": True,
            "strategy": "single",
            "duration_ms": 10.0,
            "session_id": "",
            "tags": [],
            "extra": {},
        }
        summary = TaskSummary.from_dict(old_data)
        assert summary.task_type == ""

    def test_task_type_persisted_and_reloaded(self):
        """task_type 写入文件后，新实例能正常加载。"""
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem1 = TaskMemory(data_dir=tmp)
        mem1.record_task(task="t1", task_type="automation")

        mem2 = TaskMemory(data_dir=tmp)
        recent = mem2.get_recent_summaries(n=5)
        assert recent[0].task_type == "automation"

    def test_to_dict_includes_task_type(self):
        mem = _make_memory()
        entry = mem.record_task(task="t", task_type="analysis")
        d = entry.to_dict()
        assert "task_type" in d
        assert d["task_type"] == "analysis"


# ============================================================================
# 2. TTL（热区过期）
# ============================================================================

class TestTTL:
    def test_no_ttl_returns_all_records(self):
        mem = _make_memory(ttl_seconds=0)
        for i in range(5):
            mem.record_task(task=f"t{i}")
        # TTL=0 → 不过期
        assert len(mem.get_recent_summaries(n=10)) == 5

    def test_expired_records_excluded_from_hot(self):
        """TTL 过期后，记录从热区过滤掉。"""
        mem = _make_memory(ttl_seconds=1)
        # 插入一条带有过去时间戳的记录
        from core.task_memory import TaskSummary
        old_entry = TaskSummary(
            task="old task",
            result_summary="done",
            timestamp=time.time() - 10,  # 10 秒前 > TTL=1
        )
        mem._records.append(old_entry)

        new_entry = mem.record_task(task="new task")
        recent = mem.get_recent_summaries(n=10)
        tasks = [r.task for r in recent]
        assert "old task" not in tasks
        assert "new task" in tasks

    def test_evict_expired_removes_stale(self):
        mem = _make_memory(ttl_seconds=1)
        from core.task_memory import TaskSummary
        old = TaskSummary(task="stale", timestamp=time.time() - 100)
        mem._records.append(old)
        mem.record_task(task="fresh")

        removed = mem.evict_expired()
        assert removed >= 1
        tasks = [r.task for r in mem._records]
        assert "stale" not in tasks
        assert "fresh" in tasks

    def test_evict_expired_noop_when_ttl_zero(self):
        mem = _make_memory(ttl_seconds=0)
        mem.record_task(task="t")
        removed = mem.evict_expired()
        assert removed == 0

    def test_ttl_filters_on_load_recent(self):
        """加载文件时跳过已过期条目。"""
        from core.task_memory import TaskMemory, TaskSummary
        tmp = tempfile.mkdtemp()
        jsonl = os.path.join(tmp, "task_memory.jsonl")

        expired = TaskSummary(task="expired", timestamp=time.time() - 1000)
        fresh = TaskSummary(task="fresh", timestamp=time.time())
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps(expired.to_dict()) + "\n")
            f.write(json.dumps(fresh.to_dict()) + "\n")

        mem = TaskMemory(data_dir=tmp, ttl_seconds=60)
        tasks = [r.task for r in mem._records]
        assert "expired" not in tasks
        assert "fresh" in tasks


# ============================================================================
# 3. 冷热分层
# ============================================================================

class TestHotColdTiering:
    def test_hot_limit_enforced(self):
        mem = _make_memory(hot_limit=5)
        for i in range(10):
            mem.record_task(task=f"task_{i}")
        assert len(mem._records) <= 5

    def test_hot_contains_most_recent(self):
        mem = _make_memory(hot_limit=3)
        for i in range(6):
            mem.record_task(task=f"t{i}")
        tasks = [r.task for r in mem._records]
        assert "t5" in tasks
        assert "t4" in tasks
        assert "t3" in tasks
        assert "t0" not in tasks

    def test_query_cold_storage_returns_old_records(self):
        """冷区包含热区之外的历史记录。"""
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem = TaskMemory(data_dir=tmp, hot_limit=3)
        for i in range(8):
            mem.record_task(task=f"t{i}")

        cold = mem.query_cold_storage(n=100)
        cold_tasks = [r.task for r in cold]
        # 热区有 t5, t6, t7；冷区应包含 t0..t4
        for i in range(5):
            assert f"t{i}" in cold_tasks, f"t{i} should be in cold"

    def test_query_cold_storage_empty_when_all_in_hot(self):
        mem = _make_memory(hot_limit=100)
        for i in range(5):
            mem.record_task(task=f"t{i}")
        cold = mem.query_cold_storage(n=50)
        assert cold == []

    def test_query_cold_storage_filter_by_task_type(self):
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem = TaskMemory(data_dir=tmp, hot_limit=2)
        mem.record_task(task="s1", task_type="search")
        mem.record_task(task="a1", task_type="analysis")
        mem.record_task(task="s2", task_type="search")
        mem.record_task(task="a2", task_type="analysis")

        cold = mem.query_cold_storage(n=20, task_type="search")
        types = [r.task_type for r in cold]
        assert all(t == "search" for t in types)

    def test_query_cold_respects_ttl(self):
        """冷区查询也跳过已过期记录（ttl_seconds > 0）。"""
        from core.task_memory import TaskMemory, TaskSummary
        tmp = tempfile.mkdtemp()
        jsonl = os.path.join(tmp, "task_memory.jsonl")
        expired = TaskSummary(task="cold_expired", timestamp=time.time() - 9999)
        live = TaskSummary(task="cold_live", timestamp=time.time() - 10)
        hot_anchor = TaskSummary(task="hot_anchor", timestamp=time.time())
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps(expired.to_dict()) + "\n")
            f.write(json.dumps(live.to_dict()) + "\n")
            f.write(json.dumps(hot_anchor.to_dict()) + "\n")

        # hot_limit=1 → hot_anchor 在热区; expired/live 在冷区
        mem = TaskMemory(data_dir=tmp, hot_limit=1, ttl_seconds=60)
        cold = mem.query_cold_storage(n=10)
        tasks = [r.task for r in cold]
        assert "cold_expired" not in tasks
        assert "cold_live" in tasks


# ============================================================================
# 4. 按 task_type 过滤
# ============================================================================

class TestTaskTypeFilter:
    def test_get_recent_summaries_filter(self):
        mem = _make_memory()
        mem.record_task(task="s1", task_type="search")
        mem.record_task(task="a1", task_type="analysis")
        mem.record_task(task="s2", task_type="search")

        results = mem.get_recent_summaries(n=10, task_type="search")
        assert len(results) == 2
        assert all(r.task_type == "search" for r in results)

    def test_get_recent_summaries_no_filter(self):
        mem = _make_memory()
        mem.record_task(task="s1", task_type="search")
        mem.record_task(task="a1", task_type="analysis")

        results = mem.get_recent_summaries(n=10)
        assert len(results) == 2

    def test_get_recent_summaries_filter_returns_empty_if_none_match(self):
        mem = _make_memory()
        mem.record_task(task="t", task_type="search")
        results = mem.get_recent_summaries(n=5, task_type="nonexistent")
        assert results == []

    def test_filter_falls_back_to_cold(self):
        """热区不足时，task_type 过滤会补充冷区结果。"""
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem = TaskMemory(data_dir=tmp, hot_limit=2)
        for i in range(5):
            mem.record_task(task=f"t{i}", task_type="search")

        # 热区只有 2 条 search，请求 4 条
        results = mem.get_recent_summaries(n=4, task_type="search")
        assert len(results) >= 2  # 至少热区的 2 条（冷区补充后应达到 4）


# ============================================================================
# 5. 漂移检测
# ============================================================================

class TestDriftDetection:
    def test_similarity_identical(self):
        from core.task_memory import _text_similarity
        assert _text_similarity("hello world", "hello world") == 1.0

    def test_similarity_disjoint(self):
        from core.task_memory import _text_similarity
        assert _text_similarity("aaa bbb ccc", "xxx yyy zzz") == 0.0

    def test_similarity_partial(self):
        from core.task_memory import _text_similarity
        sim = _text_similarity("hello world foo", "hello world bar")
        assert 0.0 < sim < 1.0

    def test_similarity_empty_both(self):
        from core.task_memory import _text_similarity
        assert _text_similarity("", "") == 1.0

    def test_similarity_one_empty(self):
        from core.task_memory import _text_similarity
        assert _text_similarity("", "something") == 0.0
        assert _text_similarity("something", "") == 0.0

    def test_no_cached_no_drift(self):
        mem = _make_memory()
        result = mem.check_consistency("unknown task", "some result")
        assert result.is_drift is False
        assert result.action == "none"
        assert result.cached_summary is None

    def test_identical_result_no_drift(self):
        mem = _make_memory()
        mem.record_task(task="search tutorial", result_summary="found 5 results")
        result = mem.check_consistency("search tutorial", "found 5 results")
        assert result.is_drift is False
        assert result.similarity == 1.0
        assert result.action == "none"

    def test_very_different_result_is_drift(self):
        mem = _make_memory()
        mem.configure_drift(threshold=0.5, action="human_review")
        mem.record_task(task="fetch data", result_summary="success got 100 items")
        result = mem.check_consistency("fetch data", "failed connection error timeout")
        assert result.is_drift is True
        assert result.action == "human_review"
        assert result.similarity < 0.5

    def test_drift_action_rerun(self):
        mem = _make_memory()
        mem.configure_drift(threshold=0.9, action="rerun")
        mem.record_task(task="compute X", result_summary="result A B C D E")
        result = mem.check_consistency("compute X", "result Z Z Z Z Z")
        assert result.is_drift is True
        assert result.action == "rerun"

    def test_configure_drift_invalid_action(self):
        mem = _make_memory()
        with pytest.raises(ValueError, match="action"):
            mem.configure_drift(action="invalid_value")

    def test_configure_drift_threshold_clamped(self):
        mem = _make_memory()
        mem.configure_drift(threshold=2.0)  # > 1.0 → clamped to 1.0
        assert mem._drift_threshold == 1.0
        mem.configure_drift(threshold=-1.0)  # < 0.0 → clamped to 0.0
        assert mem._drift_threshold == 0.0

    def test_drift_check_by_task_type(self):
        """按 task_type 查找缓存记录。"""
        mem = _make_memory()
        mem.record_task(task="other task", task_type="other", result_summary="irrelevant")
        mem.record_task(task="my task", task_type="search", result_summary="found 10 items")
        # task_key 不匹配，但 task_type 匹配
        result = mem.check_consistency("completely different key", "found 10 items", task_type="search")
        assert result.is_drift is False  # identical result
        assert result.cached_summary == "found 10 items"

    def test_drift_check_override_threshold(self):
        """check_consistency 的 threshold 参数覆盖实例级配置。"""
        mem = _make_memory()
        mem.configure_drift(threshold=0.1)  # 很宽松
        mem.record_task(task="task X", result_summary="alpha beta gamma")
        result = mem.check_consistency("task X", "totally different stuff xyz", threshold=0.99)
        # 使用严格阈值 0.99 → 触发漂移
        assert result.is_drift is True
        assert result.threshold == 0.99

    def test_drift_check_override_action(self):
        mem = _make_memory()
        mem.configure_drift(threshold=0.9, action="human_review")
        mem.record_task(task="task Y", result_summary="abc def ghi")
        result = mem.check_consistency("task Y", "xyz uvw rst", action="rerun", threshold=0.9)
        assert result.action == "rerun"

    def test_get_stats_includes_g6_fields(self):
        mem = _make_memory(hot_limit=50, ttl_seconds=3600.0)
        mem.record_task(task="t1", task_type="search")
        mem.record_task(task="t2", task_type="analysis")
        stats = mem.get_stats()
        assert "task_type_distribution" in stats
        assert stats["task_type_distribution"]["search"] == 1
        assert stats["task_type_distribution"]["analysis"] == 1
        assert stats["hot_limit"] == 50
        assert stats["ttl_seconds"] == 3600.0


# ============================================================================
# 6. 向后兼容（旧版签名 / 旧版文件）
# ============================================================================

class TestBackwardCompatibility:
    def test_record_task_without_task_type(self):
        """旧版调用方式不需要传 task_type。"""
        mem = _make_memory()
        entry = mem.record_task(task="old style call", result_summary="ok", success=True)
        assert entry.task_type == ""
        assert entry.task == "old style call"

    def test_old_jsonl_without_task_type_loads(self):
        """文件中无 task_type 字段的旧记录能正常加载。"""
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        jsonl = os.path.join(tmp, "task_memory.jsonl")
        old_record = {
            "summary_id": "x1",
            "timestamp": time.time(),
            "task": "legacy task",
            "result_summary": "legacy result",
            "success": True,
            "strategy": "single",
            "duration_ms": 5.0,
            "session_id": "",
            "tags": [],
            "extra": {},
            # NO task_type field
        }
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps(old_record) + "\n")

        mem = TaskMemory(data_dir=tmp)
        recent = mem.get_recent_summaries(n=5)
        assert len(recent) == 1
        assert recent[0].task == "legacy task"
        assert recent[0].task_type == ""

    def test_get_recent_summaries_default_no_filter(self):
        """get_recent_summaries() 无参数调用行为与旧版一致。"""
        mem = _make_memory()
        for i in range(5):
            mem.record_task(task=f"t{i}")
        result = mem.get_recent_summaries()
        assert len(result) == 5

    def test_inject_into_context_unchanged(self):
        """inject_into_context 行为与旧版一致。"""
        mem = _make_memory()
        mem.record_task(task="legacy task", result_summary="done")
        ctx = [{"role": "user", "content": "hello"}]
        new_ctx = mem.inject_into_context(ctx, n=1)
        assert len(new_ctx) == 2
        assert "[TaskMemory]" in new_ctx[0]["content"]

    def test_default_hot_limit_backward_compat(self):
        """默认 hot_limit=200 与旧版 _MAX_IN_MEMORY 一致。"""
        from core.task_memory import TaskMemory, _MAX_IN_MEMORY
        mem = TaskMemory(data_dir=tempfile.mkdtemp())
        assert mem._hot_limit == _MAX_IN_MEMORY

    def test_default_ttl_zero(self):
        """默认 ttl_seconds=0（不过期），向后兼容。"""
        from core.task_memory import TaskMemory
        mem = TaskMemory(data_dir=tempfile.mkdtemp())
        assert mem._ttl_seconds == 0.0


# ============================================================================
# 7. API 路由集成测试
# ============================================================================

class TestAPIRoutes:
    """通过 FastAPI TestClient 测试 c_stage 路由。"""

    def _make_app(self, mem=None):
        """构建一个包含 c_stage 路由的最小 FastAPI 应用。"""
        import core.task_memory as tm_module
        from fastapi import FastAPI
        from core.routes.c_stage import create_router

        app = FastAPI()
        # 注入测试用的内存实例（替换单例）
        if mem is not None:
            tm_module._instance = mem
        router = create_router()
        app.include_router(router)
        return app

    def _client(self, mem=None):
        from httpx import AsyncClient, ASGITransport
        app = self._make_app(mem=mem)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.asyncio
    async def test_memory_tasks_no_filter(self):
        mem = _make_memory()
        mem.record_task(task="t1", task_type="search")
        mem.record_task(task="t2", task_type="analysis")
        async with self._client(mem=mem) as client:
            resp = await client.get("/api/v1/memory/tasks?n=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_memory_tasks_with_task_type_filter(self):
        mem = _make_memory()
        mem.record_task(task="s1", task_type="search")
        mem.record_task(task="a1", task_type="analysis")
        mem.record_task(task="s2", task_type="search")
        async with self._client(mem=mem) as client:
            resp = await client.get("/api/v1/memory/tasks?task_type=search")
        data = resp.json()
        assert data["success"] is True
        assert data["count"] == 2
        assert data["task_type_filter"] == "search"

    @pytest.mark.asyncio
    async def test_memory_cold_endpoint(self):
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem = TaskMemory(data_dir=tmp, hot_limit=2)
        for i in range(5):
            mem.record_task(task=f"t{i}", task_type="search")
        async with self._client(mem=mem) as client:
            resp = await client.get("/api/v1/memory/cold?n=50")
        data = resp.json()
        assert data["success"] is True
        assert data["count"] >= 3  # 5 records - 2 hot = 3 cold

    @pytest.mark.asyncio
    async def test_memory_cold_filter_by_task_type(self):
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem = TaskMemory(data_dir=tmp, hot_limit=2)
        mem.record_task(task="s1", task_type="search")
        mem.record_task(task="a1", task_type="analysis")
        mem.record_task(task="s2", task_type="search")
        mem.record_task(task="a2", task_type="analysis")
        async with self._client(mem=mem) as client:
            resp = await client.get("/api/v1/memory/cold?task_type=analysis")
        data = resp.json()
        assert data["success"] is True
        for r in data["records"]:
            assert r["task_type"] == "analysis"

    @pytest.mark.asyncio
    async def test_drift_config_get(self):
        mem = _make_memory()
        mem.configure_drift(threshold=0.7, action="rerun")
        async with self._client(mem=mem) as client:
            resp = await client.get("/api/v1/memory/drift/config")
        data = resp.json()
        assert data["success"] is True
        assert data["threshold"] == pytest.approx(0.7)
        assert data["action"] == "rerun"

    @pytest.mark.asyncio
    async def test_drift_config_put(self):
        mem = _make_memory()
        async with self._client(mem=mem) as client:
            resp = await client.put(
                "/api/v1/memory/drift/config",
                json={"threshold": 0.6, "action": "human_review"},
            )
        data = resp.json()
        assert data["success"] is True
        assert data["threshold"] == pytest.approx(0.6)
        assert data["action"] == "human_review"

    @pytest.mark.asyncio
    async def test_drift_config_put_invalid_action(self):
        mem = _make_memory()
        async with self._client(mem=mem) as client:
            resp = await client.put(
                "/api/v1/memory/drift/config",
                json={"action": "explode"},
            )
        assert resp.status_code == 400
        assert resp.json()["success"] is False

    @pytest.mark.asyncio
    async def test_drift_check_no_drift(self):
        mem = _make_memory()
        mem.configure_drift(threshold=0.5, action="human_review")
        mem.record_task(task="search tutorials", result_summary="found 5 results")
        async with self._client(mem=mem) as client:
            resp = await client.post(
                "/api/v1/memory/drift/check",
                json={"task_key": "search tutorials", "new_result": "found 5 results"},
            )
        data = resp.json()
        assert data["success"] is True
        assert data["is_drift"] is False

    @pytest.mark.asyncio
    async def test_drift_check_with_drift(self):
        mem = _make_memory()
        mem.configure_drift(threshold=0.5, action="human_review")
        mem.record_task(task="process files", result_summary="completed successfully all items")
        async with self._client(mem=mem) as client:
            resp = await client.post(
                "/api/v1/memory/drift/check",
                json={"task_key": "process files", "new_result": "fatal error crashed system"},
            )
        data = resp.json()
        assert data["success"] is True
        assert data["is_drift"] is True
        assert data["action"] == "human_review"

    @pytest.mark.asyncio
    async def test_drift_check_missing_task_key(self):
        mem = _make_memory()
        async with self._client(mem=mem) as client:
            resp = await client.post(
                "/api/v1/memory/drift/check",
                json={"new_result": "something"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_memory_stats_includes_g6_fields(self):
        mem = _make_memory(hot_limit=50, ttl_seconds=3600)
        mem.record_task(task="t", task_type="search")
        async with self._client(mem=mem) as client:
            resp = await client.get("/api/v1/memory/stats")
        data = resp.json()
        assert data["success"] is True
        assert "task_type_distribution" in data
        assert "hot_limit" in data
        assert "ttl_seconds" in data
