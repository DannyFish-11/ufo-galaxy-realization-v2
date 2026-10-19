"""桌面自动化是**一个整体**,并且按现场挑方式(所有者定)。

System API、UIA、GUI 坐标、微软 UFO 都是桌面自动化:一张登记表(``core.desktop_automation``)、一个执行入口
(Windows 执行仲裁器)、交给 Computer Use。顺序由三样确定的事实定:这一步带了什么信息、前台程序上各后端的战绩、
现场前台是谁。只换顺序,不去兜底;每一步的结果里写明为什么这么试、谁做成的、之前谁没成。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core import desktop_automation as da

REPO = Path(__file__).resolve().parent.parent


def _runner(name: str, calls: List[str], ok: bool = True, unsupported: bool = False):
    async def run(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        calls.append(name)
        if unsupported:
            return {"success": False, "unsupported": True, "error": f"{name} 不接"}
        return {"success": ok, "error": "" if ok else f"{name} 没做成"}

    return run


@pytest.fixture()
def record(tmp_path):
    rec = da.TrackRecord(path=str(tmp_path / "rec.json"))
    da.reset_track_record(rec)
    yield rec
    da.reset_track_record(None)


@pytest.fixture(autouse=True)
def _no_foreground(monkeypatch):
    monkeypatch.setattr(da, "foreground_app", lambda **kw: "notepad.exe")


# ── 1. 这一步带了什么:明知做不成的不去空试 ─────────────────────────────


def test_what_the_step_carries_decides_who_is_even_asked():
    assert da.backend_can("win32", "launch_app", {}) is None
    assert da.backend_can("win32", "click", {"x": 1, "y": 2})
    assert da.backend_can("microsoft_ufo", "click", {"x": 1, "y": 2}), "UFO 只接按控件身份的"
    assert da.backend_can("microsoft_ufo", "find_and_click", {"name": "确定"}) is None
    assert da.backend_can("windows_uia", "find_and_click", {}), "没给名字 / automation_id 就不派给控件级"
    assert da.backend_can("pyautogui", "click", {}), "没给坐标别点 (0,0)"
    assert da.backend_can("desktop_node", "cursor_position", {}) is None


def test_a_level_nobody_can_take_is_skipped_with_the_reason(record):
    calls: List[str] = []
    uia = da.LevelRunner(da.LEVEL_UIA, [("windows_uia", _runner("windows_uia", calls))], record)
    gui = da.LevelRunner(da.LEVEL_GUI, [("pyautogui", _runner("pyautogui", calls))], record)
    order, skipped = da.arrange_levels(
        ["system_api", "uia", "gui", "vlm"],
        {"system_api": None, "uia": uia, "gui": gui, "vlm": object()},
        "click",
        {"x": 5, "y": 6},
        app="notepad.exe",
    )
    assert order == ["system_api", "uia", "gui", "vlm"], "别人注入 / 没有的执行器不替它判断;能接的保持精度顺序"
    order, skipped = da.arrange_levels(
        ["uia", "gui", "vlm"], {"uia": uia, "gui": gui, "vlm": object()}, "find_and_click", {}, app=""
    )
    assert order == ["vlm"], "没给控件名字的找控件,控件级、坐标级都接不了,只剩视觉"
    reasons = {sk["level"]: sk["why"] for sk in skipped}
    assert "名字" in reasons["uia"] and "不管这个动作" in reasons["gui"]


# ── 2. 前台程序上的战绩:一直失败的往后排 ──────────────────────────────


def test_a_backend_that_keeps_failing_on_this_app_moves_back(record):
    for _ in range(3):
        record.record("notepad.exe", "windows_uia", False, 40)
    record.record("notepad.exe", "microsoft_ufo", True, 30)
    calls: List[str] = []
    level = da.LevelRunner(
        da.LEVEL_UIA,
        [("windows_uia", _runner("windows_uia", calls)), ("microsoft_ufo", _runner("microsoft_ufo", calls))],
        record,
    )
    out = asyncio.run(level("find_and_click", {"name": "确定"}, "local"))
    assert calls == ["microsoft_ufo"], "在这个程序上一直失败的本仓 UIA 应排到 UFO 后面"
    assert out["backend"] == "microsoft_ufo" and out["selection"]["order"] == ["microsoft_ufo", "windows_uia"]
    assert out["selection"]["app"] == "notepad.exe"


def test_a_whole_level_that_fails_on_this_app_moves_behind_the_others_but_vision_stays_last(record):
    for _ in range(4):
        record.record("game.exe", "windows_uia", False, 10)
    uia = da.LevelRunner(da.LEVEL_UIA, [("windows_uia", _runner("windows_uia", []))], record)
    gui = da.LevelRunner(da.LEVEL_GUI, [("pyautogui", _runner("pyautogui", []))], record)
    order, _ = da.arrange_levels(
        ["uia", "gui", "vlm"], {"uia": uia, "gui": gui, "vlm": object()}, "click", {"x": 1, "y": 1}, app="game.exe"
    )
    assert order == ["gui", "uia", "vlm"], "只换顺序不去兜底:控件级挪后,仍在;视觉永远最后"


def test_no_record_means_the_default_precision_order(record):
    calls: List[str] = []
    level = da.LevelRunner(
        da.LEVEL_GUI,
        [("pyautogui", _runner("pyautogui", calls, ok=False)), ("desktop_node", _runner("desktop_node", calls))],
        record,
    )
    out = asyncio.run(level("click", {"x": 1, "y": 1}, "local"))
    assert calls == ["pyautogui", "desktop_node"]
    assert out["backend"] == "desktop_node" and out["tried"][0]["backend"] == "pyautogui"


def test_saying_it_does_not_take_the_step_is_not_counted_as_failing(record):
    level = da.LevelRunner(da.LEVEL_UIA, [("windows_uia", _runner("windows_uia", [], unsupported=True))], record)
    asyncio.run(level("find_and_click", {"name": "x"}, "local"))
    assert record.stats("notepad.exe", "windows_uia") == (0, 0, 0.0)


def test_the_record_lives_in_the_data_dir_and_comes_back(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    rec = da.TrackRecord()
    rec.record("excel.exe", "microsoft_ufo", True, 120)
    saved = json.loads((tmp_path / "desktop_backend_record.json").read_text(encoding="utf-8"))
    assert saved["excel.exe"]["backends"]["microsoft_ufo"]["ok"] == 1
    again = da.TrackRecord()
    assert again.stats("excel.exe", "microsoft_ufo")[0] == 1


# ── 3. 微软 UFO:只取它的「手」,装没装照实说 ──────────────────────────


class _Ctl:
    def wrapper_object(self):
        return self


class _Win:
    def __init__(self, seen):
        self.seen = seen

    def child_window(self, **crit):
        self.seen["crit"] = crit
        return _Ctl()

    def wrapper_object(self):
        return self


class _Desk:
    def __init__(self, seen):
        self.seen = seen

    def window(self, **kw):
        self.seen["window"] = kw
        return _Win(self.seen)


def test_ufo_clicks_and_types_by_control_identity():
    seen: Dict[str, Any] = {}

    class _Recv:
        def __init__(self, control, app):
            seen["recv"] = True

        def click_input(self, params):
            seen["click"] = params
            return "Click action has been executed"

        def set_edit_text(self, params):
            seen["text"] = params
            return "ok"

    out = da.ufo_do("find_and_click", {"name": "确定"}, receiver_cls=_Recv, desktop=_Desk(seen))
    assert out["success"] and seen["crit"] == {"title": "确定"} and seen["window"] == {"active_only": True}
    assert seen["click"] == {"button": "left", "double": False}

    out = da.ufo_do(
        "find_and_type",
        {"automation_id": "q", "text": "你好", "window": "记事本"},
        receiver_cls=_Recv,
        desktop=_Desk(seen),
    )
    assert out["success"] and seen["text"]["text"] == "你好" and seen["window"] == {"title": "记事本"}


def test_ufo_error_strings_are_failures_not_success():
    class _Recv:
        def __init__(self, *a):
            pass

        def set_edit_text(self, params):
            return "An error occurred: control not editable"

    out = da.ufo_do("find_and_type", {"name": "x", "text": "y"}, receiver_cls=_Recv, desktop=_Desk({}))
    assert out["success"] is False and "An error occurred" in out["error"]


def test_ufo_says_plainly_when_it_is_not_installed(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "ufo" else real(name, *a))
    why = da.ufo_installed()
    assert "PYTHONPATH" in why and "微软 UFO" in why


def test_the_incomplete_vendored_copy_is_not_put_on_sys_path():
    """``external/microsoft_ufo`` 自己 import ufo.* 与 UFO 的 config,不完整;往 sys.path 里塞它只会让同名顶层包
    (``transport`` / ``protocol`` / ``agents`` ……)被它抢走。core 里不许再这么做。"""
    import re

    literal = re.compile(r"[\"']microsoft_ufo[\"']")
    offenders = []
    for path in (REPO / "core").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if literal.search(text) and "sys.path.insert" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], offenders


# ── 4. 一个入口:仲裁器、旧入口都经它 ─────────────────────────────────


def test_the_arbiter_skips_a_level_with_the_reason_and_structural_only_never_starts_vision(record):
    from core.windows_execution_arbiter import WindowsExecutionArbiter, WinExecStatus

    vlm_calls: List[str] = []

    async def _vlm(device_id, instruction, shot):
        vlm_calls.append(instruction)
        return {"success": True}

    gui_calls: List[str] = []
    arb = WindowsExecutionArbiter(
        uia_executor=da.LevelRunner(da.LEVEL_UIA, [("windows_uia", _runner("windows_uia", []))], record),
        gui_executor=da.LevelRunner(da.LEVEL_GUI, [("pyautogui", _runner("pyautogui", gui_calls, ok=False))], record),
        vlm_executor=_vlm,
        use_defaults=False,
    )
    res = asyncio.run(arb.execute(action="find_and_click", params={}, device_id="local", structural_only=True))
    assert res.success is False and vlm_calls == [], "structural_only 不起视觉闭环"
    skipped = [a for a in res.attempts if a["status"] == WinExecStatus.SKIPPED.value and a["level"] == "uia"]
    assert skipped and "名字" in skipped[0]["error"]


def test_the_windows_agent_only_acts_on_this_machine(monkeypatch):
    from core.device_agent_manager import DeviceInfo, DeviceType, WindowsDeviceAgent

    hits: List[str] = []

    class _Arb:
        async def execute(self, **kw):
            hits.append(kw["action"])
            assert kw["structural_only"] is True

            class _R:
                success = True
                result = {"backend": "pyautogui"}

                class final_level:
                    value = "gui"

            return _R()

    monkeypatch.setattr("core.windows_execution_arbiter.get_windows_arbiter", lambda: _Arb())
    far = WindowsDeviceAgent(
        DeviceInfo(device_id="office-pc", device_type=DeviceType.WINDOWS, device_name="办公室电脑")
    )
    asyncio.run(far.connect())
    out = asyncio.run(far.execute_command("click", {"x": 1, "y": 1}))
    assert out["success"] is False and "不是本机" in out["error"] and hits == []

    here = WindowsDeviceAgent(
        DeviceInfo(device_id="pc", device_type=DeviceType.WINDOWS, device_name="这台", metadata={"host": "localhost"})
    )
    asyncio.run(here.connect())
    out = asyncio.run(here.execute_command("click", {"x": 1, "y": 1}))
    assert out == {"success": True, "method": "gui/pyautogui"} and hits == ["click"]


def test_a_natural_language_task_from_the_old_entrance_goes_to_computer_use(monkeypatch):
    from core import computer_use_loop
    from core.microsoft_ufo_integration import GalaxyIntegrationService

    seen: List[str] = []

    async def _run(instruction, **kw):
        seen.append(instruction)
        return {"success": True, "stop_reason": "done", "steps": []}

    monkeypatch.setattr(computer_use_loop, "run_computer_use_task", _run)
    monkeypatch.setattr(computer_use_loop, "computer_use_enabled", lambda: True)
    out = asyncio.run(GalaxyIntegrationService().execute_task("把标题改成周报", app_name="WINWORD.EXE"))
    assert seen == ["在 WINWORD.EXE 里:把标题改成周报"] and out["success"] is True


def test_the_status_says_what_each_level_has_here(auth_headers):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes import computer_use

    app = FastAPI()
    app.include_router(computer_use.router)
    body = TestClient(app).get("/api/v1/computer-use/status", headers=auth_headers).json()
    levels = {lv["level"]: lv for lv in body["desktop"]["levels"]}
    assert list(levels) == ["system_api", "uia", "gui", "vlm"]
    ufo = [b for b in levels["uia"]["backends"] if b["name"] == "microsoft_ufo"][0]
    assert ufo["available"] or ufo["reason"], "用不了要说为什么"
    assert [b["name"] for b in levels["gui"]["backends"]] == ["pyautogui", "desktop_node"]


def test_the_node_92_path_says_not_here_for_a_device_it_does_not_know(monkeypatch):
    """坐标级那条 HTTP 打自动控制节点(Node_92)的路只认设备控制服务里登记过的设备:没登记就照实说「不接」,
    不记成它的失败(原先它标着「本进程键鼠」、看着随时可用,真点下去才回 Device not found 并被记一笔)。"""
    from core.device_control_service import device_control

    monkeypatch.setattr(device_control, "devices", {})
    runner, why = da._make_pyautogui()
    assert runner is not None and why == ""
    out = asyncio.run(runner("click", {"x": 1, "y": 2}, "local"))
    assert out["success"] is False and out["unsupported"] is True and "没有登记" in out["error"]


def _fake(name, level, ok):
    async def run(action, params, device_id):
        return {"success": True}

    return da.Backend(name, level, name, lambda: (run, "") if ok else (None, f"{name} 用不了"))


def test_the_banner_says_ready_only_when_this_desktop_can_be_operated():
    """启动横幅那一行说的是「这台电脑的桌面能不能动手」。只剩经自动控制节点给登记过的设备动手的那条路时,
    不算这台能动手:不是 Windows 桌面就照实说不适用(不算降级),是 Windows 却一条路都没有才算部分可用。"""
    remote_only = (_fake("win32", da.LEVEL_SYSTEM_API, False), _fake("pyautogui", da.LEVEL_GUI, True))
    state, line = da.summary_line(backends=remote_only, platform="linux")
    assert state == da.SUMMARY_NO_DESKTOP and "不是 Windows 桌面" in line
    state, _ = da.summary_line(backends=remote_only, platform="win32")
    assert state == da.SUMMARY_NONE
    here = (_fake("win32", da.LEVEL_SYSTEM_API, True), _fake("pyautogui", da.LEVEL_GUI, True))
    state, line = da.summary_line(backends=here, platform="linux")
    assert state == da.SUMMARY_READY and line.startswith("系统接口:win32")


def test_the_windows_only_desktop_node_says_so_off_windows(monkeypatch):
    monkeypatch.setattr(da.sys, "platform", "linux")
    runner, why = da._make_desktop_node()
    assert runner is None and "只在 Windows 上" in why


def test_the_core_services_banner_does_not_count_not_applicable_as_degraded():
    from launcher.core_services import CoreServiceLauncher

    summary, status, details = CoreServiceLauncher.banner(
        {"device_agent_manager": "running", "device_status_api": "running", "microsoft_ufo_integration": "info"}
    )
    assert (summary, status) == ("2/2 就绪", "ok")
    assert details[-1] == ("桌面自动化", "不适用(这台没有 Windows 桌面)", "info")
    summary, status, _ = CoreServiceLauncher.banner(
        {"device_agent_manager": "running", "device_status_api": "running", "microsoft_ufo_integration": "partial"}
    )
    assert (summary, status) == ("2/3 就绪 · 1 个部分可用", "warn")


def test_the_node_92_row_says_it_depends_on_the_device(tmp_path, monkeypatch):
    """第 6 轮真跑：状态接口把 Node_92 那条（名字叫 pyautogui）写成「能用」、原因空着，而启动日志同时说「pyautogui 没装」。

    这条路是 HTTP 打设备那头的自动控制节点，本机装没装 pyautogui 与它无关；能不能动手看那台设备登记了没有 —— 照这个说。
    """
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    rows = {r["name"]: r for lv in da.describe(app="notepad.exe")["levels"] for r in lv["backends"]}
    row = rows["pyautogui"]
    if row["available"]:
        assert "按设备" in row["reason"] and "Node_92" in row["reason"], row
