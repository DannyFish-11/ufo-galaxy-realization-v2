"""core/island_cards.py — 灵动岛上的卡片:这台电脑上正在发生、人该余光知道的事

借鉴 WinIslands(Windows 灵动岛)的「上岛推送」那一套,只取适合这里的部分:

* **一张卡一个 id**:同一个 id 再推一次是**原地更新**,不另起一张、不换队列位置 —— 「桌面操作 第 3/15 步」
  走到第 4 步是同一张卡往前走,不是第二张卡;
* **有先后**:``high`` > ``normal`` > ``low``,同级新的在前;岛上只画排第一的那张,其余在展开态里列出来;
* **会过期**:``ttl_s`` 秒后自己消失(``None`` = 一直在,直到推它的那一方撤掉,比如进行中的桌面操作);
* **卡片不改岛的长短**:岛的宽度只按它自己的上下限走,字放不下就截断 —— 推一张卡岛就忽长忽短,那是噪音;
* **只放类型化的短字段**:标题、副标题、一句说明、进度(0–1)、语气(info / success / warning / error),
  每一项截断。不放原始结果、截图、参数。

谁会推卡(都是**这台电脑上**的事,不是别的设备上的):

* 桌面操作(Computer Use)—— 跑到第几步(带进度),跑完独立核对的结论(:mod:`core.computer_use_verdict`);
* 「没收口的结果」—— 补跑后仍没收口、进了隔离队列(:mod:`core.truth_chain_recovery`);
* 等你同意的设备 —— 陌生设备来登记,进了接入候选(:mod:`core.device_onboarding.join_paths`)。

怎么到岛上:与对话消息、推演步骤同一条 ``/ws/desktop-presence``,一帧 ``{"type": "island", "payload":
{"cards": [...], "seq": n}}``,每次有变化推整份(卡很少,整份比增量简单,也不怕丢一帧);覆盖层刚连上时
:mod:`core.presence_fanout` 补发一份。不走 ``payload.render`` —— 那是在场姿态,卡片是事件。

非阻塞、永不抛出:推不出去只是岛上少一张卡,推卡的那一方照常。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.IslandCards")

TONES = ("info", "success", "warning", "error")
PRIORITIES = ("high", "normal", "low")

#: 不说多久的卡,默认在岛上待几秒(与 WinIslands 不同,这里的卡都是「刚发生了什么」,不该挂半分钟)
DEFAULT_TTL_S = 8.0
#: 队列最多留几张;再多就把排在最后、最旧的挤掉(岛是余光看的,不是收件箱)
MAX_CARDS = 6

_TEXT_LIMITS = {"title": 24, "subtitle": 48, "body": 160}

_BACKGROUND: Set["asyncio.Task[Any]"] = set()


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class IslandCards:
    """卡片队列。进程内单例见 :func:`get_island_cards`。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cards: Dict[str, Dict[str, Any]] = {}
        self._order = 0
        self._seq = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ 推 / 撤

    def post(
        self,
        card_id: str,
        *,
        kind: str,
        title: str,
        subtitle: str = "",
        body: str = "",
        progress: Optional[float] = None,
        tone: str = "info",
        priority: str = "normal",
        ttl_s: Optional[float] = DEFAULT_TTL_S,
        action: str = "",
    ) -> Optional[Dict[str, Any]]:
        """推一张卡;同一个 ``card_id`` 是原地更新(保留它在队列里的先后)。标题为空不推,返回 ``None``。

        ``action`` 只认 ``"stop"``(岛上画「停下」)与 ``"panel"``(岛上画「打开面板」),别的当没有。
        """
        title = _clip(title, _TEXT_LIMITS["title"])
        if not card_id or not title:
            return None
        if progress is not None:
            try:
                progress = min(1.0, max(0.0, float(progress)))
            except (TypeError, ValueError):
                progress = None
        now = time.time()
        with self._lock:
            old = self._cards.get(card_id)
            self._order += 1
            card = {
                "id": card_id,
                "kind": _clip(kind, 24) or "notice",
                "title": title,
                "subtitle": _clip(subtitle, _TEXT_LIMITS["subtitle"]),
                "body": _clip(body, _TEXT_LIMITS["body"]),
                "progress": progress,
                "tone": tone if tone in TONES else "info",
                "priority": priority if priority in PRIORITIES else "normal",
                "action": action if action in ("stop", "panel") else "",
                "posted_at": old["posted_at"] if old else now,
                "order": old["order"] if old else self._order,
                "expires_at": None if ttl_s is None else now + max(0.5, float(ttl_s)),
            }
            self._cards[card_id] = card
            self._prune(now)
            while len(self._cards) > MAX_CARDS:
                victim = self._ranked(now)[-1]["id"]
                self._cards.pop(victim, None)
        self._publish()
        return self._public(card, now)

    def remove(self, card_id: str) -> bool:
        with self._lock:
            gone = self._cards.pop(card_id, None) is not None
        if gone:
            self._publish()
        return gone

    def reset(self) -> None:
        with self._lock:
            self._cards.clear()
            self._seq = 0

    # ------------------------------------------------------------------ 读

    def active(self) -> List[Dict[str, Any]]:
        """还没过期的卡,排好先后(岛上画第一张)。"""
        now = time.time()
        with self._lock:
            self._prune(now)
            return [self._public(c, now) for c in self._ranked(now)]

    def frame(self) -> Dict[str, Any]:
        with self._lock:
            seq = self._seq
        return {"type": "island", "payload": {"cards": self.active(), "seq": seq}}

    # ------------------------------------------------------------------ 内部

    def _ranked(self, now: float) -> List[Dict[str, Any]]:
        rank = {p: i for i, p in enumerate(PRIORITIES)}
        return sorted(self._cards.values(), key=lambda c: (rank[c["priority"]], -c["order"]))

    def _prune(self, now: float) -> None:
        for key in [k for k, c in self._cards.items() if c["expires_at"] is not None and c["expires_at"] <= now]:
            self._cards.pop(key, None)

    @staticmethod
    def _public(card: Dict[str, Any], now: float) -> Dict[str, Any]:
        out = {k: v for k, v in card.items() if k not in ("expires_at", "order", "posted_at")}
        # 过期时刻给相对秒数:覆盖层自己按它数,不用跟后端对表
        exp = card["expires_at"]
        out["expires_in_s"] = None if exp is None else round(max(0.0, exp - now), 1)
        return out

    def _publish(self) -> None:
        """排一次广播:在事件循环里就地排;在别的线程里(补跑计时器)交回记下的那个循环;都不行就不推。"""
        with self._lock:
            self._seq += 1
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
        except RuntimeError:
            loop = None
        if loop is not None:
            self._spawn(loop)
            return
        saved = self._loop
        if saved is not None and saved.is_running() and not saved.is_closed():
            try:
                saved.call_soon_threadsafe(self._spawn, saved)
            except RuntimeError:  # 循环刚好关了
                pass

    def _spawn(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            from core.lumiv_websocket_bridge import GalaxyPresenceBridge

            task = loop.create_task(GalaxyPresenceBridge.get_instance()._ws_broadcast(self.frame()))
            _BACKGROUND.add(task)
            task.add_done_callback(_BACKGROUND.discard)
        except Exception as exc:  # noqa: BLE001 — 推不出去只是岛上少一张卡
            logger.debug("灵动岛卡片没推出去: %s", exc)


_cards: Optional[IslandCards] = None
_cards_lock = threading.Lock()


def get_island_cards() -> IslandCards:
    """进程内单例。"""
    global _cards
    with _cards_lock:
        if _cards is None:
            _cards = IslandCards()
        return _cards


def post_card(card_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """推卡的便捷入口:永不抛出(推卡的那一方不该因为岛而出错)。"""
    try:
        return get_island_cards().post(card_id, **fields)
    except Exception as exc:  # noqa: BLE001
        logger.debug("灵动岛卡片没推上: %s", exc)
        return None


def remove_card(card_id: str) -> None:
    try:
        get_island_cards().remove(card_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("灵动岛卡片没撤掉: %s", exc)


__all__ = [
    "DEFAULT_TTL_S",
    "MAX_CARDS",
    "PRIORITIES",
    "TONES",
    "IslandCards",
    "get_island_cards",
    "post_card",
    "remove_card",
]
