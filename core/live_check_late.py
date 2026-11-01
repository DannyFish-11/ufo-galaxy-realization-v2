"""core/live_check_late.py —— 边说边核的慢的两级：联网核、换一个模型裁决；核完给那条回答挂晚到的勘误。

设计见 ``docs/GROUNDED_AGENT_DESIGN.md`` §3.2（后两行）、§3.3（「这一轮已经结束」那一行）、§4（猜想）。
快的两级（这一轮的工具结果、在线表）在 :mod:`core.live_check`，赶在说出口之前；这里的要秒级，只能事后改。

**时机**：一轮已经结束（回答交出去了、写进会话了）之后，在后台做 —— 不挡这一轮，也不进这一轮的上下文
（后台任务用一个空的上下文起：裁判的字不会流进人的对话，裁判的调用也不记进这一轮的账）。

**核什么**（规则，不调模型；每轮最多 :data:`MAX_LATE_CHECKS` 句）：

* 标了「猜」的句子（我猜 / 可能 / 也许 / 估计 / 大概……）：猜想当检索词去查（HyDE），核完补一句跟进，
  并记进猜想账本（:mod:`core.conjecture_ledger`）；
* 说「现在 / 最新 / 今年……」又带着数字的句子：时效性资讯，模型的知识有截止，最容易错在这里。

**去哪核**：联网搜索 —— Node_22 Brave（要 ``BRAVE_API_KEY``；结果带摘要）。Google 节点只回链接、没有摘要，拿它
裁决等于让裁判猜，所以不用。

**谁裁决**：**换一个模型**，只看「这句话 + 搜索结果」；这一轮回答用过的厂商一律不当裁判（提出者自报不算，
同 ``scripts/check_verdict_independence.py`` 的原则）。裁判说「驳倒 / 证实」却指不出一条在搜索结果里的出处
→ 当没核（查不到不等于驳倒）。

**结论**：驳倒 → 会话里那条回答的文字改掉（原句后跟「（更正：…）」）、面板收一帧 WS ``revise`` 原地划掉、
岛上一张「刚才的回答有一处更正」；猜想被证实 → 同样挂上「已核实」；查不到 → 什么都不改（猜想在账上还是「猜」）。

只核人发起的回合（自发注意力、心跳、主动感知不核）。没配联网搜索、没有第二个模型可当裁判：什么都不改，
:func:`status` 照实说缺哪样（``GET /api/v1/agent/live-check``）。语音不补念晚到的勘误（所有者的决定：
口头只当场更正）；别的设备发起的回合，勘误只落会话，那台设备下次拉历史时看到。
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Sequence, Set, Tuple

from core.live_check import REFUTED, SUPPORTED, UNVERIFIED, Revision, corrected_text, split_sentences

logger = logging.getLogger("Galaxy.LiveCheckLate")

#: 一轮最多事后核几句（每句一次搜索 + 一次裁判调用）
MAX_LATE_CHECKS = 2
SEARCH_TIMEOUT_S = 15.0
JUDGE_TIMEOUT_S = 30.0
#: 给裁判看几条搜索结果
EVIDENCE_ITEMS = 5
SEARCH_NODE = "Node_22_BraveSearch"
#: 不核的来源（与 core.presence_line.BACKGROUND_SOURCES 同一份意思：不是人在问）
_NOT_A_PERSON = frozenset({"ambient", "heartbeat", "active_perception"})

_GUESS = re.compile(r"(我猜|猜测|我估计|估计|可能|也许|或许|大概|应该是|说不定)")
#: 给人的建议（「你可能需要……」）不是对事实的猜
_ADVICE = re.compile(r"(你|您)(可能|也许|或许|大概)?(需要|要|得|可以|想)")
_CURRENT = re.compile(
    r"(最新|现在|目前|当前|如今|今天|今年|本周|这周|本月|最近|刚刚|新发布|发布了|上市|价格|股价|汇率|比分|排名)"
)
_HAS_NUMBER = re.compile(r"\d")

_BACKGROUND: Set["asyncio.Task[Any]"] = set()


def late_kinds(sentence: str) -> Tuple[str, ...]:
    """这句话要不要事后去核、按什么核。空元组 = 不核。"""
    s = sentence.strip()
    if len(s) < 6 or s.endswith(("？", "?")):
        return ()
    if _GUESS.search(s) and not _ADVICE.search(s):
        return ("conjecture",)
    if _CURRENT.search(s) and _HAS_NUMBER.search(s):
        return ("current_fact",)
    return ()


def web_search_ready() -> Tuple[bool, str]:
    if (os.environ.get("BRAVE_API_KEY") or "").strip():
        return True, "Brave 联网搜索"
    return False, "没配联网搜索(BRAVE_API_KEY);Google 节点只回链接、没有摘要,核不了"


def _router() -> Any:
    from core.multi_llm_router import get_llm_router

    return get_llm_router()


def _providers_used_since(router: Any, started_at: float) -> Set[str]:
    """这一轮(从 ``started_at`` 起)调用过的厂商 —— 它们说的话,不由它们自己来裁决。"""
    return {
        str(h.get("provider"))
        for h in list(getattr(router, "call_history", []) or [])
        if h.get("timestamp", 0) >= started_at
    }


def judge_candidates(exclude: Set[str]) -> List[str]:
    """能当裁判的厂商:可用、有适配器、这一轮没用过。"""
    try:
        router = _router()
        return [
            name
            for name, cfg in router.providers.items()
            if name not in exclude and cfg.is_available() and router.adapters.get(name) is not None
        ]
    except Exception:  # noqa: BLE001
        return []


async def _search(query: str) -> Tuple[List[Dict[str, str]], str]:
    from core.node_invocation import InvocationSource, invoke_node

    inv = await invoke_node(
        SEARCH_NODE,
        "search",
        {"query": query[:200], "count": EVIDENCE_ITEMS},
        invocation_source=InvocationSource.SYSTEM,
        timeout_ms=SEARCH_TIMEOUT_S * 1000,
    )
    if not inv.success:
        return [], str(inv.error or "联网搜索没成功")
    data = inv.result if isinstance(inv.result, dict) else {}
    data = data.get("data", data) if isinstance(data.get("data"), dict) else data
    items = [
        {"title": str(r.get("title") or ""), "url": str(r.get("url") or ""), "text": str(r.get("description") or "")}
        for r in (data.get("results") or [])
        if isinstance(r, dict) and r.get("url")
    ]
    return items[:EVIDENCE_ITEMS], "" if items else "联网搜索没搜到东西"


_JUDGE_SYSTEM = (
    "你是核对员。只看给你的「一句话」和「搜索结果」，不要用你自己记得的知识。判断这句话：\n"
    "supported = 搜索结果明确支持它；refuted = 搜索结果明确与它矛盾；unverified = 结果不够下结论。\n"
    '只输出一个 JSON 对象：{"verdict": "supported|refuted|unverified", '
    '"correct": "refuted 时按搜索结果改正后的说法（一句话），否则空串", "source": "所依据那条结果的 url"}'
)


def _parse_verdict(raw: str, urls: Sequence[str]) -> Tuple[str, str, str]:
    start, end = raw.find("{"), raw.rfind("}")
    try:
        data = json.loads(raw[start : end + 1]) if 0 <= start < end else {}
    except ValueError:
        data = {}
    verdict = str(data.get("verdict") or "").strip().lower()
    source = str(data.get("source") or "").strip()
    if verdict not in (SUPPORTED, REFUTED) or source not in urls:
        return UNVERIFIED, "", ""  # 给不出搜索结果里的出处:查不到不等于驳倒
    correct = str(data.get("correct") or "").strip()[:160]
    if verdict == REFUTED and not correct:
        return UNVERIFIED, "", ""
    return verdict, correct, source


async def _judge(sentence: str, evidence: List[Dict[str, str]], judge: str) -> Tuple[str, str, str]:
    lines = "\n".join(f"[{i + 1}] {e['title']} —— {e['text']}（{e['url']}）" for i, e in enumerate(evidence))
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": f"一句话：{sentence.strip()}\n\n搜索结果：\n{lines}"},
    ]
    resp = await asyncio.wait_for(
        _router().chat(messages, provider=judge, auto_failover=False, temperature=0.0, max_tokens=300),
        JUDGE_TIMEOUT_S,
    )
    return _parse_verdict(str(getattr(resp, "content", "") or ""), [e["url"] for e in evidence])


def candidates(text: str, already: Sequence[str] = ()) -> List[Tuple[int, str, str]]:
    """(句子编号, 句子, 按什么核):快的两级已经核过的句子不再核;猜想排在前面。"""
    sentences, tail = split_sentences(text)
    done = {a.strip() for a in already}
    out = []
    for seg, s in enumerate(sentences + ([tail] if tail.strip() else [])):
        kinds = late_kinds(s)
        if kinds and s.strip() not in done:
            out.append((seg, s, kinds[0]))
    out.sort(key=lambda c: c[2] != "conjecture")
    return out[:MAX_LATE_CHECKS]


async def check_turn(
    text: str, *, session_id: str = "", started_at: float = 0.0, already: Sequence[str] = ()
) -> List[Revision]:
    """核一轮回答里该事后核的句子,返回要挂上去的修订(证实的猜想、驳倒的句子)。永不抛出。"""
    picked = candidates(text, already)
    if not picked:
        return []
    from core import conjecture_ledger

    guesses = {
        seg: await asyncio.to_thread(conjecture_ledger.record, s, session_id=session_id)
        for seg, s, kind in picked
        if kind == "conjecture"
    }
    ready, _why = web_search_ready()
    judges = judge_candidates(_providers_used_since(_router(), started_at)) if ready else []
    out: List[Revision] = []
    for seg, sentence, kind in picked:
        verdict, note, source, judge = UNVERIFIED, "", "", ""
        if judges:
            try:
                evidence, _err = await _search(sentence)
                if evidence:
                    judge = judges[0]
                    verdict, note, source = await _judge(sentence, evidence, judge)
            except Exception as exc:  # noqa: BLE001 — 核不了就当没核
                logger.debug("事后核对出错(当没核): %s", exc)
        if seg in guesses and judges:  # 没真去核(没配联网 / 没有裁判)的猜想留在账上「没核」,不记成「查不到」
            await asyncio.to_thread(
                conjecture_ledger.settle, guesses[seg], verdict, note=note, source=source, judge=judge
            )
        if verdict == REFUTED or (verdict == SUPPORTED and kind == "conjecture"):
            note = note if verdict == REFUTED else "搜索结果支持这个说法"
            out.append(Revision(seg, sentence, verdict, note, f"web:{source}"))
    return out


async def deliver(session_id: str, revisions: List[Revision]) -> None:
    """把晚到的勘误挂到那条回答上:会话文字、面板(WS ``revise``)、岛上一张卡。永不抛出。"""
    if not revisions:
        return
    rows = [{**r.to_dict(), "late": True} for r in revisions]
    try:
        from core.session_manager import get_session_manager

        await get_session_manager().revise_message(
            session_id, revisions[0].original.strip(), lambda c: corrected_text(c, revisions), rows
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("勘误没写进会话: %s", exc)
    try:
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        frame = {"type": "revise", "payload": {"session_id": session_id, "revisions": rows, "late": True}}
        await GalaxyPresenceBridge.get_instance()._ws_broadcast(frame)  # noqa: SLF001 — 与批准清单同一条推法
    except Exception as exc:  # noqa: BLE001
        logger.debug("勘误没推到面板: %s", exc)
    from core.island_cards import post_card

    fixed = sum(1 for r in revisions if r.verdict == REFUTED)
    title = f"刚才的回答有{'一' if fixed == 1 else fixed}处更正" if fixed else "刚才猜的那句核实了"
    post_card(f"late-revise:{session_id}", kind="correction", title=title, subtitle="联网核对", ttl_s=20)


async def _run(text: str, session_id: str, started_at: float, already: Sequence[str]) -> None:
    try:
        await deliver(session_id, await check_turn(text, session_id=session_id, started_at=started_at, already=already))
    except Exception as exc:  # noqa: BLE001
        logger.debug("事后核对没做完: %s", exc)


def after_turn(text: str, *, session_id: str, source: str, started_at: float, already: Sequence[str] = ()) -> bool:
    """一轮收尾之后把慢的两级交给后台。返回是否真起了核对(没有该核的句子、不是人问的都不起)。永不抛出。"""
    try:
        if not text or not session_id or source in _NOT_A_PERSON or not candidates(text, already):
            return False
        loop = asyncio.get_running_loop()
        # 空上下文:裁判的字不流进人的对话(当前令牌流),裁判的调用也不记进这一轮的账
        task = loop.create_task(_run(text, session_id, started_at, tuple(already)), context=contextvars.Context())
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("事后核对没起来: %s", exc)
        return False


def status() -> Dict[str, Any]:
    """核对线现在能做到哪一级、缺什么;猜想账本的校准。给人看,不进决策。"""
    from core import conjecture_ledger

    ready, why = web_search_ready()
    judges = judge_candidates(set())
    return {
        "fast": {"turn_ledger": True, "presence": True},
        "web_search": {"available": ready, "detail": why},
        "judge": {
            # 回答的那个厂商不当裁判:至少要有两个可用的厂商,才有一个是「别的模型」
            "available": len(judges) >= 2,
            "providers": judges,
            "detail": "裁判从这一轮没用过的厂商里挑;只配了一个厂商时,它自己答的话没有别的模型来裁决",
        },
        "max_late_checks_per_turn": MAX_LATE_CHECKS,
        "conjectures": {**conjecture_ledger.calibration(), "recent": conjecture_ledger.entries(limit=10)},
        "checked_at": time.time(),
    }


__all__ = [
    "MAX_LATE_CHECKS",
    "after_turn",
    "candidates",
    "check_turn",
    "deliver",
    "judge_candidates",
    "late_kinds",
    "status",
    "web_search_ready",
]
