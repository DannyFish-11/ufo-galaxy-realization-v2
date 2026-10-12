"""识别模型一次没下下来,语音交互不该整场「未启用」:后台隔几分钟重探下载源,通了再开。

所有者 Windows 真机日志:下载源一次探测没通 → Whisper 只认本地缓存 → ``语音交互 未启用``,
要想再试只能重启。
"""

from __future__ import annotations

import asyncio
import types

import core.hf_endpoint as hf
from launcher.services import GalaxyUnified


def _fake(results):
    calls = []

    async def start_voice_interaction():
        calls.append(1)
        return results.pop(0)

    me = types.SimpleNamespace(start_voice_interaction=start_voice_interaction)
    me._retry_voice_later = lambda **kw: GalaxyUnified._retry_voice_later(me, **kw)
    return me, calls


def test_it_retries_after_the_source_comes_back(monkeypatch):
    probes = iter(["", "", "https://hf-mirror.com"])
    forced = []

    def pick(force=False, **_):
        forced.append(force)
        return next(probes)

    monkeypatch.setattr(hf, "pick_endpoint", pick)
    me, calls = _fake([True])

    async def run():
        me._retry_voice_later(every_s=0, tries=5)
        await me._voice_retry_task

    asyncio.run(run())
    assert len(calls) == 1, "下载源没通的那两轮不该去加载模型"
    assert forced == [True, True, True], "每次都要强制重探 —— 不能吃 5 分钟的负缓存"


def test_it_gives_up_after_a_bounded_number_of_tries(monkeypatch):
    monkeypatch.setattr(hf, "pick_endpoint", lambda force=False, **_: "https://hf-mirror.com")
    me, calls = _fake([False, False, False])

    async def run():
        me._retry_voice_later(every_s=0, tries=3)
        await me._voice_retry_task

    asyncio.run(run())
    assert len(calls) == 3


def test_only_one_retry_runs_at_a_time(monkeypatch):
    monkeypatch.setattr(hf, "pick_endpoint", lambda force=False, **_: "")
    me, _ = _fake([])

    async def run():
        me._retry_voice_later(every_s=0, tries=2)
        first = me._voice_retry_task
        me._retry_voice_later(every_s=0, tries=2)
        assert me._voice_retry_task is first
        await first

    asyncio.run(run())


def test_the_download_failure_branch_schedules_it():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "launcher" / "services.py").read_text(encoding="utf-8")
    branch = src[src.index('"snapshot folder", "internet"') :][:500]
    assert "self._retry_voice_later()" in branch
