"""
core/agent/intent_router.py
============================
意图路由器 — 判定"聊天 vs 任务执行"

支持两级分类：
  1. 规则引擎（快速、零延迟）
  2. LLM 增强分类（可选，用于模糊边界）

输出标准化 IntentResult（Pydantic 模型）：
  - mode: "chat_only" | "task_execute" | "hybrid"
  - confidence: 0.0 – 1.0
  - task_hint: 任务简述（task_execute / hybrid 时填充）
  - raw_intent: 底层意图标签（复用 ai_intent.ParsedIntent）
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Agent.IntentRouter")

# ──────────────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────────────

class IntentMode:
    CHAT_ONLY = "chat_only"
    TASK_EXECUTE = "task_execute"
    HYBRID = "hybrid"


class IntentResult(BaseModel):
    """标准化意图路由结果。"""

    mode: str = IntentMode.CHAT_ONLY
    """处理模式：chat_only / task_execute / hybrid"""

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    """分类置信度"""

    task_hint: str = ""
    """任务简述（task_execute / hybrid 时非空）"""

    raw_intent: str = "chat"
    """底层意图标签（来自 ai_intent.ParsedIntent.intent 或规则推断）"""

    method: str = "rules"
    """分类方法：rules / llm / rules+llm"""

    latency_ms: float = 0.0
    """分类耗时（毫秒）"""

    def is_execution(self) -> bool:
        """是否需要进入执行链路（task_execute 或 hybrid）。"""
        return self.mode in (IntentMode.TASK_EXECUTE, IntentMode.HYBRID)


# ──────────────────────────────────────────────────────────────────────────────
# 规则引擎
# ──────────────────────────────────────────────────────────────────────────────

# 高置信度任务执行关键词（命中即为 task_execute）
_TASK_KW_HIGH: List[str] = [
    # 中文 — 设备控制
    "打开", "关闭", "启动", "运行", "安装", "卸载", "截图", "截屏",
    "点击", "滑动", "输入", "搜索", "发送", "下载", "上传",
    "复制", "粘贴", "传输", "同步", "分享",
    "拍照", "录屏", "录音", "播放", "暂停", "停止",
    "查看电量", "查看状态", "连接设备", "断开设备",
    "帮我操作", "帮我执行", "帮我控制",
    "在手机上", "在电脑上", "在平板上", "在设备上",
    "切换应用", "返回桌面", "锁屏", "解锁",
    "传到手机", "传到电脑", "发到手机", "发到电脑",
    "跨设备", "同步剪贴板", "设备间",
    # 中文 — 任务/工具
    "帮我写", "帮我生成", "帮我分析", "帮我总结", "帮我查",
    "帮我做", "帮我完成", "帮我处理", "帮我创建", "帮我规划",
    "执行", "运行代码", "调用", "生成", "创建文件", "创建目录",
    "读取文件", "写入文件", "删除文件", "搜索文件",
    "提交", "部署", "构建", "测试",
    # 中文 — 通用任务动词（带明确宾语场景）
    "做一个", "做个", "做一份", "制作一个", "制作一份",
    "写一个", "写一段", "写代码", "写脚本", "写报告",
    "创建一个", "创建一份", "生成一个", "生成一份",
    "分析一下", "分析这个", "分析数据", "分析代码",
    "总结一下", "整理一下", "规划一下",
    "实现一个", "实现功能", "完成任务",
    # 英文
    "open ", "close ", "launch ", "run ", "install ", "uninstall ",
    "click ", "swipe ", "type ", "screenshot", "send ", "download ",
    "upload ", "execute ", "control ", "operate ",
    "on my phone", "on my pc", "on device", "on android",
    "take photo", "record ", "play ", "pause ", "stop ",
    "write code", "generate ", "create file", "read file", "delete ",
    "search for", "find file", "deploy ", "build ", "commit ",
    # 英文 — 通用任务动词
    "write a ", "write me ", "create a ", "create an ", "make a ", "make me ",
    "build a ", "build me ", "implement ", "develop ", "design a ",
    "analyze ", "analyse ", "summarize ", "summarise ", "plan ", "schedule ",
    "help me with", "do this ", "do the ", "complete ",
]

# 低置信度任务词（结合上下文判断，单独出现可能是聊天）
# 注意：末尾空格是有意为之，防止"please" 匹配 "displeased" 等词的部分字符串
_TASK_KW_LOW: List[str] = [
    "帮我", "我想", "能不能", "可以帮", "请帮",
    "help me", "can you", "could you", "please ",
]

# 强聊天指示词（命中则倾向 chat_only，除非同时有高置信度任务词）
_CHAT_KW: List[str] = [
    "你好", "hi", "hello", "聊聊", "说说", "告诉我", "介绍",
    "什么是", "为什么", "怎么", "如何理解", "解释",
    "有趣", "好玩", "推荐", "建议", "觉得",
    "讲个故事", "讲笑话", "陪我",
]


def _classify_by_rules(message: str) -> IntentResult:
    """基于关键词规则快速分类意图。"""
    msg = message.lower().strip()

    high_hit = any(kw in msg for kw in _TASK_KW_HIGH)
    chat_hit = any(kw in msg for kw in _CHAT_KW)

    # 缓存第一个命中的任务关键词（避免重复遍历）
    task_kw = next((kw for kw in _TASK_KW_HIGH if kw in msg), "").strip()

    # ① 高置信度任务词优先判定（即使消息极短，如"截图"、"截屏"）
    if high_hit and chat_hit:
        # 同时命中任务词和聊天词 → hybrid
        return IntentResult(
            mode=IntentMode.HYBRID,
            confidence=0.75,
            task_hint=task_kw,
            raw_intent="hybrid",
            method="rules",
        )

    if high_hit:
        return IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=0.9,
            task_hint=task_kw,
            raw_intent="task_execute",
            method="rules",
        )

    # ② 极短消息（无高置信度任务词）→ 聊天
    if len(msg) < 4:
        return IntentResult(mode=IntentMode.CHAT_ONLY, confidence=0.9, method="rules")

    # ③ 低置信度任务词检查（消息已 >= 4 字符）
    low_hit = any(kw in msg for kw in _TASK_KW_LOW)

    if chat_hit and not low_hit:
        return IntentResult(mode=IntentMode.CHAT_ONLY, confidence=0.85, method="rules")

    if low_hit:
        # 弱任务信号 → 倾向任务执行（如 "帮我…"、"help me…"），但不够确定
        # 使用 task_execute 而非 chat_only，以触发 Agent 创建链路
        task_kw_low = next((kw for kw in _TASK_KW_LOW if kw in msg), "").strip()
        return IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=0.65,
            task_hint=task_kw_low,
            raw_intent="task_execute",
            method="rules",
        )

    # 无明确信号 → 对于较长的消息（>= 10 字符）默认进入任务执行链，
    # 对于极短的模糊消息保持聊天模式。
    # 设计原则：默认执行（task_execute），仅纯问答/闲聊保留 chat_only。
    if len(msg) >= 10:
        return IntentResult(
            mode=IntentMode.TASK_EXECUTE,
            confidence=0.55,
            task_hint="",
            raw_intent="task_execute",
            method="rules",
        )
    return IntentResult(mode=IntentMode.CHAT_ONLY, confidence=0.7, method="rules")


# ──────────────────────────────────────────────────────────────────────────────
# LLM 增强分类（可选）
# ──────────────────────────────────────────────────────────────────────────────

_LLM_CLASSIFY_PROMPT = """\
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
    timeout: float = 8.0,
) -> Optional[IntentResult]:
    """使用 LLM 增强意图分类（返回 None 表示 LLM 不可用或超时）。"""
    try:
        import json as _json

        prompt = _LLM_CLASSIFY_PROMPT.format(message=message)
        messages = [
            {"role": "system", "content": "你是一个意图分类助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]

        # 兼容两种路由器接口
        if hasattr(llm_router, "chat"):
            raw = await asyncio.wait_for(
                llm_router.chat(messages, temperature=0.0, max_tokens=128),
                timeout=timeout,
            )
            # LLMResponse 或 dict
            if hasattr(raw, "content"):
                text = raw.content
            elif isinstance(raw, dict):
                text = raw.get("content") or raw.get("response") or ""
            else:
                text = str(raw)
        else:
            return None

        # 提取 JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None
        data = _json.loads(match.group())

        mode = data.get("mode", IntentMode.CHAT_ONLY)
        if mode not in (IntentMode.CHAT_ONLY, IntentMode.TASK_EXECUTE, IntentMode.HYBRID):
            mode = IntentMode.CHAT_ONLY

        return IntentResult(
            mode=mode,
            confidence=float(data.get("confidence", 0.7)),
            task_hint=str(data.get("task_hint", "")),
            raw_intent=str(data.get("intent", "chat")),
            method="llm",
        )
    except asyncio.TimeoutError:
        logger.warning("LLM 意图分类超时 (%.1fs)", timeout)
        return None
    except Exception as exc:
        logger.debug("LLM 意图分类异常: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 主路由器类
# ──────────────────────────────────────────────────────────────────────────────

class IntentRouter:
    """意图路由器：规则优先，LLM 增强低置信度场景。"""

    def __init__(self, llm_router: Optional[Any] = None) -> None:
        self._llm_router = llm_router

    async def route(
        self,
        message: str,
        context: Optional[List[Dict[str, str]]] = None,
        use_llm: bool = True,
        llm_confidence_threshold: float = 0.6,
    ) -> IntentResult:
        """
        路由意图。

        Args:
            message: 用户输入
            context: 对话历史（可选）
            use_llm: 是否允许 LLM 增强（规则置信度不足时）
            llm_confidence_threshold: 低于此置信度触发 LLM 复核

        Returns:
            IntentResult
        """
        t0 = time.monotonic()

        # 步骤 1：规则分类
        rule_result = _classify_by_rules(message)
        logger.debug(
            "规则分类: mode=%s confidence=%.2f",
            rule_result.mode,
            rule_result.confidence,
        )

        # 步骤 2：若规则置信度不足 + LLM 可用 → LLM 增强
        final = rule_result
        if (
            use_llm
            and self._llm_router is not None
            and rule_result.confidence < llm_confidence_threshold
        ):
            llm_result = await _classify_by_llm(message, self._llm_router)
            if llm_result is not None:
                # LLM 覆盖置信度较低的规则结果
                if llm_result.confidence > rule_result.confidence:
                    llm_result.method = "rules+llm"
                    final = llm_result
                    logger.debug(
                        "LLM 分类覆盖规则: mode=%s confidence=%.2f",
                        final.mode,
                        final.confidence,
                    )

        final.latency_ms = (time.monotonic() - t0) * 1000
        return final
