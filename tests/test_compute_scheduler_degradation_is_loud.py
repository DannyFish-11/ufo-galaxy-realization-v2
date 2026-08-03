"""ComputeScheduler 退化必须响亮 —— 不能静默退回它要修的那个 bug。

背景
----
`core/local_model_backends.py` 的 `LlamaCppBackend.load_model` 在加载前问
`ComputeScheduler` 要分配决策（卸多少层到 GPU）。引入它的理由写在原注释里：

    此前 n_gpu_layers 写死 -1（全部上 GPU）：显存不够时直接 OOM，没有降级。

问题是这两处的失败处理原先都是**哑的**：

* 调度失败 → `logger.debug("ComputeScheduler unavailable ...")`
  兜底值恰恰就是 `-1`，也就是**退回它被引入来修的那个行为**。生产上只看得到
  一次莫名其妙的 OOM，看不到"调度器没生效"这个原因。
* `register_loaded` 失败 → `except Exception: pass`，一个字都不留。
  但它把本次分配写进 `ComputeScheduler._models`，而 `gpu_model_count` /
  `max_gpu_models` 这些准入判断都读它。漏记一次，后续分配就按偏多的余量下判断
  （过量承诺 GPU），最终触发的正是它要防的 OOM。

这份测试钉的是**行为**（真的调 load_model，真的让调度器抛，抓 caplog），
不是"源码里有没有出现 warning 这个词"。
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import pytest


class _FakeLlama:
    """顶掉 llama_cpp.Llama —— 测试环境没有这个包，且我们不关心真加载。"""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.fixture()
def _stub_llama_cpp(monkeypatch: pytest.MonkeyPatch):
    mod = types.ModuleType("llama_cpp")
    mod.Llama = _FakeLlama  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    return mod


@pytest.fixture()
def _backend(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from core.local_model_backends import LlamaCppBackend

    gguf = tmp_path / "m.q4.gguf"
    gguf.write_bytes(b"x" * 2048)

    backend = LlamaCppBackend()
    monkeypatch.setattr(backend, "_resolve_model_path", lambda _mid: str(gguf))
    return backend


def _load(backend) -> bool:
    import asyncio

    return asyncio.run(backend.load_model("m"))


class TestSchedulerUnavailableIsLoud:
    def test_scheduler_failure_logs_warning_not_debug(
        self, _stub_llama_cpp, _backend, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """调度器抛异常时必须留 WARNING —— debug 级等于没说。"""

        def _boom():
            raise RuntimeError("scheduler exploded")

        monkeypatch.setattr("core.compute_scheduler.get_compute_scheduler", _boom)

        with caplog.at_level(logging.WARNING):
            assert _load(_backend) is True

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "调度器失败时没有任何 WARNING —— 退化是静默的"

    def test_warning_states_the_consequence_not_just_unavailable(
        self, _stub_llama_cpp, _backend, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """光说'unavailable'没用，必须说清后果：层卸载没生效、可能 OOM。

        这条是这份测试的重点。原消息 "ComputeScheduler unavailable (fallback
        n_gpu_layers=-1)" 字面上没错，但读的人无从知道 -1 意味着"退回 OOM 行为"。
        """

        def _boom():
            raise RuntimeError("scheduler exploded")

        monkeypatch.setattr("core.compute_scheduler.get_compute_scheduler", _boom)

        with caplog.at_level(logging.WARNING):
            _load(_backend)

        blob = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
        assert "OOM" in blob, f"退化告警没有点明 OOM 风险：{blob!r}"
        assert "n_gpu_layers" in blob, f"退化告警没有给出实际生效的值：{blob!r}"


class TestRegisterLoadedFailureIsLoud:
    def test_register_loaded_failure_is_not_swallowed(
        self, _stub_llama_cpp, _backend, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """登记失败会让调度器账目偏少 → 后续过量承诺，不能 `except: pass`。"""

        class _Alloc:
            model_id = "m"
            device = "gpu:0"
            n_gpu_layers = 20
            reason = "test"
            is_gpu = True

        class _Sched:
            async def schedule_model(self, *_a, **_k):
                return _Alloc()

            def register_loaded(self, _alloc):
                raise RuntimeError("registry write failed")

        monkeypatch.setattr("core.compute_scheduler.get_compute_scheduler", lambda: _Sched())

        with caplog.at_level(logging.WARNING):
            assert _load(_backend) is True

        blob = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
        assert "register_loaded" in blob, f"登记失败被吞了：{blob!r}"

    def test_successful_path_stays_quiet(
        self, _stub_llama_cpp, _backend, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """自证：一切正常时不该有 WARNING。

        没有这条，上面几条可能因为「任何路径都在刷 WARNING」而假绿。
        """

        class _Alloc:
            model_id = "m"
            device = "gpu:0"
            n_gpu_layers = 20
            reason = "test"
            is_gpu = True

        class _Sched:
            async def schedule_model(self, *_a, **_k):
                return _Alloc()

            def register_loaded(self, _alloc):
                return None

        monkeypatch.setattr("core.compute_scheduler.get_compute_scheduler", lambda: _Sched())

        with caplog.at_level(logging.WARNING):
            assert _load(_backend) is True

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warnings, f"正常路径不该有 WARNING：{[r.getMessage() for r in warnings]}"
