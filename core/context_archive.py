"""core/context_archive.py — 被压掉的那一段，**原文整段留着**
================================================================

修的是什么
==========
上一轮的 :mod:`core.context_compaction` 做的是**永久删除**:摘要生成好，原文就从
消息列表里删掉了，磁盘上只留一条摘要文本。模型再也没有任何办法翻回去。

这正是 ACM 那篇论文里被单列出来做消融的那个退化变体（源码里的
``disable_query_memory`` / ``MANAGE_CONTEXT_TOOL_NOQUERY``）——**关掉检索之后，
"压缩"就退化成"删除"**。我上一轮做的就是那个变体，缺的正是让"无损"这两个字
成立的另一半。

这个模块补的就是那一半：压缩之前，把**完整的原始消息**整段落盘。

为什么必须是原文，不能是摘要
============================
摘要是有损的，而且损在哪儿**当时不知道**:压缩发生在第 12 轮，而第 40 轮才会有人
问起第 5 轮那个约束的确切措辞。摘要器在第 12 轮无从判断哪句话以后会要紧。

所以口径是:

* 窗口里放的是**目录**(段号 + 摘要)——它只负责让模型知道"有这么一段、大概讲了
  什么、编号是几"；
* 真正的细节永远从**归档原文**里取回(见 ``query_memory``)。

摘要因此不再承担"替代历史"的职责，只承担"帮模型判断该翻哪一段"。这也是为什么
这一版**不再把摘要合并成一条**:合并是为了防"反复重新摘导致越压越漂"，而每段只
从原文摘一次的话，根本不会漂——那是我上一版自己造出来的问题。

不可逆性反过来了
================
以前丢的是窗口里的副本(磁盘上还有摘要)；现在丢的是**唯一的原文**。所以这个目录
不属于任何"临时文件"或"缓存"语义:**没有任何按时间/容量自动淘汰的路径**，
唯一的删除入口是 :func:`drop_session`，而它只被"清除对话"那条用户明确要求的路调用
(见该函数的说明)——不能让某个 tmp 清理路径顺手带走，也不该由这一层自作主张淘汰。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.ContextArchive")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 归档根目录。与 ``runtime/`` 下其它"这台机器的运行时事实"同级。
#:
#: **不是缓存**:这里存的是被压掉那段对话的唯一原文，删了就真没了。
_ROOT = PROJECT_ROOT / "runtime" / "context_archive"

#: 会话 id 里允许出现的字符 —— 其余一律换成 ``_``。
#:
#: 这不是洁癖:会话 id 来自调用方，直接拿去拼路径就是一条目录穿越
#: (``../../etc``)。归档写的是文件、读的也是文件，两头都要过这一关。
#:
#: **但白名单本身不够。** 这一条第一版就是只有白名单，而白名单里放行了 ``.`` ——
#: 于是 ``../../etc/evil`` 因为斜杠被替换而失效(变成 ``.._.._etc_evil``)，
#: **裸的 ``..`` 却原样穿过**:``_ROOT / ".."`` 就是归档根的父目录，也就是
#: ``runtime/``。那意味着 ``drop_session("..")`` 会 ``rmtree`` 掉整个 ``runtime/``
#: (模型状态、实测记录、全部会话归档)，而 ``drop_session(".")`` 会删掉所有人的归档。
#:
#: 教训是:**消毒之后必须再验一次落点**，不能靠"我把危险字符都替换掉了"这种推理 ——
#: 那种推理漏掉的恰恰是不含危险字符的那几个(``.`` / ``..``)。落点检查见 :func:`_dir`。
_SAFE = re.compile(r"[^0-9A-Za-z_.-]")

#: ``query_memory`` 单次最多把多少字符的原文喂给提取调用。
#:
#: 归档段可能很大(一段里有好几个全文工具结果)，整段塞进提取调用会做两件坏事:
#: 把这次提取的窗口自己撑爆，以及让提取模型在噪声里找针。超出就按段内消息**从后
#: 往前**取——近的那几条通常是结论所在。
MAX_QUERY_CHARS = 24000


def _safe(session_id: str) -> str:
    return _SAFE.sub("_", session_id.strip())[:120]


def _dir(session_id: str) -> Optional[Path]:
    """这个会话的归档目录；**任何落不到归档根正下方的一律返回 ``None``**。

    两道，缺一不可:

    1. 字符白名单(:data:`_SAFE`)——挡掉斜杠、空字节之类；
    2. **落点检查** —— 消毒之后再确认它确实是 ``_ROOT`` 的**直接子目录**。

    第二道不是冗余。白名单放行了 ``.``，所以 ``..`` 能原样穿过第一道，而
    ``_ROOT / ".."`` 就是归档根的父目录。只靠第一道的推理("危险字符都换掉了")
    漏掉的正是这几个**不含危险字符**的输入。

    用"父目录必须恰好是 ``_ROOT``"而不是 ``is_relative_to``:后者对 ``_ROOT`` 自身
    也成立，而 ``drop_session(".")`` 落在 ``_ROOT`` 上就会删掉所有人的归档。
    """
    sid = _safe(session_id)
    if not sid or sid.strip(".") == "":
        return None
    candidate = _ROOT / sid
    try:
        if candidate.resolve().parent != _ROOT.resolve():
            return None
    except OSError:  # 路径解析不了(权限/循环链接)就当它不合法
        return None
    return candidate


def _entry_of(m: Dict[str, Any]) -> Dict[str, Any]:
    """一条消息的**归档形态** —— 保留重放/检索所需的全部字段。

    ``tool_calls`` / ``tool_call_id`` 必须一起留着:少了它们，归档下来的就不是一段
    可理解的对话，而是一堆孤立的文本 —— 谁调了什么、这条结果回的是哪一次调用，
    全都对不上了。
    """
    entry: Dict[str, Any] = {"role": str(m.get("role", "?")), "content": m.get("content", "")}
    if m.get("tool_calls"):
        entry["tool_calls"] = m["tool_calls"]
    if m.get("tool_call_id"):
        entry["tool_call_id"] = m["tool_call_id"]
    if m.get("name"):
        entry["name"] = m["name"]
    return entry


def next_segment_id(session_id: str) -> int:
    """这个会话下一段的编号（从 1 开始）。"""
    return len(list_segments(session_id)) + 1


def list_segments(session_id: str) -> List[int]:
    """这个会话已经归档了哪几段，升序。"""
    d = _dir(session_id)
    if not d or not d.is_dir():
        return []
    out: List[int] = []
    for p in d.glob("segment_*.json"):
        try:
            out.append(int(p.stem.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(out)


def archive_segment(session_id: str, messages: List[Dict[str, Any]], summary: str) -> Optional[int]:
    """把 *messages* 整段原文落盘，返回段号；**落不下来返回 ``None``**。

    返回 ``None`` 时调用方**必须放弃这次压缩** —— 归档失败还照压，压出来的就是
    不可逆的删除，而调用方和模型都会以为它是可逆的。那种"以为有后路其实没有"
    比一开始就不压危险得多。
    """
    d = _dir(session_id)
    if d is None or not messages:
        return None
    seg_id = next_segment_id(session_id)
    payload = {
        "segment_id": seg_id,
        "summary": str(summary or ""),
        "message_count": len(messages),
        "entries": [_entry_of(m) for m in messages if isinstance(m, dict)],
    }
    try:
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_json(d / f"segment_{seg_id}.json", payload, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "归档段 %s 落盘失败，本次**不压缩**（压了就是不可逆删除，而模型会以为还能翻回去）：%s",
            seg_id,
            exc,
        )
        return None
    logger.info("已归档第 %s 段：%d 条原文（会话 %s）", seg_id, len(messages), session_id)
    return seg_id


def load_segment(session_id: str, segment_id: int) -> Optional[Dict[str, Any]]:
    """取回某一段的完整归档；不存在返回 ``None``。"""
    d = _dir(session_id)
    if d is None:
        return None
    try:
        p = d / f"segment_{int(segment_id)}.json"
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("归档段 %s 读取失败: %s", segment_id, exc)
        return None


def render_segment_text(segment: Dict[str, Any], max_chars: int = MAX_QUERY_CHARS) -> str:
    """把一段归档渲染成可读文本，超长时**从后往前**保留。

    从后往前而不是从前往后:一段对话里结论通常在后面(工具跑完了、模型下了判断)，
    截头保尾比截尾保头更可能留住要找的东西。截掉了要**说出来**，否则提取模型会
    以为自己看到的是全部。
    """
    entries = segment.get("entries") or []
    lines: List[str] = []
    total = 0
    truncated = False
    for m in reversed(entries):
        if not isinstance(m, dict):
            continue
        piece = f"{m.get('role', '?')}: {str(m.get('content') or '')}"
        if total + len(piece) > max_chars:
            truncated = True
            break
        lines.append(piece)
        total += len(piece)
    lines.reverse()
    if truncated:
        lines.insert(0, f"…[本段更早的部分未载入，原文共 {len(entries)} 条；需要时可再查一次并说明要找更早的内容]…")
    return "\n".join(lines)


def drop_session(session_id: str) -> int:
    """删掉这个会话的全部归档，返回删了几段。

    为什么这个函数必须存在、而且必须被"清除对话"那条路调用
    ======================================================
    这个模块新引入了一处**存用户原话的地方**。而 ``DELETE /api/v1/ai/conversation/
    {session_id}``（"清除对话记忆"）此前只清对话记忆那一份 —— 它不知道归档的存在。

    不接上去的后果不是"文件多了"，是**"清除"变成一句假话**:用户点了清除，而他说过
    的每一句原话仍然完整躺在 ``runtime/context_archive/`` 里。新加一个存储却不接进
    已有的清除路径，就是在用户背后留了一份他以为已经删掉的副本。

    这也是这一层唯一的删除入口:归档不是缓存，没有任何按时间/容量自动淘汰的路径 ——
    要删只能是有人**明确要求**删掉这个会话。
    """
    d = _dir(session_id)
    if d is None or not d.is_dir():
        return 0
    count = len(list_segments(session_id))
    try:
        shutil.rmtree(d)
    except OSError as exc:
        logger.warning("会话 %s 的归档清除失败（原话仍在磁盘上）: %s", session_id, exc)
        return 0
    logger.info("已清除会话 %s 的全部归档：%d 段原文", session_id, count)
    return count
