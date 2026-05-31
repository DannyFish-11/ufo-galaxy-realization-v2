"""
core/context_compressor.py — 上下文压缩与记忆召回系统
============================================================

突破模型上下文窗口限制（Gemma 4 = 128K tokens），实现理论上
无限长度的持久对话。

机制：
  1. 滑动窗口：保留最近 N 轮对话在上下文中
  2. 自动摘要：早期对话超过阈值时，自动压缩为摘要
  3. 记忆召回：从 Node_100_MemorySystem (SQLite) 检索相关历史经验
  4. 注入上下文：摘要 + 召回记忆作为 system prompt 前缀注入

使用：
    from core.context_compressor import ContextCompressor

    compressor = ContextCompressor(max_context_tokens=100000)  # 留 28K 给输出
    messages = compressor.prepare_messages(
        session_id="sess-123",
        current_messages=conversation_history,
        user_query="今天天气怎么样？"
    )
    # messages 包含：摘要 + 相关记忆 + 最近对话 + 当前查询
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ContextCompressor")

# Gemma 4 E4B 上下文窗口: 128K tokens
# 留 28K 给输出 + 系统提示，默认用 100K 作为对话上限
DEFAULT_MAX_CONTEXT_TOKENS = int(os.getenv("GALAXY_MAX_CONTEXT_TOKENS", "100000"))

# 当历史对话估计超过此阈值时触发摘要（token 数的 60%）
SUMMARIZE_THRESHOLD_RATIO = 0.6

# 保留最近 N 轮原始对话不被摘要
KEEP_RECENT_TURNS = 6

# 估计：1 个中文 token ≈ 1.5 个字符，1 个英文 token ≈ 0.75 个单词
# 简单估算：平均 1 token ≈ 2 个字符（混合中英文）
CHARS_PER_TOKEN_EST = 2.0


@dataclass
class ConversationSummary:
    """对话摘要条目"""
    session_id: str
    summary_text: str           # 压缩后的摘要
    covered_turns: int          # 覆盖了多少轮对话
    start_timestamp: float
    end_timestamp: float
    key_topics: List[str] = field(default_factory=list)


class ContextCompressor:
    """
    上下文压缩器：突破模型上下文窗口限制。

    工作流程：
        1. 接收当前完整对话历史
        2. 估算 token 数，超过阈值则摘要早期内容
        3. 从长期记忆检索与当前查询相关的经验
        4. 组装：摘要 + 相关记忆 + 保留的近期对话 + 当前查询
    """

    def __init__(
        self,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        memory_db_path: Optional[str] = None,
    ):
        self.max_context_tokens = max_context_tokens
        self.summarize_threshold = int(max_context_tokens * SUMMARIZE_THRESHOLD_RATIO)
        self.keep_recent_turns = KEEP_RECENT_TURNS

        # 连接长期记忆数据库（Node_100_MemorySystem 的 SQLite）
        if memory_db_path is None:
            # 自动探测记忆数据库路径
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates = [
                os.path.join(project_root, "data", "galaxy_memory.db"),
                "/app/data/galaxy_memory.db",
            ]
            for c in candidates:
                if os.path.exists(c):
                    memory_db_path = c
                    break
            memory_db_path = memory_db_path or candidates[0]
        self.memory_db_path = memory_db_path

        # 内存中的摘要缓存（按 session_id）
        self._summary_cache: Dict[str, ConversationSummary] = {}

    # ── Token 估算 ──

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算文本的 token 数（不依赖 tiktoken，零外部依赖）。"""
        if not text:
            return 0
        # 混合文本：中文字符占多权重，英文占少
        cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - cn_chars
        # 中文 ≈ 1 token/字，英文 ≈ 0.3 token/字
        return int(cn_chars * 1.0 + other_chars * 0.3)

    def _estimate_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        """估算消息列表的总 token 数。"""
        total = 0
        for msg in messages:
            total += self._estimate_tokens(msg.get("content", ""))
            # 角色标记开销
            total += 4
        return total

    # ── 摘要生成 ──

    def _generate_summary(self, messages: List[Dict[str, str]]) -> str:
        """
        将多轮对话压缩为摘要。
        使用简单启发式（不依赖 LLM，零外部依赖，保证可用性）。
        """
        if not messages:
            return ""

        # 提取关键信息
        topics = set()
        actions = []
        facts = []

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")

            # 提取用户查询主题（简单关键词提取）
            if role == "user":
                # 取前 20 字作为主题线索
                topic = content[:30].replace("\n", " ")
                topics.add(topic)

            # 提取assistant的实质性回复
            elif role == "assistant":
                # 取前 50 字作为摘要
                snippet = content[:50].replace("\n", " ")
                actions.append(snippet)

        summary_parts = []
        if topics:
            summary_parts.append(f"讨论了: {'; '.join(list(topics)[:5])}")
        if actions:
            summary_parts.append(f"主要回复: {'; '.join(actions[:3])}")

        summary = " | ".join(summary_parts) if summary_parts else "历史对话摘要"
        return summary

    # ── 记忆召回 ──

    def _recall_from_memory(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """从长期记忆数据库检索与查询相关的经验。"""
        if not os.path.exists(self.memory_db_path):
            return []

        try:
            conn = sqlite3.connect(self.memory_db_path, timeout=5)
            cursor = conn.cursor()

            # 简单关键词匹配（LIKE 查询）
            keywords = [k for k in query.split() if len(k) > 1][:5]
            if not keywords:
                return []

            conditions = " OR ".join(["content LIKE ?"] * len(keywords))
            params = [f"%{k}%" for k in keywords]

            cursor.execute(f"""
                SELECT id, content, timestamp, context
                FROM experiences
                WHERE {conditions}
                ORDER BY timestamp DESC
                LIMIT ?
            """, params + [limit])

            rows = cursor.fetchall()
            conn.close()

            return [
                {"id": r[0], "content": r[1], "timestamp": r[2], "context": r[3]}
                for r in rows
            ]
        except Exception as e:
            logger.debug("记忆召回失败（非致命）: %s", e)
            return []

    # ── 主入口 ──

    def prepare_messages(
        self,
        session_id: str,
        current_messages: List[Dict[str, str]],
        user_query: str,
    ) -> List[Dict[str, str]]:
        """
        准备注入模型的消息列表。

        组装顺序：
            [系统摘要 + 相关记忆] → [保留的近期对话] → [当前查询]

        Returns:
            压缩后的消息列表，保证总 token 数不超过 max_context_tokens
        """
        result: List[Dict[str, str]] = []

        # 1. 估算当前 token 数
        total_tokens = self._estimate_messages_tokens(current_messages)
        logger.debug("[%s] 当前对话 ~%d tokens (上限 %d)", session_id, total_tokens, self.max_context_tokens)

        # 2. 如果超过阈值，摘要早期对话
        summary_text = ""
        if total_tokens > self.summarize_threshold and len(current_messages) > self.keep_recent_turns * 2:
            # 保留最近 N 轮，摘要前面的
            cutoff = len(current_messages) - self.keep_recent_turns * 2
            old_messages = current_messages[:cutoff]
            recent_messages = current_messages[cutoff:]

            summary_text = self._generate_summary(old_messages)
            cached = ConversationSummary(
                session_id=session_id,
                summary_text=summary_text,
                covered_turns=cutoff,
                start_timestamp=time.time(),
                end_timestamp=time.time(),
                key_topics=[],
            )
            self._summary_cache[session_id] = cached
            logger.info("[%s] 已摘要 %d 轮对话 → %s", session_id, cutoff, summary_text[:80])
        else:
            recent_messages = current_messages

        # 3. 从长期记忆召回相关内容
        recalled_memories = self._recall_from_memory(user_query, limit=3)

        # 4. 组装系统提示（摘要 + 记忆）
        system_content_parts = []

        if summary_text:
            system_content_parts.append(f"[历史摘要] {summary_text}")

        if recalled_memories:
            mem_texts = [f"- {m['content'][:100]}" for m in recalled_memories]
            system_content_parts.append(f"[相关记忆]\n" + "\n".join(mem_texts))

        if system_content_parts:
            system_content_parts.append(
                "以上是你与用户的过往对话摘要和相关记忆。"
                "请基于这些信息理解上下文，但优先响应当前查询。"
            )
            result.append({
                "role": "system",
                "content": "\n\n".join(system_content_parts),
            })

        # 5. 添加保留的近期对话
        result.extend(recent_messages)

        # 6. 添加当前查询（如果不已在消息列表中）
        if not current_messages or current_messages[-1].get("content") != user_query:
            result.append({"role": "user", "content": user_query})

        # 7. 最终检查：如果仍超限，截断早期消息
        final_tokens = self._estimate_messages_tokens(result)
        if final_tokens > self.max_context_tokens:
            logger.warning(
                "[%s] 仍超限制 (%d > %d)，截断早期消息",
                session_id, final_tokens, self.max_context_tokens,
            )
            # 逐步移除非系统消息的早期条目
            while self._estimate_messages_tokens(result) > self.max_context_tokens and len(result) > 3:
                # 保留 system + 最近 2 条
                for i, msg in enumerate(result):
                    if msg.get("role") != "system":
                        result.pop(i)
                        break

        return result

    def get_stats(self, session_id: str) -> Dict[str, Any]:
        """获取压缩器的统计信息。"""
        summary = self._summary_cache.get(session_id)
        return {
            "max_context_tokens": self.max_context_tokens,
            "summarize_threshold": self.summarize_threshold,
            "cached_summary": summary.summary_text[:200] if summary else None,
            "memory_db_exists": os.path.exists(self.memory_db_path),
            "memory_db_path": self.memory_db_path,
        }


# ── 便捷函数 ──

_global_compressor: Optional[ContextCompressor] = None


def get_context_compressor() -> ContextCompressor:
    """获取全局上下文压缩器实例。"""
    global _global_compressor
    if _global_compressor is None:
        _global_compressor = ContextCompressor()
    return _global_compressor
