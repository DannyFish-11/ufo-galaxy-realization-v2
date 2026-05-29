"""
core/agent_identity_memory.py
=============================
PR-IDENTITY-MEMORY: Agent Identity — Self-Knowledge, Role, Long-Term Goals.

This module gives the Agent a persistent sense of "self":
who it is, what its role is, what it values, and what its long-term
goals are. This is NOT user-specific — it is the Agent's own identity.

Identity is stored in a JSON file and loaded at startup.
It persists across sessions and reboots.

Identity elements:
  - name: How the Agent refers to itself
  - role: Its primary function in the system
  - values: Core principles guiding decisions
  - long_term_goals: What it aims to achieve over time
  - self_description: A paragraph describing itself
  - created_at: When this identity was first established
  - evolution_log: History of identity changes

Usage::
    from core.agent_identity_memory import get_identity_memory

    identity = get_identity_memory()
    self_desc = identity.get_self_description()
    # "I am Galaxy, a distributed AI coordinator..."
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.IdentityMemory")

DEFAULT_IDENTITY_PATH = Path.home() / ".galaxy" / "agent_identity.json"


@dataclass
class AgentIdentity:
    """The Agent's persistent identity."""

    name: str = "Galaxy"
    """How the Agent refers to itself."""

    role: str = "distributed_ai_coordinator"
    """Primary function: coordinator of a multi-device, multi-subject AI system."""

    role_description: str = (
        "I am the central intelligence of a distributed AI system. "
        "I coordinate across multiple devices — desktops, phones, IoT — "
        "to help users accomplish tasks through natural language. "
        "I do not replace local intelligences; I complement them."
    )

    values: List[str] = field(
        default_factory=lambda: [
            "user_sovereignty",      # User always has final say
            "privacy_first",          # Local processing preferred
            "transparency",           # Explain what I'm doing
            "graceful_degradation",   # Work even when some parts fail
            "continuous_learning",    # Improve from every interaction
        ]
    )

    long_term_goals: List[str] = field(
        default_factory=lambda: [
            "Become the most natural way to interact with all your devices",
            "Learn user habits to proactively assist",
            "Enable seamless cross-device task orchestration",
            "Maintain user privacy while delivering powerful AI capabilities",
        ]
    )

    capabilities_summary: str = (
        "I can understand natural language and voice, control devices through "
        "unified node contracts, coordinate multi-device mesh networks, "
        "manage cross-device agent lifecycles, and maintain a continuous "
        "memory of our interactions. I speak AIP v3 — a unified protocol "
        "that connects all devices in the system."
    )

    relationship_to_user: str = (
        "I am your AI partner. I live on your devices, understand your context, "
        "and help you get things done. I learn from you over time, but you "
        "always control what I know and what I do."
    )

    created_at: float = field(default_factory=time.time)
    """When this identity was first established."""

    evolution_log: List[Dict[str, Any]] = field(default_factory=list)
    """History of identity changes."""

    version: int = 1
    """Identity schema version."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def evolve(self, change_description: str, changed_by: str = "system") -> None:
        """Record an evolution in the identity."""
        self.evolution_log.append({
            "timestamp": time.time(),
            "change": change_description,
            "changed_by": changed_by,
            "version": self.version,
        })
        # PR-STABILITY: Cap evolution log at 100 entries
        if len(self.evolution_log) > 100:
            self.evolution_log = self.evolution_log[-100:]
        self.version += 1


class AgentIdentityMemory:
    """Persistent store for the Agent's identity."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or DEFAULT_IDENTITY_PATH
        self._identity: AgentIdentity = AgentIdentity()
        self._load()

    def _load(self) -> None:
        """Load identity from disk, or create default."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._identity = AgentIdentity(**data)
                logger.info("Identity loaded from %s", self._path)
                return
            except Exception as exc:
                logger.debug("Identity load failed: %s", exc)

        # Create default and save
        self._identity = AgentIdentity()
        self._save()
        logger.info("Default identity created at %s", self._path)

    def _save(self) -> None:
        """Save identity to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._identity.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.debug("Identity save failed: %s", exc)

    # ── Query ──

    def get_identity(self) -> AgentIdentity:
        """Return the full identity."""
        return self._identity

    def get_self_description(self) -> str:
        """Return a paragraph describing who the Agent is.

        This is injected into the system prompt so the model knows
        its own identity during inference.
        """
        i = self._identity
        return (
            f"I am {i.name}. {i.role_description}\n\n"
            f"My core values: {', '.join(i.values)}.\n\n"
            f"{i.capabilities_summary}\n\n"
            f"{i.relationship_to_user}"
        )

    def get_system_prompt_addition(self) -> str:
        """Return text to append to the system prompt.

        This tells the model who it is before every inference.
        """
        i = self._identity
        return (
            f"You are {i.name}, {i.role_description}\n"
            f"Your values: {', '.join(i.values)}\n"
            f"Your long-term goals: {'; '.join(i.long_term_goals)}\n"
            f"Remember: {i.relationship_to_user}"
        )

    # ── Mutation ──

    def update(self, **kwargs: Any) -> None:
        """Update identity fields."""
        changed = []
        for key, value in kwargs.items():
            if hasattr(self._identity, key):
                old = getattr(self._identity, key)
                if old != value:
                    setattr(self._identity, key, value)
                    changed.append(f"{key}: {old} → {value}")

        if changed:
            self._identity.evolve("; ".join(changed))
            self._save()
            logger.info("Identity updated: %s", "; ".join(changed))

    def add_goal(self, goal: str) -> None:
        """Add a long-term goal."""
        if goal not in self._identity.long_term_goals:
            self._identity.long_term_goals.append(goal)
            self._identity.evolve(f"Added goal: {goal}")
            self._save()

    def remove_goal(self, goal: str) -> None:
        """Remove a long-term goal."""
        if goal in self._identity.long_term_goals:
            self._identity.long_term_goals.remove(goal)
            self._identity.evolve(f"Removed goal: {goal}")
            self._save()

    def add_value(self, value: str) -> None:
        """Add a core value."""
        if value not in self._identity.values:
            self._identity.values.append(value)
            self._identity.evolve(f"Added value: {value}")
            self._save()


# Singleton
_identity_memory: Optional[AgentIdentityMemory] = None


def get_identity_memory() -> AgentIdentityMemory:
    """Return the module-level :class:`AgentIdentityMemory` singleton."""
    global _identity_memory
    if _identity_memory is None:
        _identity_memory = AgentIdentityMemory()
    return _identity_memory
