"""core.stop_key — 它在动手时，人按 Esc 叫停

要解决什么
----------
表达期它可能正在动你的鼠标键盘，那恰恰是人最需要能叫停的时刻。面板上有停止键，
但面板多半是关着的；要一个**不用找**的停法：按 Esc。

为什么不在外壳（Electron / Tauri）里注册全局快捷键
------------------------------------------------
它自己动手时**也会按 Esc** —— ``core/computer_use_loop.py`` 规划器的动作表里就写着
``press_key: {"key": "<enter|tab|esc|...>"}``。外壳的全局快捷键（Windows 上是
``RegisterHotKey``）有两个毛病，碰上这件事都是硬伤：

* **分不清是谁按的**：注入的按键同样触发热键 —— 它按一下 Esc 关弹窗，把自己停了；
* **会把键吞掉**：热键占住的键到不了前台窗口 —— 它按的那一下 Esc 根本没送到。

所以这里用低层键盘监听（pynput，``suppress=False``，**不吞键**），只认**真人按下**
的那一下：pynput 1.8 起在 Windows（``LLKHF_INJECTED``）与 macOS（事件源进程号）上
给得出「这一下是不是注入的」。它在同一个进程里，状态直接进渲染契约
（``RenderPosture.stop_key``），两个外壳都不用改。

给不出这一位的地方就**不占**，岛上也就不写「Esc 停止」，停止走面板：

* Linux：X11 上 XTest 注入的键与真按的一模一样；Wayland 根本看不到全局按键；
* pynput 太旧（< 1.8）或不可用；macOS 没给「辅助功能」授权（收不到按键）；
* ``GALAXY_STOP_KEY=false``（有的安全软件会把键盘钩子当成键盘记录器，留一个关掉的口子）。

写着能停而按了没用，比不写更糟。

刻意的边界
----------
* **只在动手期间监听**：进 ``acting`` 时起、出 ``acting`` 时停。全局键盘钩子看得见
  所有按键；这里只看 Esc、只在它动手的那一段。常驻的话，每一下按键都要过一遍这个
  进程 —— GIL 忙的时候就是全系统的输入延迟，而且 Windows 会把超时的钩子摘掉。
* **人按 Esc 的那一下照样送到前台窗口**。不吞键是为了不吞它自己的键，代价是人的
  那一下也会到前台（多半是关掉一个弹窗），可以接受。
* **监听回调里什么都不做**，只把「停」投递回事件循环（见 ``acquire`` 的 ``on_press``）。
  低层钩子的回调拖久了会被系统摘掉。
* 计数而不是开关：两个请求同时在动手时，一个停手不能把另一个的叫停键也撤了。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any, Callable, Optional, Set

logger = logging.getLogger("Galaxy.StopKey")

__all__ = ["LABEL", "acquire", "release", "label", "availability"]

#: 渲染端照抄到岛上的那个键名。
LABEL = "Esc"

_lock = threading.Lock()
_holders = 0
# 每一段「有人占着」的编号。监听是在另一条线程里起的，起来的时候可能早已没人要了
# （动手只持续了几毫秒），也可能又开始了新的一段 —— 靠它认出自己是不是过期的那一个。
_generation = 0
_listener: Any = None
_armed = False
_on_press: Optional[Callable[[], None]] = None
# 不可用的原因每种只说一次：动手一次说一次的话，日志里全是它。
_reported: Set[str] = set()


def availability() -> str:
    """此刻能不能占叫停键。能 → ``""``；不能 → 原因（人读的一句话）。"""
    if (os.environ.get("GALAXY_STOP_KEY") or "").strip().lower() in ("0", "false", "off", "no"):
        return "GALAXY_STOP_KEY 关着"
    if not (sys.platform.startswith("win") or sys.platform == "darwin"):
        return "这个平台分不清人按的键和它自己注入的键（X11 上 XTest 注入的键与真按的一模一样；Wayland 看不到全局按键）"
    try:
        from pynput import _info  # noqa: PLC0415 — 只有真要占的时候才碰它

        version = tuple(getattr(_info, "__version__", ()) or ())
    except Exception as exc:  # noqa: BLE001
        return f"pynput 不可用: {exc}"
    if version < (1, 8, 0):
        shown = ".".join(str(v) for v in version) or "?"
        return f"pynput {shown} 太旧 —— 1.8 起才分得清人按的和注入的"
    return ""


def _report_once(why: str) -> None:
    if why in _reported:
        return
    _reported.add(why)
    logger.info("不占叫停键（%s）—— 动手期间岛上不写「%s 停止」，停止走面板", why, LABEL)


def _make_listener(on_key: Callable[[bool, bool], None]) -> Any:
    """造一个键盘监听器。``on_key(is_esc, injected)``。测试替换这一处。"""
    from pynput import keyboard  # noqa: PLC0415

    esc = keyboard.Key.esc

    def _press(key: Any, injected: bool = False) -> None:
        on_key(key == esc, bool(injected))

    return keyboard.Listener(on_press=_press, suppress=False)


def _on_key(is_esc: bool, injected: bool) -> None:
    """跑在监听线程里。只认真人按下的 Esc，其余一概不看。"""
    if not is_esc or injected or not _armed:
        return
    callback = _on_press
    if callback is None:
        return
    try:
        callback()
    except Exception:  # noqa: BLE001 — 监听线程里抛出去会把监听停掉
        logger.debug("叫停键回调失败(非致命)", exc_info=True)


def _arm(generation: int) -> None:
    """在独立线程里把监听起起来（``wait()`` 要等钩子装好，不能卡事件循环）。"""
    global _listener, _armed
    try:
        listener = _make_listener(_on_key)
    except Exception as exc:  # noqa: BLE001
        _report_once(f"开不了键盘监听: {exc}")
        return
    # macOS：没有授权时监听照样"起得来"，只是一个键也收不到 —— 那就不能说能停。
    if getattr(listener, "IS_TRUSTED", True) is False:
        _report_once("macOS 没给这个进程「辅助功能」授权，收不到按键")
        return
    try:
        listener.start()
        listener.wait()
    except Exception as exc:  # noqa: BLE001
        _report_once(f"键盘监听起不来: {exc}")
        try:
            listener.stop()
        except Exception:  # noqa: BLE001
            pass
        return
    with _lock:
        if generation == _generation and _holders > 0 and _listener is None:
            _listener, listener = listener, None
            _armed = True
    if listener is not None:
        # 起来的时候这一段已经结束了（动手只持续了一小会儿）：原样收掉。
        try:
            listener.stop()
        except Exception:  # noqa: BLE001
            pass
    else:
        logger.info("叫停键已占用：%s（只认真人按下的，不吞键）", LABEL)


def acquire(on_press: Callable[[], None]) -> None:
    """占一份。第一份才真的去起监听；起没起来看 :func:`label`。

    ``on_press`` 跑在监听线程里 —— 它只该把「停」投递回事件循环，别的什么都不做。
    """
    global _holders, _generation, _on_press
    with _lock:
        _holders += 1
        _on_press = on_press
        if _holders != 1:
            return
        _generation += 1
        generation = _generation
    why = availability()
    if why:
        _report_once(why)
        return
    threading.Thread(target=_arm, args=(generation,), name="galaxy-stop-key", daemon=True).start()


def release() -> None:
    """还一份。最后一份还掉时停监听。多还不出错（按 0 算）。"""
    global _holders, _listener, _armed, _on_press
    with _lock:
        if _holders == 0:
            return
        _holders -= 1
        if _holders:
            return
        listener, _listener = _listener, None
        _armed = False
        _on_press = None
    if listener is not None:
        try:
            listener.stop()
        except Exception:  # noqa: BLE001
            logger.debug("停键盘监听失败(非致命)", exc_info=True)


def label() -> str:
    """此刻按哪个键能叫停；没占到就是空串。"""
    return LABEL if _armed else ""
