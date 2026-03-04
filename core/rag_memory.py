"""
RAGMemory — 检索增强记忆系统
==============================

Phase 4 Matrix OS 核心组件。

将分散的记忆/知识系统统一为一个可被 Agent 调用的 RAG 管道:

1. 经验记忆 (Experience Log):
   - Agent 每次执行的 Thought/Action/Observation 自动归档
   - 按 device_id / agent_name / timestamp 索引
   - 支持相似经验检索 (为 Agent 提供 Few-shot 参考)

2. 知识库检索 (Knowledge RAG):
   - 对接 Node_105_UnifiedKnowledgeBase 和 Node_72_KnowledgeBase
   - 向量相似性搜索 + 关键词混合
   - 返回最相关的知识片段注入到 Agent system_prompt

3. 对话记忆 (Conversation):
   - 融合 ai_intent.ConversationMemory
   - 长短期记忆管理
   - 跨会话摘要

4. 学习积累 (Learning):
   - 从重复 pattern 中提取知识
   - 自动生成新工具/新规则建议
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger("UFO-Galaxy.RAGMemory")


@dataclass
class ExperienceEntry:
    """Agent 执行经验条目"""
    experience_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agent_name: str = ""
    device_id: str = ""
    instruction: str = ""
    steps: List[Dict] = field(default_factory=list)
    final_output: str = ""
    success: bool = True
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "experience_id": self.experience_id,
            "agent_name": self.agent_name,
            "device_id": self.device_id,
            "instruction": self.instruction,
            "steps": self.steps,
            "final_output": self.final_output,
            "success": self.success,
            "timestamp": self.timestamp,
            "tags": self.tags,
        }

    def to_text(self) -> str:
        """转换为可检索的文本"""
        step_texts = []
        for s in self.steps:
            step_texts.append(
                f"Thought: {s.get('thought', '')}\n"
                f"Action: {s.get('action', '')}\n"
                f"Observation: {s.get('observation', '')}"
            )
        return (
            f"Task: {self.instruction}\n"
            f"Agent: {self.agent_name}\n"
            f"Steps:\n" + "\n---\n".join(step_texts) + "\n"
            f"Result: {self.final_output}\n"
            f"Success: {self.success}"
        )


@dataclass
class KnowledgeChunk:
    """知识片段"""
    chunk_id: str = ""
    content: str = ""
    source: str = ""          # 来源 (node_name, file_path, url)
    relevance_score: float = 0.0
    metadata: Dict = field(default_factory=dict)


class RAGMemory:
    """
    检索增强记忆系统

    统一入口, 整合:
    - 经验日志 (内存 + 文件持久化)
    - 知识库检索 (对接现有 Node)
    - 对话记忆 (对接 ai_intent)
    - 学习积累 (pattern → rule)

    新增：命名空间/租户隔离
    - 传入 namespace 参数时，按命名空间读写，互不干扰
    - 不传 namespace 则使用全局（默认）行为，兼容现有代码
    """

    def __init__(self, data_dir: str = None, namespace: str = ""):
        self._namespace = namespace or ""
        self._data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "rag_memory"
        )
        # 若有命名空间，使用独立子目录
        if self._namespace:
            self._data_dir = os.path.join(self._data_dir, "ns_" + self._namespace)
        os.makedirs(self._data_dir, exist_ok=True)

        # 统计 (必须在 _load_experiences 之前初始化)
        self._stats = {"experiences_total": 0, "queries_total": 0, "patterns_learned": 0}

        # 经验库 (内存 + 文件)
        self._experiences: List[ExperienceEntry] = []
        self._load_experiences()

        # 学习到的 patterns
        self._patterns: List[Dict] = []

    @staticmethod
    def namespace_for(device_id: str = "", worker_id: str = "") -> str:
        """从 device_id 或 worker_id 推导 namespace 字符串"""
        if device_id:
            return f"device_{device_id}"
        if worker_id:
            return f"worker_{worker_id}"
        return ""

    # ================================================================
    # 经验记录
    # ================================================================

    def log_experience(
        self,
        agent_name: str,
        instruction: str,
        steps: List[Dict],
        final_output: str,
        success: bool,
        device_id: str = "",
        tags: List[str] = None,
    ) -> ExperienceEntry:
        """记录一次 Agent 执行经验"""
        entry = ExperienceEntry(
            agent_name=agent_name,
            device_id=device_id,
            instruction=instruction,
            steps=steps,
            final_output=final_output,
            success=success,
            tags=tags or [],
        )
        self._experiences.append(entry)
        self._stats["experiences_total"] += 1

        # 持久化
        self._save_experience(entry)

        # 检查 patterns
        self._detect_patterns(entry)

        logger.info(
            f"Experience logged: {entry.experience_id} "
            f"[{agent_name}] success={success}"
        )
        return entry

    def recall_similar(
        self, instruction: str, top_k: int = 3, device_id: str = ""
    ) -> List[ExperienceEntry]:
        """检索相似经验 (N-gram + 关键词匹配 + 时间权重)"""
        self._stats["queries_total"] += 1

        if not self._experiences:
            return []

        # 关键词提取 (空格分词 + 中文 2-gram)
        keywords = set()
        for w in instruction.lower().split():
            if len(w) > 1:
                keywords.add(w)
        # 中文 2-gram / 3-gram
        for n in (2, 3):
            for i in range(len(instruction) - n + 1):
                gram = instruction[i:i+n]
                if not gram.isspace():
                    keywords.add(gram.lower())

        scored = []
        for exp in self._experiences:
            score = 0.0
            exp_text = (exp.instruction + " " + exp.agent_name + " " +
                        " ".join(exp.tags)).lower()

            # 关键词匹配
            for kw in keywords:
                if kw in exp_text:
                    score += 10.0

            # 设备匹配加分
            if device_id and exp.device_id == device_id:
                score += 5.0

            # 成功经验加分
            if exp.success:
                score += 3.0

            # 时间衰减 (越近越好)
            age_hours = (time.time() - exp.timestamp) / 3600
            score *= max(0.1, 1.0 - age_hours / (24 * 30))  # 30天衰减到10%

            if score > 0:
                scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:top_k]]

    def format_few_shot_context(
        self, instruction: str, top_k: int = 2, device_id: str = ""
    ) -> str:
        """将相似经验格式化为 Few-shot Context, 可注入 Agent system_prompt"""
        similar = self.recall_similar(instruction, top_k, device_id)
        if not similar:
            return ""

        sections = []
        for i, exp in enumerate(similar):
            sections.append(
                f"--- Past Experience {i+1} (success={exp.success}) ---\n"
                f"Task: {exp.instruction}\n"
                f"Steps taken: {len(exp.steps)}\n"
                f"Outcome: {exp.final_output[:200]}"
            )

        return (
            "\n\nRELEVANT PAST EXPERIENCES (for reference):\n"
            + "\n\n".join(sections) + "\n"
        )

    # ================================================================
    # 知识库检索
    # ================================================================

    async def query_knowledge(
        self, query: str, top_k: int = 5, sources: List[str] = None
    ) -> List[KnowledgeChunk]:
        """
        从知识库检索相关片段

        尝试对接:
        1. Node_105_UnifiedKnowledgeBase
        2. Node_72_KnowledgeBase
        3. 内置简单搜索
        """
        chunks = []

        # 尝试 Node_105
        try:
            from nodes.Node_105_UnifiedKnowledgeBase.main import search_knowledge
            results = await asyncio.get_event_loop().run_in_executor(
                None, search_knowledge, query, top_k
            )
            for r in (results or []):
                chunks.append(KnowledgeChunk(
                    chunk_id=r.get("id", ""),
                    content=r.get("content", ""),
                    source="Node_105",
                    relevance_score=r.get("score", 0.0),
                    metadata=r.get("metadata", {}),
                ))
        except Exception as e:
            logger.debug(f"Node_105 query failed: {e}")

        # 尝试 Node_72
        if len(chunks) < top_k:
            try:
                from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem
                kb = KnowledgeBaseSystem()
                results = kb.search(query, top_k=top_k - len(chunks))
                for r in (results or []):
                    chunks.append(KnowledgeChunk(
                        content=r.get("content", r.get("text", "")),
                        source="Node_72",
                        relevance_score=r.get("score", 0.0),
                    ))
            except Exception as e:
                logger.debug(f"Node_72 query failed: {e}")

        return chunks[:top_k]

    def format_rag_context(self, chunks: List[KnowledgeChunk]) -> str:
        """将知识片段格式化为 RAG Context"""
        if not chunks:
            return ""

        sections = []
        for i, chunk in enumerate(chunks):
            sections.append(
                f"[{i+1}] (source: {chunk.source}, score: {chunk.relevance_score:.2f})\n"
                f"{chunk.content[:500]}"
            )

        return (
            "\n\nRELEVANT KNOWLEDGE:\n"
            + "\n\n".join(sections) + "\n"
        )

    # ================================================================
    # 对话记忆 (桥接)
    # ================================================================

    async def get_conversation_context(
        self, session_id: str, max_turns: int = 10
    ) -> List[Dict]:
        """获取对话记忆 (桥接 ai_intent)"""
        try:
            from core.ai_intent import get_conversation_memory
            memory = get_conversation_memory()
            return await memory.get_context(session_id, max_turns)
        except Exception:
            return []

    # ================================================================
    # 学习 & Pattern 检测
    # ================================================================

    @staticmethod
    def _extract_prefix(instruction: str, max_chars: int = 6) -> str:
        """提取指令前缀 (支持中文: 取前N个字符; 英文: 取前3个词)"""
        stripped = instruction.strip().lower()
        words = stripped.split()
        if len(words) >= 3 and all(ord(c) < 128 for c in words[0]):
            return " ".join(words[:3])
        return stripped[:max_chars]

    def _detect_patterns(self, entry: ExperienceEntry):
        """从经验中检测重复 pattern"""
        if len(self._experiences) < 3:
            return

        # 统计相同指令前缀的出现次数
        prefix = self._extract_prefix(entry.instruction)
        similar_count = sum(
            1 for e in self._experiences
            if self._extract_prefix(e.instruction) == prefix
        )

        if similar_count >= 3:
            # 检查是否已有此 pattern
            for p in self._patterns:
                if p.get("prefix") == prefix:
                    p["count"] = similar_count
                    return

            # 新 pattern
            pattern = {
                "pattern_id": str(uuid.uuid4())[:8],
                "prefix": prefix,
                "count": similar_count,
                "success_rate": sum(
                    1 for e in self._experiences
                    if " ".join(e.instruction.split()[:3]).lower() == prefix and e.success
                ) / similar_count,
                "suggested_optimization": self._suggest_optimization(prefix),
                "detected_at": time.time(),
            }
            self._patterns.append(pattern)
            self._stats["patterns_learned"] += 1
            logger.info(f"Pattern detected: '{prefix}' ({similar_count} occurrences)")

    def _suggest_optimization(self, prefix: str) -> str:
        """根据 pattern 生成优化建议"""
        matching = [
            e for e in self._experiences
            if self._extract_prefix(e.instruction) == prefix
        ]
        if not matching:
            return ""

        # 找最常见的工具组合
        tool_counts: Dict[str, int] = {}
        for e in matching:
            for s in e.steps:
                action = s.get("action", "")
                if action:
                    tool_counts[action] = tool_counts.get(action, 0) + 1

        if tool_counts:
            top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            return f"Common tools: {', '.join(t for t, _ in top_tools)}. Consider creating a template."
        return ""

    def get_learned_patterns(self) -> List[Dict]:
        return self._patterns

    # ================================================================
    # 持久化
    # ================================================================

    def _save_experience(self, entry: ExperienceEntry):
        """追加保存经验到文件"""
        try:
            log_file = os.path.join(self._data_dir, "experiences.jsonl")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Experience save failed: {e}")

    def _load_experiences(self):
        """从文件加载历史经验"""
        log_file = os.path.join(self._data_dir, "experiences.jsonl")
        if not os.path.exists(log_file):
            return

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        self._experiences.append(ExperienceEntry(
                            experience_id=data.get("experience_id", ""),
                            agent_name=data.get("agent_name", ""),
                            device_id=data.get("device_id", ""),
                            instruction=data.get("instruction", ""),
                            steps=data.get("steps", []),
                            final_output=data.get("final_output", ""),
                            success=data.get("success", True),
                            timestamp=data.get("timestamp", 0),
                            tags=data.get("tags", []),
                        ))
            self._stats["experiences_total"] = len(self._experiences)
            logger.info(f"Loaded {len(self._experiences)} historical experiences")
        except Exception as e:
            logger.warning(f"Experience load failed: {e}")

    # ================================================================
    # 综合 RAG 增强
    # ================================================================

    async def enhance_agent_prompt(
        self,
        instruction: str,
        device_id: str = "",
        include_experience: bool = True,
        include_knowledge: bool = True,
    ) -> str:
        """
        综合 RAG 增强 — 返回可追加到 system_prompt 的上下文

        这是 Agent 调用的主入口:
        1. 检索相似经验 (Few-shot)
        2. 检索相关知识 (RAG)
        3. 拼接为增强上下文
        """
        parts = []

        if include_experience:
            few_shot = self.format_few_shot_context(instruction, top_k=2, device_id=device_id)
            if few_shot:
                parts.append(few_shot)

        if include_knowledge:
            chunks = await self.query_knowledge(instruction, top_k=3)
            rag_ctx = self.format_rag_context(chunks)
            if rag_ctx:
                parts.append(rag_ctx)

        return "\n".join(parts)

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "experiences_in_memory": len(self._experiences),
            "patterns_total": len(self._patterns),
        }


# ============================================================================
# 单例
# ============================================================================

_rag_instance: Optional[RAGMemory] = None
_rag_ns_instances: Dict[str, RAGMemory] = {}


def get_rag_memory(namespace: str = "") -> RAGMemory:
    """
    获取 RAGMemory 实例。

    Args:
        namespace: 命名空间字符串（如 device_id 或 worker_id）。
                   为空时返回全局单例，保持向后兼容。
    """
    global _rag_instance
    if not namespace:
        if _rag_instance is None:
            _rag_instance = RAGMemory()
        return _rag_instance

    if namespace not in _rag_ns_instances:
        _rag_ns_instances[namespace] = RAGMemory(namespace=namespace)
    return _rag_ns_instances[namespace]


def get_rag_memory_for_device(device_id: str) -> RAGMemory:
    """便捷函数：按 device_id 获取隔离的 RAGMemory 实例"""
    ns = RAGMemory.namespace_for(device_id=device_id)
    return get_rag_memory(namespace=ns)


def get_rag_memory_for_worker(worker_id: str) -> RAGMemory:
    """便捷函数：按 worker_id 获取隔离的 RAGMemory 实例"""
    ns = RAGMemory.namespace_for(worker_id=worker_id)
    return get_rag_memory(namespace=ns)
