"""开机后 20 秒里没人说话 —— 那是正常的,不该在控制台上念一条 WARNING。

所有者真机日志(每次开机一条)::

    WARNING | 🎙️ 麦克风在收音,但 20s 内(170 块)【VAD 从未判定为说话】——这段时间没人说话就属正常;……

诊断仍然要能说出「说了话却没听见」—— 区分靠响度:有人声那么响的块、VAD 却没判成说话,才告诉人。
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import pytest

import core.multimodal.audio_capture_service as acs


def _service(monkeypatch, *, chunks, loud):
    svc = acs.AudioCaptureService.__new__(acs.AudioCaptureService)
    svc._chunks_seen, svc._speech_chunks, svc._transcripts, svc._loud_unspoken = chunks, 0, 0, loud
    monkeypatch.setenv("GALAXY_VOICE_DIAG_S", "0.01")
    return svc


def _said(svc, caplog):
    with caplog.at_level(logging.INFO, logger=acs.logger.name):
        asyncio.run(svc._voice_input_watchdog())
    return [(r.levelno, r.getMessage()) for r in caplog.records]


def test_a_quiet_room_is_said_only_in_the_log_file(monkeypatch, caplog):
    said = _said(_service(monkeypatch, chunks=170, loud=0), caplog)
    assert said and all(level < logging.WARNING for level, _ in said), said
    assert "安静" in said[0][1]


def test_loud_sound_that_was_never_heard_as_speech_is_still_reported(monkeypatch, caplog):
    said = _said(_service(monkeypatch, chunks=170, loud=12), caplog)
    assert any(level == logging.WARNING and "VAD 从未判定为说话" in msg for level, msg in said), said


@pytest.mark.parametrize(
    "samples,loud",
    [
        (np.zeros(1600, dtype=np.float32), False),
        (np.full(1600, 0.003, dtype=np.float32), False),
        (np.full(1600, 0.1, dtype=np.float32), True),
    ],
)
def test_voice_level_is_told_apart_from_room_noise(samples, loud):
    assert (acs._rms(samples) >= acs._VOICE_LEVEL_RMS) is loud
