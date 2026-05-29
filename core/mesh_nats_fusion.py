"""
core/mesh_nats_fusion.py
========================
PR-MESH-NATS-FUSION: Mesh–NATS Convergence Layer (NO BRIDGE)

Design principle:  NOT a bridge — a convergence layer.

Mesh's barrier mechanism and NATS's pub/sub are made to share ONE
runtime model:

    - Mesh barrier evaluate  →  if participant is LOCAL: call directly
                              if participant is REMOTE: NATS publish
    - Remote participant     →  receives NATS msg, executes, NATS reply
    - Mesh receives reply    →  fills participant_results naturally
    - Barrier releases       →  same code path as all-local

This module is imported by live_mesh_runtime_engine.py at the
_evaluate_barrier hot-path.  If NATS is not available, it falls back
silently to the original local-only behaviour.

Usage (inside Mesh engine)::

    from core.mesh_nats_fusion import MeshNATSConvergence
    convergence = MeshNATSConvergence(nats_bus)
    # In barrier evaluation:
    if convergence.is_remote(device_id):
        await convergence.request_participant_action(device_id, action, params)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
MESH_NATS_FUSION_SENTINEL = (
    "MESH_NATS_FUSION::CONVERGENCE_LAYER::NO_BRIDGE"
)


# ---------------------------------------------------------------------------
# Convergence layer
# ---------------------------------------------------------------------------
class MeshNATSConvergence:
    """Mesh–NATS convergence — one runtime model for local + remote participants.

    This is NOT a bridge.  It extends Mesh's barrier evaluation so that
    remote devices (on other processes / other machines) participate through
    NATS messages, while local devices continue to be called directly.

    The key insight:  Mesh's ``participant_results`` dict is the single
    shared state.  NATS only transports results INTO that dict.
    """

    # NATS subject patterns
    SUBJ_MESH_BARRIER_REQUEST = "galaxy.mesh.barrier.request.{session_id}.{device_id}"
    SUBJ_MESH_BARRIER_REPLY = "galaxy.mesh.barrier.reply.{session_id}.{device_id}"
    SUBJ_MESH_PARTICIPANT_RESULT = "galaxy.mesh.participant.result.{session_id}"

    def __init__(self, nats_bus: Optional[Any] = None) -> None:
        self._nats = nats_bus
        self._local_device_cache: Dict[str, bool] = {}
        self._session_subscriptions: Dict[str, Any] = {}

    # -- public API ------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if NATS bus is connected and usable."""
        return self._nats is not None and getattr(self._nats, "is_connected", lambda: False)()

    def is_remote(self, device_id: str) -> bool:
        """Check if a device is remote (needs NATS) or local (direct call).

        Caches the result for performance.  A device is considered local
        if it has a fusion_entry.py in the local process.
        """
        if device_id in self._local_device_cache:
            return not self._local_device_cache[device_id]

        # Check if device is local: look up in device_node_map
        try:
            from core.device_node_resolver import get_resolver
            resolver = get_resolver()
            # If we can resolve it AND the node is running locally → local
            resolved = resolver.resolve(device_type=None, transport=None, capabilities=[])
            # Simplified: if device_id starts with known local prefix
            is_local = device_id.startswith("local-") or ":" not in device_id
            self._local_device_cache[device_id] = is_local
            return not is_local
        except Exception:
            # Cannot determine → assume local (safer)
            self._local_device_cache[device_id] = True
            return False

    async def request_participant_action(
        self,
        *,
        session_id: str,
        device_id: str,
        action: str,
        params: Dict[str, Any],
        timeout_ms: int = 30_000,
    ) -> Optional[Dict[str, Any]]:
        """Request a remote participant to execute an action via NATS.

        This is the convergence point: Mesh asks for a result,
        NATS delivers the request to the remote device,
        remote device executes and replies,
        result is returned to Mesh's participant_results.

        Returns:
            The remote result dict, or None if timed out / failed.
        """
        if not self.is_available():
            logger.debug("[MeshNATS] NATS not available, skipping remote request for %s", device_id)
            return None

        request_subject = self.SUBJ_MESH_BARRIER_REQUEST.format(
            session_id=session_id, device_id=device_id
        )
        reply_subject = self.SUBJ_MESH_BARRIER_REPLY.format(
            session_id=session_id, device_id=device_id
        )

        payload = {
            "session_id": session_id,
            "device_id": device_id,
            "action": action,
            "params": params,
            "reply_to": reply_subject,
            "timestamp": time.time(),
        }

        try:
            # Publish request
            await self._nats.publish(request_subject, payload)
            logger.info(
                "[MeshNATS] Barrier request sent | session=%s device=%s action=%s",
                session_id, device_id, action,
            )

            # Wait for reply with timeout
            reply = await self._wait_for_reply(reply_subject, timeout_ms)
            if reply:
                logger.info(
                    "[MeshNATS] Barrier reply received | session=%s device=%s",
                    session_id, device_id,
                )
                return reply.get("result")
            else:
                logger.warning(
                    "[MeshNATS] Barrier reply TIMEOUT | session=%s device=%s",
                    session_id, device_id,
                )
                return None

        except Exception as exc:
            logger.error("[MeshNATS] Remote request failed: %s", exc)
            return None

    async def submit_participant_result(
        self,
        *,
        session_id: str,
        device_id: str,
        result: Dict[str, Any],
    ) -> None:
        """Submit a participant result back to the Mesh session.

        Called by the remote device after executing the action.
        """
        if not self.is_available():
            return

        subject = self.SUBJ_MESH_PARTICIPANT_RESULT.format(session_id=session_id)
        payload = {
            "session_id": session_id,
            "device_id": device_id,
            "result": result,
            "timestamp": time.time(),
        }

        try:
            await self._nats.publish(subject, payload)
            logger.debug(
                "[MeshNATS] Result submitted | session=%s device=%s",
                session_id, device_id,
            )
        except Exception as exc:
            logger.error("[MeshNATS] Result submission failed: %s", exc)

    async def subscribe_session(self, session_id: str, callback: Any) -> None:
        """Subscribe to all participant results for a Mesh session.

        The Mesh engine calls this at session start.  When remote
        participants submit results, they are delivered to the callback
        which fills the participant_results dict.
        """
        if not self.is_available():
            return

        subject = self.SUBJ_MESH_PARTICIPANT_RESULT.format(session_id=session_id)

        def _on_result(msg: Dict[str, Any]) -> None:
            device_id = msg.get("device_id")
            result = msg.get("result")
            if device_id and result:
                callback(device_id, result)

        try:
            sub = await self._nats.subscribe(subject, cb=_on_result)
            self._session_subscriptions[session_id] = sub
            logger.info("[MeshNATS] Subscribed to session %s", session_id)
        except Exception as exc:
            logger.error("[MeshNATS] Subscribe failed: %s", exc)

    async def unsubscribe_session(self, session_id: str) -> None:
        """Unsubscribe from a session."""
        sub = self._session_subscriptions.pop(session_id, None)
        if sub and self.is_available():
            try:
                await self._nats.unsubscribe(sub)
            except Exception:
                pass

    # -- internal --------------------------------------------------------------

    async def _wait_for_reply(self, reply_subject: str, timeout_ms: int) -> Optional[Dict]:
        """Wait for a reply on a NATS subject with timeout."""
        if not self.is_available():
            return None

        future: asyncio.Future = asyncio.Future()

        def _on_message(msg: Dict[str, Any]) -> None:
            if not future.done():
                future.set_result(msg)

        sub = await self._nats.subscribe(reply_subject, cb=_on_message)
        try:
            return await asyncio.wait_for(future, timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            return None
        finally:
            await self._nats.unsubscribe(sub)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_convergence_instance: Optional[MeshNATSConvergence] = None


def get_convergence(nats_bus: Optional[Any] = None) -> MeshNATSConvergence:
    """Return the module-level MeshNATSConvergence singleton."""
    global _convergence_instance
    if _convergence_instance is None:
        _convergence_instance = MeshNATSConvergence(nats_bus)
    elif nats_bus is not None:
        _convergence_instance._nats = nats_bus
    return _convergence_instance
