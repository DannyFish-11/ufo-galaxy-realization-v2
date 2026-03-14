"""
OpenClawd Heartbeat Scheduler
==============================

Implements an agent-level heartbeat loop for OpenClawd (OpenClaw 3.x style).

Key behaviours
--------------
* Reads task list from ``agent/HEARTBEAT.md`` (natural language + light DSL).
* Triggers ``OpenClawd.process()`` using the same pipeline as user messages.
* Tags context with ``source=heartbeat`` for logging/analytics.
* ACK suppression: if the response starts or ends with the configured
  ``ack_token`` (default ``HEARTBEAT_OK``) **and** is short (<=
  ``max_output_chars``), the output is dropped and only logged.
* Tiered model routing: defaults to ``tier1_model`` (cheap/fast); escalates
  to ``tier2_model`` when the task content matches any ``tier2_trigger``
  keyword.
* The loop is guarded behind ``heartbeat.enabled`` in ``config/agent.yaml``
  so it can be disabled without touching code.
* Secrets (API keys, etc.) live exclusively in ``.env`` — never hardcoded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.HeartbeatScheduler")

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: Dict[str, Any] = {
    "agent": {"name": "core_agent"},
    "heartbeat": {
        "enabled": True,
        "interval": "30m",
        "task_file": "agent/HEARTBEAT.md",
        "ack_token": "HEARTBEAT_OK",
        "max_output_chars": 160,
        "tier1_model": "local_small",
        "tier2_model": "gpt-4o",
        "tier2_trigger": ["complex_reasoning", "multi_step_plan", "code_generation"],
    },
}


def _load_yaml_config(path: str) -> Dict[str, Any]:
    """Load YAML config from *path*, merging with defaults.

    Falls back to defaults silently when PyYAML is not installed or the file
    does not exist — the heartbeat feature degrades gracefully.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.debug("PyYAML not available; using default heartbeat config")
        return _DEFAULT_CONFIG

    config_path = Path(path)
    if not config_path.is_absolute():
        # Resolve relative paths against the project root (two levels up from
        # this file: core/ → project root).
        project_root = Path(__file__).parent.parent
        config_path = project_root / path

    if not config_path.exists():
        logger.debug("Heartbeat config not found at %s; using defaults", config_path)
        return _DEFAULT_CONFIG

    try:
        with config_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        # Deep merge: defaults < file values
        merged: Dict[str, Any] = {}
        for key, default_val in _DEFAULT_CONFIG.items():
            if isinstance(default_val, dict):
                merged[key] = {**default_val, **loaded.get(key, {})}
            else:
                merged[key] = loaded.get(key, default_val)
        # Carry over any extra top-level keys from the file
        for key in loaded:
            if key not in merged:
                merged[key] = loaded[key]
        return merged
    except Exception as exc:
        logger.warning("Failed to parse heartbeat config %s: %s", config_path, exc)
        return _DEFAULT_CONFIG


def _parse_interval_seconds(interval_str: str) -> int:
    """Convert a human-readable interval string to seconds.

    Supported suffixes: ``s`` (seconds), ``m`` (minutes), ``h`` (hours).
    Falls back to 1800 (30 min) on parse errors.
    """
    interval_str = str(interval_str).strip().lower()
    match = re.fullmatch(r"(\d+)(s|m|h)?", interval_str)
    if not match:
        logger.warning("Cannot parse interval '%s'; defaulting to 30m", interval_str)
        return 1800
    value = int(match.group(1))
    unit = match.group(2) or "s"
    return value * {"s": 1, "m": 60, "h": 3600}[unit]


# ---------------------------------------------------------------------------
# HEARTBEAT.md parser
# ---------------------------------------------------------------------------

def load_heartbeat_tasks(task_file: str) -> str:
    """Read the HEARTBEAT.md file and return its full content as a string.

    The raw content is passed to OpenClawd as the prompt body; the agent
    decides which tasks to act on.  Returns an empty string if the file
    cannot be read.
    """
    file_path = Path(task_file)
    if not file_path.is_absolute():
        project_root = Path(__file__).parent.parent
        file_path = project_root / task_file

    if not file_path.exists():
        logger.warning("HEARTBEAT.md not found at %s", file_path)
        return ""

    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to read HEARTBEAT.md: %s", exc)
        return ""


def extract_task_lines(heartbeat_content: str) -> List[str]:
    """Return a flat list of task bullet lines from the HEARTBEAT.md content.

    Lines starting with ``-`` (possibly indented) are extracted.  This is
    used for tier-escalation classification.
    """
    lines: List[str] = []
    for line in heartbeat_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            lines.append(stripped[2:].strip())
    return lines


# ---------------------------------------------------------------------------
# ACK suppression
# ---------------------------------------------------------------------------

def is_ack_response(response: str, ack_token: str, max_chars: int) -> bool:
    """Return *True* if the response should be suppressed (ACK only).

    A response is considered a heartbeat ACK when:
    1. Its length is <= ``max_chars``, AND
    2. It starts **or** ends with ``ack_token`` (case-insensitive).

    Note: when ``max_chars`` is 0 (or negative), no response will ever be
    suppressed because any non-empty string will have length > 0.
    """
    stripped = response.strip()
    if len(stripped) > max_chars:
        return False
    token_lower = ack_token.lower()
    text_lower = stripped.lower()
    return text_lower.startswith(token_lower) or text_lower.endswith(token_lower)


# ---------------------------------------------------------------------------
# Tier routing
# ---------------------------------------------------------------------------

def should_escalate_to_tier2(task_lines: List[str], tier2_triggers: List[str]) -> bool:
    """Return *True* if any task line matches a tier-2 trigger keyword.

    Matching is case-insensitive substring check.
    """
    triggers_lower = [t.lower() for t in tier2_triggers]
    for line in task_lines:
        line_lower = line.lower()
        if any(trigger in line_lower for trigger in triggers_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# HeartbeatScheduler
# ---------------------------------------------------------------------------

class HeartbeatScheduler:
    """Async heartbeat scheduler for OpenClawd.

    Lifecycle
    ---------
    * ``start()`` — begin the background loop (idempotent).
    * ``stop()`` — signal the loop to exit and wait for it to finish.

    The scheduler is designed to be started after OpenClawd is initialised
    (e.g. inside the FastAPI ``lifespan`` context manager in
    ``galaxy_gateway/app.py``).
    """

    def __init__(
        self,
        openclawd: Any,
        config_path: str = "config/agent.yaml",
    ) -> None:
        self._openclawd = openclawd
        self._config = _load_yaml_config(config_path)
        self._hb_config: Dict[str, Any] = self._config.get("heartbeat", {})
        self._enabled: bool = bool(self._hb_config.get("enabled", True))
        self._interval_seconds: int = _parse_interval_seconds(
            self._hb_config.get("interval", "30m")
        )
        self._task_file: str = self._hb_config.get("task_file", "agent/HEARTBEAT.md")
        self._ack_token: str = self._hb_config.get("ack_token", "HEARTBEAT_OK")
        self._max_output_chars: int = int(self._hb_config.get("max_output_chars", 160))
        self._tier1_model: str = self._hb_config.get("tier1_model", "local_small")
        self._tier2_model: str = self._hb_config.get("tier2_model", "gpt-4o")
        self._tier2_triggers: List[str] = list(
            self._hb_config.get("tier2_trigger", [])
        )

        self._task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._cycle_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return *True* when heartbeat is enabled in config."""
        return self._enabled

    async def start(self) -> None:
        """Start the background heartbeat loop (no-op if disabled)."""
        if not self._enabled:
            logger.info("OpenClawd heartbeat is disabled (heartbeat.enabled=false)")
            return
        if self._task is not None and not self._task.done():
            logger.debug("Heartbeat scheduler already running")
            return
        self._stop_event.clear()
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            "OpenClawd heartbeat scheduler started (interval=%ds, task_file=%s)",
            self._interval_seconds,
            self._task_file,
        )

    async def stop(self) -> None:
        """Signal the heartbeat loop to stop and wait for clean exit."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        finally:
            self._task = None
        logger.info("OpenClawd heartbeat scheduler stopped")

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main heartbeat loop — sleeps between cycles, wakes on stop signal."""
        while not self._stop_event.is_set():
            try:
                await self._run_cycle()
            except Exception as exc:
                logger.exception("Heartbeat cycle failed: %s", exc)

            # Sleep in small increments so stop() is responsive
            elapsed = 0
            chunk = 5  # seconds
            while elapsed < self._interval_seconds and not self._stop_event.is_set():
                sleep_time = min(chunk, self._interval_seconds - elapsed)
                await asyncio.sleep(sleep_time)
                elapsed += sleep_time

    async def _run_cycle(self) -> None:
        """Execute a single heartbeat cycle."""
        self._cycle_count += 1
        cycle_start = time.time()
        logger.debug("Heartbeat cycle #%d starting", self._cycle_count)

        # 1. Load HEARTBEAT.md
        task_content = load_heartbeat_tasks(self._task_file)
        if not task_content:
            logger.info("Heartbeat: HEARTBEAT.md is empty or unreadable — skipping cycle")
            return

        # 2. Tier routing
        task_lines = extract_task_lines(task_content)
        use_tier2 = should_escalate_to_tier2(task_lines, self._tier2_triggers)
        model_hint = self._tier2_model if use_tier2 else self._tier1_model
        tier_label = "tier2" if use_tier2 else "tier1"

        # 3. Build prompt
        prompt = (
            "Process the following HEARTBEAT tasks. "
            "If there is nothing to do, respond with HEARTBEAT_OK.\n\n"
            f"{task_content}"
        )

        # 4. Build context (tags source=heartbeat for analytics)
        context = [
            {
                "role": "system",
                "content": (
                    "You are running in autonomous heartbeat mode "
                    f"(source=heartbeat, tier={tier_label}, model_hint={model_hint}). "
                    "Execute maintenance tasks silently where possible."
                ),
            }
        ]

        # 5. Call OpenClawd.process()
        try:
            result = await self._openclawd.process(
                message=prompt,
                session_id=f"heartbeat_{self._cycle_count}",
                context=context,
            )
        except Exception as exc:
            logger.error("Heartbeat: OpenClawd.process() failed: %s", exc)
            return

        # 6. ACK suppression
        response_text: str = result.get("response", "") if isinstance(result, dict) else str(result)
        elapsed_ms = int((time.time() - cycle_start) * 1000)

        if is_ack_response(response_text, self._ack_token, self._max_output_chars):
            logger.info(
                "Heartbeat cycle #%d: ACK received (%dms, %s) — suppressed from user output",
                self._cycle_count,
                elapsed_ms,
                tier_label,
            )
        else:
            logger.info(
                "Heartbeat cycle #%d: response received (%dms, %s): %.120s",
                self._cycle_count,
                elapsed_ms,
                tier_label,
                response_text,
            )


# ---------------------------------------------------------------------------
# Module-level singleton helpers (mirrors openclawd.py pattern)
# ---------------------------------------------------------------------------

_heartbeat_scheduler: Optional[HeartbeatScheduler] = None


def get_heartbeat_scheduler(
    openclawd: Optional[Any] = None,
    config_path: str = "config/agent.yaml",
) -> Optional[HeartbeatScheduler]:
    """Return the global HeartbeatScheduler instance, creating it if needed.

    If *openclawd* is ``None`` the function falls back to
    ``core.openclawd.get_openclawd()``.  Returns ``None`` when OpenClawd is
    not available.
    """
    global _heartbeat_scheduler
    if _heartbeat_scheduler is not None:
        return _heartbeat_scheduler

    if openclawd is None:
        try:
            from core.openclawd import get_openclawd
            openclawd = get_openclawd()
        except Exception as exc:
            logger.warning("Cannot create HeartbeatScheduler: OpenClawd unavailable: %s", exc)
            return None

    _heartbeat_scheduler = HeartbeatScheduler(openclawd=openclawd, config_path=config_path)
    return _heartbeat_scheduler
