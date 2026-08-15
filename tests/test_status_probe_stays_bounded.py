#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_status_probe_stays_bounded.py

钉住：**``/models/status`` 里那条落盘探测必须有界。**

怎么发现的
==========
CI 上 ``test-shard (4)`` **卡满 30 分钟被超时取消**（另外三片全绿）。本地复现不
出来 —— 这台机器 ``models/`` 是空的、HuggingFace 管理器又不可用，两条慢路径
一条都没走到。

根因是我给 llama_cpp 型号加状态时埋的：``_gguf_status`` 里原来直接调
``LlamaCppBackend._resolve_model_path``，它会 ``os.walk`` 整个 ``models/``，
还会取道 ``huggingface_model_manager``（自己会扫缓存目录甚至触网）。这是**阻塞**
调用，而我把它放进了 ``_probe_installed_async`` —— 外面包着
``asyncio.wait_for(timeout=_PROBE_BUDGET)``。

三个坑，一个比一个隐蔽
======================
1. ``wait_for`` **拦不住阻塞的同步调用**：它只能在 await 点取消。
2. 改成 ``to_thread`` 之后 ``wait_for`` 确实能提前返回了，**但线程取消不了**：
   ``asyncio.run()`` 收尾要等默认执行器里的线程结束。实测把落盘换成
   ``sleep(30)``、外面套 ``wait_for(0.3)``，整体**仍然 30 秒**。
   pytest 里每个 ``asyncio.run(get_status())`` 都会这样挂住 —— 这正是作业被取消
   的机制。
3. 所以真正的修法是**扫描自身有界**（时间 + 条目数双上限），``to_thread`` +
   ``wait_for`` 只是第二层保险。

下面按层分开钉：混在一条里测，就会像我第一版那样，用一个 30 秒的替身把第一层
架空，然后去质问第二层为什么没兜住。
"""

from __future__ import annotations

import asyncio
import time

import pytest

import core.routes.models as m


@pytest.fixture(autouse=True)
def _clean_caches():
    m._GGUF_CACHE.clear()
    m._status_cache["data"] = None
    m._status_cache["ts"] = 0.0
    yield
    m._GGUF_CACHE.clear()
    m._status_cache["data"] = None
    m._status_cache["ts"] = 0.0


class TestLayerOneTheScanIsBoundedByItself:
    """第一层：扫描自己就不许无界。这是真正治本的那层。"""

    def test_a_huge_tree_is_abandoned_at_the_entry_cap(self, monkeypatch, tmp_path):
        deep = tmp_path / "models"
        for i in range(40):
            d = deep / f"d{i}"
            d.mkdir(parents=True)
            for j in range(20):
                (d / f"f{j}.bin").write_text("x")
        monkeypatch.setattr(m, "_GGUF_SCAN_MAX_ENTRIES", 50)
        monkeypatch.setattr(m, "_models_dir", lambda: str(deep))
        t0 = time.monotonic()
        out = m._find_local_gguf("qwen3.6:35b-a3b")
        assert time.monotonic() - t0 < 5.0
        assert out == "", "触顶后应当收手报'没找到',而不是继续爬"

    def test_the_deadline_stops_a_slow_disk(self, monkeypatch, tmp_path):
        """慢盘上条目数不多但每次 stat 都很久 —— 条目上限拦不住，得靠时间上限。"""
        d = tmp_path / "models" / "x"
        d.mkdir(parents=True)
        for j in range(5):
            (d / f"f{j}.bin").write_text("x")
        monkeypatch.setattr(m, "_GGUF_SCAN_DEADLINE_S", -1.0)  # 立刻过期
        monkeypatch.setattr(m, "_models_dir", lambda: str(tmp_path / "models"))
        assert m._find_local_gguf("qwen3.6:35b-a3b") == ""

    def test_it_does_not_route_through_the_loading_path(self):
        """状态路径不许复用加载路径的实现 —— 后者可以慢、可以触网，预算不是一个量级。"""
        import inspect

        src = inspect.getsource(m._find_local_gguf)
        # 只看代码,不看文档串 —— 文档里正要解释"为什么不走那条路",别自己绊自己。
        body = src.split('"""')[-1]
        assert "_resolve_model_path" not in body, "又接回了那条无界的加载路径"
        assert "huggingface" not in body.lower(), "状态探测取道了 HF 管理器 —— 它可能触网"
        assert "_GGUF_SCAN_DEADLINE_S" in body and "_GGUF_SCAN_MAX_ENTRIES" in body, "两条上限缺了"


class TestLayerTwoOneRequestIsBounded:
    """第二层：即便扫描哪天又变慢了，单个请求也不该被它拖住。

    注意这里**必须用常驻循环**去量，不能用 ``asyncio.run`` —— 后者收尾会等
    执行器线程，量到的是"进程什么时候能退出"，不是"这次请求多久返回"。
    两件事都真实存在，但只有前者是这一层负责的。
    """

    def test_a_hanging_scan_does_not_hold_up_the_await(self, monkeypatch):
        monkeypatch.setattr(m, "_gguf_status_blocking", lambda _t: time.sleep(30))
        monkeypatch.setattr(m, "_GGUF_PROBE_BUDGET", 0.3)

        loop = asyncio.new_event_loop()
        try:
            t0 = time.monotonic()
            out = loop.run_until_complete(m._gguf_status("qwen3.6:35b-a3b"))
            elapsed = time.monotonic() - t0
        finally:
            loop.close()  # 刻意不 shutdown_default_executor:那正是第三件事

        assert elapsed < 5.0, f"这次 await 等了 {elapsed:.1f}s —— 预算没生效"
        assert out["status"] == "unknown", "超预算却报了确定结论 —— 那是在编"

    def test_the_wiring_uses_a_thread_and_a_budget(self):
        import inspect

        src = inspect.getsource(m._gguf_status)
        assert "to_thread" in src, "阻塞探测又被搬回事件循环里了"
        assert "wait_for" in src, "没有自己的预算 —— 外层那个 wait_for 管不住同步阻塞"
        probe = inspect.getsource(m._probe_installed_async)
        assert "await _gguf_status(" in probe, "调用点没 await —— 要么没走异步版,要么塞了个协程进结果里"


class TestItNeverLies:
    def test_a_timeout_reports_unknown_not_absent(self, monkeypatch):
        """探不到 ≠ 没装。谎称 absent 会让用户去重下一个已经在盘上的文件。"""
        monkeypatch.setattr(m, "_gguf_status_blocking", lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
        out = asyncio.run(m._gguf_status("qwen3.6:35b-a3b"))
        assert out["status"] == "unknown"

    def test_a_timeout_is_not_cached(self, monkeypatch):
        """超时不写缓存 —— 否则一次抖动会把"未知"钉住整整一个 TTL。"""
        monkeypatch.setattr(m, "_gguf_status_blocking", lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
        asyncio.run(m._gguf_status("qwen3.6:35b-a3b"))
        assert "qwen3.6:35b-a3b" not in m._GGUF_CACHE

        monkeypatch.setattr(m, "_gguf_status_blocking", lambda _t: {"status": "installed", "matched": "/a.gguf"})
        assert asyncio.run(m._gguf_status("qwen3.6:35b-a3b"))["status"] == "installed"

    def test_the_result_is_cached_so_polling_does_not_rewalk_the_disk(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            m,
            "_gguf_status_blocking",
            lambda t: calls.append(t) or {"status": "installed", "ollama_reachable": False, "matched": "/a.gguf"},
        )
        for _ in range(5):
            asyncio.run(m._gguf_status("qwen3.6:35b-a3b"))
        assert len(calls) == 1, f"探了 {len(calls)} 次 —— 缓存没生效"
