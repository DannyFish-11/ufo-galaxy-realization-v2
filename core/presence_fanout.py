"""在场帧往外分发的另外三条路 —— 进程内订阅、感知变化监视、新连上的客户端补发。

在场桥(``core/lumiv_websocket_bridge.py``)管「这一拍是什么」,并把它推给两条**跨进程**的路(WS、IPC)。
这里是桥的三个补充,各自都是一次真实断点的修法:

1. **进程内订阅**(:func:`publish` / :func:`add_render_listener`)
   右下角托盘那只桌宠与后端同进程。它直接收桥广播出去的**同一份** ``payload.render`` ——
   不另问、不另算,与面板、覆盖层那两只读的是同一帧,三只才不会讲岔。
   订阅时若已经广播过,立刻补发最近那一份:托盘起得比第一次广播晚,也不会停在「不知道」。

2. **感知变化监视**(:func:`start_perception_watch`)
   感知那几位(在不在收、按没按隐私暂停、四条模态各自的状态)变了,**没有任何事件**会顺带广播:
   按下隐私暂停走的是 ``/api/perception/desktop/privacy/pause``,帧停了「在收」要过一会儿才翻成 false。
   静息相位里没有别的广播,于是三只桌宠的眼睛一直停在上一个样子 —— 面板曾经写着「下一帧最快 0.4 秒」,
   而静息时根本没有下一帧。现在每秒核一次、变了才推:算一次感知视图约 1.5 µs,不变就什么都不发。
   第一拍必推:进程里还没有任何广播时,托盘与刚连上的界面靠它拿到第一份样子。

3. **新连上的客户端补发名册**(:func:`welcome`)
   设备名册(``panel_feed``)只在设备 / 任务事件时才推。断线重连上来的面板若只等下一次事件,
   断开期间上线下线的设备就一直是旧的。新连上的那一个先补一份,不打扰别的客户端。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Lumiv.PresenceFanout")

#: 感知那几位多久核一次(秒)。
WATCH_S: float = 1.0

_RENDER_LISTENERS: List[Callable[[Dict[str, Any]], None]] = []
#: 最近一次广播出去的 render(给后来的订阅者补发用)。
_LAST_RENDER: Optional[Dict[str, Any]] = None
#: 最近一次**广播**里感知那几位的样子。单个新客户端的快照不走 publish,不算「广播过」。None = 还没广播过。
_SENT_KEY: Optional[Tuple[Any, ...]] = None
#: fire-and-forget 的任务要留个引用,否则事件循环的弱引用会让它半路被回收。
_TASKS: set = set()


def _call(fn: Callable[[Dict[str, Any]], None], render: Dict[str, Any]) -> None:
    try:
        fn(render)
    except Exception:  # noqa: BLE001 — 一个订阅者坏了不能拖垮广播
        logger.debug("render listener failed (non-fatal)", exc_info=True)


def add_render_listener(fn: Callable[[Dict[str, Any]], None]) -> None:
    """订阅每一次广播出去的 ``payload.render``。回调在事件循环线程里被调用,要快。"""
    if fn not in _RENDER_LISTENERS:
        _RENDER_LISTENERS.append(fn)
    if _LAST_RENDER is not None:
        _call(fn, _LAST_RENDER)


def publish(msg: Dict[str, Any]) -> None:
    """桥每广播一次就调一次:记下这一拍感知的样子,把这一份 render 交给进程内的订阅者。"""
    global _LAST_RENDER, _SENT_KEY
    render = (msg.get("payload") or {}).get("render")
    if not isinstance(render, dict):
        return
    _LAST_RENDER = render
    _SENT_KEY = perception_key(render.get("perception") or {})
    for fn in list(_RENDER_LISTENERS):
        _call(fn, render)


def _field(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def perception_key(view: Any) -> Tuple[Any, ...]:
    """感知里会改变桌宠样子 / 面板那几行的几位。``view`` 是契约里的 PerceptionView,或它广播出去的那份字典。"""
    mods = tuple((_field(m, "modality"), _field(m, "state")) for m in (_field(view, "modalities") or ()))
    return (_field(view, "source"), bool(_field(view, "is_sensing")), bool(_field(view, "privacy_paused")), mods)


async def _watch(bridge: Any) -> None:
    from core.phase_contract import resolve_perception_view

    while bridge._started:
        try:
            view = resolve_perception_view(
                speaking=bool(bridge._speaking),
                ambient_action=bridge._ambient_action or "none",
                ambient_rationale=bridge._ambient_rationale,
            )
            if perception_key(view) != _SENT_KEY:
                await bridge._broadcast_state()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 核一次失败不该停掉以后每一次
            logger.debug("perception watch tick failed (non-fatal)", exc_info=True)
        await asyncio.sleep(WATCH_S)


def start_perception_watch(bridge: Any) -> None:
    """在当前事件循环里起感知监视;没有事件循环(同步调用的测试)就不起,也不报错。"""
    try:
        task = asyncio.get_running_loop().create_task(_watch(bridge))
    except RuntimeError:
        return
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def snapshot_to(bridge: Any, websocket: Any, timeout: float) -> None:
    """给单个客户端发一份当前状态(封顶超时:注册时客户端卡死不拖住调用方)。

    快照只发给这一个客户端 —— 不许把本该广播给所有人的那一拍转移用掉(``consume_edge=False``),
    也不算「广播过」(不走 :func:`publish`)。
    """
    try:
        await asyncio.wait_for(websocket.send_json(bridge._build_message(consume_edge=False)), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — 含 TimeoutError
        logger.debug("Send to single client failed: %s", exc)


async def _send_feed(websocket: Any, timeout: float) -> None:
    try:
        from core.routes.panel import build_panel_feed

        feed = await build_panel_feed()
        await asyncio.wait_for(websocket.send_json({"type": "panel_feed", "feed": feed}), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.debug("给新客户端补发 panel feed 失败(非致命): %s", exc)


async def _send_island(websocket: Any, timeout: float) -> None:
    """灵动岛上此刻有卡就补发一份(core.island_cards):覆盖层中途才连上,也看得到正在跑的桌面操作。"""
    try:
        from core.island_cards import get_island_cards

        frame = get_island_cards().frame()
        if frame["payload"]["cards"]:
            await asyncio.wait_for(websocket.send_json(frame), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.debug("给新客户端补发灵动岛卡片失败(非致命): %s", exc)


def welcome(websocket: Any, timeout: float) -> None:
    """给刚连上的这一个客户端补一份设备名册、灵动岛上的卡(后台发,不拖住注册)。"""
    for send in (_send_feed, _send_island):
        task = asyncio.create_task(send(websocket, timeout))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)


__all__ = [
    "WATCH_S",
    "add_render_listener",
    "perception_key",
    "publish",
    "snapshot_to",
    "start_perception_watch",
    "welcome",
]
