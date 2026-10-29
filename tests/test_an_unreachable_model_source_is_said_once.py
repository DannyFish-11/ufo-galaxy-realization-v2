"""HF 下载源不可达时,Kokoro 模型预取的那条告警在一个窗口里只说一次。

第 8 轮真跑(下载源全不可达的机器):启动那一秒里同一条「Kokoro 模型拉取失败(HF 下载源不可达,本次跳过预取、
不做多轮重试刷屏)」连打三遍 —— 预取标记在不可达时回滚(源恢复后可再试),而选语音引擎时每问一次可用就再来一遍。
"""

from __future__ import annotations

import logging
import threading


def _run_fetch(ke):
    ke.kick_background_fetch()
    for t in threading.enumerate():
        if t.name == "kokoro-fetch":
            t.join(timeout=5)


def test_three_probes_in_a_row_warn_once(monkeypatch, caplog):
    import core.hf_endpoint as hf
    import core.tts.kokoro_engine as ke

    monkeypatch.setattr(hf, "pick_endpoint", lambda: "")
    monkeypatch.setattr(ke, "model_files_present", lambda: False)
    monkeypatch.setattr(ke, "_fetch_started", False)
    monkeypatch.setattr(ke, "_unreachable_said_at", -ke._UNREACHABLE_QUIET_S)
    monkeypatch.setenv("GALAXY_KOKORO_AUTOFETCH", "1")
    with caplog.at_level(logging.WARNING, logger=ke.logger.name):
        for _ in range(3):
            _run_fetch(ke)
    said = [r for r in caplog.records if "HF 下载源不可达" in r.getMessage()]
    assert len(said) == 1
    assert ke._fetch_started is False, "标记照旧回滚:源恢复后还会再试"
