"""记忆卡片 —— 把一条记忆线折成一张张「连续三天」的切片。

**这个文件是「怎么切」的唯一定义处。** 面板只渲染切好的片,自己不做任何分段
判断:同一条线在面板上切成五张、在别的界面上切成六张,那就是同一个事实两处各存,
而且两边都以为自己是对的。

## 为什么是三天

一天太碎(一条线上大多数天什么都没有,卡片会退化成一串空格),一周太粗(一周里
换过三个话题也只剩一张卡)。三天是「还记得清那几天在干嘛」的粒度。天数由
``SLICE_DAYS`` 一处说了算。

## 起点锚在**这条线的第一条轮次**,不是今天

按今天倒推的话,同一条线昨天看和今天看会切在不同的地方 —— 卡片的边界会自己漂,
昨天那张卡今天变成另一张。锚在第一条轮次,边界就只随内容增长而增长。

## ``weight`` 为 0 与为 None 是两件事

* ``0.0`` —— 这三天**确实什么都没发生**。它在线的时间范围之内,只是空的。
* ``None`` —— 这三天**没有留下可读的记录**。有轮次落在这一段里,但它们没有可用
  的时间戳,所以「这段有多浓」这个问题没有答案。

把 None 当成 0 画出来,就是把「不知道」画成「确实没有」—— 而这两种情况下用户该
做的事完全不同(一个是正常的安静期,一个是记录出了问题)。契约里
``MemoryCard.weight`` 因此是 ``number | null``,卡面上前者是空、后者是虚线空心。

## ``weight`` 相对谁归一

相对**这条线上最忙的那一段**。绝对值(比如"每天 50 轮算满")在不同使用强度的人
之间没有可比性:一个每天聊两句的人会看到一整排几乎空白的卡。相对归一回答的是
「这三天在我自己的这条线里算忙还是算闲」,那才是看卡片的人想知道的。

线上只有一段有内容时,那一段是 1.0 —— 不是 0。它确实是最忙的那一段。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 一张卡片盖住几天。改这里就改了所有界面上的卡片粒度。
SLICE_DAYS = 3

#: 一天多少秒。闰秒不管 —— 这里要的是「哪三天」,不是精确计时。
_DAY_S = 86400.0

#: 卡面中段那条「图」分几段。段数固定,于是不同卡片的图形可以直接比高低。
PROFILE_BINS = 6

#: 一条轮次的时间戳小于这个值就当作「没有时间戳」。
#:
#: 0 与 None 都会被 ``float(... or 0.0)`` 变成 0.0,而 1970 年的轮次不存在 ——
#: 真出现 0 就说明这条记录没记住自己是什么时候的。这个判断只在这里做一次。
_TS_FLOOR = 1.0


def _turn_ts(turn: Any) -> float:
    """一条轮次的时间戳;拿不到返回 0.0(**不是**返回现在)。

    返回 ``time.time()`` 兜底的话,一条没有时间戳的旧记录会被算成「刚刚发生」,
    于是它会跳进最新那张卡里 —— 一个凭空出现的、谁也想不通的数字。
    """
    if isinstance(turn, dict):
        raw = turn.get("timestamp", 0.0)
    else:
        raw = getattr(turn, "timestamp", 0.0)
    try:
        ts = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return ts if ts >= _TS_FLOOR else 0.0


def _turn_modalities(turn: Any) -> List[str]:
    """这条轮次带进来了哪些模态。没记录就是空 —— 不猜成「文字」。"""
    md = turn.get("metadata") if isinstance(turn, dict) else getattr(turn, "metadata", None)
    if not isinstance(md, dict):
        return []
    out: List[str] = []
    raw = md.get("modalities")
    if isinstance(raw, (list, tuple)):
        out.extend(str(m) for m in raw if m)
    for key, name in (("has_image", "image"), ("has_audio", "audio"), ("has_screen", "screen")):
        if md.get(key):
            out.append(name)
    seen: Dict[str, None] = {}
    for m in out:
        seen.setdefault(m, None)
    return list(seen)


def _day_floor(ts: float) -> float:
    """把时间戳压到当天零点(本地时区)。

    卡片的边界是「哪三天」,不是「从第一条轮次那一刻起的 72 小时」。后者会让
    第一张卡从下午三点开始 —— 人不是这么记日子的。
    """
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _iso_day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def slice_turns_into_cards(
    turns: Sequence[Any],
    *,
    titles: Optional[Dict[str, str]] = None,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """把一条线上的全部轮次折成卡片。**这是那步判断本身。**

    ``turns`` 是这条线上所有会话的轮次合起来的一串(顺序无所谓,这里自己排)。
    ``titles`` 是用户给某张卡起的名字,键是卡片 id;没有就用时段本身当标题。

    返回按时间升序的卡片列表 —— 最旧在前。抽卡那侧要倒过来显示是它的事,
    顺序在这里只定义一次。
    """
    if not turns:
        return []

    dated: List[Tuple[float, Any]] = []
    undated: List[Any] = []
    for t in turns:
        ts = _turn_ts(t)
        (dated.append((ts, t)) if ts else undated.append(t))

    if not dated:
        # **一条有时间戳的轮次都没有。** 不能凭空造一段时间出来,但也不能装作
        # 什么都没有 —— 那些轮次真实存在。给一张 weight=None 的卡:有内容,
        # 但「这几天有多浓」这个问题没有答案。
        return [
            {
                "id": "undated",
                "title": (titles or {}).get("undated", ""),
                "from": "",
                "to": "",
                "weight": None,
                "turns": len(undated),
                "modalities": sorted({m for t in undated for m in _turn_modalities(t)}),
                "profile": [],
            }
        ]

    dated.sort(key=lambda p: p[0])
    span = SLICE_DAYS * _DAY_S
    origin = _day_floor(dated[0][0])
    last = max(dated[-1][0], float(now) if now else dated[-1][0])

    # 桶的个数由「第一条轮次到最后一条轮次」决定 —— 中间空着的段照样成桶,
    # 那些就是 weight=0 的安静期。跳过它们的话,卡片之间会出现看不见的时间断层。
    bucket_count = max(1, int((last - origin) // span) + 1)
    buckets: List[List[Tuple[float, Any]]] = [[] for _ in range(bucket_count)]
    for ts, t in dated:
        idx = min(bucket_count - 1, max(0, int((ts - origin) // span)))
        buckets[idx].append((ts, t))

    # 没有时间戳的那些轮次全部挂到**最后一张**卡,并让它的 weight 变成 None:
    # 那张卡确实有内容,但已经数不清它到底有多浓了。丢掉它们会让总轮次数对不上。
    if undated:
        buckets[-1].extend((0.0, t) for t in undated)

    busiest = max((len(b) for b in buckets), default=0)
    cards: List[Dict[str, Any]] = []
    for i, bucket in enumerate(buckets):
        start = origin + i * span
        end = start + span - 1.0
        has_undated = any(ts == 0.0 for ts, _ in bucket)
        count = len(bucket)

        if has_undated:
            weight: Optional[float] = None
            profile: List[float] = []
        else:
            weight = (count / busiest) if busiest else 0.0
            profile = _profile(bucket, start, span)

        cid = f"{_iso_day(start)}+{SLICE_DAYS}d"
        cards.append(
            {
                "id": cid,
                "title": (titles or {}).get(cid, ""),
                "from": _iso_day(start),
                "to": _iso_day(end),
                "weight": weight,
                "turns": count,
                "modalities": sorted({m for _, t in bucket for m in _turn_modalities(t)}),
                "profile": profile,
            }
        )
    return cards


def _profile(bucket: Iterable[Tuple[float, Any]], start: float, span: float) -> List[float]:
    """卡面中段那条图:这三天内部的疏密。

    段内归一(最高的一段是 1.0),因为它回答的是「这三天里忙在哪一头」——
    与别的卡片比高低是 ``weight`` 的活,两件事不要混在一根线里。
    """
    bins = [0] * PROFILE_BINS
    width = span / PROFILE_BINS
    for ts, _ in bucket:
        k = min(PROFILE_BINS - 1, max(0, int((ts - start) / width)))
        bins[k] += 1
    top = max(bins) if bins else 0
    return [round(b / top, 3) if top else 0.0 for b in bins]


def cards_for_thread(session_id: str, *, session_manager: Any = None) -> Dict[str, Any]:
    """一条会话所在那条**记忆线**的全部卡片。

    卡片折的是线,不是单个会话 —— 一条线上可能有十来次对话,而卡片要回答的是
    「这三天我跟它在忙什么」,那件事横跨会话。
    """
    from core.session_manager import get_session_manager

    sm = session_manager or get_session_manager()
    root = sm.thread_root_of(session_id) if session_id else ""
    if not root:
        # 查不到线**不是**「这条线上没有卡片」。前者说明这个 session_id 后端不认识,
        # 面板该说「读不到」;后者是一条空线。两者混掉就会把查错的 id 画成空白。
        return {"thread_root": "", "known": False, "session_count": 0, "cards": []}

    sessions = sm.sessions_in_thread(root)
    turns: List[Any] = []
    titles: Dict[str, str] = {}
    for s in sessions:
        turns.extend(m.to_dict() for m in (getattr(s, "history", None) or []))
        for cid, name in ((getattr(s, "metadata", None) or {}).get("memory_card_titles") or {}).items():
            titles[str(cid)] = str(name)

    return {
        "thread_root": root,
        "known": True,
        "session_count": len(sessions),
        "slice_days": SLICE_DAYS,
        "cards": slice_turns_into_cards(turns, titles=titles),
    }
