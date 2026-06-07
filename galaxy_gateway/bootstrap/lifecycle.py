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
            # PR-AIP-UNIFIED: Send via AIPTransport
            try:
                from core.aip_transport import get_aip_transport
                await get_aip_transport().send(
                    response.model_dump(mode="json") if hasattr(response, 'model_dump') else response,
                    device_id,
                    transport="websocket",
                )
            except Exception:
                # Fallback: direct WS
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
            logger.warning("OpenClawd heartbeat scheduler not started (non-fatal): %s", e, exc_info=True)  # H4 fixed

    # ── Phase 6: LLM router reference ──
    try:
        from core.multi_llm_router import get_llm_router
        app.state.llm_router_instance = get_llm_router()
        logger.info("MultiLLMRouter reference acquired")
    except Exception as e:
        logger.warning("MultiLLMRouter unavailable: %s", e, exc_info=True)  # H4 fixed

    # ── Phase 7: Agent Swarm Coordinator ──
    try:
        from core.swarm_coordinator import SwarmCoordinator
        app.state.swarm_coordinator = SwarmCoordinator()
        logger.info("Agent Swarm Coordinator initialized")
    except Exception as e:
        logger.warning("SwarmCoordinator unavailable (swarm endpoint will degrade): %s", e, exc_info=True)  # H4 fixed

    logger.info("Galaxy Gateway initialized successfully")

    # ── PR-STABILITY-INIT: Initialize dead-code modules into startup chain ──
    # These modules were created but never initialized. They are now integrated
    # into the official startup sequence with graceful degradation.

    # 1. Agent Identity Memory — loads persistent self-identity
    try:
        from core.agent_identity_memory import get_identity_memory  # noqa: PLC0415
        _identity = get_identity_memory()
        logger.info("AgentIdentity: loaded — %s", _identity.get_identity().name)
        app.state.agent_identity = _identity
    except Exception as _id_err:
        logger.debug("AgentIdentity init skipped (non-fatal): %s", _id_err, exc_info=True)  # H4 fixed

    # 2. Node Capability Loader — discovers node actions on startup
    try:
        from core.node_capability_loader import get_capability_loader  # noqa: PLC0415
        _loader = get_capability_loader()
        # Defer loading to background — don't block startup
        async def _load_capabilities_bg():
            try:
                result = await _loader.load_all_capabilities()
                logger.info("NodeCapability: loaded %d nodes", len(result))
            except Exception as _cl_err:
                logger.debug("NodeCapability background load failed: %s", _cl_err, exc_info=True)  # H4 fixed
        asyncio.create_task(_load_capabilities_bg())  # L3 fixed: use asyncio directly
        app.state.capability_loader = _loader
    except Exception as _cl_err:
        logger.debug("NodeCapability init skipped (non-fatal): %s", _cl_err, exc_info=True)  # H4 fixed

    # 3. State Sync Bus — cross-standard synchronization
    try:
        from core.state_sync_bus import install_default_sync  # noqa: PLC0415
        install_default_sync()
        logger.info("StateSyncBus: default sync handlers installed")
    except Exception as _ss_err:
        logger.debug("StateSyncBus init skipped (non-fatal): %s", _ss_err, exc_info=True)  # H4 fixed

    # 4. Tailscale Manager — optional VPN tunnel monitoring
    try:
        from core.tailscale_manager import get_tailscale_manager  # noqa: PLC0415
        _ts_mgr = get_tailscale_manager()
        await _ts_mgr.initialize()
        if _ts_mgr.is_available():
            logger.info("Tailscale: available at %s", _ts_mgr.get_tailscale_ip())
        app.state.tailscale_manager = _ts_mgr
    except Exception as _ts_err:
        logger.debug("Tailscale init skipped (non-fatal): %s", _ts_err, exc_info=True)  # H4 fixed

    # 5. Voice Wake Module — local "Galaxy" wake-word detection
    try:
        from core.voice_wake_module import get_voice_wake  # noqa: PLC0415
        _vw = get_voice_wake()
        if _vw.is_available():
            # Callback: trigger LIMINAL phase via handle_request.
            # DesktopPresenceRuntime has no tristate_field; phase is driven
            # exclusively through the handle_request lifecycle (SILENT→LIMINAL
            #→MANIFEST→SILENT).  We fire a minimal wake-word request.
            def _on_wake_word():
                async def _wake_request():
                    try:
                        from core.desktop_presence_runtime import (  # noqa: PLC0415
                            get_desktop_presence_runtime,
                        )
                        dpr = get_desktop_presence_runtime()
                        if dpr is not None:
                            await dpr.handle_request(
                                message="[wake-word: Galaxy]",
                                source="voice_wake",
                            )
                            logger.info("VoiceWake: 'Galaxy' detected → LIMINAL via handle_request")
                    except Exception as _we:
                        logger.debug("VoiceWake: handle_request failed: %s", _we)
                asyncio.create_task(_wake_request())  # L3 fixed: use asyncio directly

            started = _vw.start(callback=_on_wake_word)
            if started:
                logger.info("VoiceWake: 'Galaxy' wake-word detection active")
            app.state.voice_wake = _vw
    except Exception as _vw_err:
        logger.debug("VoiceWake init skipped (non-fatal): %s", _vw_err, exc_info=True)  # H4 fixed

    # 6. Feedback Loop — execution result tracking
    try:
        from core.feedback_loop import get_feedback_loop  # noqa: PLC0415
        _fb = get_feedback_loop()
        app.state.feedback_loop = _fb
        logger.info("FeedbackLoop: initialized (%d history entries)", len(_fb._history))
    except Exception as _fb_err:
        logger.debug("FeedbackLoop init skipped (non-fatal): %s", _fb_err, exc_info=True)  # H4 fixed

    logger.info("PR-STABILITY-INIT: all modules integrated")

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
        logger.warning("NATS Gateway Adapter init error (non-fatal): %s", e, exc_info=True)  # H4 fixed

    # ── Phase C: MeshCoordinator sender injection ──
    # NOTE: Mesh senders are already injected by core/routes/hybrid.py
    # at application startup. The hybrid module provides P2P (WS-simulated),
    # Relay, and WS senders with full API endpoints.
    # Lifecycle injection here would conflict with hybrid.py's setup.
    # See: core/routes/hybrid.py Phase 5 for the canonical injection point.
    logger.debug("Mesh senders: using hybrid.py canonical injection")

    # ── Stale-device cleanup background task ──
    # Periodically calls android_bridge.cleanup_stale_devices() to mark
    # devices whose heartbeats have exceeded the 120s liveness window as
    # disconnected in the transport cache.  This ensures the routing layer
    # never dispatches to a device that has silently gone offline.
    # Cleanup interval: 90 s (heartbeat timeout is 120 s, OkHttp TCP ping 20 s).
    app.state.stale_cleanup_task = None  # H5 fixed: store on app.state instead of local var
    try:
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
                await asyncio.sleep(_cleanup_interval)
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
                        exc_info=True,  # H4 fixed
                    )

        app.state.stale_cleanup_task = asyncio.create_task(_periodic_stale_cleanup())  # H5 fixed
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
            exc_info=True,  # H4 fixed
        )

    # ── MasterBrain: cloud-side orchestrator ──
    from core.master_brain import master_brain_enabled

    if master_brain_enabled():
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
            logger.warning("MasterBrain startup failed (non-fatal): %s", _mb_err, exc_info=True)  # H4 fixed
    else:
        logger.info(
            "MasterBrain: disabled (set GALAXY_MASTER_BRAIN_ENABLED=true to enable)"
        )

    # ── Security posture logging ──
    from core.auth import is_auth_enabled, get_active_tokens, ensure_auth_config_validated
    ensure_auth_config_validated()
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

    # ── Phase 8: AIPTransport adapter registration ──
    # PR-AIP-UNIFIED: Register physical transport adapters.
    # NOTE: NATS is NOT here — NATS is a task distribution layer,
    # parallel to AIP Transport, not a transport adapter.
    # Migrated from nodes/: MQTT(Node_41), BLE(Node_38), Serial(Node_48)
    try:
        from core.aip_transport import get_aip_transport
        from core.adapters import (
            WebSocketAdapter,
            MQTTAdapter, TCPAdapter, UDPAdapter,
            BLEAdapter, SerialAdapter,
            DBusAdapter, CANBusAdapter,
        )

        aip_transport = get_aip_transport()
        aip_transport.register_adapter(WebSocketAdapter(websocket_manager))
        # PR-28: Tailscale P2P — register before others so it gets priority
        ts_adapter = None
        try:
            from core.adapters.tailscale_p2p_adapter import TailscaleP2PAdapter
            ts_adapter = TailscaleP2PAdapter()
            if await ts_adapter.initialize():
                aip_transport.register_adapter(ts_adapter)
                logger.info("PR-28: TailscaleP2PAdapter registered and active")
                # PR-28: Start P2P inbound server for direct connections
                try:
                    await ts_adapter.start_server()
                    logger.info("PR-28: Tailscale P2P inbound server started")
                except Exception as srv_exc:
                    logger.warning("PR-28: P2P server start failed (non-fatal): %s", srv_exc)
            else:
                logger.debug("PR-28: Tailscale not available, P2P adapter skipped")
        except Exception as exc:
            logger.debug("PR-28: TailscaleP2PAdapter registration skipped: %s", exc)

        aip_transport.register_adapter(MQTTAdapter())
        aip_transport.register_adapter(TCPAdapter())
        aip_transport.register_adapter(UDPAdapter())
        aip_transport.register_adapter(BLEAdapter())
        aip_transport.register_adapter(SerialAdapter())
        aip_transport.register_adapter(DBusAdapter())
        aip_transport.register_adapter(CANBusAdapter())

        # PR-AIP-v52: 启动 TCP P2P 和 UDP 监听服务
        try:
            tcp_adapter = aip_transport.get_adapter("tcp")
            if tcp_adapter:
                await tcp_adapter.start_server()
                tcp_adapter.register_local_service(device_id)
        except Exception as _tcp_err:
            logger.debug("TCP P2P server start failed (non-fatal): %s", _tcp_err)

        try:
            udp_adapter = aip_transport.get_adapter("udp")
            if udp_adapter:
                await udp_adapter.start()
        except Exception as _udp_err:
            logger.debug("UDP listener start failed (non-fatal): %s", _udp_err)

        app.state.aip_transport = aip_transport
        logger.info(
            "AIPTransport adapters registered: %s",
            aip_transport.list_adapters(),
        )
    except Exception as _aip_err:
        logger.warning("AIPTransport adapter registration failed (non-fatal): %s", _aip_err)

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
        _gw_app.aip_transport = getattr(app.state, "aip_transport", None)
    except Exception as _bc_err:
        logger.debug("Module-level backward-compat globals update failed: %s", _bc_err)

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("Shutting down Galaxy Gateway...")

    # Cancel the stale-device cleanup background task first.
    # H3 fixed: await task cancellation with timeout; H5 fixed: use app.state
    if getattr(app.state, 'stale_cleanup_task', None) is not None:
        try:
            app.state.stale_cleanup_task.cancel()
            await asyncio.wait_for(asyncio.shield(app.state.stale_cleanup_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            logger.warning("Stale cleanup shutdown error", exc_info=True)

    # H7 fixed: add timeout and proper error logging for heartbeat scheduler stop
    if app.state.heartbeat_scheduler is not None:
        try:
            await asyncio.wait_for(app.state.heartbeat_scheduler.stop(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("Heartbeat scheduler stop timed out")
        except Exception as e:
            logger.error("Heartbeat scheduler stop failed: %s", e, exc_info=True)

    try:
        from core.master_brain import get_master_brain

        brain = get_master_brain()
        if brain is not None:
            await brain.stop()
    except Exception:
        pass

    if app.state.nats_adapter is not None:
        try:
            await app.state.nats_adapter.stop()
        except Exception:
            pass

    await task_orchestrator.stop()
    await websocket_manager.stop()

    # PR-AIP-v52: 关闭 AIPTransport 适配器（TCP P2P, UDP, BLE, etc.）
    aip_transport = getattr(app.state, "aip_transport", None)
    if aip_transport is not None:
        try:
            await aip_transport.close_all()
            logger.debug("AIPTransport adapters closed")
        except Exception:
            pass

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
        _gw_app.aip_transport = None
    except Exception:
        pass

    logger.info("Galaxy Gateway shut down")
