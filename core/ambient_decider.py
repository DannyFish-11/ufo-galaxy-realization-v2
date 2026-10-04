"""core/ambient_decider.py — 注意力头：把一拍观察变成「三选一」决策
=====================================================================

默认决策脑 :class:`LLMRouterDecider`（走系统统一 LLM 路由）与把主脑自由文本解析成严格三选一的
:func:`parse_decision`。从 ``core/ambient_attention_loop.py`` 原样搬出 —— 那个文件已经逼近
1000 行的体量线，而治理层（:mod:`core.ambient_governance`）要接进循环，得先腾出地方。

``core.ambient_attention_loop`` 原样再导出这里的名字，既有的
``from core.ambient_attention_loop import LLMRouterDecider, parse_decision`` 不用改；测试里对
``LLMRouterDecider._vision_usable`` 的类级替换照旧有效（同一个类对象）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.ambient_types import RECENT_MEMORY_N as _RECENT_MEMORY_N
from core.ambient_types import (
    AmbientAction,
    AmbientDecision,
    AmbientObservation,
)

logger = logging.getLogger("Galaxy.Ambient")

#: 模态协商层不可用时只告警一次(循环 2 秒一拍,每拍刷一条就成噪音)。
_VISION_NEGOTIATION_WARNED = False


# 严格三选一输出格式：第一行必须是三个动作词之一，后续行给理由/内容。
_DECISION_FORMAT = (
    "你是一个桌面 AI 的『注意力头』。你持续在场地看着用户的摄像头/屏幕、听着麦克风，"
    "但你的唯一任务不是描述画面，而是判断【此刻该不该主动介入】。\n"
    "严格从以下三选一，且第一行只能是这三个词之一：\n"
    "SPEAK   —— 此刻确实值得你主动开口（如用户明显卡住、出现你被托付留意的事、用户回到座位）。\n"
    "SILENT  —— 看到了但不值得打扰（用户在正常操作、只是光线/无关变化）。这应是绝大多数情况的答案。\n"
    "DELEGATE—— 不该嘴上说，而该派一个后台任务（如反复报错需查日志、需要 OCR 提取屏幕文字）。\n"
    "输出格式（严格）：\n"
    "第一行：SPEAK 或 SILENT 或 DELEGATE\n"
    "第二行起：理由（一句话）。若为 SPEAK，另起一行以『说：』开头写出你要说的话；"
    "若为 DELEGATE，另起一行以『派：』开头写出要委托的任务。\n"
    "克制是美德——拿不准就选 SILENT。"
)


class LLMRouterDecider:
    """默认决策脑：走系统统一 LLM 路由（与面板/克隆界面选好的主脑一致）。

    多模态:构造 OpenAI 风格的 image_url content part;路由的 Ollama 适配器会
    自动转成 Ollama 的 images 字段(见 multi_llm_router._to_ollama_messages),
    因此对 OpenAI 兼容后端与本地 Ollama 后端都成立——真正模型无关。
    图像发送失败时优雅降级为纯文本(带上屏幕结构化上下文)。
    """

    def __init__(self, router: Optional[Any] = None) -> None:
        self._router = router

    def _get_router(self):
        if self._router is None:
            from core.multi_llm_router import get_llm_router

            self._router = get_llm_router()
        return self._router

    @staticmethod
    def _image_part(image_b64: str, mime: str) -> Dict[str, Any]:
        url = image_b64 if image_b64.startswith("data:") else f"data:{mime or 'image/jpeg'};base64,{image_b64}"
        return {"type": "image_url", "image_url": {"url": url}}

    def _build_messages(self, obs: AmbientObservation) -> List[Dict[str, Any]]:
        text_lines = [_DECISION_FORMAT, ""]
        if obs.recent_memory:
            text_lines.append("最近你注意到的（供连续性参考）：")
            text_lines.extend(f"- {m}" for m in obs.recent_memory[-_RECENT_MEMORY_N:])
            text_lines.append("")
        if obs.screen_meta:
            title = obs.screen_meta.get("window_title") or obs.screen_meta.get("title")
            if title:
                text_lines.append(f"当前活动窗口：{title}")
        # 听:asr_bridge 已转写出文字 → 直接把用户说的话交给模型判断；
        # 未转写(native 待服务/转写失败)则只提示"有声音"。
        if obs.audio_transcript:
            text_lines.append(f"（麦克风此刻听到：「{obs.audio_transcript}」）")
        elif obs.audio_b64:
            text_lines.append("（麦克风此刻有新的声音输入。）")

        # 可打扰性:把「克制是美德」从祈使句变成可测量的输入。
        # 没有可用证据时是空串 —— 不写模棱两可的话进提示词。
        if obs.interruptibility_note:
            text_lines.append(obs.interruptibility_note)

        # 融合看:屏幕 + 摄像头两路都发给模型(此前只发一路)。仅当统一模态协商层
        # 判定当前模型【看得见】(vision 可用)时才附图——换到无视觉模型自动省掉图像,
        # 不给瞎子发图、不白烧 token。协商层不可用时保守按"能看"处理,不回退视觉。
        images: List[tuple] = []
        if self._vision_usable():
            if obs.screen_b64:
                images.append(("屏幕截图", obs.screen_b64, obs.screen_mime))
            if obs.camera_b64:
                images.append(("摄像头画面", obs.camera_b64, obs.camera_mime))
            # 兼容:调用方只塞了 frame_b64(未分路)时,仍发主帧。
            if not images and obs.frame_b64:
                images.append(("画面", obs.frame_b64, obs.frame_mime))

        if len(images) > 1:
            text_lines.append("（以下依次是：" + "、".join(lbl for lbl, _, _ in images) + "）")
        text_lines.append("现在，请判断此刻该 SPEAK / SILENT / DELEGATE。")
        text = "\n".join(text_lines)

        if images:
            content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
            for _lbl, b64, mime in images:
                content.append(self._image_part(b64, mime))
            return [{"role": "user", "content": content}]
        return [{"role": "user", "content": text}]

    @staticmethod
    def _vision_usable() -> bool:
        """当前模型是否看得见(经统一模态协商层)。

        协商层不可用时**仍然返回 True**(继续附图) —— 方向是刻意的:
        反过来(协商一挂就不发图)会在模型明明有视觉时,把这条循环悄悄变成瞎的,
        而且没有任何迹象;多发一次图的代价小得多,``decide()`` 本来就有一条纯文本
        重试兜底接得住后端不认图的情况。

        改掉的是**静默**这一点。降级可以发生,但不许没人知道 —— 循环 2 秒一拍,
        所以只在**第一次**说一句,不刷屏。
        """
        try:
            from core.modality_capability import negotiate

            return negotiate().vision_in.usable
        except Exception as exc:  # noqa: BLE001
            global _VISION_NEGOTIATION_WARNED
            if not _VISION_NEGOTIATION_WARNED:
                _VISION_NEGOTIATION_WARNED = True
                logger.warning(
                    "模态协商层不可用(%s):注意力循环继续按【看得见】处理并附图 —— "
                    "若当前模型其实没有视觉,后端可能拒收,届时会走纯文本重试兜底。"
                    "本条只说一次。",
                    type(exc).__name__,
                )
            return True

    async def decide(self, obs: AmbientObservation) -> AmbientDecision:
        router = self._get_router()
        messages = self._build_messages(obs)
        try:
            resp = await router.chat(messages, temperature=0.2, max_tokens=200)
            text = (resp.content or "").strip()
        except Exception as exc:  # noqa: BLE001 — 多模态发送失败等
            # 纯文本降级重试一次
            logger.debug("Ambient decider 多模态调用失败,降级纯文本: %s", exc)
            try:
                fallback = [
                    {
                        "role": "user",
                        "content": (
                            messages[0]["content"][0]["text"]
                            if isinstance(messages[0]["content"], list)
                            else messages[0]["content"]
                        ),
                    }
                ]
                resp = await router.chat(fallback, temperature=0.2, max_tokens=200)
                text = (resp.content or "").strip()
            except Exception as exc2:  # noqa: BLE001
                logger.debug("Ambient decider 纯文本降级也失败: %s", exc2)
                return AmbientDecision(action=AmbientAction.SILENT, rationale=f"决策不可用: {exc2}")
        return parse_decision(text)


def parse_decision(text: str) -> AmbientDecision:
    """把主脑的自由文本解析成严格三选一。

    第一行的第一个可辨识词决定 action;拿不准一律 SILENT(克制优先)。
    """
    if not text:
        return AmbientDecision(action=AmbientAction.SILENT, rationale="空响应")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = lines[0].upper() if lines else "SILENT"

    if head.startswith("SPEAK"):
        action = AmbientAction.SPEAK
    elif head.startswith("DELEGATE"):
        action = AmbientAction.DELEGATE
    elif head.startswith("SILENT"):
        action = AmbientAction.SILENT
    else:
        # 首行不规范：在全文里找线索，否则保守 SILENT
        upper = text.upper()
        if "DELEGATE" in upper:
            action = AmbientAction.DELEGATE
        elif "SPEAK" in upper:
            action = AmbientAction.SPEAK
        else:
            action = AmbientAction.SILENT

    rationale = ""
    utterance = ""
    task = ""
    for ln in lines[1:]:
        if ln.startswith("说：") or ln.startswith("说:"):
            utterance = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif ln.startswith("派：") or ln.startswith("派:"):
            task = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif not rationale:
            rationale = ln

    # SPEAK 但没给出要说的话 → 用理由兜底；仍为空则降级 SILENT（不空口说白话）
    if action == AmbientAction.SPEAK and not utterance:
        utterance = rationale
        if not utterance:
            return AmbientDecision(action=AmbientAction.SILENT, rationale="SPEAK 无内容,降级沉默")
    # DELEGATE 但没给出任务 → 用理由兜底；仍为空则降级 SILENT
    if action == AmbientAction.DELEGATE and not task:
        task = rationale
        if not task:
            return AmbientDecision(action=AmbientAction.SILENT, rationale="DELEGATE 无任务,降级沉默")

    salient = action in (AmbientAction.SPEAK, AmbientAction.DELEGATE)
    return AmbientDecision(action=action, rationale=rationale, utterance=utterance, task=task, salient=salient)
