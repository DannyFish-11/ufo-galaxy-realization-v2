"""HF 下载源探测:机器忙的时候也别把通着的源判成「均不可达」。

所有者 Windows 真机日志:``HF 下载源均不可达(https://hf-mirror.com / https://huggingface.co)``,
随后 Kokoro 跳过预取、Whisper 只认本地缓存 ——「语音交互 未启用」整场。同一台机器此前下过 Whisper。
启动那一阵机器被压满,原先「每个 2 秒、挨个探」很容易两边都超时。现在并发探、每个 6 秒、
全不通再补探一轮。
"""

from __future__ import annotations

import threading
import time

import pytest

import core.hf_endpoint as hf


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(hf, "_cache", {"ts": 0.0, "endpoint": None})
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("GALAXY_HF_ENDPOINT", raising=False)
    monkeypatch.delenv("GALAXY_HF_MIRROR", raising=False)
    monkeypatch.setattr(hf, "quiet_progress_bars", lambda: None)


def test_the_default_deadline_is_not_two_seconds_any_more():
    assert hf._PROBE_TIMEOUT_S >= 5 and hf._PROBE_ROUNDS >= 2


def test_candidates_are_probed_at_the_same_time(monkeypatch):
    inflight = []
    peak = []
    lock = threading.Lock()

    def slow(base, timeout):
        with lock:
            inflight.append(base)
            peak.append(len(inflight))
        time.sleep(0.3)
        with lock:
            inflight.remove(base)
        return base == "https://huggingface.co"

    monkeypatch.setattr(hf, "_probe", slow)
    t0 = time.monotonic()
    assert hf.pick_endpoint() == "https://huggingface.co"
    assert max(peak) == 2, "两个源还是挨个探的 —— 慢的那一个会把总时长翻倍"
    assert time.monotonic() - t0 < 0.55


def test_the_preferred_source_wins_when_both_answer(monkeypatch):
    monkeypatch.setattr(hf, "_probe", lambda base, timeout: True)
    assert hf.pick_endpoint() == "https://hf-mirror.com"


def test_a_source_that_answers_only_on_the_second_round_is_still_used(monkeypatch):
    calls = {"n": 0}

    def flaky(base, timeout):
        calls["n"] += 1
        return calls["n"] > 2  # 第一轮两个都没答上

    monkeypatch.setattr(hf, "_probe", flaky)
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    assert hf.pick_endpoint() == "https://hf-mirror.com"


def test_really_unreachable_is_still_reported_and_cached(monkeypatch):
    seen = []
    monkeypatch.setattr(hf, "_probe", lambda base, timeout: seen.append(base) or False)
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    assert hf.pick_endpoint() == ""
    n = len(seen)
    assert n == 2 * hf._PROBE_ROUNDS
    assert hf.pick_endpoint() == "" and len(seen) == n, "负缓存期内又探了一遍"
