"""
core/agent/intent_router.py
============================
意图路由器 -- 判定"聊天 vs 任务执行"

支持两级分类：
  1. 规则引擎（快速、零延迟）
  2. LLM 增强分类（可选，用于模糊边界）

输出标准化 IntentResult（Pydantic 模型）：
  - mode: "chat_only" | "task_execute" | "hybrid"
  - confidence: 0.0 - 1.0
  - task_hint: 任务简述（task_execute / hybrid 时填充）
  - raw_intent: 底层意图标签（复用 ai_intent.ParsedIntent）
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, Final, List, Optional, Tuple

from pydantic import BaseModel, Field, validator

logger = logging.getLogger("Galaxy.Agent.IntentRouter")

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------

# High-confidence task execution keywords (hit means task_execute)
_TASK_KW_HIGH: Final[List[str]] = [
    # Chinese -- device control
    "打开",
    "关闭",
    "启动",
    "运行",
    "安装",
    "卸载",
    "截图",
    "截屏",
    "点击",
    "滑动",
    "输入",
    "搜索",
    "发送",
    "下载",
    "上传",
    "复制",
    "粘贴",
    "传输",
    "同步",
    "分享",
    "拍照",
    "录屏",
    "录音",
    "播放",
    "暂停",
    "停止",
    "查看电量",
    "查看状态",
    "连接设备",
    "断开设备",
    "帮我操作",
    "帮我执行",
    "帮我控制",
    "在手机上",
    "在电脑上",
    "在平板上",
    "在设备上",
    "切换应用",
    "返回桌面",
    "锁屏",
    "解锁",
    "传到手机",
    "传到电脑",
    "发到手机",
    "发到电脑",
    "跨设备",
    "同步剪贴板",
    "设备间",
    # Chinese -- task/tool
    "帮我写",
    "帮我生成",
    "帮我分析",
    "帮我总结",
    "帮我查",
    "帮我做",
    "帮我完成",
    "帮我处理",
    "帮我创建",
    "帮我规划",
    "执行",
    "运行代码",
    "调用",
    "生成",
    "创建文件",
    "创建目录",
    "读取文件",
    "写入文件",
    "删除文件",
    "搜索文件",
    "提交",
    "部署",
    "构建",
    "测试",
    # Chinese -- generic task verbs (with explicit object context)
    "做一个",
    "做个",
    "做一份",
    "制作一个",
    "制作一份",
    "写一个",
    "写一段",
    "写代码",
    "写脚本",
    "写报告",
    "创建一个",
    "创建一份",
    "生成一个",
    "生成一份",
    "分析一下",
    "分析这个",
    "分析数据",
    "分析代码",
    "总结一下",
    "整理一下",
    "规划一下",
    "实现一个",
    "实现功能",
    "完成任务",
    # English
    "open ",
    "close ",
    "launch ",
    "run ",
    "install ",
    "uninstall ",
    "click ",
    "swipe ",
    "type ",
    "screenshot",
    "send ",
    "download ",
    "upload ",
    "execute ",
    "control ",
    "operate ",
    "on my phone",
    "on my pc",
    "on device",
    "on android",
    "take photo",
    "record ",
    "play ",
    "pause ",
    "stop ",
    "write code",
    "generate ",
    "create file",
    "read file",
    "delete ",
    "search for",
    "find file",
    "deploy ",
    "build ",
    "commit ",
    # English -- generic task verbs
    "write a ",
    "write me ",
    "create a ",
    "create an ",
    "make a ",
    "make me ",
    "build a ",
    "build me ",
    "implement ",
    "develop ",
    "design a ",
    "analyze ",
    "analyse ",
    "summarize ",
    "summarise ",
    "plan ",
    "schedule ",
    "help me with",
    "do this ",
    "do the ",
    "complete ",
]

# Low-confidence task keywords (context-dependent, alone may be chat)
# Note: trailing space is intentional to prevent partial matches
_TASK_KW_LOW: Final[List[str]] = [
    "帮我",
    "我想",
    "能不能",
    "可以帮",
    "请帮",
    "help me",
    "can you",
    "could you",
    "please ",
]

# Strong chat indicators (hit tends toward chat_only, unless high-confidence task word also hit)
_CHAT_KW: Final[List[str]] = [
    "你好",
    "hi",
    "hello",
    "聊聊",
    "说说",
    "告诉我",
    "介绍",
    "什么是",
    "为什么",
    "怎么",
    "如何理解",
    "解释",
    "有趣",
    "好玩",
    "推荐",
    "建议",
    "觉得",
    "讲个故事",
    "讲笑话",
    "陪我",
]

# Classification thresholds
_RULE_CONFIDENCE_HIGH: Final[float] = 0.9
_RULE_CONFIDENCE_MEDIUM: Final[float] = 0.75
_RULE_CONFIDENCE_LOW: Final[float] = 0.55
_RULE_CONFIDENCE_MINIMAL: Final[float] = 0.65

# Message length thresholds
_SHORT_MESSAGE_THRESHOLD: Final[int] = 4
_LONG_MESSAGE_THRESHOLD: Final[int] = 10

# LLM classification defaults
_DEFAULT_LLM_TIMEOUT: Final[float] = 8.0
_DEFAULT_LLM_CONFIDENCE: Final[float] = 0.7
_DEFAULT_LLM_CONFIDENCE_THRESHOLD: Final[float] = 0.6

# ------------------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------------------


class IntentMode:
    """Intent mode constants."""

    CHAT_ONLY: Final[str] = "chat_only"
    TASK_EXECUTE: Final[str] = "task_execute"
    HYBRID: Final[str] = "hybrid"


class IntentResult(BaseModel):
    """Standardized intent routing result.

    Attributes:
        mode: Processing mode -- chat_only / task_execute / hybrid.
        confidence: Classification confidence score [0.0, 1.0].
        task_hint: Brief task description (non-empty for task_execute/hybrid).
        raw_intent: Underlying intent label.
        method: Classification method used -- rules / llm / rules+llm.
        latency_ms: Classification latency in milliseconds.
    """

    mode: str = IntentMode.CHAT_ONLY
    """处理模式：chat_only / task_execute / hybrid"""

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    """分类置信度 [0.0, 1.0]"""

    task_hint: str = Field(default="", max_length=256)
    """任务简述（task_execute / hybrid 时非空）"""

    raw_intent: str = "chat"
    """底层意图标签（来自 ai_intent.ParsedIntent.intent 或规则推断）"""

    method: str = "rules"
    """分类方法：rules / llm / rules+llm"""

    latency_ms: float = Field(default=0.0, ge=0.0)
    """分类耗时（毫秒）"""

    @validator("mode")
    def mode_must_be_valid(cls, v: str) -> str:
        """Validate mode is one of the allowed values."""
        if v not in (IntentMode.CHAT_ONLY, IntentMode.TASK_EXECUTE, IntentMode.HYBRID):
            raise ValueError(f"Invalid mode: {v}")
        return v

    @validator("confidence")
    def confidence_in_range(cls, v: float) -> float:
        """Ensure confidence is within valid range."""
        return max(0.0, min(1.0, v))

    def is_execution(self) -> bool:
        """Return True if mode requires execution path (task_execute or hybrid)."""
        return self.mode in (IntentMode.TASK_EXECUTE, IntentMode.HYBRID)


# ------------------------------------------------------------------------------
# Rule engine
# ------------------------------------------------------------------------------


def _classify_by_rules(message: str) -> IntentResult:
    """Classify intent based on keyword rules (fast, zero-latency).

    Classification logic:
      1. High-confidence task keyword + chat keyword -> hybrid (0.75)
      2. High-confidence task keyword only -> task_execute (0.9)
      3. Short message (< 4 chars) -> chat_only (0.9)
      4. Chat keyword without low-confidence task keyword -> chat_only (0.85)
      5. Low-confidence task keyword -> task_execute (0.65)
      6. Long message (>= 10 chars) -> task_execute (0.55)
      7. Default -> chat_only (0.7)

    Args:
        message: The user message to classify.

    Returns:
        IntentResult with classification result.
    """
    msg = message.lower().strip()

    high_hit: bool = any(kw in msg for kw in _TASK_KW_HIGH)
    chat_hit: bool = any(kw in msg for kw in _CHAT_KW)

    # Cache first matched task keyword (avoid repeated iteration)
    task_kw: str = next((kw for kw in _TASK_KW_HIGH if kw in msg), "").strip()

    # Case 1: Both high-confidence task word and chat word hit -> hybrid
    if high_hit and chat_hit:
        return IntentResult(
            mode=IntentMode.HYBRID,
            confidence=_RULE_CONFIDENCE_MEDIUM,
            task_hint=task_kw,
            raw_intent="hybrid",
            method="rules",
        )

    # Case 2: High-confidence task word only -> task_execute
    if high_hit:
        return IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=_RULE_CONFIDENCE_HIGH,
            task_hint=task_kw,
            raw_intent="task_execute",
            method="rules",
        )

    # Case 3: Very short message (no high-confidence task word) -> chat
    if len(msg) < _SHORT_MESSAGE_THRESHOLD:
        return IntentResult(
            mode=IntentMode.CHAT_ONLY,
            confidence=_RULE_CONFIDENCE_HIGH,
            method="rules",
        )

    # Case 4: Chat keyword without low-confidence task keyword
    low_hit: bool = any(kw in msg for kw in _TASK_KW_LOW)

    if chat_hit and not low_hit:
        return IntentResult(
            mode=IntentMode.CHAT_ONLY,
            confidence=0.85,
            method="rules",
        )

    # Case 5: Low-confidence task word -> task_execute (uncertain)
    if low_hit:
        task_kw_low = next((kw for kw in _TASK_KW_LOW if kw in msg), "").strip()
        return IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=_RULE_CONFIDENCE_MINIMAL,
            task_hint=task_kw_low,
            raw_intent="task_execute",
            method="rules",
        )

    # Case 6: No clear signal -- for longer messages (>= 10 chars) default to task_execute,
    # for very short ambiguous messages stay in chat mode.
    if len(msg) >= _LONG_MESSAGE_THRESHOLD:
        return IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=_RULE_CONFIDENCE_LOW,
            task_hint="",
            raw_intent="task_execute",
            method="rules",
        )

    # Default: chat_only
    return IntentResult(mode=IntentMode.CHAT_ONLY, confidence=0.7, method="rules")


# ------------------------------------------------------------------------------
# LLM-enhanced classification (optional)
# ------------------------------------------------------------------------------

# LLM classification prompt template
_LLM_CLASSIFY_PROMPT: Final[str] = """\
请判断下面这条用户消息的处理模式，只需返回 JSON，格式如下：
{"mode": "<chat_only|task_execute|hybrid>", "confidence": <0.0-1.0>, "task_hint": "<简短任务描述或空字符串>", "intent": "<意图标签>"}

规则：
- chat_only：纯聊天、问答、闲聊，不需要调用任何工具或设备
- task_execute：需要调用工具/设备/代码执行才能完成
- hybrid：既包含聊天成分，又需要执行某个任务

用户消息：
{message}
"""


async def _classify_by_llm(
    message: str,
    llm_router: Any,
    timeout: float = _DEFAULT_LLM_TIMEOUT,
) -> Optional[IntentResult]:
    """Use LLM to enhance intent classification (returns None if LLM unavailable or times out).

    Args:
        message: User message to classify.
        llm_router: LLM router instance with chat capability.
        timeout: Maximum time to wait for LLM response in seconds.

    Returns:
        IntentResult from LLM classification, or None if failed.
    """
    try:
        import json as _json

        prompt = _LLM_CLASSIFY_PROMPT.format(message=message)
        messages = [
            {"role": "system", "content": "你是一个意图分类助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]

        # Compatible with two router interfaces
        if hasattr(llm_router, "chat"):
            raw = await asyncio.wait_for(
                llm_router.chat(messages, temperature=0.0, max_tokens=128),
                timeout=timeout,
            )
            # LLMResponse or dict
            if hasattr(raw, "content"):
                text = raw.content
            elif isinstance(raw, dict):
                text = raw.get("content") or raw.get("response") or ""
            else:
                text = str(raw)
        else:
            return None

        # Extract JSON
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.debug("No JSON found in LLM classification response")
            return None
        data = _json.loads(match.group())

        mode = data.get("mode", IntentMode.CHAT_ONLY)
        if mode not in (IntentMode.CHAT_ONLY, IntentMode.TASK_EXECUTE, IntentMode.HYBRID):
            mode = IntentMode.CHAT_ONLY

        return IntentResult(
            mode=mode,
            confidence=float(data.get("confidence", _DEFAULT_LLM_CONFIDENCE)),
            task_hint=str(data.get("task_hint", "")),
            raw_intent=str(data.get("intent", "chat")),
            method="llm",
        )
    except asyncio.TimeoutError:
        logger.warning("LLM intent classification timeout (%.1fs)", timeout)
        return None
    except asyncio.CancelledError:
        raise  # Always propagate cancellation
    except Exception as exc:
        logger.debug("LLM intent classification exception: %s", exc)
        return None


# ------------------------------------------------------------------------------
# Main router class
# ------------------------------------------------------------------------------


class IntentRouter:
    """Intent router: rules-first, LLM enhancement for low-confidence scenarios.

    The router first applies fast keyword-based classification. If the rule-based
    confidence is below a threshold and LLM is available, it falls back to LLM
    classification for a second opinion.

    Attributes:
        _llm_router: Optional LLM router for enhanced classification.
    """

    def __init__(self, llm_router: Optional[Any] = None) -> None:
        """Initialize IntentRouter.

        Args:
            llm_router: LLM router instance for LLM-enhanced classification.
                        May be None if LLM enhancement is not available.
        """
        self._llm_router = llm_router

    async def route(
        self,
        message: str,
        context: Optional[List[Dict[str, str]]] = None,
        use_llm: bool = True,
        llm_confidence_threshold: float = _DEFAULT_LLM_CONFIDENCE_THRESHOLD,
    ) -> IntentResult:
        """Route intent through rules-first, optionally LLM-enhanced classification.

        Args:
            message: User input message.
            context: Conversation history (optional).
            use_llm: Whether to allow LLM enhancement when rule confidence is low.
            llm_confidence_threshold: Trigger LLM review when rule confidence is below this value.

        Returns:
            IntentResult with classification mode, confidence, and metadata.
        """
        t0 = time.monotonic()

        # Step 1: Rule-based classification
        rule_result: IntentResult = _classify_by_rules(message)
        logger.debug(
            "Rule classification: mode=%s confidence=%.2f",
            rule_result.mode,
            rule_result.confidence,
        )

        # Step 2: If rule confidence is low + LLM available -> LLM enhancement
        final: IntentResult = rule_result
        if (
            use_llm
            and self._llm_router is not None
            and rule_result.confidence < llm_confidence_threshold
        ):
            llm_result: Optional[IntentResult] = await _classify_by_llm(
                message, self._llm_router
            )
            if llm_result is not None:
                # LLM overrides lower-confidence rule results
                if llm_result.confidence > rule_result.confidence:
                    llm_result.method = "rules+llm"
                    final = llm_result
                    logger.debug(
                        "LLM classification overrides rules: mode=%s confidence=%.2f",
                        final.mode,
                        final.confidence,
                    )

        final.latency_ms = (time.monotonic() - t0) * 1000
        return final
