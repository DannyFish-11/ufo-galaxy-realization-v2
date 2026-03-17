"""
Galaxy — Persona Rules (PR-3)
================================

Centralised rule constants consumed by :class:`~core.persona.emotion_engine.EmotionEngine`.

Design:
* All mutation amounts are module-level constants — easy to audit and tune.
* Keyword lists mirror the style used in :mod:`core.interaction.scene_interpreter`.
* No model calls, no external I/O.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Gratitude / positive keywords → trust_level +
# ---------------------------------------------------------------------------

GRATITUDE_KEYWORDS: tuple = (
    "谢谢", "感谢", "谢谢你", "非常感谢", "多谢", "thanks", "thank you",
    "awesome", "great", "perfect", "excellent", "nice", "好的", "棒",
)

# ---------------------------------------------------------------------------
# Frustration / negative keywords → mood → concerned, urgency +
# ---------------------------------------------------------------------------

FRUSTRATION_KEYWORDS: tuple = (
    "不对", "错误", "失败", "不行", "崩溃", "坏了", "没用", "不管用",
    "wrong", "error", "fail", "broken", "crash", "bad", "terrible", "awful",
)

# ---------------------------------------------------------------------------
# Curiosity keywords → curiosity +
# ---------------------------------------------------------------------------

CURIOSITY_KEYWORDS: tuple = (
    "为什么", "怎么", "如何", "是什么", "能不能", "可以吗", "原理",
    "why", "how", "what", "can you", "could you", "explain", "tell me",
    "什么意思",
)

# ---------------------------------------------------------------------------
# Urgency keywords → urgency +, energy +
# ---------------------------------------------------------------------------

URGENCY_KEYWORDS: tuple = (
    "紧急", "立刻", "马上", "快", "赶紧", "hurry", "urgent", "asap",
    "immediately", "now", "快点", "尽快",
)

# ---------------------------------------------------------------------------
# Delta magnitudes
# ---------------------------------------------------------------------------

# Trust
TRUST_GRATITUDE_DELTA: float = 0.10

# Frustration
FRUSTRATION_URGENCY_DELTA: float = 0.15
FRUSTRATION_ENERGY_DELTA: float = -0.10

# Curiosity
CURIOSITY_DELTA: float = 0.08

# Urgency keywords
URGENCY_KEYWORD_DELTA: float = 0.15
URGENCY_ENERGY_DELTA: float = 0.10

# Long message → focus +
LONG_MSG_FOCUS_DELTA: float = 0.08
LONG_MSG_THRESHOLD: int = 80  # characters

# Short message → energy slight decay
SHORT_MSG_ENERGY_DELTA: float = -0.03
SHORT_MSG_THRESHOLD: int = 10  # characters

# Task success / failure
TASK_SUCCESS_TRUST_DELTA: float = 0.05
TASK_SUCCESS_ENERGY_DELTA: float = 0.08
TASK_FAILURE_URGENCY_DELTA: float = 0.20
TASK_FAILURE_ENERGY_DELTA: float = -0.12

# CONTROL_CONSOLE mode → focus +
CONTROL_CONSOLE_FOCUS_DELTA: float = 0.10
CONTROL_CONSOLE_URGENCY_DELTA: float = 0.05

# AMBIENT_COMPANION mode → energy slight restore
AMBIENT_ENERGY_DELTA: float = 0.05

# ---------------------------------------------------------------------------
# Mood label derivation thresholds
# ---------------------------------------------------------------------------

def derive_mood(urgency: float, focus: float, energy: float, trust_level: float) -> str:
    """Derive a qualitative mood label from the numeric state.

    Rule priority (highest first):
    1. urgency > 0.6  → ``"concerned"``
    2. focus > 0.8    → ``"focused"``
    3. energy < 0.35  → ``"tired"``
    4. trust_level > 0.75  → ``"warm"``
    5. default        → ``"calm"``
    """
    if urgency > 0.6:
        return "concerned"
    if focus > 0.8:
        return "focused"
    if energy < 0.35:
        return "tired"
    if trust_level > 0.75:
        return "warm"
    return "calm"


def derive_expression_mode(mood: str, energy: float) -> str:
    """Derive expression_mode from mood and energy level."""
    if mood == "concerned":
        return "direct"
    if mood == "focused":
        return "precise"
    if mood == "tired":
        return "gentle"
    if mood == "warm":
        return "warm"
    if energy > 0.75:
        return "vibrant"
    return "quiet_luminous"


__all__ = [
    "GRATITUDE_KEYWORDS",
    "FRUSTRATION_KEYWORDS",
    "CURIOSITY_KEYWORDS",
    "URGENCY_KEYWORDS",
    "TRUST_GRATITUDE_DELTA",
    "FRUSTRATION_URGENCY_DELTA",
    "FRUSTRATION_ENERGY_DELTA",
    "CURIOSITY_DELTA",
    "URGENCY_KEYWORD_DELTA",
    "URGENCY_ENERGY_DELTA",
    "LONG_MSG_FOCUS_DELTA",
    "LONG_MSG_THRESHOLD",
    "SHORT_MSG_ENERGY_DELTA",
    "SHORT_MSG_THRESHOLD",
    "TASK_SUCCESS_TRUST_DELTA",
    "TASK_SUCCESS_ENERGY_DELTA",
    "TASK_FAILURE_URGENCY_DELTA",
    "TASK_FAILURE_ENERGY_DELTA",
    "CONTROL_CONSOLE_FOCUS_DELTA",
    "CONTROL_CONSOLE_URGENCY_DELTA",
    "AMBIENT_ENERGY_DELTA",
    "derive_mood",
    "derive_expression_mode",
]
