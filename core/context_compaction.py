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


def restore_anchor(messages: List[Dict[str, Any]], session_id: str) -> bool:
    """进程重启后，把这个会话上次留下的摘要**贴回**上下文。贴了返回 ``True``。

    为什么必须有这一步
    ==================
    上一轮做了 :func:`save_anchor`，也做了 :func:`load_anchor`，还写了"摘要跨重启
    持久化，进程重启后同一个会话不会突然失忆" —— **但没有任何一处生产代码调用
    load_anchor**。写进去了，从来没读出来过。摘要文件在磁盘上安安静静地攒着，而
    重启后的会话该失忆照样失忆。

    这是"接了等于没接"的一个标准样本：写侧有、读侧没有，两个方向都有函数、都有
    测试，链条中间断着 —— 而且不会有任何一条错误。

    什么时候贴、什么时候不贴
    ========================
    只在**真的失忆了**的时候贴：消息列表已经有摘要锚 → 不贴(这一轮压过了)；
    消息列表还很长 → 不贴(历史本来就在，摘要是它的**有损副本**，两份都在等于让
    模型看到同一段过去的两个版本)。只有"存着摘要、而手上的消息短得像刚开始"这一种
    情况才是重启失忆，才该贴。

    宁可少贴一次(退回原来的行为:失忆)，也不要多贴一次(制造一段自相矛盾的过去)。
    """
    if not session_id or _find_anchor(messages) is not None:
        return False
    # 长度门槛与压缩的保留窗口同一个数：多过这些条，历史本身还在，不需要副本。
    if len(messages) > KEEP_RECENT_MESSAGES + 1:
        return False
    summary = load_anchor(session_id)
    if not summary:
        return False

    anchor_msg = {"role": "system", "content": f"{ANCHOR_MARKER}\n{summary}"}
    insert_at = 0
    while (
        insert_at < len(messages)
        and isinstance(messages[insert_at], dict)
        and messages[insert_at].get("role") == "system"
    ):
        insert_at += 1
    messages.insert(insert_at, anchor_msg)
    logger.info("会话 %s 重启后取回了上次的摘要（%d 字）—— 不是从零开始", session_id, len(summary))
    return True


def observe_system_head(messages: List[Dict[str, Any]]) -> int:
    """顺手量一下这次装配的**系统头**有多长并记下来；返回量到的 token 数。

    为什么是在这里量
    ================
    ``context_trim`` 的基线里"系统提示 + 人格 + 工具契约"那一段，原来和"给回复留多少"
    捆在一个拍出来的 2048 里 —— 它是决定 ``n_ctx`` 的那条式子里最后一个没有依据的数。
    系统头的真长度**只有在装配之后才知道**(它取决于装了哪些技能、人格是什么状态)，
    而 ``n_ctx`` 要在**加载模型时**就定下来。两个时刻错开了，所以只能这一轮量、
    下一轮用 —— 与 KV 单价那条完全同构。

    量的是**不含摘要锚**的那一段：摘要是压缩自己的产物，把它算进"这套部署的系统头
    有多长"就成了自己量自己(见 ``context_measurements`` 模块文档那条硬规矩)。

    全程 best-effort：量不到、记不下都不影响本轮。
    """
    try:
        head, _to_compact, _recent = _split_for_compaction(messages)
        real_head = [m for m in head if ANCHOR_MARKER not in str(m.get("content") or "")]
        if not real_head:
            return 0
        tokens = estimate_tokens(real_head)
        if tokens > 0:
            from core.context_measurements import record_system_head_tokens  # noqa: PLC0415

            record_system_head_tokens(tokens)
        return tokens
    except Exception as exc:  # noqa: BLE001
        logger.debug("系统头长度实测跳过(不影响本轮): %s", exc)
        return 0


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
