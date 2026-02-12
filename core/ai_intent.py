"""
UFO Galaxy - AI 意图理解引擎
=============================

融合元气 AI Bot 精髓 - 智能感知：

模块内容：
  1. IntentParser       - LLM 意图解析（自然语言 → 结构化命令）
  2. ConversationMemory - 对话记忆系统（上下文理解）
  3. SmartRecommender   - 智能推荐引擎（个性化建议）
  4. SemanticSearch     - 语义搜索（向量化匹配）

目标：
  用户说"帮我整理任务" → 系统理解意图 → 自动执行 → 显示结果
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("UFO-Galaxy.AIIntent")


# ============================================================================
# 1. 意图解析器
# ============================================================================

@dataclass
class ParsedIntent:
    """解析后的意图"""
    intent: str              # 意图标签: task_manage, device_control, query, chat, etc.
    command: str             # 映射的命令
    targets: List[str]       # 目标节点/设备
    params: Dict[str, Any]   # 命令参数
    confidence: float        # 置信度 0-1
    raw_text: str            # 原始文本
    context_used: bool       # 是否使用了上下文
    suggestions: List[str]   # 后续建议

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "command": self.command,
            "targets": self.targets,
            "params": self.params,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
            "context_used": self.context_used,
            "suggestions": self.suggestions,
        }


class IntentParser:
    """
    意图解析器

    两级解析：
      1. 规则引擎 - 关键词匹配（低延迟，< 1ms）
      2. LLM 引擎 - 语义理解（高精度，需 API Key）
    """

    # 规则映射表
    RULE_PATTERNS = {
        "task_manage": {
            "keywords": ["任务", "待办", "计划", "安排", "整理", "todo", "task", "plan"],
            "command": "task_manage",
            "target": "Node_02_Tasker",
        },
        "device_control": {
            "keywords": ["设备", "手机", "打开", "关闭", "截图", "点击", "device"],
            "command": "device_control",
            "target": "device",
        },
        "file_operation": {
            "keywords": ["文件", "目录", "创建", "删除", "上传", "下载", "file"],
            "command": "file_operation",
            "target": "Node_06_Filesystem",
        },
        "search": {
            "keywords": ["搜索", "查找", "查询", "找", "search", "find", "query"],
            "command": "search",
            "target": "Node_20_Qdrant",
        },
        "ocr": {
            "keywords": ["识别", "OCR", "文字", "图片", "截图识别"],
            "command": "ocr",
            "target": "Node_15_OCR",
        },
        "system_status": {
            "keywords": ["状态", "健康", "运行", "监控", "status", "health"],
            "command": "system_status",
            "target": "system",
        },
        "chat": {
            "keywords": ["聊天", "对话", "问", "说", "chat", "talk"],
            "command": "chat",
            "target": "llm",
        },
        "network": {
            "keywords": ["网络", "连接", "IP", "端口", "Tailscale", "network"],
            "command": "network",
            "target": "Node_82_NetworkGuard",
        },
        "code": {
            "keywords": ["代码", "编程", "运行", "执行", "code", "run", "execute"],
            "command": "code_execute",
            "target": "Node_117_OpenCode",
        },
    }

    def __init__(self, llm_client=None):
        self._llm = llm_client
        self._parse_cache: Dict[str, ParsedIntent] = {}

    async def parse(self, text: str, context: Optional[Dict] = None) -> ParsedIntent:
        """
        解析用户输入意图

        优先使用规则引擎，低置信度时回退到 LLM
        """
        # 缓存命中
        cache_key = hashlib.md5(text.lower().strip().encode()).hexdigest()
        if cache_key in self._parse_cache:
            return self._parse_cache[cache_key]

        # 第一级：规则引擎
        result = self._parse_by_rules(text)

        # 如果置信度不够高且有 LLM，使用 LLM 增强
        if result.confidence < 0.7 and self._llm:
            try:
                llm_result = await self._parse_by_llm(text, context)
                if llm_result and llm_result.confidence > result.confidence:
                    result = llm_result
                    result.context_used = context is not None
            except Exception as e:
                logger.warning(f"LLM intent parsing failed, using rule result: {e}")

        # 生成后续建议
        result.suggestions = self._generate_suggestions(result.intent)

        # 缓存结果
        self._parse_cache[cache_key] = result
        if len(self._parse_cache) > 1000:
            # 简单 LRU：清除一半
            keys = list(self._parse_cache.keys())
            for k in keys[:500]:
                del self._parse_cache[k]

        return result

    def _parse_by_rules(self, text: str) -> ParsedIntent:
        """规则引擎解析"""
        text_lower = text.lower()
        best_intent = None
        best_score = 0

        for intent_name, pattern in self.RULE_PATTERNS.items():
            score = 0
            for keyword in pattern["keywords"]:
                if keyword.lower() in text_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_intent = intent_name

        if best_intent and best_score > 0:
            pattern = self.RULE_PATTERNS[best_intent]
            confidence = min(0.3 + best_score * 0.2, 0.9)
            return ParsedIntent(
                intent=best_intent,
                command=pattern["command"],
                targets=[pattern["target"]],
                params={"instruction": text},
                confidence=confidence,
                raw_text=text,
                context_used=False,
                suggestions=[],
            )

        # 默认回退到聊天
        return ParsedIntent(
            intent="chat",
            command="chat",
            targets=["llm"],
            params={"message": text},
            confidence=0.3,
            raw_text=text,
            context_used=False,
            suggestions=[],
        )

    async def _parse_by_llm(self, text: str, context: Optional[Dict]) -> Optional[ParsedIntent]:
        """LLM 意图解析"""
        available_intents = list(self.RULE_PATTERNS.keys()) + ["chat"]

        system_prompt = f"""你是 UFO Galaxy 意图解析器。用户会输入自然语言，你需要：
1. 判断意图类别（可选: {', '.join(available_intents)}）
2. 提取命令和参数
3. 确定目标节点

返回 JSON 格式：
{{"intent": "...", "command": "...", "targets": [...], "params": {{...}}, "confidence": 0.0-1.0}}"""

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if context and context.get("history"):
            for h in context["history"][-3:]:
                messages.append(h)
        messages.append({"role": "user", "content": text})

        try:
            import httpx

            # 尝试不同的 LLM 提供商
            api_key = os.environ.get("OPENAI_API_KEY", "")
            api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")

            if not api_key:
                api_key = os.environ.get("DEEPSEEK_API_KEY", "")
                api_base = "https://api.deepseek.com/v1"

            if not api_key:
                return None

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "max_tokens": 256,
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)

                return ParsedIntent(
                    intent=parsed.get("intent", "chat"),
                    command=parsed.get("command", "chat"),
                    targets=parsed.get("targets", ["llm"]),
                    params=parsed.get("params", {"message": text}),
                    confidence=float(parsed.get("confidence", 0.8)),
                    raw_text=text,
                    context_used=True,
                    suggestions=[],
                )
        except Exception as e:
            logger.warning(f"LLM intent parse failed: {e}")
            return None

    def _generate_suggestions(self, intent: str) -> List[str]:
        """生成后续建议"""
        suggestion_map = {
            "task_manage": ["查看所有任务", "创建新任务", "按优先级排序"],
            "device_control": ["查看设备状态", "截取屏幕", "执行自动化流程"],
            "file_operation": ["列出目录", "上传文件", "搜索文件"],
            "search": ["按语义搜索", "查看历史搜索", "筛选结果"],
            "ocr": ["识别文字", "提取表格", "翻译内容"],
            "system_status": ["查看节点状态", "检查健康", "查看日志"],
            "chat": ["继续对话", "切换模型", "清除上下文"],
            "network": ["检查连接", "查看端口", "测试延迟"],
            "code": ["执行代码", "查看输出", "保存结果"],
        }
        return suggestion_map.get(intent, ["继续操作", "查看帮助"])


# ============================================================================
# 2. 对话记忆系统
# ============================================================================

@dataclass
class ConversationTurn:
    """对话轮次"""
    role: str          # user / assistant / system
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """
    对话记忆系统

    支持：
      - 短期记忆（当前会话上下文，最近 20 轮）
      - 长期记忆（Redis / 向量数据库持久化）
      - 摘要压缩（超出窗口时自动摘要）
      - 用户偏好学习
    """

    def __init__(self, cache_backend=None, max_turns: int = 20):
        self._cache = cache_backend
        self.max_turns = max_turns
        self._sessions: Dict[str, List[ConversationTurn]] = {}
        self._user_profiles: Dict[str, Dict[str, Any]] = {}

    async def add_turn(self, session_id: str, role: str, content: str, metadata: Optional[Dict] = None):
        """添加对话轮次"""
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        turn = ConversationTurn(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self._sessions[session_id].append(turn)

        # 超出最大轮次时裁剪
        if len(self._sessions[session_id]) > self.max_turns:
            self._sessions[session_id] = self._sessions[session_id][-self.max_turns:]

        # 持久化到缓存
        if self._cache:
            await self._persist_session(session_id)

        # 学习用户偏好
        if role == "user":
            self._learn_preference(session_id, content)

    async def get_context(self, session_id: str, max_turns: int = 10) -> List[Dict]:
        """获取对话上下文"""
        turns = self._sessions.get(session_id, [])

        # 尝试从缓存恢复
        if not turns and self._cache:
            turns = await self._restore_session(session_id)

        context = []
        for turn in turns[-max_turns:]:
            context.append({
                "role": turn.role,
                "content": turn.content,
            })
        return context

    async def get_summary(self, session_id: str) -> str:
        """获取会话摘要"""
        turns = self._sessions.get(session_id, [])
        if not turns:
            return "空会话"

        topics = set()
        for turn in turns:
            if turn.role == "user":
                words = turn.content[:50]
                topics.add(words)

        return f"会话包含 {len(turns)} 轮对话，涉及主题: {', '.join(list(topics)[:5])}"

    def get_user_profile(self, session_id: str) -> Dict[str, Any]:
        """获取用户偏好画像"""
        return self._user_profiles.get(session_id, {
            "frequent_intents": {},
            "preferred_model": None,
            "interaction_count": 0,
        })

    async def clear_session(self, session_id: str):
        """清除会话"""
        self._sessions.pop(session_id, None)
        if self._cache:
            await self._cache.delete(f"conversation:{session_id}")

    def _learn_preference(self, session_id: str, content: str):
        """学习用户偏好"""
        if session_id not in self._user_profiles:
            self._user_profiles[session_id] = {
                "frequent_intents": defaultdict(int),
                "preferred_model": None,
                "interaction_count": 0,
                "first_seen": time.time(),
            }
        profile = self._user_profiles[session_id]
        profile["interaction_count"] += 1

        # 简单的意图统计
        for intent, pattern in IntentParser.RULE_PATTERNS.items():
            if any(kw in content.lower() for kw in pattern["keywords"]):
                profile["frequent_intents"][intent] += 1

    async def _persist_session(self, session_id: str):
        """持久化会话到缓存"""
        try:
            turns_data = [
                {
                    "role": t.role,
                    "content": t.content,
                    "timestamp": t.timestamp,
                    "metadata": t.metadata,
                }
                for t in self._sessions[session_id]
            ]
            await self._cache.set(
                f"conversation:{session_id}",
                json.dumps(turns_data, ensure_ascii=False),
                ttl=3600,
            )
        except Exception as e:
            logger.warning(f"Failed to persist session {session_id}: {e}")

    async def _restore_session(self, session_id: str) -> List[ConversationTurn]:
        """从缓存恢复会话"""
        try:
            raw = await self._cache.get(f"conversation:{session_id}")
            if raw:
                data = json.loads(raw)
                turns = [
                    ConversationTurn(
                        role=t["role"],
                        content=t["content"],
                        timestamp=t.get("timestamp", time.time()),
                        metadata=t.get("metadata", {}),
                    )
                    for t in data
                ]
                self._sessions[session_id] = turns
                return turns
        except Exception as e:
            logger.warning(f"Failed to restore session {session_id}: {e}")
        return []


# ============================================================================
# 3. 智能推荐引擎
# ============================================================================

class SmartRecommender:
    """
    智能推荐引擎

    基于：
      - 用户历史行为
      - 当前上下文
      - 系统状态
      - 时间模式
    """

    def __init__(self, memory: Optional[ConversationMemory] = None):
        self._memory = memory
        self._action_history: Dict[str, List[Dict]] = defaultdict(list)

    async def get_recommendations(
        self, session_id: str, current_context: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """获取智能推荐"""
        recommendations = []

        # 1. 基于用户偏好
        if self._memory:
            profile = self._memory.get_user_profile(session_id)
            freq_intents = profile.get("frequent_intents", {})
            if freq_intents:
                top_intent = max(freq_intents, key=freq_intents.get)
                recommendations.append({
                    "type": "frequent_action",
                    "intent": top_intent,
                    "label": f"常用: {top_intent}",
                    "confidence": 0.8,
                })

        # 2. 基于时间模式
        hour = datetime.now().hour
        if 9 <= hour <= 11:
            recommendations.append({
                "type": "time_based",
                "intent": "task_manage",
                "label": "早间任务规划",
                "confidence": 0.6,
            })
        elif 14 <= hour <= 17:
            recommendations.append({
                "type": "time_based",
                "intent": "system_status",
                "label": "下午系统巡检",
                "confidence": 0.5,
            })

        # 3. 基于系统状态
        if current_context:
            devices = current_context.get("devices", {})
            if devices:
                offline_count = sum(
                    1 for d in devices.values()
                    if d.get("status") != "online"
                )
                if offline_count > 0:
                    recommendations.append({
                        "type": "system_alert",
                        "intent": "device_control",
                        "label": f"{offline_count} 设备离线",
                        "confidence": 0.9,
                    })

        # 4. 快捷操作
        recommendations.extend([
            {"type": "quick_action", "intent": "system_status", "label": "系统状态", "confidence": 0.4},
            {"type": "quick_action", "intent": "search", "label": "语义搜索", "confidence": 0.4},
        ])

        # 按置信度排序，去重
        seen = set()
        unique = []
        for r in sorted(recommendations, key=lambda x: x["confidence"], reverse=True):
            if r["intent"] not in seen:
                seen.add(r["intent"])
                unique.append(r)

        return unique[:5]

    def record_action(self, session_id: str, intent: str, success: bool):
        """记录用户操作（用于强化学习）"""
        self._action_history[session_id].append({
            "intent": intent,
            "success": success,
            "timestamp": time.time(),
        })
        # 保留最近 200 条
        if len(self._action_history[session_id]) > 200:
            self._action_history[session_id] = self._action_history[session_id][-100:]


# ============================================================================
# 4. 语义搜索（轻量版，不依赖外部向量数据库）
# ============================================================================

class SemanticSearch:
    """
    语义搜索引擎

    双模式：
      - 本地模式：Jaccard 相似度（无外部依赖）
      - Qdrant 模式：向量数据库语义搜索（高精度）

    自动检测 Qdrant 可用性并升级。
    """

    def __init__(self, qdrant_url: str = ""):
        self._index: Dict[str, Dict[str, Any]] = {}
        self._qdrant_client = None
        self._collection_name = "ufo_galaxy_docs"
        self._qdrant_url = qdrant_url or os.environ.get("QDRANT_URL", "")
        self._qdrant_ready = False

    async def initialize_qdrant(self):
        """尝试连接 Qdrant 向量数据库"""
        if not self._qdrant_url:
            return False
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._qdrant_client = QdrantClient(url=self._qdrant_url, timeout=5)
            # 检查连接
            self._qdrant_client.get_collections()

            # 确保 collection 存在
            collections = [c.name for c in self._qdrant_client.get_collections().collections]
            if self._collection_name not in collections:
                self._qdrant_client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )

            self._qdrant_ready = True
            logger.info(f"Qdrant 已连接: {self._qdrant_url}")
            return True
        except ImportError:
            logger.info("qdrant-client 未安装，使用本地搜索模式")
            return False
        except Exception as e:
            logger.info(f"Qdrant 不可用: {e}，使用本地搜索模式")
            return False

    def index_document(self, doc_id: str, content: str, metadata: Optional[Dict] = None):
        """索引文档（本地模式）"""
        words = set(content.lower().split())
        self._index[doc_id] = {
            "content": content,
            "words": words,
            "metadata": metadata or {},
            "indexed_at": time.time(),
        }

    async def index_document_vector(self, doc_id: str, content: str, vector: List[float], metadata: Optional[Dict] = None):
        """索引文档到 Qdrant（向量模式）"""
        if not self._qdrant_ready or not self._qdrant_client:
            self.index_document(doc_id, content, metadata)
            return

        try:
            from qdrant_client.models import PointStruct
            self._qdrant_client.upsert(
                collection_name=self._collection_name,
                points=[PointStruct(
                    id=hash(doc_id) & 0x7FFFFFFFFFFFFFFF,  # 正整数
                    vector=vector,
                    payload={"doc_id": doc_id, "content": content, **(metadata or {})},
                )],
            )
        except Exception as e:
            logger.warning(f"Qdrant 索引失败: {e}")
            self.index_document(doc_id, content, metadata)

    async def search_vector(self, query_vector: List[float], top_k: int = 5) -> List[Dict]:
        """向量搜索（Qdrant 模式）"""
        if not self._qdrant_ready or not self._qdrant_client:
            return []

        try:
            results = self._qdrant_client.search(
                collection_name=self._collection_name,
                query_vector=query_vector,
                limit=top_k,
            )
            return [
                {
                    "doc_id": r.payload.get("doc_id", ""),
                    "content": r.payload.get("content", "")[:200],
                    "score": round(r.score, 4),
                    "metadata": {k: v for k, v in r.payload.items() if k not in ("doc_id", "content")},
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"Qdrant 搜索失败: {e}")
            return []

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """本地搜索（Jaccard 相似度）"""
        query_words = set(query.lower().split())
        scores = []

        for doc_id, doc in self._index.items():
            intersection = query_words & doc["words"]
            union = query_words | doc["words"]
            score = len(intersection) / max(len(union), 1)
            if score > 0:
                scores.append({
                    "doc_id": doc_id,
                    "content": doc["content"][:200],
                    "score": round(score, 4),
                    "metadata": doc["metadata"],
                })

        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]

    @property
    def document_count(self) -> int:
        return len(self._index)

    @property
    def is_vector_mode(self) -> bool:
        return self._qdrant_ready


# ============================================================================
# 全局实例
# ============================================================================

_intent_parser: Optional[IntentParser] = None
_conversation_memory: Optional[ConversationMemory] = None
_smart_recommender: Optional[SmartRecommender] = None


def get_intent_parser(**kwargs) -> IntentParser:
    global _intent_parser
    if _intent_parser is None:
        _intent_parser = IntentParser(**kwargs)
    return _intent_parser


def get_conversation_memory(**kwargs) -> ConversationMemory:
    global _conversation_memory
    if _conversation_memory is None:
        _conversation_memory = ConversationMemory(**kwargs)
    return _conversation_memory


def get_smart_recommender(**kwargs) -> SmartRecommender:
    global _smart_recommender
    if _smart_recommender is None:
        memory = kwargs.pop("memory", get_conversation_memory())
        _smart_recommender = SmartRecommender(memory=memory, **kwargs)
    return _smart_recommender
