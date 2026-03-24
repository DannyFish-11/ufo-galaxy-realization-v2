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
      1. Core subsystems bootstrapped by ``core.startup``
         (event bridge → monitoring → cache).
      2. NATS bus graceful disconnect.

    Failures are logged as warnings and do not prevent the remaining
    shutdown steps from running.
    """
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
