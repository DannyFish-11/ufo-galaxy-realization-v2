"""
core/user_preference_memory.py
==============================
PR-USER-PREF: User Preference Memory — Habits, Device Preferences, Patterns.

Stores what the user prefers: which devices they use for what,
common commands, frequently used capabilities, time-of-day patterns.

This is distinct from AgentIdentity (which is about the Agent's self)
and distinct from TaskMemory (which is about specific task executions).

Stored in JSON, per-user, persistent across sessions.

Usage::
    from core.user_preference_memory import get_user_preference_memory

    prefs = get_user_preference_memory()
    prefs.record_device_usage("phone_01", "screenshot", success=True)
    prefs.record_command_pattern("晚上", "dim_lights")
    suggested = prefs.suggest_device_for_task("screenshot")
    # Returns "phone_01" based on historical usage
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.UserPref")

DEFAULT_PREF_PATH = Path.home() / ".galaxy" / "user_preferences.json"


@dataclass
class DeviceUsage:
    """Usage pattern for a specific device."""

    device_id: str
    device_type: str = ""
    actions_used: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    success_count: int = 0
    failure_count: int = 0
    last_used: float = 0.0
    preferred: bool = False

    def record(self, action: str, success: bool) -> None:
        self.actions_used[action] += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        self.last_used = time.time()


@dataclass
class UserPreferences:
    """Aggregated user preferences."""

    # Device preferences: which device for which type of task
    device_preferences: Dict[str, str] = field(default_factory=dict)
    """task_type → preferred_device_id. E.g. {'screenshot': 'phone_01'}"""

    # Command patterns: what the user tends to say at certain times/contexts
    command_patterns: List[Dict[str, Any]] = field(default_factory=list)
    """[{time_context, command_keywords, matched_action, frequency}]"""

    # Frequently used capabilities (sorted by frequency)
    frequent_capabilities: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Time-of-day patterns
    time_patterns: Dict[str, List[str]] = field(default_factory=dict)
    """{"morning": ["check_messages"], "evening": ["dim_lights"]}"""

    # Device usage statistics
    device_usage: Dict[str, DeviceUsage] = field(default_factory=dict)

    # Interaction count
    total_interactions: int = 0

    # Last updated
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UserPreferenceMemory:
    """Persistent store for user preferences."""

    MAX_PATTERNS = 100  # Keep last 100 patterns

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DEFAULT_PREF_PATH
        self._prefs = UserPreferences()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Reconstruct DeviceUsage objects
                du_raw = data.get("device_usage", {})
                data["device_usage"] = {
                    k: DeviceUsage(**v) for k, v in du_raw.items()
                }
                self._prefs = UserPreferences(**data)
                logger.info("User preferences loaded from %s", self._path)
                return
            except Exception as exc:
                logger.debug("User pref load failed: %s", exc)

        self._prefs = UserPreferences()
        self._save()
        logger.info("Default user preferences created")

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._prefs.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.debug("User pref save failed: %s", exc)

    # ── Recording ──

    def record_device_usage(
        self,
        device_id: str,
        action: str,
        success: bool = True,
        device_type: str = "",
    ) -> None:
        """Record that a device was used for an action."""
        if device_id not in self._prefs.device_usage:
            self._prefs.device_usage[device_id] = DeviceUsage(
                device_id=device_id, device_type=device_type
            )
        self._prefs.device_usage[device_id].record(action, success)
        self._prefs.total_interactions += 1
        self._prefs.last_updated = time.time()

        # Auto-update device_preferences based on success
        if success:
            # Find the task_type for this action
            task_type = self._infer_task_type(action)
            if task_type:
                current = self._prefs.device_preferences.get(task_type)
                if current is None or self._prefs.device_usage[current].success_count < self._prefs.device_usage[device_id].success_count:
                    self._prefs.device_preferences[task_type] = device_id

        self._save()

    def record_command(self, user_input: str, matched_action: str) -> None:
        """Record a command pattern from user input."""
        # Extract time context
        hour = time.localtime().tm_hour
        time_context = self._hour_to_context(hour)

        # Extract keywords (simple approach)
        keywords = [w for w in user_input.lower().split() if len(w) > 1]

        pattern = {
            "time_context": time_context,
            "keywords": keywords[:5],  # Keep top 5
            "matched_action": matched_action,
            "frequency": 1,
            "last_seen": time.time(),
        }

        # Merge with existing similar patterns
        merged = False
        for p in self._prefs.command_patterns:
            if p["matched_action"] == matched_action and p["time_context"] == time_context:
                p["frequency"] += 1
                p["last_seen"] = time.time()
                merged = True
                break

        if not merged:
            self._prefs.command_patterns.append(pattern)
            # Trim if too many
            if len(self._prefs.command_patterns) > self.MAX_PATTERNS:
                self._prefs.command_patterns.sort(key=lambda x: x["frequency"], reverse=True)
                self._prefs.command_patterns = self._prefs.command_patterns[: self.MAX_PATTERNS]

        # Update frequent capabilities
        self._prefs.frequent_capabilities[matched_action] += 1
        self._prefs.last_updated = time.time()
        self._save()

    # ── Query ──

    def suggest_device_for_task(self, task_type: str) -> Optional[str]:
        """Suggest the best device for a task type based on history."""
        return self._prefs.device_preferences.get(task_type)

    def get_preferred_device(self, device_id: str) -> bool:
        """Check if a device is marked as preferred."""
        du = self._prefs.device_usage.get(device_id)
        return du.preferred if du else False

    def get_frequent_actions(self, n: int = 10) -> List[str]:
        """Get most frequently used actions."""
        sorted_caps = sorted(
            self._prefs.frequent_capabilities.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [cap for cap, _ in sorted_caps[:n]]

    def get_device_stats(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get usage statistics for a device."""
        du = self._prefs.device_usage.get(device_id)
        if du is None:
            return None
        total = du.success_count + du.failure_count
        return {
            "device_id": du.device_id,
            "device_type": du.device_type,
            "total_uses": total,
            "success_rate": du.success_count / total if total > 0 else 0,
            "most_used_actions": sorted(
                du.actions_used.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "last_used": du.last_used,
        }

    # ── Helpers ──

    def _infer_task_type(self, action: str) -> str:
        """Infer task type from action name."""
        task_map = {
            "screenshot": "screenshot",
            "tap": "ui_interaction",
            "swipe": "ui_interaction",
            "click": "ui_interaction",
            "type": "text_input",
            "shell": "system_command",
            "read": "data_access",
            "write": "data_access",
            "publish": "messaging",
            "subscribe": "messaging",
        }
        for key, task in task_map.items():
            if key in action.lower():
                return task
        return "general"

    def _hour_to_context(self, hour: int) -> str:
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 14:
            return "noon"
        elif 14 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 22:
            return "evening"
        else:
            return "night"


# Singleton
_user_pref: Optional[UserPreferenceMemory] = None


def get_user_preference_memory() -> UserPreferenceMemory:
    """Return the module-level :class:`UserPreferenceMemory` singleton."""
    global _user_pref
    if _user_pref is None:
        _user_pref = UserPreferenceMemory()
    return _user_pref
