#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_ingress_token_never_reaches_logs.py

设备接入消息里现在**带着凭证**（``token``），所以"这条消息会不会被整个打进日志"
从一个理论问题变成了实际问题：日志会落盘、会被收集、会被贴进 issue。

CodeQL 的 ``py/clear-text-logging-sensitive-data`` 在设备接入这条链上报了 10 处。
逐条看过之后，它们打的都是 ``device_id`` / ``type`` / ``trace_id`` / 缺失字段名
这类**非凭证**内容，唯一打整包的那处（registration.py 的 ``safe_payload``）已经
显式把 ``token`` 摘掉了。CodeQL 看不见那道过滤 —— 它把"字典里有一个 token 键"
当成"整个字典都是敏感的"，于是从这个字典里读出来的每一个值都算敏感。

**但"我读过代码，觉得没问题"不是判据。** 这个文件把它变成判据：真的驱动一遍
接入链，把所有日志抓下来，断言令牌一个字符都没出现在里面。

CodeQL 那 10 条据此记进 ``config/codeql_findings_ledger.json``（false-positive），
本文件就是台账里那条的 ``guarded_by`` —— 哪天有人真往日志里写了令牌，这里会红，
而不是等 CodeQL 的告警淹在存量里没人看。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.capability_token import issue_token

#: 一枚一眼能认出来的令牌 —— 真漏进日志时，断言的报错里能直接看到是哪一段。
_MARKER = "SHOULD-NEVER-BE-LOGGED-a1b2c3d4e5f6"


def _ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


def _register_msg(device_id: str, token: str, **extra: Any) -> Dict[str, Any]:
    msg = {
        "version": "3.0",
        "type": "device_register",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "platform": "android",
        "model": "TestPhone",
        "token": token,
    }
    msg.update(extra)
    return msg


def _all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """把捕获到的每一条日志摊平成一段文本。

    同时看 ``getMessage()``（格式化后的结果）与 ``args``（未格式化的参数）——
    只看前者会漏掉 ``logger.debug`` 这类在等级不够时不做格式化的记录，
    那正是"平时看不见、开了 DEBUG 就漏"的形状。
    """
    parts = []
    for r in caplog.records:
        try:
            parts.append(r.getMessage())
        except Exception:  # noqa: BLE001 — 格式化失败也要把原始内容纳入检查
            parts.append(str(r.msg))
        parts.append(repr(r.args))
        parts.append(repr(getattr(r, "__dict__", {})))
    return "\n".join(parts)


@pytest.fixture(autouse=True)
def _capture_everything(caplog):
    """抓**所有**等级。只抓 WARNING 以上会让 debug 里的泄漏静默溜过去。"""
    caplog.set_level(logging.DEBUG)
    return caplog


# ---------------------------------------------------------------------------
# 一、正常注册：令牌不进日志
# ---------------------------------------------------------------------------


def test_valid_registration_does_not_log_the_token(caplog, monkeypatch):
    from galaxy_gateway.android_bridge import AndroidBridge

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    device_id = f"logsafe-{uuid.uuid4().hex[:8]}"
    token = issue_token(device_id, ["device:status"])

    bridge = AndroidBridge()
    ack = asyncio.run(bridge.handle_message(_ws(), _register_msg(device_id, token)))

    assert ack and ack.get("success") is True, ack
    text = _all_log_text(caplog)
    assert token not in text, "配对令牌被打进了日志"
    # 对照：device_id 是**应该**能在日志里看到的 —— 否则这条断言不区分
    # "令牌没漏"和"这条链压根没跑起来、日志本来就是空的"。
    assert device_id in text, "整条链没产生任何日志，上面那条断言等于没测"


def test_env_token_is_not_logged_either(caplog, monkeypatch):
    """环境令牌与配对令牌是两条不同的凭证，别只堵一条。"""
    from galaxy_gateway.android_bridge import AndroidBridge

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", _MARKER)
    device_id = f"logsafe-env-{uuid.uuid4().hex[:8]}"

    bridge = AndroidBridge()
    asyncio.run(bridge.handle_message(_ws(), _register_msg(device_id, _MARKER)))

    assert _MARKER not in _all_log_text(caplog)


# ---------------------------------------------------------------------------
# 二、失败路径：正是"把整包打出来"的那条
# ---------------------------------------------------------------------------


def test_registration_exception_path_redacts_the_token(caplog, monkeypatch):
    """``registration.py`` 的兜底 except 会把 payload 打出来 —— CodeQL 报的就是它。

    这里刻意把 UDM 写入弄崩，走到那条 ``logger.error(... payload=%s ...)``，
    确认 ``safe_payload`` 那道过滤真的把 token 摘掉了。
    """
    from galaxy_gateway.android.handlers.registration import handle_device_register

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    device_id = f"logsafe-boom-{uuid.uuid4().hex[:8]}"
    token = issue_token(device_id, ["device:status"])

    bridge = MagicMock()
    bridge._lock = asyncio.Lock()
    bridge._devices = {}
    bridge._sync_device_router_session = MagicMock()

    def _boom(*_a, **_k):
        raise RuntimeError("UDM 写入炸了（本用例刻意制造）")

    bridge._write_registration_to_udm = _boom

    ack = asyncio.run(handle_device_register(bridge, _ws(), _register_msg(device_id, token)))

    assert ack and ack.get("success") is False
    text = _all_log_text(caplog)
    assert token not in text, "异常兜底把带令牌的整包打进了日志"
    # 对照：确认真的走到了那条打 payload 的分支（否则本条测了个寂寞）
    assert "payload=" in text or "Device registration failed" in text


def test_rejected_registration_does_not_log_the_token(caplog, monkeypatch):
    """被拒的注册同样不许把令牌打出来 —— 拒绝路径上的日志往往写得更随手。"""
    from galaxy_gateway.android_bridge import AndroidBridge

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", "some-other-valid-token-0123456789abcd")
    device_id = f"logsafe-rej-{uuid.uuid4().hex[:8]}"

    bridge = AndroidBridge()
    ack = asyncio.run(bridge.handle_message(_ws(), _register_msg(device_id, _MARKER)))

    assert ack and ack.get("success") is False
    assert _MARKER not in _all_log_text(caplog)


def test_malformed_message_with_token_does_not_log_it(caplog, monkeypatch):
    """缺必填字段会走 android_bridge 的 malformed 分支（CodeQL 报的另一处）。

    ``device_id`` 必须是**空串**而不是干脆不给：反向验证时发现，只是不给的话
    ``normalise_to_v3_dict`` 会补一个 ``"unknown"``，``missing`` 就是空的 ——
    这条分支根本走不到，断言无论代码对错都绿。那是个不区分的断言，
    下面的正向对照就是为了让这种情况直接红。
    """
    from galaxy_gateway.android_bridge import AndroidBridge

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    bridge = AndroidBridge()
    bad = {"type": "device_register", "device_id": "", "token": _MARKER}

    ack = asyncio.run(bridge.handle_message(_ws(), bad))

    text = _all_log_text(caplog)
    # 正向对照：确认真的落在 malformed 那条分支上
    assert ack and ack.get("error_code") == "MISSING_REQUIRED_FIELDS", ack
    assert "malformed message" in text, "没走到 malformed 分支，下面那条断言不成立"
    assert _MARKER not in text


def test_unknown_message_type_with_token_does_not_log_it(caplog, monkeypatch):
    from galaxy_gateway.android_bridge import AndroidBridge

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    bridge = AndroidBridge()
    msg = _register_msg(f"logsafe-{uuid.uuid4().hex[:8]}", _MARKER, type="no_such_type_at_all")

    asyncio.run(bridge.handle_message(_ws(), msg))

    assert _MARKER not in _all_log_text(caplog)


# ---------------------------------------------------------------------------
# 三、那份脱敏名单本身
# ---------------------------------------------------------------------------


def test_redaction_list_covers_the_credential_field_names():
    """``safe_payload`` 那道过滤靠一份字段名清单。清单漏一个名字就等于漏一条。"""
    import inspect

    from galaxy_gateway.android.handlers import registration

    src = inspect.getsource(registration)
    start = src.index("_SENSITIVE_FIELDS = frozenset(")
    block = src[start : src.index(")", src.index("}", start))]
    for name in ("token", "password", "credential", "secret", "auth", "api_key"):
        assert f'"{name}"' in block, f"脱敏名单里没有 {name}"


def test_redaction_actually_drops_the_token_key():
    """行为层面再钉一次：过滤后的字典里不许还有 token。"""
    import inspect

    from galaxy_gateway.android.handlers import registration

    src = inspect.getsource(registration)
    assert "safe_payload = {k: v for k, v in message.items() if k not in _SENSITIVE_FIELDS}" in src
    assert (
        "payload=%s" in src and "message," not in src.split("safe_payload")[1][:400]
    ), "打的应该是 safe_payload 而不是原始 message"
