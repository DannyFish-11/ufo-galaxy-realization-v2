"""
launcher/shutdown.py — Graceful shutdown of core subsystems.

Responsibilities:
- async_shutdown: disconnect NATS bus and shut down core subsystems
  (event bridge, monitoring, cache) in a safe order.
"""

import logging

logger = logging.getLogger("Galaxy")


async def async_shutdown() -> None:
    """异步关闭核心子系统。

    Shutdown order:
      0. Persist in-flight task lifecycle snapshot so restart recovery can
         recover pending tasks after the next process start.
      1. Core subsystems bootstrapped by ``core.startup``
         (event bridge → monitoring → cache).
      2. NATS bus graceful disconnect.

    Failures are logged as warnings and do not prevent the remaining
    shutdown steps from running.
    """
    # Step 0: Persist in-flight task lifecycle state before any subsystem
    # teardown.  This ensures that tasks pending at shutdown time are
    # durably recorded and can be recovered by RuntimeRestartRecoveryCoordinator
    # on the next process start.
    try:
        from core.task_envelope_lifecycle_registry import persist_lifecycle_snapshot

        _ok = persist_lifecycle_snapshot()
        if _ok:
            logger.info("async_shutdown: lifecycle snapshot persisted for restart recovery.")
        else:
            logger.warning("async_shutdown: lifecycle snapshot persist returned False.")
    except Exception as exc:
        logger.warning("async_shutdown: lifecycle snapshot persist failed — %s", exc)

    try:
        from core.master_brain import get_master_brain

        brain = get_master_brain()
        if brain is not None:
            await brain.stop()
    except Exception as exc:
        logger.warning("MasterBrain 关闭异常: %s", exc)

    try:
        from core.startup import shutdown_subsystems
        await shutdown_subsystems()
    except Exception as exc:
        logger.warning("子系统关闭异常: %s", exc)

    try:
        from core.nats_bus import nats_bus
        await nats_bus.disconnect()
    except Exception as exc:
        logger.warning("NATS Bus 关闭异常: %s", exc)
