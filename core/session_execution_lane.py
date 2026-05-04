from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Optional


@dataclass
class SessionExecutionLane:
    conversation_session_id: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_count: int = 0
    active_control_session_id: str = ""
    last_control_session_id: str = ""
    active_since: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "conversation_session_id": self.conversation_session_id,
            "pending_count": self.pending_count,
            "active_control_session_id": self.active_control_session_id,
            "last_control_session_id": self.last_control_session_id,
            "active_since": self.active_since,
            "locked": self.lock.locked(),
        }


class SessionExecutionLaneManager:
    def __init__(self) -> None:
        self._lanes: Dict[str, SessionExecutionLane] = {}
        self._lock = asyncio.Lock()

    async def _get_lane(self, conversation_session_id: str) -> SessionExecutionLane:
        async with self._lock:
            lane = self._lanes.get(conversation_session_id)
            if lane is None:
                lane = SessionExecutionLane(
                    conversation_session_id=conversation_session_id
                )
                self._lanes[conversation_session_id] = lane
            return lane

    @asynccontextmanager
    async def acquire(
        self,
        conversation_session_id: str,
        *,
        control_session_id: str,
    ) -> AsyncIterator[SessionExecutionLane]:
        lane = await self._get_lane(conversation_session_id)
        lane.pending_count += 1
        await lane.lock.acquire()
        lane.pending_count -= 1
        lane.active_control_session_id = control_session_id
        lane.last_control_session_id = control_session_id
        lane.active_since = time.time()
        try:
            yield lane
        finally:
            lane.active_control_session_id = ""
            lane.active_since = 0.0
            lane.lock.release()

    def snapshot(self, conversation_session_id: str) -> Optional[Dict[str, object]]:
        lane = self._lanes.get(conversation_session_id)
        return lane.to_dict() if lane else None

    def list_lanes(self) -> Dict[str, Dict[str, object]]:
        return {sid: lane.to_dict() for sid, lane in self._lanes.items()}


_lane_manager: Optional[SessionExecutionLaneManager] = None


def get_session_execution_lane_manager() -> SessionExecutionLaneManager:
    global _lane_manager
    if _lane_manager is None:
        _lane_manager = SessionExecutionLaneManager()
    return _lane_manager


def reset_session_execution_lane_manager() -> None:
    global _lane_manager
    _lane_manager = None

