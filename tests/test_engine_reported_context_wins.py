#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_engine_reported_context_wins.py

钉住：**模型由外部引擎伺候时，上下文长度问它，不自己算。**

修的是什么
==========
``ComputeScheduler.context_budget_for`` 那整套推算的前提是"权重是我们加载的、
KV cache 是我们分配的"。模型由一台 OpenAI 兼容引擎伺候时（FreeToken 的
``ft serve``、vLLM、llama.cpp server），这个前提整个不成立 —— 算出来的不再是
"我要开多长"，而是**对别人已经开了多长的一次猜测**。

猜高了：早被引擎静默截断（截断在那一层没有任何报错）；猜低了：白白提前压缩、丢
细节。而这个数**同时是压缩阈值**（``OpenClawd._react_n_ctx`` 取自同一处），所以
猜错的代价是双份的。

两个数不是一回事
================
FreeToken 源码 ``server/openai_api.py::_model_context_length`` 的注释写得很清楚::

    The model ceiling, not `min(ceiling, KV budget)`: a rebuild moves the latter

* ``model.ctx`` —— 模型天花板（``max_seq_len``）；
* ``kv.total_pages × kv.page_size`` —— **此刻**真正装得下多少，会随 cache rebuild 变。

真正能用的是**两者取小**。本文件用真的 HTTP 服务喂 ``/v1/stats``，形状照
FreeToken 的 ``server/stats.py::build_stats`` 抄，不是编的。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import core.served_engine_facts as SEF
from core.compute_scheduler import ComputeScheduler

TAG = "qwen3.6:35b-a3b"
SERVED_ID = "Qwen3.6-35B-A3B"  # FreeToken 取 --model 路径的 basename


def _spawn(*, ctx, total_pages, page_size, model_id=SERVED_ID, kv=True, vram_bytes=7_300_000_000):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _j(self, o):
            b = json.dumps(o).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            p = self.path.rstrip("/")
            if p.endswith("/models"):
                return self._j({"data": [{"id": model_id}]})
            if p.endswith("/v1/stats"):
                doc = {
                    "instance_id": "i1",
                    "model": {"id": model_id, "ctx": ctx, "attn": "mha", "moe": True},
                    "uptime_s": 12,
                    "mamba": None,
                    "swa": None,
                    "vram_bytes": vram_bytes,
                    "throughput": {"decode_tps": 39.3, "prefill_tps": 800.0},
                    "requests": {
                        "active": 0,
                        "completed": 3,
                        "p95_ms": 120,
                        "ttft_mean_ms": 40,
                        "prompt_tokens_total": 100,
                        "completion_tokens_total": 20,
                    },
                }
                doc["kv"] = {"used_pages": 10, "total_pages": total_pages, "page_size": page_size} if kv else None
                return self._j(doc)
            self.send_response(404)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"127.0.0.1:{srv.server_port}"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from core.multi_llm_router import _LOCAL_OPENAI_LANES

    for lane in _LOCAL_OPENAI_LANES:
        for suffix in ("URL", "MODEL", "SERVES", "KEY"):
            monkeypatch.delenv(f"{lane['env_prefix']}_{suffix}", raising=False)
    monkeypatch.delenv("GALAXY_LLAMA_CTX", raising=False)
    SEF.clear_cache()
    yield
    SEF.clear_cache()


@pytest.fixture
def engine():
    made = []

    def _make(**kw):
        srv, addr = _spawn(**kw)
        made.append(srv)
        return addr

    yield _make
    for s in made:
        s.shutdown()


def _budget(tag=TAG):
    return ComputeScheduler().context_budget_for(tag)


class TestWithoutAnEngineNothingChanges:
    def test_the_static_path_still_answers(self):
        n, why = _budget()
        assert n > 0
        assert "引擎" not in why, "没配引擎却说是引擎报的"


class TestTheEngineIsAsked:
    def test_the_smaller_of_ceiling_and_kv_wins(self, engine, monkeypatch):
        addr = engine(ctx=262144, total_pages=40000, page_size=1)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", TAG)
        n, why = _budget()
        assert n == 40000, f"没取小：{n} / {why}"
        assert "KV 容量" in why, f"理由说不出被谁卡住：{why}"

    def test_the_ceiling_wins_when_kv_is_roomier(self, engine, monkeypatch):
        """反面：只看 KV 会在这里给出 99999，那是模型根本吃不下的长度。"""
        addr = engine(ctx=8192, total_pages=99999, page_size=1)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", TAG)
        n, why = _budget()
        assert n == 8192 and "模型上限" in why, f"{n} / {why}"

    def test_a_page_is_not_assumed_to_be_one_token(self, engine, monkeypatch):
        """DSV4 强制 page_size=128，TRTLLM 后端要 16/32/64 —— 假设 1 会低估几十倍。"""
        addr = engine(ctx=1048576, total_pages=500, page_size=128)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", TAG)
        assert _budget()[0] == 500 * 128

    def test_no_kv_report_falls_back_to_the_ceiling_not_to_the_static_guess(self, engine, monkeypatch):
        addr = engine(ctx=32768, total_pages=0, page_size=0, kv=False)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", TAG)
        n, why = _budget()
        assert n == 32768 and "未报 KV" in why, f"{n} / {why}"


class TestItRefusesToClaimTheWrongEngine:
    """**认错比认不出更糟** —— 认不出只是退回推算，认错会拿另一台的容量当这一位的真值。"""

    def test_a_foreign_tag_is_not_claimed(self, engine, monkeypatch):
        addr = engine(ctx=262144, total_pages=40000, page_size=1)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        _n, why = _budget("qwythos-9b-v2")
        assert "引擎" not in why, f"拿了别人的容量：{why}"

    def test_the_self_reported_id_is_matched_modulo_separators(self, engine, monkeypatch):
        """引擎按自己那套命名报（``Qwen3.6-35B-A3B``），与目录 tag 只差分隔符。"""
        addr = engine(ctx=262144, total_pages=40000, page_size=1)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)  # 故意不给 SERVES
        assert _budget()[0] == 40000

    def test_the_two_c_tier_candidates_never_normalize_to_each_other(self):
        """同尺寸同架构的两个候选被认混，就是拿一位的容量去定另一位。"""
        a = SEF._normalize_model_id("qwen3.6:35b-a3b")
        b = SEF._normalize_model_id("agents-a1:35b-a3b")
        assert a != b

    def test_no_family_fallback_by_root_name(self, engine, monkeypatch):
        """``get_model`` 有家族兜底，容量口径**不许**有 —— 与 ``exact_model`` 同一个理由。"""
        addr = engine(ctx=99999, total_pages=99999, page_size=1, model_id="qwen3.6:27b")
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        _n, why = _budget(TAG)
        assert "引擎" not in why, f"按根名认领了另一个型号：{why}"

    def test_every_catalog_tag_normalizes_uniquely(self):
        import core.model_catalog as mc

        seen = {}
        for t in mc.choice_order():
            n = SEF._normalize_model_id(t)
            assert n not in seen, f"{t} 与 {seen[n]} 归一化后撞车"
            seen[n] = t


class TestItDegradesQuietly:
    def test_an_explicit_override_still_wins(self, engine, monkeypatch):
        addr = engine(ctx=262144, total_pages=40000, page_size=1)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", TAG)
        monkeypatch.setenv("GALAXY_LLAMA_CTX", "12345")
        n, why = _budget()
        assert n == 12345 and "显式指定" in why

    def test_a_reply_without_credible_capacity_is_treated_as_no_reply(self, engine, monkeypatch):
        """应答了但 ctx=0、kv=null —— 空壳事实不许压过静态推算。"""
        addr = engine(ctx=0, total_pages=0, page_size=0, kv=False)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_SERVES", TAG)
        _n, why = _budget()
        assert "引擎" not in why, why

    def test_a_dead_address_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", "127.0.0.1:1")
        n, why = _budget()
        assert n > 0 and "引擎" not in why

    def test_the_two_unreliable_paths_each_leave_a_trace(self, caplog):
        """返回值都是 0，但背后是**两个不同的问题**，都得说出来。

        * 转不成整数 → 协议对不上（字段改名/类型变了/我们读错了字段）。不说出来，
          下次 FreeToken 改一版字段名，现场只看到"怎么又按静态推算了"；
        * 转得成但离谱 → 引擎报了脏数据。

        与 ``tests/test_empty_return_is_distinguishable`` 钉的那条同一个立场：空值
        可以取同一个，但**失败不许不留痕迹**。
        """
        with caplog.at_level("WARNING"):
            SEF._credible_ctx("不是数", "model.ctx", "http://x")
        assert "协议" in caplog.text, "字段类型不对却没留下任何线索"
        caplog.clear()
        with caplog.at_level("WARNING"):
            SEF._credible_ctx(SEF._MAX_CREDIBLE_CTX + 1, "model.ctx", "http://x")
        assert "可信区间" in caplog.text, "报了个离谱的值却静默吞掉"

    def test_an_absurd_number_is_rejected(self):
        """不可信的"实测值"比没有更危险 —— 它会理直气壮地压过声明。"""
        assert SEF._credible_ctx(0) == 0
        assert SEF._credible_ctx(-1) == 0
        assert SEF._credible_ctx(SEF._MAX_CREDIBLE_CTX + 1) == 0
        assert SEF._credible_ctx("不是数") == 0
        assert SEF._credible_ctx(262144) == 262144


class TestTheCacheCannotGoStale:
    def test_the_ttl_is_short_because_a_rebuild_moves_kv(self):
        """``POST /v1/cache/rebuild`` 不重启就能改 KV 容量。缓存久了拿到的是过期
        的"真值" —— 比静态推算更有欺骗性，因为它看起来是量出来的。"""
        assert 0 < SEF.CACHE_TTL_S <= 30

    def test_clearing_actually_clears(self, engine, monkeypatch):
        addr = engine(ctx=262144, total_pages=40000, page_size=1)
        monkeypatch.setenv("GALAXY_REASONING_OPENAI_URL", addr)
        SEF.probe(addr)
        assert SEF._cache, "根本没缓存"
        SEF.clear_cache()
        assert not SEF._cache
