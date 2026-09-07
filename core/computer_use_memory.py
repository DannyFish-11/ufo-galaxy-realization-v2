"""core/computer_use_memory.py — 让桌面闭环记得住自己看过的屏幕

问题的形状
==========
``core/computer_use_loop`` 是这套系统里唯一真正「看着屏幕做事」的闭环:每一步都
把截图交给多模态模型,拿回一个动作,执行,再看。但它**一个字都不写记忆** ——
``grep -n "memory\\|remember\\|recall" core/computer_use_loop.py`` 返回空。

后果是每次运行都从零开始看。同一个任务跑第二遍时,智能体不知道:

* 这个界面它上次见过;
* 上次在这个界面点那个按钮**没有反应**;
* 上一轮是卡在哪一步失败的。

它只有一份 ``history`` 活在单次 ``run()`` 的栈上 —— 那是工作记忆,函数返回就没了。
综述里 Memory 那一章讲的情景记忆(Reflexion 那类「记住上次这么做没成功」),
在这条链路上完全不存在。

为什么现在补代价很低
====================
跨模态记忆的基础设施**已经建好了**,只是没人用:

* ``core/memory/unified.UnifiedMemory.remember_media`` —— base64 → 临时文件 →
  各后端;跨模态后端原生摄入媒体,纯文本后端存 caption;
* ``core/memory/clip_provider`` —— CLIP 把文本和图像编码进**同一个向量空间**,
  所以用一句文字就能召回一张截图;
* ``core/memory/clap_provider`` —— 音频同理。

本模块只做「策略」这一层:**写什么、什么时候写、召回什么、怎么塞回提示词**。
它不碰后端,也不决定后端有没有配 —— 没配就整体是 no-op。

写入策略:只记失败与结局,不记每一步
====================================
逐步全记的代价是每一步一次 CLIP 编码(15 步的任务就是 15 次),而收益很低 ——
顺利走过去的那些步骤,下次也会顺利走过去。真正值钱的是:

* **失败的那一步** —— 这正是 Reflexion 那套东西存在的理由;
* **整个任务的结局** —— 给这段情景一个结论,否则召回时只有一堆孤立的失败。

于是典型一次运行写 0~3 条,而不是 15 条。

召回策略:每次运行召回一次,不是每步一次
========================================
每步召回会让提示词膨胀,也会把一次运行的延迟乘上步数。而「过往经验」这件事在
一次任务里基本是恒定的 —— 开跑前问一次就够。

默认开,而不是又一个默认关的开关
================================
本仓已经有好几个「建好了、默认关着、没有文档」的多模态开关
(``GALAXY_NATIVE_MM_CHAT`` / ``GALAXY_MEMORY_MEDIA`` / ``GALAXY_ENABLE_MULTIMODAL_INGEST``)。
再加一个只会让这个模式更严重。

这里默认开是**安全**的,因为它的前置条件已经是一道天然的闸:没有配置任何记忆后端
时 ``UnifiedMemory.enabled`` 为 False,本模块整体退化成 no-op,一次调用都不会发生。
真要关仍然可以 ``GALAXY_CU_MEMORY=0``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ComputerUse.Memory")

#: 召回条数上限。多了会把规划提示词挤满,而排在后面的相关度已经很低。
MAX_RECALL = 3

#: 召回时按这个倍数多取,再由 ``_rank_by_outcome`` 自己排。后端只会算语义相似度,
#: 分不出成功与失败;取够数再筛就没得筛了。
RECALL_OVERFETCH = 4

#: 一次召回里最多放几条**失败**的经验。失败是有用的(上次这么做没成),但写入侧
#: 是无条件写的 —— 同一个任务失败五次成功一次,不设上限就会召回三条全是失败,
#: 而成功的那条被自己的失败挤了出去。
MAX_FAILURE_RECALL = 1

#: 注入提示词的单条经验最大长度,防止一条超长记忆吃掉整个上下文。
MAX_EXPERIENCE_CHARS = 200

#: 记忆里给这条链路打的标签,便于与其它来源的记忆区分。
TAG = "computer_use"


def memory_enabled() -> bool:
    """本模块是否启用(默认开;``GALAXY_CU_MEMORY=0`` 关)。

    与 ``computer_use_enabled`` 同型:未设置或空串都算开,只有显式的假值才关。
    """
    raw = os.environ.get("GALAXY_CU_MEMORY")
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


class ComputerUseEpisodicMemory:
    """桌面闭环的情景记忆:写失败与结局,召回过往经验。

    Args:
        memory: 注入的记忆门面(测试用替身)。``None`` 时惰性取
            ``core.memory.get_unified_memory()`` —— 惰性是必要的:导入期就取会
            在还没配置后端时把单例定死。

    所有方法都**不抛异常**。记忆是辅助设施,它坏掉不该让一个正在操作真实键鼠的
    闭环中断 —— 那个取舍方向不能反。
    """

    def __init__(self, memory: Any = None) -> None:
        self._memory = memory
        self._resolved = memory is not None

    # ── 后端解析 ────────────────────────────────────────────────────────────

    def _get_memory(self) -> Any:
        if not self._resolved:
            try:
                from core.memory import get_unified_memory  # noqa: PLC0415

                self._memory = get_unified_memory()
            except Exception as exc:  # noqa: BLE001 — 记忆层不可用只是没有记忆
                logger.debug("统一记忆不可用,本次运行无情景记忆: %s", exc)
                self._memory = None
            self._resolved = True
        return self._memory

    @property
    def available(self) -> bool:
        """有没有可用的记忆后端。没有时本模块整体是 no-op。"""
        if not memory_enabled():
            return False
        mem = self._get_memory()
        return bool(mem is not None and getattr(mem, "enabled", False))

    # ── 召回 ────────────────────────────────────────────────────────────────

    async def recall_experience(self, instruction: str) -> str:
        """召回与 *instruction* 相关的过往经验,返回可直接塞进提示词的文本。

        没有可用后端、没有命中、或召回失败时一律返回空串 —— 调用方据此决定
        「不加这一段」,而不是加一段「(无)」去占位。空串比占位更诚实:模型看到
        「过往经验:(无)」会以为系统查过且确实没有,而实际可能是记忆层根本没配。
        """
        if not self.available or not instruction.strip():
            return ""
        try:
            # **多取一些再自己排。** 后端给的是纯语义相似度 —— 它不知道哪条是
            # 成功的经验、哪条是失败的尝试,于是一次失败会和一次成功抢同一个名额。
            # 取 MAX_RECALL 个再筛就没得筛了,所以这里按 OVERFETCH 倍取。
            hits = await asyncio.to_thread(self._get_memory().recall, instruction, top_k=MAX_RECALL * RECALL_OVERFETCH)
        except Exception as exc:  # noqa: BLE001
            logger.debug("情景记忆召回失败(不影响任务): %s", exc)
            return ""
        return self._format_experience(self._rank_by_outcome(hits or []))

    @staticmethod
    def _outcome_of(hit: Any) -> str:
        """这条经验记的是一次成功还是一次失败。分不出来算 ``unknown``。

        两处都看,不是冗余:

        * ``metadata["tags"]`` —— 写入时打的标(``execution_planner`` 会打
          ``success`` / ``failure``),这是**权威**的那一份;
        * 正文里的「结果[失败]」—— 后端各有各的元数据支持程度,有的会在往返中把
          tags 丢掉。丢了之后正文里那四个字是**唯一还剩下的**结果信号。

        只看第一处,遇到丢 tags 的后端就整批变成 unknown,加权等于没加。
        """
        meta = getattr(hit, "metadata", None) or {}
        tags = meta.get("tags") or ()
        if "failure" in tags:
            return "failure"
        if "success" in tags:
            return "success"
        content = getattr(hit, "content", "") or ""
        if "结果[失败]" in content:
            return "failure"
        if "结果[成功]" in content:
            return "success"
        return "unknown"

    @classmethod
    def _rank_by_outcome(cls, hits: List[Any]) -> List[Any]:
        """按结果重排:成功的优先,失败的**留但设上限**。

        ## 为什么不是把失败的过滤掉

        失败的经验是**有用的** —— "上次在这个界面点那个按钮没反应"正是
        Reflexion 那类情景记忆的价值所在。全滤掉等于把教训一起扔了。

        ## 为什么必须设上限

        写入那一侧(``core/agent/execution_planner.py``)是**无条件写**的:每次执行
        都进长期记忆,成功失败只差一个 tag。而召回是纯语义 top_k。于是同一个任务
        试了五次失败一次成功,召回的三条很可能全是失败 —— 成功的那条被自己的
        五次失败挤出去了。模型看到的是"这条路走不通"的五份证据和零份反例。

        所以:成功的先排,失败的最多占 ``MAX_FAILURE_RECALL`` 个名额,``unknown``
        (旧数据、别的链路写的)排在成功之后、失败之前 —— 它们没有"这次没成"这个
        负面信号,不该被当成失败处理。
        """
        buckets: Dict[str, List[Any]] = {"success": [], "unknown": [], "failure": []}
        for hit in hits:
            buckets[cls._outcome_of(hit)].append(hit)
        ranked = buckets["success"] + buckets["unknown"] + buckets["failure"][:MAX_FAILURE_RECALL]
        return ranked[:MAX_RECALL]

    @classmethod
    def _format_experience(cls, hits: List[Any]) -> str:
        """把召回结果排成提示词里的一段。纯函数,便于单测。"""
        lines: List[str] = []
        for hit in hits[:MAX_RECALL]:
            content = (getattr(hit, "content", "") or "").strip().replace("\n", " ")
            if not content:
                continue
            modality = getattr(hit, "modality", "text") or "text"
            # 标出模态:让模型知道这条经验背后是一张真实截图,而不是谁写的一句话。
            prefix = "[截图]" if modality == "image" else ""
            # 失败的经验**标出来**。正文里本来就常带「结果[失败]」,但那是写入方的
            # 格式约定,别的链路写进来的不一定有。标签由召回这一侧统一加,模型才不会
            # 把一次失败的尝试读成一条可照做的经验。
            if cls._outcome_of(hit) == "failure":
                prefix = "[上次失败]" + prefix
            lines.append(f"- {prefix}{content[:MAX_EXPERIENCE_CHARS]}")
        return "\n".join(lines)

    # ── 写入 ────────────────────────────────────────────────────────────────

    async def remember_failure(
        self,
        instruction: str,
        *,
        index: int,
        action: str,
        params: Dict[str, Any],
        error: str,
        screen_b64: Optional[str] = None,
    ) -> None:
        """记下失败的一步。带上当时的截图,让下次能凭「这个界面」召回。

        刻意接收平铺参数而不是 ``StepRecord``:那个类定义在 ``computer_use_loop``
        里,反过来 import 会成环。少一个类型耦合,换一份可以被别的链路(比如安卓侧)
        复用的能力。
        """
        caption = (
            f"[computer_use 失败] 任务:{instruction[:80]} | "
            f"步骤{index}: {action}({json.dumps(params, ensure_ascii=False)}) → 失败:{error[:80]}"
        )
        await self._write(caption, screen_b64=screen_b64, kind="failure", instruction=instruction)

    async def remember_outcome(
        self,
        instruction: str,
        *,
        success: bool,
        stop_reason: str,
        message: str,
        step_count: int,
        screen_b64: Optional[str] = None,
    ) -> None:
        """记下整个任务的结局,给这段情景一个结论。

        没有它,召回出来的只会是一堆孤立的失败步骤 —— 模型看得到「上次点这里失败
        了」,却不知道那次任务最终是绕过去了还是彻底没做成。这两种情况下该采取的
        下一步完全不同。
        """
        verdict = "完成" if success else "未完成"
        caption = (
            f"[computer_use 结局:{verdict}] 任务:{instruction[:80]} | "
            f"共{step_count}步 | 停止原因:{stop_reason} | {message[:80]}"
        )
        await self._write(caption, screen_b64=screen_b64, kind="outcome", instruction=instruction)

    async def _write(
        self,
        caption: str,
        *,
        screen_b64: Optional[str],
        kind: str,
        instruction: str,
    ) -> None:
        """统一写入口。有截图走 ``remember_media``,没有则退回纯文本 ``remember``。

        退回纯文本而不是跳过:一步失败了但那一拍恰好没取到屏幕帧,这件事本身仍然
        值得记 —— 「在这个任务的第 N 步失败过」比什么都不记有用。
        """
        if not self.available:
            return
        mem = self._get_memory()
        metadata = {"kind": kind, "instruction": instruction[:200], "loop": "computer_use"}
        try:
            if screen_b64:
                await asyncio.to_thread(
                    mem.remember_media,
                    screen_b64,
                    modality="image",
                    mime="image/jpeg",
                    tags=[TAG, kind],
                    metadata=metadata,
                    caption=caption,
                )
            else:
                # 刻意**不传** origin。``core.memory_provenance.stamp`` 在不传时会退到
                # ``context_provenance`` 的运行时下界 —— 那是个保守默认("这一轮里进过
                # 网页正文,这一轮产生的记忆就按外部来源记")。
                #
                # 传 origin="computer_use_loop" 会绕过那道判断,把这条记忆标成"智能体
                # 自己的知识"。但失败的 caption 里含着模型给的理由和屏幕上的报错文本
                # —— 那是被屏幕内容影响过的东西,不是干净来源。按该模块自己的原则:
                # 宁可把一条本来干净的记忆标成外部,也不要把一条外部来的标成干净的。
                #
                # 是哪个子系统写的,由 metadata["loop"] 记着,不需要靠 origin 表达。
                await asyncio.to_thread(
                    mem.remember,
                    caption,
                    tags=[TAG, kind],
                    metadata=metadata,
                )
        except Exception as exc:  # noqa: BLE001 — 写不进记忆不该中断真实操作
            logger.debug("情景记忆写入失败(不影响任务): %s", exc)
