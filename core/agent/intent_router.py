"""
Galaxy - Intent Router
========================

将用户输入分类为三种模式:
  chat_only     — 纯对话，不执行任务（不注入 SOUL）
  task_execute  — 纯任务执行（注入 SOUL + AGENTS）
  hybrid        — 先聊天再执行，或二者交织（注入 SOUL + AGENTS）

分类策略（双轨）:
  1. 规则引擎   — 关键词 + 启发式，< 1ms，零成本
  2. LLM 增强   — 语义理解，接口可用时触发，高精度

RouterDecision 包含:
  mode        — IntentMode 枚举
  confidence  — 0.0-1.0 置信度
  intent_label— 细粒度意图标签（task_manage / device_control / chat ...）
  reasoning   — 分类依据（日志 / 调试用途）
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.IntentRouter")


# ============================================================================
# 枚举与数据模型
# ============================================================================

class IntentMode(str, Enum):
    """消息处理模式"""
    CHAT_ONLY = "chat_only"
    TASK_EXECUTE = "task_execute"
    HYBRID = "hybrid"


@dataclass
class RouterDecision:
    """意图路由决策结果"""
    mode: IntentMode
    confidence: float
    intent_label: str
    reasoning: str
    suggested_tools: List[str] = field(default_factory=list)
    raw_llm_output: Optional[str] = None

    def is_execution(self) -> bool:
        """是否需要进入执行链路（task_execute 或 hybrid）"""
        return self.mode in (IntentMode.TASK_EXECUTE, IntentMode.HYBRID)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "confidence": self.confidence,
            "intent_label": self.intent_label,
            "reasoning": self.reasoning,
            "suggested_tools": self.suggested_tools,
        }


# ============================================================================
# 规则引擎关键词表
# ============================================================================

# 明确执行意图关键词（中文）
_EXEC_KW_ZH = [
    "打开", "关闭", "启动", "运行", "安装", "卸载",
    "截图", "截屏", "点击", "滑动", "输入", "搜索",
    "发送", "下载", "上传", "传输", "同步", "分享",
    "拍照", "录屏", "录音", "播放", "暂停", "停止",
    "帮我操作", "帮我执行", "帮我控制", "帮我实现",
    "在手机上", "在电脑上", "在平板上", "在设备上",
    "切换应用", "返回桌面", "锁屏", "解锁",
    "传到手机", "传到电脑", "发到手机", "发到电脑",
    "跨设备", "同步剪贴板", "设备间",
    "写代码", "生成代码", "创建文件", "删除文件",
    "查找文件", "移动文件", "复制文件",
    "执行命令", "运行脚本", "调用接口",
    "帮我", "自动", "自动化", "批量",
]

# 明确执行意图关键词（英文/小写）
_EXEC_KW_EN = [
    "open ", "close ", "launch ", "run ", "install ",
    "click ", "swipe ", "screenshot", "send ", "download ",
    "upload ", "execute ", "control ", "operate ",
    "on my phone", "on my pc", "on device", "on android",
    "take photo", "record ", "create file", "delete file",
    "write code", "generate code", "run script",
    "help me ", "automate ", "batch ",
]

# 明确聊天意图（这些命中则优先判定为 chat_only）
_CHAT_KW_ZH = [
    "你好", "嗨", "你是谁", "介绍", "聊聊", "说说",
    "什么是", "如何理解", "解释", "讲一下", "告诉我",
    "谢谢", "感谢", "再见", "拜拜",
    "哈哈", "笑", "好的", "明白",
    "能不能", "可不可以", "有没有", "是不是",
]

_CHAT_KW_EN = [
    "hello", "hi ", "who are you", "what is ", "explain ",
    "tell me", "describe ", "how does ", "thank",
    "bye", "goodbye", "ok", "sure",
]

# 混合关键词模式（先聊后执行，或问题中含执行请求）
_HYBRID_PATTERNS = [
    r".{0,20}(然后|接着|再|之后).{0,20}(帮我|执行|运行|打开)",
    r"(先|首先).{0,30}(然后|再).{0,30}(帮|打开|运行)",
    r"(解释|说明|讲讲).{0,40}(并|同时|然后|顺便).{0,30}(执行|帮我)",
]
_HYBRID_RE = [re.compile(p) for p in _HYBRID_PATTERNS]

# 极短消息几乎都是闲聊
_CHAT_ONLY_MAX_LEN = 6


# ============================================================================
# IntentRouter
# ============================================================================

class IntentRouter:
    """
    意图路由器

    classify() 是主入口，返回 RouterDecision:
      1. 极短消息 → chat_only (快速路径)
      2. 混合模式正则 → hybrid
      3. 执行关键词命中 → task_execute
      4. 聊天关键词命中 → chat_only
      5. 可选: LLM 语义增强（llm_router 不为 None 时）
      6. 默认兜底 → chat_only（保守策略，避免误触发执行）
    """

    def __init__(self, llm_router=None):
        """
        Args:
            llm_router: 可选，MultiLLMRouter 实例。
                        提供后对规则无法确定的消息用 LLM 语义增强分类。
        """
        self._llm_router = llm_router
        logger.info("IntentRouter 初始化 (llm_enhanced=%s)", llm_router is not None)

    def set_llm_router(self, llm_router) -> None:
        """动态注入 LLM 路由器（允许延迟注入）"""
        self._llm_router = llm_router

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def classify(
        self,
        message: str,
        context: Optional[List[Dict[str, str]]] = None,
    ) -> RouterDecision:
        """
        分类消息意图。

        Args:
            message: 用户消息
            context: 历史对话上下文（可选，用于 LLM 增强）

        Returns:
            RouterDecision
        """
        msg = message.strip()
        if not msg:
            return RouterDecision(
                mode=IntentMode.CHAT_ONLY,
                confidence=1.0,
                intent_label="empty",
                reasoning="消息为空",
            )

        # 快速路径: 极短消息
        if len(msg) <= _CHAT_ONLY_MAX_LEN:
            return RouterDecision(
                mode=IntentMode.CHAT_ONLY,
                confidence=0.85,
                intent_label="chat",
                reasoning=f"消息长度 ≤ {_CHAT_ONLY_MAX_LEN} 字，判定为闲聊",
            )

        # 规则引擎
        rule_decision = self._rule_classify(msg)

        # 如果规则置信度 ≥ 0.8，直接返回，无需 LLM
        if rule_decision.confidence >= 0.8:
            logger.debug(
                "IntentRouter[rule]: mode=%s conf=%.2f label=%s",
                rule_decision.mode.value,
                rule_decision.confidence,
                rule_decision.intent_label,
            )
            return rule_decision

        # LLM 语义增强（规则模糊时）
        if self._llm_router is not None:
            try:
                llm_decision = await self._llm_classify(msg, context or [])
                # LLM 置信度更高时采用 LLM 结果
                if llm_decision.confidence > rule_decision.confidence:
                    logger.debug(
                        "IntentRouter[llm]: mode=%s conf=%.2f label=%s",
                        llm_decision.mode.value,
                        llm_decision.confidence,
                        llm_decision.intent_label,
                    )
                    return llm_decision
            except Exception as e:
                logger.debug("LLM 意图分类失败，回退到规则结果: %s", e)

        return rule_decision

    # ------------------------------------------------------------------
    # 规则引擎
    # ------------------------------------------------------------------

    def _rule_classify(self, msg: str) -> RouterDecision:
        """基于关键词和规则的快速分类"""
        msg_lower = msg.lower()

        # 1. 混合模式检测（正则）
        for pattern in _HYBRID_RE:
            if pattern.search(msg):
                return RouterDecision(
                    mode=IntentMode.HYBRID,
                    confidence=0.82,
                    intent_label="hybrid",
                    reasoning="匹配混合模式正则（先聊后执行或联合描述）",
                )

        # 2. 执行关键词计分
        exec_score = 0
        exec_hits: List[str] = []
        for kw in _EXEC_KW_ZH:
            if kw in msg:
                exec_score += 1
                exec_hits.append(kw)
        for kw in _EXEC_KW_EN:
            if kw in msg_lower:
                exec_score += 1
                exec_hits.append(kw)

        # 3. 聊天关键词计分
        chat_score = 0
        chat_hits: List[str] = []
        for kw in _CHAT_KW_ZH:
            if kw in msg:
                chat_score += 1
                chat_hits.append(kw)
        for kw in _CHAT_KW_EN:
            if kw in msg_lower:
                chat_score += 1
                chat_hits.append(kw)

        # 4. 决策逻辑
        if exec_score > 0 and chat_score > 0:
            # 两者都命中 → hybrid
            return RouterDecision(
                mode=IntentMode.HYBRID,
                confidence=0.75,
                intent_label="hybrid",
                reasoning=f"执行关键词={exec_hits}, 聊天关键词={chat_hits}",
            )

        if exec_score >= 2:
            return RouterDecision(
                mode=IntentMode.TASK_EXECUTE,
                confidence=min(0.65 + exec_score * 0.08, 0.95),
                intent_label=self._infer_exec_label(msg, exec_hits),
                reasoning=f"执行关键词命中 {exec_score} 个: {exec_hits[:4]}",
                suggested_tools=self._suggest_tools(exec_hits),
            )

        if exec_score == 1:
            return RouterDecision(
                mode=IntentMode.TASK_EXECUTE,
                confidence=0.65,
                intent_label=self._infer_exec_label(msg, exec_hits),
                reasoning=f"执行关键词命中 1 个: {exec_hits}",
                suggested_tools=self._suggest_tools(exec_hits),
            )

        if chat_score >= 1:
            return RouterDecision(
                mode=IntentMode.CHAT_ONLY,
                confidence=min(0.70 + chat_score * 0.08, 0.90),
                intent_label="chat",
                reasoning=f"聊天关键词命中 {chat_score} 个: {chat_hits[:4]}",
            )

        # 5. 启发式：消息较长时倾向于需要执行
        if len(msg) > 50:
            return RouterDecision(
                mode=IntentMode.TASK_EXECUTE,
                confidence=0.52,
                intent_label="task_manage",
                reasoning=f"消息较长（{len(msg)} 字），规则无明确分类，倾向任务执行",
            )

        # 6. 默认兜底：chat_only（保守）
        return RouterDecision(
            mode=IntentMode.CHAT_ONLY,
            confidence=0.55,
            intent_label="chat",
            reasoning="规则无明确分类，保守降级到 chat_only",
        )

    def _infer_exec_label(self, msg: str, hits: List[str]) -> str:
        """从命中的执行关键词推断细粒度意图标签"""
        device_kw = {"打开", "关闭", "截图", "点击", "滑动", "录屏", "手机", "设备", "click", "swipe", "screenshot"}
        file_kw = {"文件", "创建", "删除", "移动", "写", "file", "create", "delete"}
        code_kw = {"代码", "脚本", "函数", "写代码", "生成代码", "code", "script"}
        search_kw = {"搜索", "查找", "查询", "search", "find"}
        for kw in hits:
            if kw in device_kw:
                return "device_control"
            if kw in file_kw:
                return "file_operation"
            if kw in code_kw:
                return "code"
            if kw in search_kw:
                return "search"
        return "task_manage"

    def _suggest_tools(self, exec_hits: List[str]) -> List[str]:
        """根据命中关键词建议候选工具"""
        tools: List[str] = []
        hit_set = set(exec_hits)
        if hit_set & {"截图", "screenshot", "截屏"}:
            tools.append("device_screenshot")
        if hit_set & {"打开", "启动", "open ", "launch "}:
            tools.append("device_launch_app")
        if hit_set & {"搜索", "search "}:
            tools.append("web_search")
        if hit_set & {"代码", "脚本", "code", "script"}:
            tools.append("code_execute")
        if hit_set & {"文件", "file", "create file", "delete file"}:
            tools.append("filesystem")
        return tools

    # ------------------------------------------------------------------
    # LLM 语义增强
    # ------------------------------------------------------------------

    async def _llm_classify(
        self,
        message: str,
        context: List[Dict[str, str]],
    ) -> RouterDecision:
        """
        使用 LLM 对规则无法确定的消息进行语义分类。

        系统提示要求 LLM 以 JSON 格式返回分类结果，避免自由文本解析歧义。
        """
        system_prompt = (
            "你是 Galaxy 智能体的意图分类模块。\n"
            "根据用户消息，输出 JSON 格式分类（只输出 JSON，不加任何解释）：\n"
            '{"mode": "chat_only|task_execute|hybrid", '
            '"confidence": 0.0-1.0, '
            '"intent_label": "chat|device_control|task_manage|file_operation|code|search|hybrid", '
            '"reasoning": "简短说明"}\n\n'
            "规则：\n"
            "- chat_only: 问候、提问、闲聊、解释性问题，不需要系统执行任何操作\n"
            "- task_execute: 明确要求系统执行某操作（设备控制、文件操作、代码运行等）\n"
            "- hybrid: 既有聊天也有任务，或不确定时包含执行成分"
        )

        messages = [{"role": "system", "content": system_prompt}]
        for ctx in (context or [])[-4:]:
            messages.append(ctx)
        messages.append({"role": "user", "content": message})

        response = await self._llm_router.chat_completion(
            messages=messages,
            task_type="FAST_RESPONSE",
        )
        raw = response.choices[0].message.content or ""

        # 解析 JSON 响应
        import json
        # 提取 JSON 块（防止 LLM 在 JSON 前后加了文字）
        json_match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"LLM 未返回有效 JSON: {raw[:200]}")

        data = json.loads(json_match.group())
        mode_str = data.get("mode", "chat_only")
        try:
            mode = IntentMode(mode_str)
        except ValueError:
            mode = IntentMode.CHAT_ONLY

        return RouterDecision(
            mode=mode,
            confidence=float(data.get("confidence", 0.7)),
            intent_label=data.get("intent_label", "chat"),
            reasoning=data.get("reasoning", "LLM 分类"),
            raw_llm_output=raw,
        )
