"""core/desktop_automation.py — 这台电脑的桌面自动化:**一个整体**,按现场挑方式
==========================================================================

所有者定:系统里不管是 System API、UIA、GUI 坐标,还是微软 UFO 的桌面自动化,都是「桌面自动化」,
整合成一个整体,交给 Computer Use;而且**按实际的现场情况,哪一个更合适用哪一个**。本模块就是这个整体:
有哪几级、每一级有哪几个后端、这一步该按什么顺序试、在这台机器上谁能用、用不了是为什么。

四级、六个后端
--------------
1. **系统接口**(``system_api``):``win32`` —— 启动 / 聚焦 / 关窗口、剪贴板、文件、进程。「打开记事本」一个调用就够,
   不该被规划成点坐标。
2. **控件**(``uia``):按控件身份操作(名字 / automation_id),不经过鼠标,窗口挪了也点得准。
   ``windows_uia``(本仓,comtypes)与 ``microsoft_ufo``(微软 UFO 的 ``ControlReceiver``,经 pywinauto)。
3. **坐标**(``gui``):按屏幕坐标模拟键鼠。``pyautogui``(本进程 ``core.device_control_service``)与
   ``desktop_node``(桌面操作节点 ``Node_36_UIAWindows``)。
4. **视觉**(``vlm``):截屏 → 视觉模型 → 一步一步做,即 Computer Use 闭环本身(``core.computer_use_loop``)。

按现场挑
--------
顺序不是写死的,由三样**确定的事实**决定(不从文字里猜):

* **这一步带了什么信息**(:func:`backend_can`):系统接口只接它认得的动作;微软 UFO 只接带控件身份的点击与输入;
  ``find_and_click`` 没给名字 / automation_id 就不派给控件级 …… 明知做不成的后端不去空试,跳过的原因写进结果。
* **前台程序上的战绩**(:class:`TrackRecord`):按「程序 × 后端」记成功次数、失败次数、平均耗时,落在数据目录
  ``desktop_backend_record.json``。同一个程序上一直失败的后端(至少试过 3 次、成功率不到三分之一)往后排 ——
  游戏、画布类程序、一些 Electron 应用读不出控件树,控件级每次都白试;同一级里成功率高、耗时短的排前。
* **现场探一下**(:func:`foreground_app`):前台是哪个程序(Win32 取前台窗口的进程名)。战绩按它分开记。

只换顺序,不去掉兜底:前面的都不行,照样往下走;视觉级永远最后。没有战绩时(刚装好)就是上面的默认顺序。
每一步的结果里写明这一步按什么顺序试的、谁做成的、之前谁没成、为什么(``backend`` / ``tried`` / ``selection``)。

执行入口只有一个
----------------
``core.windows_execution_arbiter.get_windows_arbiter().execute(...)`` —— 仲裁器按级降级,每一级的执行器由本模块组装
(:func:`level_executor`),跨级的顺序由 :func:`arrange_levels` 定。用它的:Computer Use 闭环的每一步、
``/api/v1/ui/act``、混合执行器、``DeviceAgentManager`` 的 Windows 设备、``core.microsoft_ufo_integration`` 的旧接口。
Computer Use 是这一整体的「脑子」:它看屏幕、决定下一步;每一步落到键鼠都经这条链。

刻意不在其中的
--------------
* 微软 UFO 的 ``AppAgent`` / ``HostAgent``:那是 UFO 自己的一套「脑子」(自己的提示词与模型调用)。这里只取 UFO 的
  **手**(控件操作),决定下一步的只有 Computer Use 一个 —— 两个脑子抢同一套键鼠,现场分不清是谁点的。
* ``nodes/Node_36_UIAWindows/ufo_deep_integration.py`` 的 ``launch_app`` / ``close_app``:能执行任意程序,按
  ``scripts/check_wiring.py`` 的豁免理由保持不可达(启动程序走第 1 级)。
* ``external/microsoft_ufo/`` 那份源码**不完整**:``automator/`` 自己 ``import ufo.*`` 与 UFO 的 ``config.config_loader``,
  这两样都不在仓库里,它本身跑不起来。UFO 后端认的是**装好的**微软 UFO(能 ``import ufo``,即把 microsoft/UFO 的
  代码放进 PYTHONPATH)。没装就照实说没装。

远端的 Windows 不归这里:隔着网络替对方决定点哪儿,手里那张界面图已经过时了。远端走 ``agent_deploy`` +
``agent_execute``,由对端用它自己的这条链执行(见 ``core.routes.ui_act.targets_this_machine``)。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("Galaxy.DesktopAutomation")

LEVEL_SYSTEM_API = "system_api"
LEVEL_UIA = "uia"
LEVEL_GUI = "gui"
LEVEL_VLM = "vlm"

#: 默认(没有战绩时)的级序 —— 精度从高到低。
LEVEL_ORDER: Tuple[str, ...] = (LEVEL_SYSTEM_API, LEVEL_UIA, LEVEL_GUI, LEVEL_VLM)

LEVEL_LABELS: Dict[str, str] = {
    LEVEL_SYSTEM_API: "系统接口",
    LEVEL_UIA: "控件",
    LEVEL_GUI: "坐标",
    LEVEL_VLM: "视觉",
}

#: 桌面操作节点(坐标级的第二个后端、也是 Computer Use 的缺省落手节点)。
DESKTOP_NODE = "Node_36_UIAWindows"

#: 规范动作 → ``Node_36_UIAWindows`` 的动作名。其它节点的别名在 ``core.routes.ui_act._ACTION_ALIAS``。
NODE_ACTIONS: Dict[str, str] = {
    "click": "click",
    "double_click": "double_click",
    "right_click": "right_click",
    "type": "type_text",
    "press_key": "press_key",
    "hotkey": "hotkey",
    "scroll": "scroll",
    "move": "move_mouse",
    "drag": "drag",
    "middle_click": "middle_click",
    "triple_click": "triple_click",
    "hold_key": "hold_key",
    "mouse_down": "mouse_down",
    "mouse_up": "mouse_up",
    # 节点那边这个动作早就有,只是名字不一样 —— 复用,不新开一个。
    "cursor_position": "get_mouse_position",
    "zoom": "zoom",
}

#: 战绩里「这个后端在这个程序上不行」的判据:至少试过这么多次、成功率低于这个比例。
DEMOTE_MIN_TRIES = 3
DEMOTE_BELOW_RATE = 1 / 3

Runner = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]


def _has_identity(params: Dict[str, Any]) -> bool:
    return bool(params.get("name") or params.get("automation_id"))


def _has_point(params: Dict[str, Any]) -> bool:
    return params.get("x") is not None and params.get("y") is not None


# ---------------------------------------------------------------------------
# 每个后端:接哪些动作(只看这一步带了什么,不试)
# ---------------------------------------------------------------------------


def _win32_actions() -> frozenset:
    try:
        from core.system_api.windows_system_api import SUPPORTED_ACTIONS

        return frozenset(SUPPORTED_ACTIONS)
    except Exception:  # noqa: BLE001
        return frozenset()


_UIA_ACTIONS = frozenset({"click", "type", "press_key", "press_keys", "find_and_click", "find_and_type", "scroll"})
_UFO_CLICKS = frozenset({"click", "find_and_click", "double_click"})
_UFO_TYPES = frozenset({"type", "find_and_type"})
_GUI_ACTIONS = frozenset(
    {
        "click",
        "double_click",
        "type",
        "type_text",
        "input",
        "input_text",
        "scroll",
        "press_key",
        "key",
        "screenshot",
        "open_app",
        "launch_app",
    }
)
_POINT_ACTIONS = frozenset({"click", "double_click", "right_click", "move"})


def backend_can(name: str, action: str, params: Dict[str, Any]) -> Optional[str]:
    """这个后端接不接这一步。接返回 ``None``;不接返回原因(人话,进结果)。"""
    act = (action or "").strip().lower()
    if name == "win32":
        return None if act in _win32_actions() else "系统接口不管这个动作"
    if name == "windows_uia":
        if act not in _UIA_ACTIONS:
            return "本仓 UIA 不管这个动作"
        if act.startswith("find_and_") and not _has_identity(params):
            return "没给控件名字或 automation_id"
        if act == "click" and not _has_point(params):
            return "没给坐标"
        return None
    if name == "microsoft_ufo":
        if act not in _UFO_CLICKS | _UFO_TYPES:
            return "微软 UFO 只接点击与输入"
        if not _has_identity(params):
            return "微软 UFO 要按控件身份(名字 / automation_id)操作"
        return None
    if name == "pyautogui":
        if act not in _GUI_ACTIONS:
            return "自动控制节点不管这个动作"
        if act in _POINT_ACTIONS and not _has_point(params):
            return "没给坐标"
        return None
    if name == "desktop_node":
        # 节点自己处理没给坐标的情况(在当前光标处),这里不替它判
        return None if act in NODE_ACTIONS else f"{DESKTOP_NODE} 不管这个动作"
    return None


# ---------------------------------------------------------------------------
# 现场:前台是哪个程序
# ---------------------------------------------------------------------------

_FG_CACHE: Dict[str, Any] = {"at": 0.0, "app": ""}
_FG_TTL_S = 1.0


def _win32_foreground_process() -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    import psutil

    return str(psutil.Process(pid.value).name() or "")


def foreground_app(*, probe: Optional[Callable[[], str]] = None) -> str:
    """前台程序的进程名(小写,如 ``notepad.exe``);拿不到返回空串。1 秒内复用上一次(一步动作里会问好几次)。"""
    now = time.monotonic()
    if probe is None and now - _FG_CACHE["at"] < _FG_TTL_S:
        return _FG_CACHE["app"]
    app = ""
    try:
        if probe is not None:
            app = probe() or ""
        elif sys.platform == "win32":
            app = _win32_foreground_process()
    except Exception as exc:  # noqa: BLE001 — 拿不到前台程序不影响执行,只是战绩记到「未知程序」上
        logger.debug("取前台程序失败: %s", exc)
    app = app.strip().lower()
    if probe is None:
        _FG_CACHE.update(at=now, app=app)
    return app


# ---------------------------------------------------------------------------
# 战绩:程序 × 后端
# ---------------------------------------------------------------------------


class TrackRecord:
    """按「前台程序 × 后端」记成功 / 失败 / 平均耗时。只记数,不存动作内容。

    落盘在数据目录(``GALAXY_DATA_DIR``)的 ``desktop_backend_record.json``;程序最多记 ``MAX_APPS`` 个(最久没用的先丢)。
    写盘最多每 ``SAVE_EVERY_S`` 秒一次、在工作线程里写,不卡事件循环。
    """

    MAX_APPS = 200
    SAVE_EVERY_S = 10.0

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self._last_save = 0.0

    def _file(self) -> str:
        if self._path:
            return self._path
        from core.data_paths import data_path

        return data_path("desktop_backend_record.json")

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                with open(self._file(), encoding="utf-8") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict):
                    self._data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
            except FileNotFoundError:
                pass
            except Exception as exc:  # noqa: BLE001 — 坏了就从头记,不影响执行
                logger.warning("桌面后端战绩读不出来,从头记: %s", exc)
            self._loaded = True

    def stats(self, app: str, backend: str) -> Tuple[int, int, float]:
        """(成功次数, 失败次数, 平均耗时毫秒)。"""
        self._ensure_loaded()
        with self._lock:
            row = (self._data.get(app) or {}).get("backends", {}).get(backend) or {}
            return int(row.get("ok", 0)), int(row.get("fail", 0)), float(row.get("ms", 0.0))

    def demoted(self, app: str, backend: str) -> bool:
        ok, fail, _ = self.stats(app, backend)
        tries = ok + fail
        return tries >= DEMOTE_MIN_TRIES and ok / tries < DEMOTE_BELOW_RATE

    def rate(self, app: str, backend: str) -> float:
        ok, fail, _ = self.stats(app, backend)
        return (ok + 1) / (ok + fail + 2)  # 拉普拉斯平滑:没试过的按一半算

    def record(self, app: str, backend: str, ok: bool, ms: float) -> None:
        self._ensure_loaded()
        with self._lock:
            entry = self._data.setdefault(app, {"backends": {}})
            entry["at"] = time.time()
            row = entry["backends"].setdefault(backend, {"ok": 0, "fail": 0, "ms": 0.0})
            n = row["ok"] + row["fail"]
            row["ms"] = round((row["ms"] * n + max(0.0, ms)) / (n + 1), 1)
            row["ok" if ok else "fail"] += 1
            if len(self._data) > self.MAX_APPS:
                for stale in sorted(self._data, key=lambda k: self._data[k].get("at", 0))[
                    : len(self._data) - self.MAX_APPS
                ]:
                    self._data.pop(stale, None)
            due = time.monotonic() - self._last_save >= self.SAVE_EVERY_S
            if due:
                self._last_save = time.monotonic()
                snapshot = json.loads(json.dumps(self._data))
        if due:
            self._save_soon(snapshot)

    def _save_soon(self, snapshot: Dict[str, Any]) -> None:
        def _write() -> None:
            try:
                from core.atomic_json import atomic_write_json

                atomic_write_json(self._file(), snapshot, indent=None)
            except Exception as exc:  # noqa: BLE001
                logger.debug("桌面后端战绩没写成: %s", exc)

        try:
            asyncio.get_running_loop().run_in_executor(None, _write)
        except RuntimeError:  # 不在事件循环里(脚本 / 测试):就地写
            _write()

    def summary(self, app: str) -> Dict[str, Dict[str, Any]]:
        self._ensure_loaded()
        with self._lock:
            rows = dict((self._data.get(app) or {}).get("backends", {}))
        return {k: dict(v) for k, v in rows.items()}


_RECORD: Optional[TrackRecord] = None


def track_record() -> TrackRecord:
    global _RECORD
    if _RECORD is None:
        _RECORD = TrackRecord()
    return _RECORD


def reset_track_record(record: Optional[TrackRecord] = None) -> None:
    """测试用:换一份战绩(或清掉单例)。"""
    global _RECORD
    _RECORD = record
    _FG_CACHE.update(at=0.0, app="")


# ---------------------------------------------------------------------------
# 后端:怎么建出执行器
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Backend:
    """一个后端:属于哪一级、叫什么、怎么建出它的执行器。

    ``make()`` 返回 ``(执行器, 用不了的原因)``:建得出来原因为空串;建不出来执行器为 ``None``、原因说清是哪一种。
    """

    name: str
    level: str
    label: str
    make: Callable[[], Tuple[Optional[Runner], str]]


def _make_win32() -> Tuple[Optional[Runner], str]:
    try:
        from core.system_api.windows_system_api import get_windows_system_api

        facade = get_windows_system_api()
    except Exception as exc:  # noqa: BLE001
        return None, f"系统接口模块载不进来: {type(exc).__name__}"
    if not facade.is_available:
        return None, "不是 Windows,或 Win32 接口不可用"

    async def run(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        resp = facade.dispatch(action, params, device_id=device_id)
        if not resp.handled:
            return {
                "success": False,
                "unsupported": True,
                "error": resp.fallback_reason or f"system_api: unsupported action '{action}'",
            }
        return {"success": resp.success, "error": resp.error or "", **resp.data}

    return run, ""


def _make_windows_uia() -> Tuple[Optional[Runner], str]:
    try:
        from windows_client.autonomy.autonomy_manager import WindowsAutonomyManager

        manager = WindowsAutonomyManager()
    except Exception as exc:  # noqa: BLE001
        return None, f"Windows UIA(comtypes)用不了: {type(exc).__name__}"

    async def run(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        try:
            result = manager.execute_action({"type": action, "params": params})
            return result if isinstance(result, dict) else {"success": bool(result)}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    return run, ""


def ufo_installed() -> str:
    """微软 UFO 装没装、能不能用;能用返回空串,不能用返回原因。只查找、不导入(导入要读它的配置,很重)。"""
    for module, why in (
        ("ufo", "没装微软 UFO:把 microsoft/UFO 的代码放进 PYTHONPATH(能 import ufo)即启用"),
        ("pywinauto", "没装 pywinauto(微软 UFO 靠它操作控件,只有 Windows 上有)"),
    ):
        try:
            if importlib.util.find_spec(module) is None:
                return why
        except (ImportError, ValueError):
            return why
    return ""


def _ufo_selector(params: Dict[str, Any]) -> Dict[str, str]:
    crit: Dict[str, str] = {}
    if params.get("name"):
        crit["title"] = str(params["name"])
    if params.get("automation_id"):
        crit["auto_id"] = str(params["automation_id"])
    if params.get("control_type"):
        crit["control_type"] = str(params["control_type"])
    return crit


def ufo_do(action: str, params: Dict[str, Any], *, receiver_cls: Any = None, desktop: Any = None) -> Dict[str, Any]:
    """用微软 UFO 的 ``ControlReceiver`` 按控件身份做一个动作(同步;调用方放到线程里跑)。

    ``receiver_cls`` / ``desktop`` 可注入(测试不需要 Windows 也不需要 UFO)。
    """
    why = backend_can("microsoft_ufo", action, params)
    if why:
        return {"success": False, "unsupported": True, "error": why}
    act = action.strip().lower()
    try:
        if receiver_cls is None:
            from ufo.automator.ui_control.controller import ControlReceiver as receiver_cls  # noqa: N813
        if desktop is None:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
    except Exception as exc:  # noqa: BLE001 — 装了但载不起来(缺 UFO 的配置等)要说出来
        return {"success": False, "error": f"微软 UFO 载不起来: {type(exc).__name__}: {exc}"}
    try:
        title = params.get("window") or params.get("window_title")
        window = desktop.window(title=str(title)) if title else desktop.window(active_only=True)
        control = window.child_window(**_ufo_selector(params)).wrapper_object()
        receiver = receiver_cls(control, window.wrapper_object())
        if act in _UFO_CLICKS:
            out = receiver.click_input({"button": params.get("button", "left"), "double": act == "double_click"})
        else:
            out = receiver.set_edit_text({"text": str(params.get("text", "")), "clear_current_text": True})
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"微软 UFO 没做成: {type(exc).__name__}: {exc}"}
    # set_edit_text 出错时不抛,回一句「An error occurred: …」—— 照它的约定认出来
    if isinstance(out, str) and out.startswith("An error occurred"):
        return {"success": False, "error": out}
    return {"success": True, "detail": str(out)[:200]}


def _make_microsoft_ufo() -> Tuple[Optional[Runner], str]:
    why = ufo_installed()
    if why:
        return None, why

    async def run(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        # pywinauto 找控件是同步的、可能几百毫秒:不放在事件循环里
        return await asyncio.to_thread(ufo_do, action, params)

    return run, ""


def _make_pyautogui() -> Tuple[Optional[Runner], str]:
    try:
        from core.device_control_service import device_control
    except Exception as exc:  # noqa: BLE001
        return None, f"设备控制服务载不进来: {type(exc).__name__}"

    async def run(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        # 这条路是 HTTP 打自动控制节点(Node_92,它那边跑 pyautogui),只认在设备控制服务里登记过的设备。
        # 没登记 = 这条路在这儿用不上:照实说「不接」,不记成它的失败(仲裁器建好之后设备才登记也照样能用)。
        if device_control.get_device(device_id) is None:
            return {
                "success": False,
                "unsupported": True,
                "error": f"设备控制服务里没有登记 {device_id},自动控制节点那条路用不上",
            }
        try:
            result = await device_control.execute_action(device_id=device_id, action=action, params=params)
            return result if isinstance(result, dict) else {"success": bool(result)}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    return run, ""


def _make_desktop_node() -> Tuple[Optional[Runner], str]:
    if sys.platform != "win32":  # 节点自己就这么回:「This node only works on Windows」
        return None, f"桌面操作节点 {DESKTOP_NODE} 只在 Windows 上能动手(这台是 {sys.platform})"
    try:
        from core.node_invocation import InvocationSource, invoke_node
    except Exception as exc:  # noqa: BLE001
        return None, f"节点调用模块载不进来: {type(exc).__name__}"

    async def run(action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        result = await invoke_node(
            DESKTOP_NODE, NODE_ACTIONS.get(action, action), params, invocation_source=InvocationSource.UNKNOWN
        )
        return {"success": bool(getattr(result, "success", False)), "error": getattr(result, "error", "") or ""}

    return run, ""


BACKENDS: Tuple[Backend, ...] = (
    Backend("win32", LEVEL_SYSTEM_API, "Win32 系统接口", _make_win32),
    Backend("windows_uia", LEVEL_UIA, "Windows UIA(本仓)", _make_windows_uia),
    Backend("microsoft_ufo", LEVEL_UIA, "微软 UFO", _make_microsoft_ufo),
    Backend("pyautogui", LEVEL_GUI, "自动控制节点 Node_92(pyautogui)", _make_pyautogui),
    Backend("desktop_node", LEVEL_GUI, f"桌面操作节点 {DESKTOP_NODE}", _make_desktop_node),
)


# ---------------------------------------------------------------------------
# 一级的执行器:可用的后端按现场排序,第一个成功的为准
# ---------------------------------------------------------------------------


class LevelRunner:
    """一级的执行器。仲裁器按 ``(action, params, device_id)`` 调它;它按现场给本级的后端排序、逐个试、记战绩。

    还回答两个问题(仲裁器排级序时用):这一步本级**有没有人接**(:meth:`can`)、本级在当前程序上**是不是全军覆没**
    (:meth:`demoted_here`)。
    """

    def __init__(self, level: str, runners: Sequence[Tuple[str, Runner]], record: Optional[TrackRecord] = None):
        self.level = level
        self._runners = list(runners)
        self._record = record

    @property
    def backends(self) -> List[str]:
        return [name for name, _ in self._runners]

    def _rec(self) -> TrackRecord:
        return self._record or track_record()

    def can(self, action: str, params: Dict[str, Any]) -> Optional[str]:
        """本级有没有后端接这一步;都不接返回原因。"""
        whys = [f"{n}:{w}" for n, _ in self._runners if (w := backend_can(n, action, params))]
        return None if len(whys) < len(self._runners) else ";".join(whys)

    def demoted_here(self, app: str, action: str, params: Dict[str, Any]) -> bool:
        names = [n for n, _ in self._runners if backend_can(n, action, params) is None]
        return bool(names) and all(self._rec().demoted(app, n) for n in names)

    def order(
        self, app: str, action: str, params: Dict[str, Any]
    ) -> Tuple[List[Tuple[str, Runner]], List[Dict[str, str]]]:
        """(按现场排好的后端, 跳过的后端与原因)。不在战绩里垫底的排前,同档里成功率高、耗时短的排前,再同就按登记顺序。"""
        rec = self._rec()
        keep: List[Tuple[Tuple[int, float, float, int], str, Runner]] = []
        skipped: List[Dict[str, str]] = []
        for idx, (name, runner) in enumerate(self._runners):
            why = backend_can(name, action, params)
            if why:
                skipped.append({"backend": name, "why": why})
                continue
            _, _, ms = rec.stats(app, name)
            keep.append(((1 if rec.demoted(app, name) else 0, -rec.rate(app, name), ms, idx), name, runner))
        keep.sort(key=lambda t: t[0])
        return [(n, r) for _, n, r in keep], skipped

    async def __call__(self, action: str, params: Dict[str, Any], device_id: str) -> Dict[str, Any]:
        app = foreground_app()
        ordered, skipped = self.order(app, action, params)
        if not ordered:
            return {
                "success": False,
                "unsupported": True,
                "error": "本级没有后端接这一步",
                "selection": {"app": app, "skipped": skipped},
            }
        rec = self._rec()
        tried: List[Dict[str, str]] = []
        last: Dict[str, Any] = {}
        for name, runner in ordered:
            started = time.monotonic()
            try:
                last = await runner(action, params, device_id)
            except Exception as exc:  # noqa: BLE001 — 一个后端炸了,下一个照样试
                last = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            ok = bool(last.get("success") or last.get("status") == "success")
            if not last.get("unsupported"):  # 后端自己说不接的不算它失败
                rec.record(app, name, ok, (time.monotonic() - started) * 1000)
            if ok:
                return {
                    **last,
                    "backend": name,
                    "selection": {"app": app, "order": [n for n, _ in ordered], "skipped": skipped},
                    **({"tried": tried} if tried else {}),
                }
            tried.append({"backend": name, "error": str(last.get("error") or "没做成")})
        return {
            **last,
            "success": False,
            "backend": ordered[-1][0],
            "tried": tried,
            "selection": {"app": app, "order": [n for n, _ in ordered], "skipped": skipped},
        }


def level_executor(
    level: str, *, backends: Tuple[Backend, ...] = BACKENDS, record: Optional[TrackRecord] = None
) -> Optional[LevelRunner]:
    """组装一级的执行器;这一级一个后端都建不出来就返回 ``None``(仲裁器把这一级记成「跳过」,``uia_available`` 据此照实回答)。"""
    runners: List[Tuple[str, Runner]] = []
    for b in backends:
        if b.level != level:
            continue
        runner, why = b.make()
        if runner is None:
            logger.debug("桌面自动化 | %s/%s 不可用: %s", level, b.name, why)
            continue
        runners.append((b.name, runner))
    return LevelRunner(level, runners, record) if runners else None


def arrange_levels(
    levels: Sequence[str], executors: Dict[str, Any], action: str, params: Dict[str, Any], *, app: Optional[str] = None
) -> Tuple[List[str], List[Dict[str, str]]]:
    """按现场排级序:(排好的级, 跳过的级与原因)。

    * 本级是本模块组装的执行器、且这一步本级没人接 → 跳过(原因写清);
    * 本级能接、但在当前前台程序上全军覆没 → 挪到后面(视觉级之前);
    * 别人注入的执行器(测试、特殊部署)不认得它的能力 → 原样保留,不替它判断;
    * 视觉级永远最后。
    """
    app = foreground_app() if app is None else app
    front: List[str] = []
    back: List[str] = []
    tail: List[str] = []
    skipped: List[Dict[str, str]] = []
    for level in levels:
        ex = executors.get(level)
        if level == LEVEL_VLM:
            tail.append(level)
            continue
        if isinstance(ex, LevelRunner):
            why = ex.can(action, params)
            if why:
                skipped.append({"level": level, "why": why})
                continue
            if ex.demoted_here(app, action, params):
                back.append(level)
                continue
        front.append(level)
    return front + back + tail, skipped


def describe(*, backends: Tuple[Backend, ...] = BACKENDS, app: Optional[str] = None) -> Dict[str, Any]:
    """这台机器上桌面自动化的现状:每一级、每个后端能不能用(不能用是为什么),以及当前前台程序上的战绩。

    给状态接口与启动横幅用。视觉级就是 Computer Use 闭环,开关与感知新鲜度由它自己的状态接口说。
    """
    app = foreground_app() if app is None else app
    record = track_record()
    levels: List[Dict[str, Any]] = []
    for level in (LEVEL_SYSTEM_API, LEVEL_UIA, LEVEL_GUI):
        rows = []
        for b in backends:
            if b.level != level:
                continue
            runner, why = b.make()
            if runner is not None and b.name in _REMOTE_ONLY:
                # 「能用」只是这条路接得上：动不动得了手看那台设备 —— 别让它读成「这台本机装了 pyautogui」
                why = "按设备：只对在设备控制服务里登记过的设备走得通（键鼠在那台的自动控制节点 Node_92 上）"
            ok, fail, ms = record.stats(app, b.name)
            rows.append(
                {
                    "name": b.name,
                    "label": b.label,
                    "available": runner is not None,
                    "reason": why,
                    "here": {"ok": ok, "fail": fail, "avg_ms": ms, "demoted": record.demoted(app, b.name)},
                }
            )
        levels.append(
            {
                "level": level,
                "label": LEVEL_LABELS[level],
                "available": any(r["available"] for r in rows),
                "backends": rows,
            }
        )
    try:
        from core.computer_use_loop import computer_use_enabled

        vlm_on = bool(computer_use_enabled())
    except Exception:  # noqa: BLE001
        vlm_on = False
    levels.append(
        {
            "level": LEVEL_VLM,
            "label": LEVEL_LABELS[LEVEL_VLM],
            "available": vlm_on,
            "backends": [
                {
                    "name": "computer_use",
                    "label": "Computer Use 闭环",
                    "available": vlm_on,
                    "reason": "" if vlm_on else "GALAXY_COMPUTER_USE 关着",
                }
            ],
        }
    )
    return {"entry": "core.windows_execution_arbiter", "foreground_app": app, "levels": levels}


#: 只经自动控制节点给「在设备控制服务里登记过的设备」动手的后端 —— 它能不能碰到**这台电脑**,要看这台登记了没有,
#: 启动时说不准,所以不拿它算「这台电脑的桌面能不能动手」
_REMOTE_ONLY = ("pyautogui",)

SUMMARY_READY = "running"
SUMMARY_NONE = "partial"
SUMMARY_NO_DESKTOP = "info"


def summary_line(*, backends: Tuple[Backend, ...] = BACKENDS, platform: Optional[str] = None) -> Tuple[str, str]:
    """启动横幅那一行:(状态, 一句话)。

    * ``running`` —— 这台电脑的桌面至少有一条路能直接动手(系统接口 / 控件 / 桌面操作节点);
    * ``partial`` —— 是 Windows,但这几条都用不上(要看原因、补依赖);
    * ``info`` —— 这台不是 Windows 桌面(Linux 服务器、容器):本来就没有能操作的桌面,不算降级。
    """
    parts: List[str] = []
    here = False
    for level in (LEVEL_SYSTEM_API, LEVEL_UIA, LEVEL_GUI):
        names = []
        for b in backends:
            if b.level == level and b.make()[0] is not None:
                names.append(b.label)
                here = here or b.name not in _REMOTE_ONLY
        parts.append(f"{LEVEL_LABELS[level]}:{'、'.join(names) if names else '无'}")
    line = ";".join(parts)
    if here:
        return SUMMARY_READY, line
    if (platform or sys.platform) != "win32":
        return SUMMARY_NO_DESKTOP, f"这台不是 Windows 桌面,没有能直接操作的桌面({line})"
    return SUMMARY_NONE, line


__all__ = [
    "BACKENDS",
    "SUMMARY_NO_DESKTOP",
    "SUMMARY_NONE",
    "SUMMARY_READY",
    "DESKTOP_NODE",
    "LEVEL_GUI",
    "LEVEL_LABELS",
    "LEVEL_ORDER",
    "LEVEL_SYSTEM_API",
    "LEVEL_UIA",
    "LEVEL_VLM",
    "NODE_ACTIONS",
    "Backend",
    "LevelRunner",
    "TrackRecord",
    "arrange_levels",
    "backend_can",
    "describe",
    "foreground_app",
    "level_executor",
    "reset_track_record",
    "summary_line",
    "track_record",
    "ufo_do",
    "ufo_installed",
]
