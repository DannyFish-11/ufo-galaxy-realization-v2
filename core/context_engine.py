"""
UFO Galaxy - 上下文管理引擎
============================

提供跨会话上下文持久化、用户画像和智能检索。
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ContextEngine")


class ContextManager:
    """上下文管理器 - 会话上下文存储、检索和用户画像"""

    def __init__(self, config: Optional[Dict] = None):
        self._config = config or {}
        self._contexts: Dict[str, List[Dict]] = {}
        self._user_profiles: Dict[str, Dict] = {}
        logger.info("上下文管理引擎已初始化")

    async def save_context(
        self,
        session_id: str,
        user_id: str,
        messages: List[Dict],
        metadata: Optional[Dict] = None,
    ) -> dict:
        if session_id not in self._contexts:
            self._contexts[session_id] = []
        entry = {
            "user_id": user_id,
            "messages": messages,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        self._contexts[session_id].append(entry)
        return {"success": True, "session_id": session_id, "entries": len(self._contexts[session_id])}

    async def get_context(self, session_id: str, limit: Optional[int] = None) -> dict:
        entries = self._contexts.get(session_id, [])
        if limit:
            entries = entries[-limit:]
        return {"success": True, "session_id": session_id, "entries": entries}

    async def search_context(
        self, query: str, user_id: Optional[str] = None, limit: int = 5
    ) -> dict:
        results = []
        for session_id, entries in self._contexts.items():
            for entry in entries:
                if user_id and entry.get("user_id") != user_id:
                    continue
                for msg in entry.get("messages", []):
                    content = msg.get("content", "")
                    if query.lower() in content.lower():
                        results.append({
                            "session_id": session_id,
                            "message": msg,
                            "timestamp": entry.get("timestamp"),
                        })
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        return {"success": True, "query": query, "results": results}

    async def get_user_profile(self, user_id: str) -> dict:
        profile = self._user_profiles.get(user_id, {
            "user_id": user_id,
            "session_count": 0,
            "preferences": {},
            "created_at": time.time(),
        })
        return profile

    async def get_stats(self) -> dict:
        total_entries = sum(len(v) for v in self._contexts.values())
        return {
            "total_sessions": len(self._contexts),
            "total_entries": total_entries,
            "total_users": len(self._user_profiles),
        }
