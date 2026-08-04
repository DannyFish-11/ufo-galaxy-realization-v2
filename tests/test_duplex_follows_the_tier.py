#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_duplex_follows_the_tier.py
=========================================
双工语音必须**跟着档位能力走**，而不是跟着一个手动开关走。

原状：``duplex_enabled()`` 是一个纯环境开关（``GALAXY_VOICE_DUPLEX``，默认关），
与「当前档位的模型到底有没有 realtime 能力」完全无关。而判据的原料本来全都在：

* ``PROVIDER_REGISTRY`` 维护着每家的 ``realtime_models`` / ``default_realtime_model``；
* ``DuplexSessionConfig.from_env()`` 会按权威顺序解析密钥、过滤占位符、
  本地端点免 key、B 档原生自动推导 realtime 地址；
* ``core.modality_capability.negotiate()`` 给出当前档位的原生听/说结论。

装了一整套判据，最外层那个「开不开」却不看它们 —— 于是「B 档原生已就绪、本地
realtime 端点也推得出来」的机器上，双工照样永远不启动。和第 0 层修掉的 lockstep
手动开关是同一个病。

一条产品判断写在判据里而不是藏着：**自动档只对本机原生供给放行**。云端 realtime
按分钟计费，探到有 key 就自动连上去等于替用户花钱，所以云端一律要显式开
（``requires_opt_in``），但仍然如实报「可用」而不是假装没有。
"""

from __future__ import annotations

from typing import Any

import pytest

import core.voice_duplex_session as vds
from core.voice_duplex_capability import duplex_capability
from core.voice_duplex_session import DuplexSessionConfig, duplex_enabled


class _Res:
    def __init__(self, mode: str) -> None:
        self.mode = mode


class _Plan:
    def __init__(self, audio_in: str, audio_out: str) -> None:
        self.audio_in = _Res(audio_in)
        self.audio_out = _Res(audio_out)


def _cfg(url: str) -> DuplexSessionConfig:
    return DuplexSessionConfig(url=url, api_key="", model="m", voice="v", provider="p")


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    """三态判定必须从"未设置"出发测，否则测的是别人机器上的环境。"""
    monkeypatch.delenv("GALAXY_VOICE_DUPLEX", raising=False)


def _patch_supply(monkeypatch, cfg: Any, plan: Any = None) -> None:
    monkeypatch.setattr(DuplexSessionConfig, "from_env", classmethod(lambda cls, **kw: cfg))
    if plan is not None:
        monkeypatch.setattr("core.modality_capability.negotiate", lambda **kw: plan)


# ===========================================================================
# 一、能力判定如实反映真实供给
# ===========================================================================


def test_no_supply_is_reported_as_unavailable_with_a_reason(monkeypatch) -> None:
    """端点/密钥都没有 → 不可用，且必须说得出为什么。"""
    _patch_supply(monkeypatch, None)
    cap = duplex_capability()
    assert cap.available is False
    assert cap.reason, "不可用却说不出原因 —— '开了开关却没生效'就无从排查"


def test_local_native_supply_is_available_and_needs_no_opt_in(monkeypatch) -> None:
    """B 档原生就绪 + 本地 realtime 端点 → 可用，且不需要额外开关（本机不花钱）。"""
    _patch_supply(monkeypatch, _cfg("ws://localhost:32550/v1/realtime"), _Plan("native", "native"))
    cap = duplex_capability()
    assert cap.available is True
    assert cap.source == "native_local"
    assert cap.requires_opt_in is False


def test_local_endpoint_without_native_tier_is_not_counted_as_capable(monkeypatch) -> None:
    """本地地址是由**服务开关**推导来的；档位模型不原生听/说时连上去也是空转。"""
    _patch_supply(monkeypatch, _cfg("ws://localhost:32550/v1/realtime"), _Plan("bridge", "bridge"))
    cap = duplex_capability()
    assert cap.available is False, "服务开关开着就当成有能力 —— 这正是要修的那种假判据"
    assert "原生" in cap.reason


def test_half_native_tier_does_not_count(monkeypatch) -> None:
    """只原生听、不原生说（或反过来）都不构成双工 —— 双工要求两边同时原生。"""
    _patch_supply(monkeypatch, _cfg("ws://localhost:32550/v1/realtime"), _Plan("native", "bridge"))
    assert duplex_capability().available is False


def test_cloud_supply_is_available_but_requires_explicit_opt_in(monkeypatch) -> None:
    """云端 realtime 端点与密钥都在 → 如实报可用，但要显式开（按分钟计费）。"""
    _patch_supply(monkeypatch, _cfg("wss://api.openai.com/v1/realtime?model=gpt-realtime"))
    cap = duplex_capability()
    assert cap.available is True, "有供给却谎报没有 —— 面板会显示'不支持'"
    assert cap.source == "cloud_realtime"
    assert cap.requires_opt_in is True


def test_capability_probe_never_raises(monkeypatch) -> None:
    """探针异常不得掀翻语音链路。"""

    def _boom(cls, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(DuplexSessionConfig, "from_env", classmethod(_boom))
    cap = duplex_capability()
    assert cap.available is False
    assert "boom" in cap.reason


# ===========================================================================
# 二、三态开关：显式开 / 显式关 / 未设置时跟档位
# ===========================================================================


def test_auto_turns_duplex_on_when_the_tier_really_supports_it(monkeypatch) -> None:
    """核心：没设开关，但 B 档原生已就绪 → 双工自动可用。"""
    _patch_supply(monkeypatch, _cfg("ws://localhost:32550/v1/realtime"), _Plan("native", "native"))
    assert duplex_enabled() is True, "档位明明具备双工能力，双工却仍然不启动"


def test_auto_stays_off_when_the_tier_cannot_do_it(monkeypatch) -> None:
    """对照组：档位不具备时自动档必须保持关，否则上一条等于恒真。"""
    _patch_supply(monkeypatch, None)
    assert duplex_enabled() is False


def test_auto_does_not_spend_money_on_the_user_s_behalf(monkeypatch) -> None:
    """自动档不替用户开云端按分钟计费的链路。"""
    _patch_supply(monkeypatch, _cfg("wss://api.openai.com/v1/realtime?model=gpt-realtime"))
    assert duplex_enabled() is False, "自动档把云端 realtime 打开了 —— 那是在替用户花钱"


def test_explicit_on_wins_over_capability(monkeypatch) -> None:
    """用户明说要试就去试：显式开时不再问能力（连不上各层自会记原因并回落回合制）。"""
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
    _patch_supply(monkeypatch, None)
    assert duplex_enabled() is True


def test_explicit_off_wins_over_capability(monkeypatch) -> None:
    """显式关就是关，哪怕档位完全具备能力。"""
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "0")
    _patch_supply(monkeypatch, _cfg("ws://localhost:32550/v1/realtime"), _Plan("native", "native"))
    assert duplex_enabled() is False


def test_explicit_on_enables_the_cloud_path(monkeypatch) -> None:
    """云端需要的正是这个显式开关 —— 开了就得真的能走云端。"""
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
    _patch_supply(monkeypatch, _cfg("wss://api.openai.com/v1/realtime?model=gpt-realtime"))
    assert duplex_enabled() is True


# ===========================================================================
# 三、探针不得吵、不得说假话
# ===========================================================================


def test_probe_does_not_warn_about_a_switch_the_user_never_turned_on(caplog) -> None:
    """探针只是在问问题，不该以 WARNING 报"双工语音已开启但缺少 API key"。"""
    import logging

    with caplog.at_level(logging.WARNING, logger="Galaxy.VoiceDuplex"):
        duplex_capability()
    noisy = [r for r in caplog.records if "已开启" in r.getMessage()]
    assert not noisy, f"能力探针在谎报'已开启'并刷 WARNING: {[r.getMessage() for r in noisy]}"


def test_real_from_env_still_explains_itself_when_not_probing(caplog, monkeypatch) -> None:
    """对照组：真正建连那条路仍然要把缺什么讲清楚（否则上一条是把日志删干净了）。"""
    import logging

    monkeypatch.delenv("GALAXY_REALTIME_URL", raising=False)
    monkeypatch.setattr("core.secret_resolution.resolve_secret", lambda *a, **kw: "")
    monkeypatch.setattr(vds, "_native_audio_on", lambda: False)
    with caplog.at_level(logging.WARNING, logger="Galaxy.VoiceDuplex"):
        assert DuplexSessionConfig.from_env() is None
    assert any("API key" in r.getMessage() for r in caplog.records), "非探针路径也不解释了 —— 排查线索被删光"
