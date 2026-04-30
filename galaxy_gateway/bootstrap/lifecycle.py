"""
galaxy_gateway/bootstrap/lifecycle.py — Gateway lifespan / startup / shutdown.

Extracted from ``galaxy_gateway.app`` so that the main composition module
remains a thin wiring layer.  This module owns all service initialization and
teardown logic.

Services are stored on ``app.state`` after startup so that route handlers can
access them via the dependency helpers in ``galaxy_gateway.dependencies``.
Module-level globals in ``galaxy_gateway.app`` are also updated for backward
compatibility with legacy import paths (e.g. ``connection_manager.py``).
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: C901  (acceptable complexity for a bootstrap)
    """Galaxy Gateway application lifespan — startup → yield → shutdown."""

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    logger.info("Initializing Galaxy Gateway...")

    from galaxy_gateway.transport import WebSocketManager
    from galaxy_gateway.handlers import DeviceManager, MessageHandler
    from galaxy_gateway.orchestrator import TaskOrchestrator
    from galaxy_gateway.protocol import AIPMessage

    device_manager = DeviceManager()
    message_handler = MessageHandler(device_manager)

    async def on_message(device_id: str, message: AIPMessage):
        response = await message_handler.handle_message(device_id, message)
        if response:
            await websocket_manager.send_message(device_id, response)

    async def on_connect(device_id: str):
        logger.info("Device connected: %s", device_id)

    async def on_disconnect(device_id: str):
        logger.info("Device disconnected: %s", device_id)
        device_manager.update_device_status(device_id, "offline")

    websocket_manager = WebSocketManager(
        heartbeat_interval=30,
        heartbeat_timeout=90,
        on_message=on_message,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
    )

    task_orchestrator = TaskOrchestrator(
        device_manager=device_manager,
        message_handler=message_handler,
        websocket_manager=websocket_manager,
    )

    await websocket_manager.start()
    await task_orchestrator.start()

    # Store required services on app.state
    app.state.device_manager = device_manager
    app.state.message_handler = message_handler
    app.state.websocket_manager = websocket_manager
    app.state.task_orchestrator = task_orchestrator

    # Initialize optional services — these start as None; set to real
    # objects if initialization succeeds.
    app.state.openclawd_instance = None
    app.state.llm_router_instance = None
    app.state.nats_adapter = None
    app.state.heartbeat_scheduler = None

    # ── Phase 3: OpenClawd unified intelligence entry ──
    try:
        from core.openclawd import OpenClawd
        app.state.openclawd_instance = OpenClawd()
        logger.info("OpenClawd initialized")
    except Exception as e:
        logger.warning("OpenClawd unavailable (chat endpoint will degrade): %s", e)

    # ── Agent-level heartbeat scheduler ──
    if app.state.openclawd_instance is not None:
        try:
            from core.openclawd_heartbeat import get_heartbeat_scheduler
            scheduler = get_heartbeat_scheduler(openclawd=app.state.openclawd_instance)
            if scheduler is not None:
                await scheduler.start()
                app.state.heartbeat_scheduler = scheduler
        except Exception as e:
            logger.warning("OpenClawd heartbeat scheduler not started (non-fatal): %s", e)

    # ── Phase 6: LLM router reference ──
    try:
        from core.multi_llm_router import get_llm_router
        app.state.llm_router_instance = get_llm_router()
        logger.info("MultiLLMRouter reference acquired")
    except Exception as e:
        logger.warning("MultiLLMRouter unavailable: %s", e)

    logger.info("Galaxy Gateway initialized successfully")

    # ── Phase B: NATS ↔ WebSocket gateway adapter ──
    try:
        from core.nats_bus import nats_bus
        nats_url = os.getenv("GALAXY_NATS_URL", "nats://localhost:4222")
        await nats_bus.connect()
        if nats_bus.is_connected():
            from galaxy_gateway.gateway_nats_adapter import init_gateway_nats_adapter
            adapter = init_gateway_nats_adapter(
                device_manager=device_manager,
                websocket_manager=websocket_manager,
            )
            await adapter.start()
            app.state.nats_adapter = adapter
            logger.info("NATS Gateway Adapter started (%s)", nats_url)
        else:
            logger.warning(
                "NATS Gateway Adapter: NATS unavailable (%s) — running in no-op / "
                "single-machine mode. Start NATS with: nats-server -p 4222",
                nats_url,
            )
    except Exception as e:
        logger.warning("NATS Gateway Adapter init error (non-fatal): %s", e)

    # ── Stale-device cleanup background task ──
    # Periodically calls android_bridge.cleanup_stale_devices() to mark
    # devices whose heartbeats have exceeded the 120s liveness window as
    # disconnected in the transport cache.  This ensures the routing layer
    # never dispatches to a device that has silently gone offline.
    # Cleanup interval: 90 s (heartbeat timeout is 120 s, OkHttp TCP ping 20 s).
    _stale_cleanup_task: object = None
    try:
        import asyncio as _asyncio
        from galaxy_gateway.android_bridge import android_bridge as _android_bridge

        async def _periodic_stale_cleanup() -> None:
            """Background task: prune stale AndroidBridge transport cache entries."""
            _cleanup_interval = float(
                os.getenv("GALAXY_STALE_CLEANUP_INTERVAL_S", "90")
            )
            _cleanup_timeout = float(
                os.getenv("GALAXY_STALE_CLEANUP_TIMEOUT_S", "120")
            )
            while True:
                await _asyncio.sleep(_cleanup_interval)
                try:
                    await _android_bridge.cleanup_stale_devices(
                        timeout_seconds=_cleanup_timeout
                    )
                    logger.debug(
                        "Stale device cleanup pass complete "
                        "(interval=%.0fs timeout=%.0fs)",
                        _cleanup_interval,
                        _cleanup_timeout,
                    )
                except Exception as _cln_err:
                    logger.debug(
                        "Stale device cleanup pass failed (non-fatal): %s",
                        _cln_err,
                    )

        _stale_cleanup_task = _asyncio.create_task(_periodic_stale_cleanup())
        logger.info(
            "Stale-device cleanup background task started "
            "(interval=%ss, timeout=%ss)",
            os.getenv("GALAXY_STALE_CLEANUP_INTERVAL_S", "90"),
            os.getenv("GALAXY_STALE_CLEANUP_TIMEOUT_S", "120"),
        )
    except Exception as _task_err:
        logger.warning(
            "Stale-device cleanup background task could not be started "
            "(non-fatal): %s",
            _task_err,
        )

    # ── MasterBrain: cloud-side orchestrator ──
    if os.environ.get("GALAXY_MASTER_BRAIN_ENABLED", "").lower() in ("true", "1"):
        try:
            from core.master_brain import get_master_brain
            brain = get_master_brain()
            if brain is not None:
                start_result = await brain.start()
                if start_result.get("already_started"):
                    logger.info("MasterBrain: already started (no-op)")
                elif start_result.get("success"):
                    from core.nats_bus import nats_bus as _nb
                    logger.info(
                        "MasterBrain: started — NATS=%s, subscriptions registered",
                        _nb.is_connected(),
                    )
                else:
                    logger.warning("MasterBrain: start returned failure: %s", start_result)
            else:
                logger.warning("MasterBrain: get_master_brain() returned None")
        except Exception as _mb_err:
            logger.warning("MasterBrain startup failed (non-fatal): %s", _mb_err)
    else:
        logger.info(
            "MasterBrain: disabled (set GALAXY_MASTER_BRAIN_ENABLED=true to enable)"
        )

    # ── Security posture logging ──
    from core.auth import is_auth_enabled, get_active_tokens
    if is_auth_enabled():
        active = get_active_tokens()
        if active:
            logger.info(
                "\U0001f512 Bearer token auth: ENABLED (%d active token(s)) — key rotation supported",
                len(active),
            )
        else:
            logger.warning(
                "\u26a0\ufe0f  Bearer token auth: ENABLED but no active tokens are configured — "
                "all requests will be rejected until a token is set."
            )
    else:
        logger.info(
            "\U0001f513 Bearer token auth: DISABLED (set GALAXY_AUTH_ENABLED=true to enable)"
        )

    _tls_cert = os.getenv("GALAXY_TLS_CERT", "").strip()
    _tls_key = os.getenv("GALAXY_TLS_KEY", "").strip()
    if _tls_cert and _tls_key:
        logger.info("\U0001f510 TLS: ENABLED (cert=%s)", _tls_cert)
    else:
        logger.info(
            "\U0001f513 TLS: DISABLED (set GALAXY_TLS_CERT + GALAXY_TLS_KEY to enable)"
        )

    # ── Update module-level globals in app.py for backward compatibility ──
    # (legacy imports: ``from galaxy_gateway.app import websocket_manager``)
    try:
        import galaxy_gateway.app as _gw_app
        _gw_app.device_manager = device_manager
        _gw_app.message_handler = message_handler
        _gw_app.websocket_manager = websocket_manager
        _gw_app.task_orchestrator = task_orchestrator
        _gw_app.openclawd_instance = app.state.openclawd_instance
        _gw_app.llm_router_instance = app.state.llm_router_instance
        _gw_app.nats_adapter = app.state.nats_adapter
        _gw_app.heartbeat_scheduler = app.state.heartbeat_scheduler
    except Exception as _bc_err:
        logger.debug("Module-level backward-compat globals update failed: %s", _bc_err)

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("Shutting down Galaxy Gateway...")

    # Cancel the stale-device cleanup background task first.
    if _stale_cleanup_task is not None:
        try:
            _stale_cleanup_task.cancel()  # type: ignore[union-attr]
        except Exception:
            pass

    if app.state.heartbeat_scheduler is not None:
        try:
            await app.state.heartbeat_scheduler.stop()
        except Exception:
            pass

    if app.state.nats_adapter is not None:
        try:
            await app.state.nats_adapter.stop()
        except Exception:
            pass

    await task_orchestrator.stop()
    await websocket_manager.stop()

    # Clear module-level backward-compat globals
    try:
        import galaxy_gateway.app as _gw_app
        _gw_app.device_manager = None
        _gw_app.message_handler = None
        _gw_app.websocket_manager = None
        _gw_app.task_orchestrator = None
        _gw_app.openclawd_instance = None
        _gw_app.llm_router_instance = None
        _gw_app.nats_adapter = None
        _gw_app.heartbeat_scheduler = None
    except Exception:
        pass

    logger.info("Galaxy Gateway shut down")
