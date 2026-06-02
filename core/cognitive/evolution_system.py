"""
core.cognitive.evolution_system — Cognitive Evolution System Bootstrap & Lifecycle
===================================================================================
PR-25/26/27 — Unified initialization and background maintenance for the
cognitive learning loop.

This module provides a single entry point to initialize the entire cognitive
evolution subsystem and manage its lifecycle:

    from core.cognitive.evolution_system import init_cognitive_evolution, shutdown_cognitive_evolution
    
    # On system startup (called once from main.py)
    init_cognitive_evolution()
    
    # On system shutdown
    shutdown_cognitive_evolution()

What it does
------------
1. **Initializes** all three cognitive layers (ReflectionEngine, PatternMiner,
   AdaptivePredictor) and connects them to the state event bus.
2. **Starts** a background maintenance task that periodically decays
   activation scores of reflections and patterns (Soar-style).
3. **Provides** health diagnostics for monitoring the cognitive subsystem.
4. **Gracefully shuts down** all background tasks on system exit.

Design principles
-----------------
- **Single entry point**: One function call to bring the entire cognitive
  evolution system online. No scattered initialization across modules.
- **Non-blocking**: init returns immediately; background tasks run via asyncio.
- **Fail-soft**: Any initialization failure is logged but never blocks system startup.
- **Observable**: Health metrics exposed via get_cognitive_health().
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Cognitive.Evolution")

# ── Constants ────────────────────────────────────────────────────────────

_DECAY_INTERVAL_SECONDS = 3600.0  # decay activation scores every hour
_MAINTENANCE_TASK_NAME = "cognitive_evolution_maintenance"

# ── Module-level state ────────────────────────────────────────────────────

_maintenance_task: Optional[asyncio.Task] = None
_shutdown_event: Optional[threading.Event] = None
_initialized = False
_init_lock = threading.Lock()


# ── Public API ────────────────────────────────────────────────────────────


def init_cognitive_evolution() -> None:
    """Initialize the entire cognitive evolution system.

    Safe to call multiple times — subsequent calls are no-ops.
    Should be called once during system startup (e.g., from main.py).
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        _do_init()
        _initialized = True
        logger.info("Cognitive evolution system initialized")


def shutdown_cognitive_evolution() -> None:
    """Gracefully shut down the cognitive evolution system.

    Cancels background maintenance tasks. Safe to call multiple times.
    """
    global _initialized, _maintenance_task
    if not _initialized:
        return
    
    # Signal shutdown
    if _shutdown_event is not None:
        _shutdown_event.set()
    
    # Cancel maintenance task
    if _maintenance_task is not None and not _maintenance_task.done():
        _maintenance_task.cancel()
        try:
            asyncio.get_event_loop().run_until_complete(
                asyncio.wait_for(_maintenance_task, timeout=2.0)
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    
    _initialized = False
    _maintenance_task = None
    logger.info("Cognitive evolution system shut down")


def get_cognitive_health() -> Dict[str, Any]:
    """Return health metrics for the cognitive evolution subsystem.

    Returns dict with counts, activation stats, and calibration info.
    Safe to call at any time — returns partial data if some components
    are not yet initialized.
    """
    health: Dict[str, Any] = {
        "initialized": _initialized,
        "timestamp": time.time(),
    }
    
    # ReflectionEngine stats
    try:
        from core.cognitive.reflection_engine import get_reflection_engine
        engine = get_reflection_engine()
        reflections = engine.to_dict_list()
        health["reflections"] = {
            "count": len(reflections),
            "avg_activation": round(
                sum(r.get("activation_score", 0) for r in reflections) / max(len(reflections), 1), 4
            ),
            "by_type": {},
        }
        for r in reflections:
            rt = r.get("reflection_type", "unknown")
            health["reflections"]["by_type"][rt] = health["reflections"]["by_type"].get(rt, 0) + 1
    except Exception as exc:
        health["reflections"] = {"error": str(exc)}
    
    # PatternMiner stats
    try:
        from core.cognitive.pattern_miner import get_pattern_miner
        miner = get_pattern_miner()
        patterns = miner.to_dict_list()
        health["patterns"] = {
            "count": len(patterns),
            "avg_activation": round(
                sum(p.get("activation_score", 0) for p in patterns) / max(len(patterns), 1), 4
            ),
            "by_type": {},
        }
        for p in patterns:
            pt = p.get("pattern_type", "unknown")
            health["patterns"]["by_type"][pt] = health["patterns"]["by_type"].get(pt, 0) + 1
    except Exception as exc:
        health["patterns"] = {"error": str(exc)}
    
    # AdaptivePredictor stats
    try:
        from core.cognitive.adaptive_predictor import get_adaptive_predictor
        predictor = get_adaptive_predictor()
        health["predictor"] = predictor.get_calibration_stats()
    except Exception as exc:
        health["predictor"] = {"error": str(exc)}
    
    return health


# ── Internal ──────────────────────────────────────────────────────────────


def _do_init() -> None:
    """Perform actual initialization."""
    global _shutdown_event, _maintenance_task
    
    # 1. Initialize ReflectionEngine (auto-subscribes to event bus)
    try:
        from core.cognitive.reflection_engine import get_reflection_engine
        get_reflection_engine()
        logger.debug("ReflectionEngine initialized")
    except Exception as exc:
        logger.warning("ReflectionEngine init failed (non-fatal): %s", exc)
    
    # 2. Initialize PatternMiner (auto-subscribes to event bus)
    try:
        from core.cognitive.pattern_miner import get_pattern_miner
        get_pattern_miner()
        logger.debug("PatternMiner initialized")
    except Exception as exc:
        logger.warning("PatternMiner init failed (non-fatal): %s", exc)
    
    # 3. Initialize AdaptivePredictor
    try:
        from core.cognitive.adaptive_predictor import get_adaptive_predictor
        get_adaptive_predictor()
        logger.debug("AdaptivePredictor initialized")
    except Exception as exc:
        logger.warning("AdaptivePredictor init failed (non-fatal): %s", exc)
    
    # 4. Start background maintenance task
    _shutdown_event = threading.Event()
    try:
        loop = asyncio.get_running_loop()
        _maintenance_task = loop.create_task(
            _maintenance_loop(),
            name=_MAINTENANCE_TASK_NAME,
        )
        logger.debug("Cognitive maintenance task started")
    except RuntimeError:
        # No running event loop — maintenance will not run.
        # This is acceptable for non-async environments.
        logger.debug("No async event loop — cognitive maintenance disabled")


async def _maintenance_loop() -> None:
    """Background task: periodically decay activation scores.
    
    Runs every _DECAY_INTERVAL_SECONDS (default 1 hour).
    Decays both reflections and patterns to prevent unbounded growth.
    """
    if _shutdown_event is None:
        return
    
    logger.debug("Cognitive maintenance loop started (interval=%.0fs)", _DECAY_INTERVAL_SECONDS)
    
    while not _shutdown_event.is_set():
        try:
            # Wait for interval or shutdown signal
            await asyncio.wait_for(
                _async_wait_for_shutdown(),
                timeout=_DECAY_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            # Normal interval tick — perform decay
            pass
        except asyncio.CancelledError:
            logger.debug("Cognitive maintenance loop cancelled")
            return
        
        if _shutdown_event.is_set():
            return
        
        # Decay reflections
        try:
            from core.cognitive.reflection_engine import get_reflection_engine
            engine = get_reflection_engine()
            engine.decay_all(days=1.0)
            logger.debug("ReflectionEngine decay cycle completed")
        except Exception as exc:
            logger.debug("Reflection decay failed (non-fatal): %s", exc)
        
        # Decay patterns
        try:
            from core.cognitive.pattern_miner import get_pattern_miner
            miner = get_pattern_miner()
            pruned = miner.decay_all(days=1.0)
            if pruned > 0:
                logger.debug("PatternMiner pruned %d dead patterns", pruned)
        except Exception as exc:
            logger.debug("Pattern decay failed (non-fatal): %s", exc)


async def _async_wait_for_shutdown() -> None:
    """Async helper that blocks until shutdown event is set."""
    if _shutdown_event is None:
        return
    # Poll the threading.Event in an async-friendly way
    while not _shutdown_event.is_set():
        await asyncio.sleep(1.0)
