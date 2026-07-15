"""tests/test_kokoro_prefetch.py
==================================
Kokoro 离线 TTS 模型"被动懒加载"的回归防护。

真机排查发现:此前 kick_background_fetch() 只在第一次真的要朗读、edge-tts 失败
降级时才被 speech_output._try_kokoro() 顺手踢一次——而模型 337MB、下载起步要
3 分钟以上,那时才开始必然来不及,当次对话只能落到 SAPI 机器人音,呼应所有者的
"语音为什么还是用不了"反馈。

本测试锁定两处修复:
1. unified_launcher.py 的启动序列必须【无条件】(不依赖 start_voice_interaction()
   是否成功)主动踢一次后台预取,而不是只在 speech_output 里被动触发。
2. kick_background_fetch() 拉取失败时必须用 WARNING(而非默认控制台看不到的
   INFO)上报,且带上可操作的具体路径/文件名/镜像指引。
"""

from __future__ import annotations

import importlib
import logging
import pathlib
import sys
import types

_LAUNCHER = pathlib.Path(__file__).resolve().parents[1] / "unified_launcher.py"


def test_launcher_calls_kokoro_prefetch_unconditionally_before_voice_interaction():
    src = _LAUNCHER.read_text(encoding="utf-8")
    prefetch_idx = src.find("kick_background_fetch")
    voice_idx = src.find("await self.start_voice_interaction()")
    assert prefetch_idx != -1, "unified_launcher.py 必须主动调用 kokoro kick_background_fetch"
    assert voice_idx != -1, "start_voice_interaction() 调用点消失,测试基准失效"
    assert prefetch_idx < voice_idx, (
        "Kokoro 预取必须在语音交互启动之前触发,且不能依赖其结果——" "回归了'被动懒加载,3 分钟下载来不及'的 bug"
    )
    # 预取调用不能被包在语音输入是否可用的判断之内——TTS 出声与麦克风/ASR
    # 是否可用无关,不该被 GALAXY_VOICE 挡住。
    between = src[prefetch_idx:voice_idx]
    assert "GALAXY_VOICE" not in between, "Kokoro 预取不应被 GALAXY_VOICE 麦克风开关挡住"


def _reload_kokoro_engine(monkeypatch, tmp_path):
    import core.tts.kokoro_engine as kokoro_engine

    importlib.reload(kokoro_engine)
    monkeypatch.setattr(kokoro_engine, "_fetch_started", False)
    monkeypatch.setenv("GALAXY_KOKORO_DIR", str(tmp_path))
    return kokoro_engine


class _SyncThread:
    """threading.Thread 的同步替身:start() 直接原地跑 target,便于断言副作用。"""

    def __init__(self, target=None, name=None, daemon=None):
        self._target = target

    def start(self) -> None:
        if self._target:
            self._target()


def test_autofetch_off_switch_prevents_thread(monkeypatch, tmp_path):
    kokoro_engine = _reload_kokoro_engine(monkeypatch, tmp_path)
    monkeypatch.setenv("GALAXY_KOKORO_AUTOFETCH", "0")
    ran = {"count": 0}
    monkeypatch.setattr(
        kokoro_engine.threading,
        "Thread",
        lambda *a, **k: ran.__setitem__("count", ran["count"] + 1) or _SyncThread(*a, **k),
    )
    kokoro_engine.kick_background_fetch()
    assert ran["count"] == 0, "GALAXY_KOKORO_AUTOFETCH=0 时不应起任何拉取线程"


def test_fetch_failure_logs_at_warning_with_actionable_hint(monkeypatch, tmp_path, caplog):
    kokoro_engine = _reload_kokoro_engine(monkeypatch, tmp_path)
    monkeypatch.setenv("GALAXY_KOKORO_AUTOFETCH", "1")
    monkeypatch.setattr(kokoro_engine.threading, "Thread", _SyncThread)

    fake_hub = types.ModuleType("huggingface_hub")

    def _boom(*a, **k):
        raise RuntimeError("network unreachable")

    fake_hub.hf_hub_download = _boom
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    with caplog.at_level(logging.WARNING, logger="Galaxy.TTS.Kokoro"):
        kokoro_engine.kick_background_fetch()  # _SyncThread 让 _fetch() 原地跑完

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "Kokoro 模型拉取失败" in r.message for r in warnings
    ), f"拉取失败应以 WARNING 上报,实际记录: {[(r.levelname, r.message) for r in caplog.records]}"
    assert any(kokoro_engine._model_file() in r.message for r in warnings), "警告应包含具体模型文件名"
    assert any("HF_ENDPOINT" in r.message for r in warnings), "警告应包含镜像指引"


def test_kick_background_fetch_is_idempotent(monkeypatch, tmp_path):
    kokoro_engine = _reload_kokoro_engine(monkeypatch, tmp_path)
    monkeypatch.setenv("GALAXY_KOKORO_AUTOFETCH", "1")
    starts = {"count": 0}

    def _counting_thread(target=None, name=None, daemon=None):
        starts["count"] += 1
        return _SyncThread(target=lambda: None)  # 不真的跑,只统计"起了几次线程"

    monkeypatch.setattr(kokoro_engine.threading, "Thread", _counting_thread)
    kokoro_engine.kick_background_fetch()
    kokoro_engine.kick_background_fetch()
    kokoro_engine.kick_background_fetch()
    assert starts["count"] == 1, "多次调用应幂等,只起一次拉取线程"
