"""pyautogui 的三种状态必须分得开:没装 / 装了但没桌面 / 好了。

``_initialize_fallback`` 原本只 ``except ImportError``。而无头机器上
``import pyautogui`` 抛的是 ``KeyError: 'DISPLAY'``(它在 import 期就去连 X11)
—— 不是 ImportError,于是那个异常**穿透出降级路径**。而且更早的日志会把这种
情况说成"pyautogui 未安装",可它明明装着:说的和现实相反。
"""

import asyncio
import builtins
import logging

import pytest

from core.microsoft_ufo_integration import MicrosoftUFOAutomator


def _fallback(monkeypatch, raise_exc):
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "pyautogui" and raise_exc is not None:
            raise raise_exc
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    inst = MicrosoftUFOAutomator.__new__(MicrosoftUFOAutomator)
    inst.is_initialized = False
    return inst, asyncio.run(MicrosoftUFOAutomator._initialize_fallback(inst))


def test_not_installed_says_not_installed(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        inst, ok = _fallback(monkeypatch, ImportError("No module named 'pyautogui'"))
    assert ok is False and inst.is_initialized is False
    assert "没装" in caplog.text
    assert "pip install pyautogui" in caplog.text


def test_headless_does_not_escape_and_does_not_claim_it_is_missing(monkeypatch, caplog):
    """装了但没有 DISPLAY —— 既不许抛出去,也不许说成"没装"。"""
    with caplog.at_level(logging.WARNING):
        inst, ok = _fallback(monkeypatch, KeyError("DISPLAY"))
    assert ok is False and inst.is_initialized is False
    assert "装了但" in caplog.text
    assert "没装" not in caplog.text, "装着却说没装 —— 说的和现实相反"
    assert "没有桌面" in caplog.text


def test_any_other_startup_failure_is_also_contained(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        inst, ok = _fallback(monkeypatch, RuntimeError("Xlib says no"))
    assert ok is False
    assert "Xlib says no" in caplog.text
    # 不是无头,就别硬说是无头。
    assert "没有桌面" not in caplog.text


def test_when_it_works_it_marks_itself_initialised(monkeypatch):
    inst, ok = _fallback(monkeypatch, None)
    if ok:  # 本机真有 DISPLAY
        assert inst.is_initialized is True
    else:  # 本机无头 —— 上面那条已经守住了,这里只确认没有假装成功
        assert inst.is_initialized is False


class TestNode45DoesNotDieOnAHeadlessBox:
    """同一个坑的第二处:Node_45_DesktopAuto 的模块级 import 守卫。

    它原本也只 ``except ImportError``。装上 pyautogui 之后,无头机器上那句
    ``KeyError: 'DISPLAY'`` 会**穿透出模块级**,把整个节点的导入带崩 ——
    真跑实测:``python main.py --check-only`` 的节点导入从 125/125 掉到 124/125,
    报 ``Node_45_DesktopAuto  KeyError: 'DISPLAY'``。
    """

    def test_the_module_imports_even_without_a_display(self):
        import importlib

        mod = importlib.import_module("nodes.Node_45_DesktopAuto.main")
        # 能导入进来 —— 这一条就是此前红的那一条。
        assert mod is not None
        # 用不了的时候必须说得出**为什么**,而不是一个空的 None。
        if mod.pyautogui is None:
            assert mod.pyautogui_unavailable_reason, "用不了就得说清是没装还是起不来"

    def test_it_never_claims_not_installed_when_it_is_installed(self):
        import importlib

        mod = importlib.import_module("nodes.Node_45_DesktopAuto.main")
        reason = mod.pyautogui_unavailable_reason
        if not reason:
            return  # 本机能用,没什么可断言的
        try:
            import pyautogui  # noqa: F401

            installed = True
        except Exception:
            installed = False
        if installed:
            assert "没装" not in reason, f"装着却说没装:{reason}"
