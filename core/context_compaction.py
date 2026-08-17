"""core/context_compaction.py — 会话长了要**压**，不能只是**丢**
==================================================================

修的是什么
==========
:mod:`core.context_trim` 做的三件事全是**机械丢弃**：工具结果截断、老轮次换存根、
工具表瘦身。它们省的是字节，代价是**信息真的没了** —— 被换成存根的那一轮里，
模型当时看到了什么、据此定了什么，之后再也问不回来。

短任务里这没关系（结论已经体现在其后的推理里）。长会话里这就是"断片"：聊到第 40 轮
时，第 5 轮定下的约束、用户第 8 轮纠正过的偏好，全都被换成了 ``…[已修剪]``。用户
看到的是"它怎么又忘了"，而系统这边一条错误都没有 —— 因为丢弃是**设计如此**的。

缺的是中间那一层：**丢之前先把它压成摘要**。

做法取自 2026 年这一批 Agent 的共识
====================================
* **锚定式增量摘要（anchored iterative summarization）**：全程只维护**一条**摘要，
  每次压缩把新的一段**并进**这条摘要，而不是拿全部历史重新生成一遍。重新生成的
  问题是每次都在重新解释一遍旧内容，越压越漂；并进去的那条是累积的，稳定得多。
* **三层记忆**：窗口内的工作记忆 / 长了就并进锚定摘要 / 跨会话的持久存储。
  本模块只管中间那层 —— 第一层是 ``context_trim``，第三层是 ``core.memory`` 那一套。
* **先落库再压缩（write-before-compaction）**：要留的东西在**每一轮**就写进持久层，
  不是等压缩触发那一刻才抢救。等到触发时才写，那些"用户早就说过一次"的约束可能
  已经在更早的机械修剪里没了。本模块因此**只负责压，不负责抢救** —— 它假定该落库的
  已经落过库了，并在 :func:`compact_messages` 里对此显式设防。

触发点为什么是"占用比例"而不是一个固定条数
==========================================
上下文窗口现在是**按机器算出来的**（见
:meth:`core.compute_scheduler.ComputeScheduler.context_budget_for`）：同一套代码在
24 GB 卡上可能开到 13 万 token，在 9 GB 卡上只有 2 千。写死"超过 N 条就压"在前者
是浪费（压得太早，白白丢细节），在后者是失效（压得太晚，早就截断了）。

按比例就都对：压缩在**窗口用掉七成**时触发，窗口多大由那一处算，这里不重复判断。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.ContextCompaction")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ANCHOR_FILE = PROJECT_ROOT / "runtime" / "context_anchors.json"

#: 窗口用掉多少就触发压缩。
#:
#: 取 0.7 而不是更靠后:压缩本身要调一次模型、要花时间,而且压完之后还得留出空间
#: 给这一轮的问答。卡到 0.9 再压,压缩这一步自己就可能装不下。
COMPACT_AT_UTILIZATION = 0.7

#: 压缩后保留最近多少轮**原文**。
#:
#: 不是全压成摘要 —— 最近几轮是模型正在推理的现场,压掉它等于让模型忘记自己刚在做
#: 什么。摘要负责远处,原文负责近处,这是两件事。
KEEP_RECENT_MESSAGES = 8

#: 摘要消息的标记。锚定式的前提是**能把上一条摘要认出来**,否则每次都会新插一条,
#: 压几次就有几条摘要 —— 那既浪费窗口,又让模型看到多份互相矛盾的过去。
ANCHOR_MARKER = "[会话摘要·锚定]"


def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """这批消息大约折多少 token —— 换算复用 ``context_trim`` 那一处，不另起一套。"""
    try:
        from core.context_trim import count_tokens  # noqa: PLC0415

        chars = sum(len(str(m.get("content") or "")) for m in messages if isinstance(m, dict))
        return count_tokens(chars_or_text=chars)
    except Exception as exc:  # noqa: BLE001
        logger.debug("token 估算不可用: %s", exc)
        return 0


def context_utilization(messages: List[Dict[str, Any]], n_ctx: int) -> float:
    """这批消息占了窗口的百分之几；窗口未知返回 0.0（= 判不了，不触发）。"""
    if n_ctx <= 0:
        return 0.0
    used = estimate_tokens(messages)
    return used / float(n_ctx) if used > 0 else 0.0


def should_compact(messages: List[Dict[str, Any]], n_ctx: int) -> bool:
    """该压了吗。窗口算不出来时**一律不压** —— 判不了不动手。"""
    if n_ctx <= 0 or len(messages) <= KEEP_RECENT_MESSAGES + 1:
        return False
    return context_utilization(messages, n_ctx) >= COMPACT_AT_UTILIZATION


def _find_anchor(messages: List[Dict[str, Any]]) -> Optional[int]:
    """已有摘要锚在第几条；没有返回 None。"""
    for i, m in enumerate(messages):
        if isinstance(m, dict) and ANCHOR_MARKER in str(m.get("content") or ""):
            return i
    return None


def load_anchor(session_id: str) -> str:
    """取回这个会话上次留下的摘要 —— **跨重启的连续性靠这一条**。

    没有它，进程重启后模型就从"完全不知道之前聊过什么"开始;而用户的感受是同一个
    会话突然失忆。存一条纯文本足矣:摘要本来就是为了能被原样贴回上下文。
    """
    if not session_id:
        return ""
    try:
        if _ANCHOR_FILE.exists():
            data = json.loads(_ANCHOR_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return str((data.get(session_id) or {}).get("summary") or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("会话摘要读取失败(按没有处理): %s", exc)
    return ""


def save_anchor(session_id: str, summary: str) -> None:
    """存这个会话的摘要。写失败不影响本轮对话 —— 丢的是下次的连续性，不是这次的。"""
    if not session_id or not summary:
        return
    try:
        data: Dict[str, Any] = {}
        if _ANCHOR_FILE.exists():
            loaded = json.loads(_ANCHOR_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        data[session_id] = {"summary": summary, "chars": len(summary)}
        _ANCHOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_ANCHOR_FILE, data, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("会话摘要写入失败(不影响本轮): %s", exc)


def _split_for_compaction(
    messages: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """切成 (系统头, 要压的那一段, 保留原文的最近几轮)。

    系统头(role=system 的开头几条 + 已有的摘要锚)必须原样留着 —— 它们是人格与
    工具契约,压掉会直接改变模型的行为,那不是"省点空间",是换了个 Agent。
    """
    head: List[Dict[str, Any]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if not (isinstance(m, dict) and (m.get("role") == "system" or ANCHOR_MARKER in str(m.get("content") or ""))):
            break
        head.append(m)
        i += 1
    body = messages[i:]
    if len(body) <= KEEP_RECENT_MESSAGES:
        return head, [], body
    return head, body[:-KEEP_RECENT_MESSAGES], body[-KEEP_RECENT_MESSAGES:]


def compact_messages(
    messages: List[Dict[str, Any]],
    summarize: Callable[[str, str], str],
    *,
    session_id: str = "",
    persisted_ok: bool = True,
) -> int:
    """**原地**把远处的历史并进一条锚定摘要，返回被压掉的消息条数（0 = 没压）。

    Args:
        messages: 会话消息列表，**原地修改**。
        summarize: ``(已有摘要, 待并入的新内容) -> 新摘要``。由调用方注入 ——
            本模块不自己去调模型:那会让它依赖某一条具体的推理路径,而压缩这件事
            在云端主脑和本地主脑上都该能用。
        session_id: 存摘要用;空则只压不存(本次有效，重启后不连续)。
        persisted_ok: 调用方声明"该落库的这一轮已经落过库了"。
            ``False`` 时**拒绝压缩** —— 见模块文档"先落库再压缩":压缩是不可逆的,
            在持久层还没拿到这一段之前就压,等于拿用户说过的话去赌摘要写得够全。

    Returns:
        被并进摘要的消息条数。
    """
    if not persisted_ok:
        logger.warning("持久层尚未确认收到这一段，拒绝压缩 —— 先落库再压缩，压缩不可逆")
        return 0

    head, to_compact, recent = _split_for_compaction(messages)
    if not to_compact:
        return 0

    prior = ""
    anchor_idx = _find_anchor(head)
    if anchor_idx is not None:
        prior = str(head[anchor_idx].get("content") or "").replace(ANCHOR_MARKER, "").strip()

    fresh = "\n".join(f"{m.get('role', '?')}: {str(m.get('content') or '')[:2000]}" for m in to_compact)
    try:
        merged = summarize(prior, fresh)
    except Exception as exc:  # noqa: BLE001 — 压不动就**不压**，绝不丢
        logger.warning("摘要生成失败，本次不压缩(宁可占着窗口也不丢内容): %s", exc)
        return 0
    if not merged or not merged.strip():
        logger.warning("摘要为空，本次不压缩")
        return 0

    anchor_msg = {"role": "system", "content": f"{ANCHOR_MARKER}\n{merged.strip()}"}
    if anchor_idx is not None:
        head[anchor_idx] = anchor_msg
    else:
        head.append(anchor_msg)

    messages[:] = head + recent
    save_anchor(session_id, merged.strip())
    logger.info("上下文压缩：%d 条历史并入锚定摘要（摘要 %d 字）", len(to_compact), len(merged))
    return len(to_compact)
