"""core/memory/unified.py — 统一记忆门面：路由读写到已启用的后端。"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.Unified")


class UnifiedMemory:
    """聚合多个 MemoryProvider；写入广播到全部，召回合并去重后按分数排序。"""

    def __init__(self, providers: List[MemoryProvider]) -> None:
        self.providers: List[MemoryProvider] = []
        for p in providers:
            try:
                if p.available():
                    self.providers.append(p)
            except Exception as exc:  # noqa: BLE001
                logger.debug("provider availability check failed: %s", exc)

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def backend_names(self) -> List[str]:
        return [p.backend_name for p in self.providers]

    def remember(self, content: str, **kwargs) -> None:
        """写进记忆。**所有后端的收口点**,所以来源在这里盖。

        为什么盖在这一层而不是各 provider 里:各后端对 metadata 的处置不同,
        逐个去改必然漏掉一个,而漏的表现是"某个后端里的记忆没有来源" ——
        那正好是检索时最需要来源的那一条。判据见 core/memory_provenance.py。
        """
        from core.memory_provenance import stamp  # noqa: PLC0415

        # origin 是本层的参数,**不透传给 provider** —— 各 provider 的签名里没有
        # 它,漏 pop 会让每一次写入都 TypeError。
        origin = kwargs.pop("origin", None)
        try:
            content, kwargs["metadata"] = stamp(content, origin=origin, metadata=kwargs.get("metadata"))
        except Exception as exc:  # noqa: BLE001 — 盖不上章也要让记忆写进去
            logger.warning("记忆来源盖章失败,这条将没有来源标记: %s", exc)

        for p in self.providers:
            try:
                p.remember(content, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 单后端失败不影响其它
                logger.debug("remember via %s failed: %s", p.backend_name, exc)

    def remember_media(
        self,
        data_b64: str,
        *,
        modality: str,
        mime: str = "",
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
        caption: str = "",
    ) -> None:
        """记住一段 base64 媒体（摄像头帧/麦克风片段等）。

        两件事,分开做:

        1. **摄入** —— base64 → 临时文件 → 各 provider(跨模态后端经 media_path
           原生摄入,纯文本后端存 caption)。摄入完即删临时文件。这一步只为算出
           向量,让"用一句话召回一张截图"成立。
        2. **留存** —— 同一份字节进 ``core.memory.media_store``,metadata 记
           ``media_id``。这一步是为了**召回之后还能把它拿回来**。

        为什么要分成两件:此前只有第 1 件,而 metadata 里记的是那个临时文件的
        ``media_path`` —— 它在本函数返回的那一刻就**保证不存在了**。于是记忆一直是
        "找得到、看不见":谁照着那个路径去 open(),拿到的只有 FileNotFoundError。

        视频走关键帧:整段视频塞进向量库既贵又召不准,拆成几帧之后"一句话召回
        那段视频里的某一刻"才成立。见 ``_remember_video_frames``。
        """
        if not self.providers or not data_b64:
            return
        if modality == "video":
            # 这里拿到的是**容器字节**,而这套东西里没有 ffmpeg 能把它拆成帧
            # (``MultiModalVideo`` 的注释解释了为什么本仓一路都用帧序列)。
            # 字节仍然入库(以后有解码手段时还在),但要**说清楚**它现在检索不到画面,
            # 而不是假装记住了。有帧的调用方请走 ``remember_video()``。
            logger.info(
                "收到一段视频的容器字节:本层不解码,只留存字节 + 一条文字说明。"
                "要让它按画面被召回,请传 MultiModalVideo(帧序列)给 remember_video()。"
            )

        from core.memory._media import remove_temp, write_temp_media
        from core.memory.media_store import store as _store_media

        path = write_temp_media(data_b64, mime, modality)
        media_id = _store_media(data_b64, mime=mime, modality=modality)
        try:
            md = dict(metadata or {})
            if path:
                md["media_path"] = path
            if media_id:
                # 只在**真存下来**时才写。写一个查不到的 id,与从前写一个已删除的
                # 路径是同一种错:让调用方以为有东西可拿。
                md["media_id"] = media_id
            md.setdefault("modality", modality)
            text = caption or f"[{modality} memory]"
            self.remember(text, modality=modality, tags=tags, metadata=md)
        finally:
            remove_temp(path)

    def remember_video(
        self,
        video: Any,
        *,
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
        caption: str = "",
    ) -> None:
        """记住一段视频 —— **按关键帧存**,不是把整段塞进向量库。

        入参是 ``core.schemas.multimodal.MultiModalVideo``,它本身**就是一串关键帧**
        而不是容器字节。那个类的注释把理由写得很清楚:这套东西里没有 ffmpeg,
        路由器够得着的视觉模型也没有一个吃 mp4 —— 全都只吃静止图。所以"视频"在
        本仓一路都是帧序列,记忆这一层没有理由自己搞一套。

        抽帧用 ``core.video_keyframes.sample_keyframes``(与送给模型的那条路同一个
        函数,不另写一份判据):均匀抽、**首尾必留**。每帧带自己的时间偏移写进
        metadata —— 一堆静止图说的是"屏幕上有什么",带偏移的有序帧说的是
        "发生了什么",后者才是这类记忆的价值。

        没有帧时**写一条纯文本并说明**,而不是悄悄什么都不做 —— 后者会让调用方
        以为这段视频记住了。
        """
        frames = list(getattr(video, "frames", None) or [])
        base_md = dict(metadata or {})
        base_md.setdefault("modality", "video")

        if not frames:
            base_md["video_frames"] = 0
            self.remember(
                (caption or "[video memory]") + "(这段视频没有关键帧,只留下了这行说明)",
                modality="text",
                tags=tags,
                metadata=base_md,
            )
            return

        from core.video_keyframes import sample_keyframes  # noqa: PLC0415

        picked = sample_keyframes(frames)
        total = len(picked)
        for i, frame in enumerate(picked):
            data = getattr(frame, "data", "") or ""
            if not data:
                continue
            md = dict(base_md)
            md["video_frames"] = total
            md["video_frame_index"] = i
            md["video_offset_ms"] = int(getattr(frame, "offset_ms", 0) or 0)
            offset_s = md["video_offset_ms"] / 1000
            self.remember_media(
                data,
                modality="image",
                mime=getattr(frame, "mime", "image/jpeg") or "image/jpeg",
                tags=tags,
                metadata=md,
                caption=f"{caption or '[video memory]'}(第 {i + 1}/{total} 帧 t=+{offset_s:.1f}s)",
            )

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        hits: List[MemoryHit] = []
        for p in self.providers:
            try:
                hits.extend(p.recall(query, top_k=top_k) or [])
            except Exception as exc:  # noqa: BLE001
                logger.debug("recall via %s failed: %s", p.backend_name, exc)
        # 跨后端去重（按内容），保留高分
        seen: dict = {}
        for h in hits:
            key = (h.content or "").strip()[:160]
            if key and (key not in seen or h.score > seen[key].score):
                seen[key] = h
        merged = sorted(seen.values(), key=lambda h: h.score, reverse=True)
        result = merged[:top_k]

        # 只在写入时盖章是不够的:记忆重新进上下文的那一刻若来源掉了,它就以
        # "智能体自己的知识"的身份出现 —— 污染被洗白。这里把这批结果的**最低**
        # 来源记进回执,让上下文装配那一段按真实来源算,而不是一律记成 memory。
        try:
            from core.memory_provenance import record_recall  # noqa: PLC0415

            record_recall(result)
        except Exception as exc:  # noqa: BLE001 — 记不上也要把结果还回去
            logger.debug("检索来源回执写入失败: %s", exc)

        return result


# ── 单例工厂 ────────────────────────────────────────────────────────────────

_instance: Optional[UnifiedMemory] = None


def _build() -> UnifiedMemory:
    # GALAXY_MEMORY_BACKENDS: 逗号分隔，默认 "vector"（本地后端零依赖永远可用）。
    # 加 "omni" 启用 Omni-SimpleMem 跨模态记忆（需 pip install simplemem）。
    raw = os.getenv("GALAXY_MEMORY_BACKENDS", "vector")
    wanted = {b.strip().lower() for b in raw.split(",") if b.strip()}
    providers: List[MemoryProvider] = []
    if {"vector", "vector_backend"} & wanted:
        from core.memory.vector_backend_provider import VectorBackendProvider

        providers.append(VectorBackendProvider())
    if {"omni", "omni_simplemem", "simplemem"} & wanted:
        from core.memory.omni_simplemem_provider import OmniSimpleMemProvider

        providers.append(OmniSimpleMemProvider())
    if {"clip", "crossmodal", "cross_modal"} & wanted:
        from core.memory.clip_provider import ClipMemoryProvider

        providers.append(ClipMemoryProvider())
    if {"clap", "audio"} & wanted:
        from core.memory.clap_provider import ClapMemoryProvider

        providers.append(ClapMemoryProvider())
    um = UnifiedMemory(providers)
    logger.info("UnifiedMemory initialised | backends=%s", um.backend_names or "none")
    return um


def get_unified_memory() -> UnifiedMemory:
    global _instance
    if _instance is None:
        _instance = _build()
    return _instance


def reset_unified_memory() -> None:
    """测试/重配用：清空单例。"""
    global _instance
    _instance = None
