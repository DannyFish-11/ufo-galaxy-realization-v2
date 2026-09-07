"""core/memory/media_store.py — 记忆里的媒体**真的留得住**。

## 这个模块补的是一个真缺口

在它之前,``UnifiedMemory.remember_media()`` 是这么走的:

    base64 → tempfile.mkstemp() → 各后端摄入 → **finally: 删掉临时文件**

而它同时往 metadata 里记了 ``media_path``。那个路径指向的文件在函数返回的那一刻
就**保证已经不存在**了。于是:

* 后端(CLIP/CLAP)在摄入那一刻读到了字节,把向量算出来了 —— 这部分是对的,
  "用一句话召回一张截图"确实成立;
* 但**召回之后想把那张图拿回来,没有材料**。metadata 里那个路径是个空头支票,
  谁照着它去 open() 都只会拿到 FileNotFoundError。

所以记忆一直是"跨模态检索 + 文字回放":找得到,但看不见。要把它升成真的全模态,
第一件事不是改召回,是**让字节留得下来**。

## 设计

内容寻址(sha256 前 32 位做 id)。同一张图存两次只占一份 —— 桌面闭环每一步都截图,
同一个界面会反复出现,不去重的话磁盘涨得比记忆本身快得多。

**有上限,而且逐出要留痕。** 记忆库可以无限长(文本很小),媒体不行。超出上限时按
最久未被访问逐出;被逐出之后 ``load()`` 返回 ``None`` —— 调用方据此说"这条记忆的
图已经不在了",而不是假装它还在。

**不进 git,不进备份的默认路径。** 默认落在 ``runtime/memory_media/``,与
``runtime/`` 下其它运行时产物同一处置。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.Memory.MediaStore")

#: 媒体库的默认容量(MB)。超过就按最久未访问逐出;设成 0 表示不限。
#:
#: 512MB 是这么估的:桌面闭环一步一张 1080p JPEG 约 200KB,一次二十步的任务约 4MB;
#: 环境感知那条抽帧更稀。512MB 够存上百次任务的现场,而在任何一台跑得动这套系统的
#: 机器上都不算负担。嫌大就调 GALAXY_MEMORY_MEDIA_MB。
DEFAULT_BUDGET_MB = 512

_INDEX_NAME = "index.json"


def _root() -> Path:
    return Path(os.getenv("GALAXY_MEMORY_MEDIA_DIR", "") or "runtime/memory_media")


def _budget_bytes() -> int:
    """上限,字节。``0`` 表示**不限**(明确的语义,不是"没配")。

    小数不截断:第一版写的是 ``int(float(raw))``,于是填 ``0.5`` 会被截成 0,
    而 0 在这里的意思是"不限" —— 想把库限到 512KB 的人,拿到的是无限。
    这条是被自己的逐出用例抓出来的(它填 0.001MB 想造一个很小的库,结果一个都没逐出)。
    """
    raw = os.getenv("GALAXY_MEMORY_MEDIA_MB", "") or str(DEFAULT_BUDGET_MB)
    try:
        return max(0, int(float(raw) * 1024 * 1024))
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_MB * 1024 * 1024


def enabled() -> bool:
    """媒体库开着没有。关掉时 ``store()`` 直接返回空 —— 检索照常工作,只是不留字节。

    留这个开关是给"磁盘紧张 / 不想在盘上留下截图"那种场合的。关掉之后记忆退回
    改这一版之前的样子:找得到,看不见。**这件事会在日志里说一次**,免得有人以为
    回放坏了。
    """
    return (os.getenv("GALAXY_MEMORY_MEDIA", "1") or "1").strip().lower() in ("1", "true", "yes", "on")


def _index_path() -> Path:
    return _root() / _INDEX_NAME


def _load_index() -> Dict[str, Dict]:
    try:
        return json.loads(_index_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 — 索引坏了不该让记忆整个不能用
        logger.warning("媒体库索引读不出来(%s),按空索引继续。已有文件不会被删,只是暂时找不回。", exc)
        return {}


def _save_index(index: Dict[str, Dict]) -> None:
    try:
        _root().mkdir(parents=True, exist_ok=True)
        tmp = _index_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_index_path())
    except Exception as exc:  # noqa: BLE001
        logger.warning("媒体库索引写不下去(%s):这一条的字节留下了,但下次可能找不回它。", exc)


def _evict_if_needed(index: Dict[str, Dict]) -> None:
    """超预算就按**最久未访问**逐出,并留痕。

    不按"最早存入"逐出:一张反复被召回的界面截图,存得早不代表没用;而一张存进来
    之后再没被想起过的,留着只是占地方。
    """
    budget = _budget_bytes()
    if budget <= 0:
        return  # 0 = 不限。明确的语义,见 _budget_bytes()。
    total = sum(int(e.get("size", 0)) for e in index.values())
    if total <= budget:
        return
    victims = sorted(index.items(), key=lambda kv: kv[1].get("atime", 0))
    freed = 0
    dropped = 0
    for media_id, entry in victims:
        if total - freed <= budget:
            break
        try:
            (_root() / entry["name"]).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("逐出 %s 失败(跳过): %s", media_id, exc)
            continue
        freed += int(entry.get("size", 0))
        dropped += 1
        index.pop(media_id, None)
    if dropped:
        logger.info(
            "媒体库超出 %d MB,按最久未访问逐出 %d 项(释放 %.1f MB)。"
            "被逐出的那些记忆仍然检索得到,只是图/音回放不出来了。",
            budget // (1024 * 1024),
            dropped,
            freed / 1024 / 1024,
        )


def store(data_b64: str, *, mime: str = "", modality: str = "image") -> str:
    """存一段媒体,返回 ``media_id``。存不下或没开时返回空串。

    **空串与 id 是两种结论**,调用方要分开处理:拿到空串说明这条记忆没有可回放的
    字节,它应该如实不写 media_id,而不是写一个查不到的。
    """
    if not enabled() or not data_b64:
        return ""
    try:
        raw = base64.b64decode(data_b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("媒体 base64 解不开,不入库: %s", exc)
        return ""
    if not raw:
        return ""

    media_id = hashlib.sha256(raw).hexdigest()[:32]
    from core.memory._media import _ext_for  # noqa: PLC0415 —— 后缀换算只此一处

    name = f"{media_id}{_ext_for(mime, modality)}"
    index = _load_index()
    now = time.time()

    if media_id in index:
        # 同一份字节存过了。只更新访问时间 —— 内容寻址的意义就在这:桌面闭环
        # 每一步都截图,同一个界面会反复出现,不去重的话磁盘涨得比记忆还快。
        index[media_id]["atime"] = now
        _save_index(index)
        return media_id

    try:
        _root().mkdir(parents=True, exist_ok=True)
        (_root() / name).write_bytes(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("媒体写不进库(%s):这条记忆仍然可检索,但回放不出来。", exc)
        return ""

    index[media_id] = {"name": name, "mime": mime, "modality": modality, "size": len(raw), "atime": now}
    _evict_if_needed(index)
    _save_index(index)
    return media_id


def load(media_id: str) -> Optional[Tuple[str, str]]:
    """按 id 取回 ``(base64, mime)``。取不到返回 ``None``。

    ``None`` 的意思是"这条记忆的字节已经不在了"(被逐出、被手工删了、或者当初
    就没存下)。调用方应当**照实说**,而不是把它当成"这条记忆没有媒体" ——
    那两件事不一样,前者是丢了,后者是本来就没有。
    """
    if not media_id:
        return None
    index = _load_index()
    entry = index.get(media_id)
    if not entry:
        return None
    path = _root() / entry["name"]
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        logger.info("媒体 %s 的文件不在了(索引里还记着),按丢失处理。", media_id)
        index.pop(media_id, None)
        _save_index(index)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("媒体 %s 读失败: %s", media_id, exc)
        return None
    entry["atime"] = time.time()
    _save_index(index)
    return base64.b64encode(raw).decode("ascii"), entry.get("mime", "")


def stats() -> Dict[str, float]:
    """库里现在有多少 —— 给面板和排查用。"""
    index = _load_index()
    total = sum(int(e.get("size", 0)) for e in index.values())
    return {
        "items": len(index),
        "bytes": total,
        "megabytes": round(total / 1024 / 1024, 2),
        "budget_megabytes": _budget_bytes() // (1024 * 1024),
    }


def replay_enabled() -> bool:
    """召回时**要不要把图/音真的喂回模型**。默认不要。

    与 ``core.agent.multimodal_messages.native_audio_wanted()`` 同一套分寸,理由也
    一样:回放很贵。一次召回带三条记忆,每条一张 1080p 截图,就是几千个视觉 token,
    而**绝大多数轮次用不上** —— caption 已经说了"上次在这个界面点保存没反应",
    模型据此就能改路子,不必再看一眼那张图。

    什么时候值得开:要模型**看出 caption 没写下来的东西**的时候(按钮到底是灰的
    还是不见了、报错弹窗上那行小字是什么)。那是显式的判断,所以做成显式的开关:

    * ``GALAXY_MEMORY_REPLAY_MEDIA=1`` —— 一律回放;
    * 调用方在这一轮显式要(见 ``media_parts_for(..., force=True)``)。

    默认关还有一层:回放的图要经过 ``core.modality`` 那两道闸(型号收不收、传输
    装不装得下)。默认开的话,一个纯文本型号上的每次召回都会白算一遍再被摘掉。
    """
    return (os.getenv("GALAXY_MEMORY_REPLAY_MEDIA", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def media_parts_for(hits, *, force: bool = False, max_items: int = 2) -> list:
    """把召回结果里的媒体还原成**仓内的规范表示**(OpenAI content 部件)。

    返回的部件直接拼进 content 数组即可 —— 这一轮的型号收不收、这条传输装不装得下,
    由 ``core.modality.prepare`` 统一判(那是唯一的头),这里不重复判一遍。

    ``max_items`` 卡得很紧(默认 2)。召回本身最多给三条,每条一张图就是三张;
    而"看一眼上次那个界面"通常一张就够,两张是给"之前 vs 之后"留的。

    **字节丢了要说出来**,不是当作没有媒体:被逐出、被手工删掉、当初就没存下,
    这三件事对使用者是同一个现象(看不到图),但对排查完全不同。
    """
    if not force and not replay_enabled():
        return []
    parts: list = []
    missing = 0
    for hit in hits or ():
        if len(parts) >= max_items:
            break
        meta = getattr(hit, "metadata", None) or {}
        media_id = meta.get("media_id") or ""
        if not media_id:
            continue
        loaded = load(media_id)
        if loaded is None:
            missing += 1
            continue
        data_b64, mime = loaded
        modality = meta.get("modality") or getattr(hit, "modality", "image") or "image"
        if modality == "audio":
            from core.agent.multimodal_messages import _audio_format  # noqa: PLC0415

            parts.append({"type": "input_audio", "input_audio": {"data": data_b64, "format": _audio_format(mime)}})
        else:
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime or 'image/jpeg'};base64,{data_b64}"}})
    if missing:
        logger.info(
            "召回的 %d 条记忆记着有媒体,但字节已经不在库里了(被逐出/被删/当初没存下)。"
            "这些记忆的文字部分照常可用,只是看不到画面。",
            missing,
        )
    return parts
