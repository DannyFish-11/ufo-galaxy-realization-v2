"""自发在场的**接线**契约:默认开启 + DELEGATE 真能穿透到 OpenClawd。

既有的 ``test_ambient_attention_loop.py`` 覆盖的是循环**内部**(门控、决策解析、
记忆),它把 ``handle_request`` 整个 mock 掉了 —— 于是"委托出去之后到底进没进
主体认知"这一段从来没被验证过。本文件补的就是那一段接缝,以及"默认开"这个
所有者明确要求的行为。
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── 1. 默认开启 ────────────────────────────────────────────────────────


def test_ambient_loop_defaults_to_enabled(monkeypatch):
    """未设环境变量时必须是开的 —— 默认关等于这个器官装了却从不通电。"""
    monkeypatch.delenv("GALAXY_AMBIENT_LOOP", raising=False)
    from core.ambient_attention_loop import ambient_loop_enabled

    assert ambient_loop_enabled() is True


@pytest.mark.parametrize("off", ["0", "false", "no", "off", "False", "OFF"])
def test_ambient_loop_explicit_off_still_honoured(monkeypatch, off):
    """默认开不等于关不掉:显式关闭必须仍然生效。"""
    monkeypatch.setenv("GALAXY_AMBIENT_LOOP", off)
    from core.ambient_attention_loop import ambient_loop_enabled

    assert ambient_loop_enabled() is False


def test_config_schema_default_matches_runtime_default():
    """面板配置项的默认值必须与运行时默认值一致,否则面板会显示假状态。"""
    from core.routes.config import CONFIG_SCHEMA

    entry = CONFIG_SCHEMA["GALAXY_AMBIENT_LOOP"]
    assert entry["default"] == "true", "面板默认值与 ambient_loop_enabled() 的默认必须一致"


def test_startup_no_longer_claims_default_off():
    """启动日志不能再说"未启用(=1 开启)"——那是默认关时代的话术。"""
    src = (REPO / "core" / "startup.py").read_text(encoding="utf-8")
    assert "GALAXY_AMBIENT_LOOP=1 开启" not in src, "启动提示仍停留在'默认关'的措辞"


# ── 2. ambient 是系统自己的通道,不是"未知来源" ─────────────────────────


def test_ambient_is_a_known_request_source():
    """常驻循环 DELEGATE 走的就是 source='ambient'。

    它此前不在已知来源表里,每次自发行动都会打一条 "unknown source" 警告。
    循环默认开启后,这会变成每次自主行动都刷一条的噪音。
    """
    from core.desktop_presence_runtime import DesktopPresenceRuntime

    src = inspect.getsource(DesktopPresenceRuntime._dispatch)
    known_block = src.split("if source in (")[1].split(")")[0]
    assert '"ambient"' in known_block, "ambient 必须是已知来源,不能靠 unknown 兜底分支"


# ── 3. 端到端接缝:DELEGATE → handle_request → OpenClawd.process ────────


def test_delegate_reaches_openclawd_through_real_runtime():
    """只 mock 主体核心本身,中间整条链走真代码。

    这一条锁的是"自发决策真的能驱动主体去干活",而不是停在 handle_request 门口。
    """
    from core.desktop_presence_runtime import get_desktop_presence_runtime
    from core.openclawd import get_openclawd

    runtime = get_desktop_presence_runtime()
    openclawd = get_openclawd()
    seen: dict = {}

    async def spy_process(message, **kwargs):
        seen["message"] = message
        seen["entry_mode"] = kwargs.get("entry_mode")
        return {"success": True, "response": "ok", "execution_path": "local"}

    with patch.object(type(openclawd), "process", side_effect=spy_process, autospec=False):
        result = asyncio.run(
            runtime.handle_request(
                message="查一下最近的错误日志",
                source="ambient",
                session_id="test-ambient-session",
                user_id="ambient",
                entry_mode="local",
            )
        )

    assert result.get("success") is True
    assert seen.get("message") == "查一下最近的错误日志", "自发任务必须原样送达主体核心"
    assert seen.get("entry_mode") == "local"


def test_ambient_delegate_passes_frame_as_multimodal_context():
    """委托要带上"它当时看到的画面",否则主体是瞎着去执行的。"""
    src = (REPO / "core" / "ambient_attention_loop.py").read_text(encoding="utf-8")
    delegate_src = src.split("async def _delegate(")[1].split("\n    def ")[0]
    assert "multimodal_context=mm_context" in delegate_src
    assert 'source="ambient"' in delegate_src
