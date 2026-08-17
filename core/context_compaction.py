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

这一版补上的：压缩从**有损**变成**无损**
==========================================
上一版做的是**永久删除** —— 摘要一生成，原文就没了。那正是 ACM 那篇论文里被单列
出来做消融的退化变体(``disable_query_memory``)：**关掉检索之后，"压缩"就退化成
"删除"**。

补齐的三件：

* **归档**(:mod:`core.context_archive`)：压之前把整段**原文**落盘，段号可寻址；
* **目录**：窗口里留的是 ``[归档段 N] 摘要``，摘要只负责让模型判断"该翻哪一段"，
  不再承担"替代历史"；
* **取回**：模型用 ``context__query_memory(段号, 查询)`` 把原文调回来。

因此摘要**不再合并成一条**。上一版合并是为了防"反复重新摘导致越压越漂"，而每段
只从**原文**摘一次的话根本不会漂 —— 那是上一版自己造出来的问题。合并的代价则是
段号没了，而没有段号就无从取回。

谁来决定压缩时机
================
两条并存，缺一不可：

* **模型自己**(``context__manage``，ACM 的 ``manage_context``)——它知道自己接下来
  要干什么，能在语义边界上压，而不是在某个百分比上压；
* **系统自动**(七成阈值)——**地板，每个档位都留着**。ACM 靠后训练让模型学会节奏，
  这个仓库跑的是现成权重、没有那条训练链路；**一个只在模型开口时才压缩的系统，
  会被一个从不开口的模型撑爆。**

而"模型自己管"这件事本身有门槛：ACM 自己的消融里，4B 模型做完同样训练也只有
3.4%(9B 是 57.3%)——它只跑两轮就终止，上下文管理工具根本没有用武之地。所以
A 档(Gemma 4 E2B/E4B，2B/4B 级)**不开**自主管理，见 :func:`model_manages_own_context`。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ContextCompaction")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

#: 归档段占位符的标记。用它把"这条是目录"从普通 system 消息里认出来。
#:
#: 上一版这里叫"锚定"，因为全程只有一条摘要、新的往里并。现在每段一条、各带段号,
#: 标记的职责也跟着变了:从"认出那唯一一条"变成"认出这一族",好在切分与实测系统头
#: 时把它们排除掉(它们是压缩自己的产物，不是这套部署的系统提示)。
ANCHOR_MARKER = "[会话归档·目录]"

#: 窗口里最多显示几条段目录，更早的折叠成一行范围。
#:
#: 段数会随会话长度线性涨,而每条目录都占窗口 —— 不封顶的话,压缩省下来的空间会被
#: 目录本身一点点吃回去。折叠掉的段**仍然可以按号取回**(取回不看目录在不在窗口里),
#: 折叠行会把范围说出来,模型知道 1..N 都还在。
MAX_VISIBLE_SEGMENTS = 6

#: 给摘要器的格式要求 —— 摘要要当**目录**用，不是当散文用。
#:
#: 借 ACM 的 ``<memory>`` 块思路:结构化、可扫读、点明"这一段里有什么"，这样模型才
#: 判断得出该 query 哪个段号。散文式摘要读起来顺,但回答不了"我要找的东西在不在这
#: 一段里"。
SUMMARY_FORMAT_HINT = (
    "用要点形式输出，每行一条，覆盖：本段讨论的主题、定下的结论与约束、"
    "出现过的关键事实与数字、未完成的待办。不要写成段落，不要复述原话。"
)


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


def should_compact(messages: List[Dict[str, Any]], n_ctx: int, marks: Optional[List[int]] = None) -> bool:
    """该压了吗。窗口算不出来时**一律不压** —— 判不了不动手。

    两个触发器，盯的是**不同的失败形态**
    ====================================
    * **水位**（占用 ≥ 七成）——多轮小增量慢慢涨上去；
    * **跑道**（照这个烧法只够再跑一两轮）——单轮大增量一步跨过去。

    只有水位是不够的，而且不是把阈值调低能补的::

        第 9 轮：58%   ← 水位触发器不响
        第 10 轮：一个工具返回 30 KB 日志
        第 10 轮末：118%  ← 已经被静默截断

    水位在 58% 和 118% 之间**没有采样点**，它从来没有机会响。把阈值从 0.7 调到 0.5
    只是把同一个洞往前挪：遇到更大的单次增量照样跨过去。

    Args:
        marks: 历次占用观测。给了才有跑道判据；不给就只看水位（**不是**假装跑道很长）。
    """
    if n_ctx <= 0 or len(messages) <= KEEP_RECENT_MESSAGES + 1:
        return False
    if context_utilization(messages, n_ctx) >= COMPACT_AT_UTILIZATION:
        return True
    return _runway_is_short(messages, n_ctx, marks)


def _runway_is_short(messages: List[Dict[str, Any]], n_ctx: int, marks: Optional[List[int]]) -> bool:
    """速率触发器：判不了一律 ``False``（判不了不动手）。"""
    if not marks:
        return False
    try:
        from core.context_runway import project  # noqa: PLC0415
        from core.context_trim import reply_headroom_tokens  # noqa: PLC0415

        used = estimate_tokens(messages) + reply_headroom_tokens()
        runway = project(used, n_ctx, marks)
    except Exception as exc:  # noqa: BLE001
        logger.debug("跑道不可评估(退回只看水位): %s", exc)
        return False
    if runway.is_short:
        logger.info(
            "跑道只剩约 %d 轮（每轮约 %d token，余 %d）—— 提前压缩，不等水位到七成",
            runway.rounds_left,
            runway.burn_per_round,
            runway.tokens_left,
        )
        return True
    return False


def model_manages_own_context(tier_key: str = "") -> bool:
    """这一档的主脑够不够格**自己**管上下文 —— 决定要不要把两个记忆工具暴露给它。

    为什么不是"给所有档都装上"
    ==========================
    ACM 自己的消融给了答案：4B 模型做完**同样的后训练**，准确率也只有 3.4%，而 9B
    是 57.3%。原因不是它不会调工具，是它**只跑两轮就终止**(一次浅搜 + 一次猜)——
    轨迹根本没长到需要管理上下文，工具没有用武之地。

    "何时记笔记"是一条长程策略，需要一定模型容量才学得会，不是给小模型挂两个工具
    就会自动涌现的。给 A 档(Gemma 4 E2B/E4B，2B/4B 级)挂上去，唯一确定的效果是
    **工具表变长、装配下限抬高、窗口反而更紧** —— 拿真实成本换一个不会发生的收益。

    所以按档位分：

    * **A 档**(轻量单模型) → 不开。压缩全部由七成阈值自动触发；
    * **B 档**(MiniCPM-o 4.5，全模态单模型) → 开。窗口 40960 够用；
    * **C / D 档**(双模型，推理位 35B-A3B / Qwythos-9B) → 开。ACM 验证过的正是
      9B 这一档。

    注意这**不影响**自动压缩:自动压缩在每个档位都在跑(见模块文档"谁来决定压缩
    时机")。这一栏只决定"要不要**再**给模型一个自己动手的入口"。
    """
    try:
        from core.model_catalog import load_tier  # noqa: PLC0415

        key = (tier_key or load_tier() or "").strip().upper()
    except Exception as exc:  # noqa: BLE001 — 问不出档位就按不开，宁可少给一个工具
        logger.debug("档位不可评估(按不开自主管理处理): %s", exc)
        return False
    return key in ("B", "C", "D")


def _segment_marker(segment_id: int, summary: str) -> str:
    return f"{ANCHOR_MARKER} 第 {segment_id} 段\n{summary}".rstrip()


def _segment_id_of(message: Dict[str, Any]) -> Optional[int]:
    """这条消息是第几段的目录；不是目录返回 ``None``。"""
    if not isinstance(message, dict):
        return None
    text = str(message.get("content") or "")
    if ANCHOR_MARKER not in text:
        return None
    m = re.search(r"第 (\d+) 段", text)
    return int(m.group(1)) if m else None


def _is_segment_marker(message: Dict[str, Any]) -> bool:
    return isinstance(message, dict) and ANCHOR_MARKER in str(message.get("content") or "")


def visible_segment_ids(messages: List[Dict[str, Any]]) -> List[int]:
    """当前窗口里挂着哪几段的目录，升序。"""
    out = [sid for m in messages if (sid := _segment_id_of(m)) is not None]
    return sorted(set(out))


def restore_segments(messages: List[Dict[str, Any]], session_id: str) -> int:
    """进程重启后，把这个会话已归档各段的**目录**贴回上下文。贴了几条就返回几。

    为什么必须有这一步
    ==================
    上一版做了写侧(``save_anchor``)也做了读侧函数(``load_anchor``)，但**没有任何
    一处生产代码调用读侧** —— 摘要在磁盘上安安静静地攒着，而重启后的会话该失忆
    照样失忆，且不报任何错。这一版把读侧真正接进 ``_react_loop``。

    什么时候贴、什么时候不贴
    ========================
    只在**真的失忆了**的时候贴：窗口里已经有段目录 → 不贴(这一轮已经带着了)；
    消息还很长 → 不贴(历史本身就在窗口里，目录是它的**有损副本**，两份都在等于让
    模型看到同一段过去的两个版本)。

    宁可少贴一次(退回失忆)，也不要多贴一次(制造一段自相矛盾的过去)。

    注意贴回来的**只是目录**：原文一直在归档里，模型随时可以按段号取回 —— 这正是
    "无损"跟上一版"存了摘要就算连续"的区别。
    """
    if not session_id or any(_is_segment_marker(m) for m in messages):
        return 0
    if len(messages) > KEEP_RECENT_MESSAGES + 1:
        return 0
    try:
        from core.context_archive import list_segments, load_segment  # noqa: PLC0415

        seg_ids = list_segments(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("归档段列举失败(按没有处理): %s", exc)
        return 0
    if not seg_ids:
        return 0

    insert_at = 0
    while (
        insert_at < len(messages)
        and isinstance(messages[insert_at], dict)
        and messages[insert_at].get("role") == "system"
    ):
        insert_at += 1

    added = 0
    for sid in _collapse(seg_ids):
        seg = load_segment(session_id, sid)
        if seg is None:
            continue
        messages.insert(
            insert_at + added, {"role": "system", "content": _segment_marker(sid, str(seg.get("summary") or ""))}
        )
        added += 1
    if added:
        logger.info(
            "会话 %s 重启后取回了 %d 段目录（共归档 %d 段，原文都还在，可按段号取回）",
            session_id,
            added,
            len(seg_ids),
        )
    return added


def _collapse(seg_ids: List[int]) -> List[int]:
    """段太多时只显示最近几段的目录 —— 更早的仍可按号取回，只是不占窗口。"""
    return seg_ids[-MAX_VISIBLE_SEGMENTS:] if len(seg_ids) > MAX_VISIBLE_SEGMENTS else list(seg_ids)


def _split_for_compaction(
    messages: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """切成 (系统头, 要压的那一段, 保留原文的最近几轮)。

    系统头(role=system 的开头几条 + 已有的段目录)必须原样留着 —— 它们是人格与
    工具契约,压掉会直接改变模型的行为,那不是"省点空间",是换了个 Agent。
    段目录同样不压:它是**上一次压缩的产物**，再压一次就成了摘要的摘要 —— 那正是
    这一版要避开的漂移。
    """
    head: List[Dict[str, Any]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if not (isinstance(m, dict) and (m.get("role") == "system" or _is_segment_marker(m))):
            break
        head.append(m)
        i += 1
    body = messages[i:]
    if len(body) <= KEEP_RECENT_MESSAGES:
        return head, [], body
    return head, body[:-KEEP_RECENT_MESSAGES], body[-KEEP_RECENT_MESSAGES:]


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
    summarize: Callable[[str], str],
    *,
    session_id: str = "",
    persisted_ok: bool = True,
) -> int:
    """**原地**把远处的历史归档成一段，窗口里换成一条目录。返回压掉的消息条数。

    与上一版的关键区别：**这一次是无损的。**

    原文整段落盘到 :mod:`core.context_archive`（段号可寻址），窗口里留的是
    ``[归档段 N] 摘要``。摘要只负责让模型判断"该翻哪一段"，细节随时可以用
    ``context__query_memory(N, 查询)`` 从原文取回。

    上一版是**永久删除**：摘要一生成原文就没了，模型再也问不回来 —— 那正是 ACM
    论文里被单列出来做消融的退化变体。

    Args:
        messages: 会话消息列表，**原地修改**。
        summarize: ``(这一段的原文) -> 摘要``。由调用方注入 —— 本模块不自己去调
            模型:那会让它依赖某一条具体的推理路径，而压缩这件事在云端主脑和本地
            主脑上都该能用。

            **签名从 ``(prior, fresh)`` 改成了 ``(fresh)``**:上一版每次压缩都要把
            已有摘要一起交给模型去"并"，是为了防反复重摘导致的漂移；现在每段只从
            **原文**摘一次，压根不会漂，也就不需要 prior 了。
        session_id: 归档挂在哪个会话下。**空则拒绝压缩** —— 没有会话 id 就没处
            归档，压出来的会是不可逆的删除，而调用方和模型都会以为它可逆。
        persisted_ok: 调用方声明"该落库的这一轮已经落过库了"。``False`` 时**拒绝
            压缩** —— 见模块文档"先落库再压缩"。

    Returns:
        被归档的消息条数（0 = 没压）。
    """
    if not persisted_ok:
        logger.warning("持久层尚未确认收到这一段，拒绝压缩 —— 先落库再压缩，压缩不可逆")
        return 0
    if not session_id:
        # 上一版这里是"仍然压，只是重启后不连续"。现在不行了:没有会话 id 就归档
        # 不了,而归档不了的压缩**就是删除**。宁可占着窗口。
        logger.warning("没有会话 id，无处归档，拒绝压缩 —— 归档不了的压缩就是不可逆删除")
        return 0

    head, to_compact, recent = _split_for_compaction(messages)
    if not to_compact:
        return 0

    fresh = "\n".join(f"{m.get('role', '?')}: {str(m.get('content') or '')[:2000]}" for m in to_compact)
    try:
        summary = summarize(fresh)
    except Exception as exc:  # noqa: BLE001 — 压不动就**不压**，绝不丢
        logger.warning("摘要生成失败，本次不压缩(宁可占着窗口也不丢内容): %s", exc)
        return 0
    if not summary or not summary.strip():
        logger.warning("摘要为空，本次不压缩")
        return 0
    summary = summary.strip()

    # 先归档、再删 —— 顺序不能反。归档失败就整个放弃这次压缩:此时删掉原文,
    # 窗口里那条目录会指向一个**不存在的段**,模型按号去查只会查到空,而它以为
    # 自己还有后路。
    try:
        from core.context_archive import archive_segment  # noqa: PLC0415

        seg_id = archive_segment(session_id, to_compact, summary)
    except Exception as exc:  # noqa: BLE001
        logger.warning("归档不可用，本次不压缩(压了就是不可逆删除): %s", exc)
        return 0
    if seg_id is None:
        return 0

    head.append({"role": "system", "content": _segment_marker(seg_id, summary)})
    head = _trim_visible_markers(head)
    messages[:] = head + recent
    logger.info(
        "上下文压缩：%d 条原文归档为第 %s 段（摘要 %d 字，原文可按段号取回）",
        len(to_compact),
        seg_id,
        len(summary),
    )
    return len(to_compact)


_FOLD_RE = re.compile(r"更早的第 (\d+)[–-](\d+) 段目录已折叠")


def _is_fold_note(message: Dict[str, Any]) -> bool:
    return bool(_FOLD_RE.search(str(message.get("content") or "")))


def _trim_visible_markers(head: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """段目录超过上限时，把更早的折叠成**一行**范围。

    折叠掉的段**取回不受影响** —— ``query_memory`` 按号读归档文件，不看目录还在不在
    窗口里。折叠行必须把范围说出来，否则模型会以为更早的段不存在了，而它们其实
    一条不少地躺在归档里。

    折叠行自己也要被回收
    ====================
    第一版漏了这一条:折叠行带着 ``ANCHOR_MARKER`` 但**不带段号**，于是下一轮统计
    "有几条目录"时它不算数、清理时也轮不到它 —— 每压一次就多留一行折叠行，压到
    第九次窗口里躺着 6 条目录 + 3 行折叠行。**为省窗口而做的东西自己在占窗口**，
    而且不会有任何一条错误。所以每次都把旧折叠行摘掉、按累计范围重写一行。
    """
    folded_before: List[int] = []
    for m in head:
        if (hit := _FOLD_RE.search(str(m.get("content") or ""))) is not None:
            folded_before += [int(hit.group(1)), int(hit.group(2))]
    head = [m for m in head if not _is_fold_note(m)]

    marked = [(i, sid) for i, m in enumerate(head) if (sid := _segment_id_of(m)) is not None]
    if len(marked) <= MAX_VISIBLE_SEGMENTS and not folded_before:
        return head

    drop_idx = {i for i, _ in marked[: max(0, len(marked) - MAX_VISIBLE_SEGMENTS)]}
    dropped = sorted(folded_before + [sid for i, sid in marked if i in drop_idx])
    if not dropped:
        return head
    kept = [m for i, m in enumerate(head) if i not in drop_idx]
    note = {
        "role": "system",
        "content": (
            f"{ANCHOR_MARKER} 更早的第 {dropped[0]}–{dropped[-1]} 段目录已折叠" f"（原文仍在归档里，可直接按段号取回）"
        ),
    }
    first_marker = next((i for i, m in enumerate(kept) if _is_segment_marker(m)), len(kept))
    kept.insert(first_marker, note)
    return kept


def fuel_gauge(
    messages: List[Dict[str, Any]], n_ctx: int, reply_headroom: int = 0, marks: Optional[List[int]] = None
) -> str:
    """给模型看的**油表**：这次装配占了多少、窗口有多大。窗口未知返回空串。

    为什么要报给模型
    ================
    ACM 的做法:每个工具结果末尾追加 ``[CURRENT CONTEXT TOKEN: N]``。没有这个数,
    模型**根本无从判断**该不该压缩 —— 它看不见自己的上下文有多满,只能凭感觉,
    而"凭感觉"的结果就是要么从不压(撑爆被静默截断)、要么一上来就压(白丢细节)。

    N 取**保守上界**：当前装配量 + 这一轮回复可能生成的最大 token。ACM 那边加的是
    ``max_new_tokens``，理由一样 —— 这样 N 可以直接跟窗口比：``N ≈ 窗口`` 就意味着
    **下一次生成会失败**，必须现在就压。少加这一项的话，模型会在"看起来还剩一点"
    的时候撞上截断。

    这个口径与 :func:`core.context_trim.assembled_token_demand` 里的"回复留白"是
    同一件事，所以调用方直接把那个数传进来，不在这里另算一份。
    """
    if n_ctx <= 0:
        return ""
    used = estimate_tokens(messages) + max(0, int(reply_headroom or 0))
    pct = int(used * 100 / n_ctx)

    # 跑道：水位说"现在多满"，跑道说"照这个烧法还剩多远"。后者才是模型真正需要的
    # 那个量 —— 58% 听着还宽裕，但如果每轮烧掉窗口的三成，那就是"下一轮就溢出"。
    runway_text = ""
    try:
        from core.context_runway import project  # noqa: PLC0415

        runway_text = project(used, n_ctx, marks).render()
    except Exception as exc:  # noqa: BLE001 — 报不出跑道就只报水位，绝不报假数
        logger.debug("跑道渲染跳过: %s", exc)

    hint = ""
    if pct >= int(COMPACT_AT_UTILIZATION * 100):
        hint = "（已过压缩阈值：该整理上下文了）"
    return f"[当前上下文 token: {used} / 窗口 {n_ctx}（{pct}%）{hint}{runway_text}]"
