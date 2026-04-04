"""
Agent Bridge — Runtime Handoff Layer (Round 5)
===============================================

**Architecture role: RUNTIME HANDOFF ADAPTER — not a parallel authority**
--------------------------------------------------------------------------
``AgentBridge`` is a **runtime handoff adapter** within the gateway's
cross-device execution substrate.  It is NOT a top-level dispatch authority.

Authority model::

    Canonical chain: OpenClawd → CommandRouter → DeviceRouter → device
                                                       ↓
                                             AgentBridge.handoff()
                                              (optional handoff only)

``AgentBridge`` is called BY ``DeviceRouter`` (or its internal substrate)
as an *optional* runtime handoff step — it does NOT originate dispatch
decisions.  When the runtime is unreachable or disabled, the bridge
transparently falls back to the caller-supplied local executor.

AGENT_BRIDGE_ROLE sentinel: "runtime_handoff_adapter"

Mediates between the gateway / DeviceRouter and a downstream Agent Runtime
(e.g. OpenClawd) for cross-device task flows.

When the cross-device switch is **ON** and a task is marked as eligible for
runtime takeover, ``AgentBridge.handoff()`` delegates execution to the
configured runtime endpoint and routes the response back.  If the runtime is
unreachable or exceeds the timeout the bridge transparently falls back to the
caller-supplied local executor, emits a structured log, and increments the
fallback metric counter.

Handoff contract fields
-----------------------
trace_id        str     Unique per request; used for deduplication and logs.
capability      str     Primary capability required by the task.
exec_mode       str     "local" | "remote" | "both"  (AIP v3 field).
route_mode      str     AIP v3 route_mode (e.g. "direct", "broadcast").
session         dict    Session / context dict forwarded as-is to runtime.
task            dict    The original task payload.
callback_channel str    Preferred response channel: "ws" | "webrtc" | "nats".

Environment variables
---------------------
GALAXY_RUNTIME_URL
    HTTP(S) base URL of the agent runtime.  ``POST /handoff`` is called.
    Default: ``http://localhost:9000``  (no-op when runtime is absent).
GALAXY_RUNTIME_TIMEOUT
    Seconds to wait for runtime response before falling back.  Default: ``10``.
GALAXY_RUNTIME_ENABLED
    Set to ``0``, ``false``, or ``no`` to disable the bridge entirely
    (all tasks stay local).  Default: ``1`` (enabled).

Backward compatibility
----------------------
* When ``GALAXY_CROSS_DEVICE_ENABLED=0`` the bridge immediately returns the
  standard disabled response — no runtime call is made.
* When ``GALAXY_RUNTIME_ENABLED=0`` all tasks stay local regardless of the
  cross-device switch.
* When the runtime is unreachable or times out, the caller-supplied
  ``local_fallback`` coroutine is awaited and its result is returned.

Idempotency
-----------
``AgentBridge`` maintains an in-process LRU cache of recent ``trace_id`` →
result mappings.  A duplicate handoff with the same ``trace_id`` returns the
cached result immediately without a second runtime call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Architecture role declaration
# ---------------------------------------------------------------------------

AGENT_BRIDGE_ROLE: str = "runtime_handoff_adapter"
"""Role sentinel: AgentBridge is a runtime handoff adapter within the
gateway's cross-device execution substrate.  It is NOT a top-level dispatch
authority.  It is called by DeviceRouter as an optional handoff step only,
and MUST NOT originate or own cross-device dispatch decisions."""

# Import observability helpers (lazy-safe: importable at module level).
from galaxy_gateway.observability import (  # noqa: E402
    TraceContext,
    emit_gateway_log,
    get_gateway_metrics,
)

# ---------------------------------------------------------------------------
# PR-3 (post-533 dual-repo unification): canonicalization sentinels
# ---------------------------------------------------------------------------

CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE: str = (
    "pr3_post533_canonical_handoff_posture_propagation_active"
)
"""Sentinel: HandoffContract.source_runtime_posture is the canonical posture
field that propagates the source-device runtime participation posture through
the bridge handoff pipeline.  Declared in PR-3 of the post-533 dual-repo
runtime-host unification track (MAIN repo side)."""

HANDOFF_CONTRACT_IS_POSTURE_AWARE: str = (
    "pr3_post533_handoff_contract_is_posture_aware"
)
"""Sentinel: HandoffContract carries source_runtime_posture and includes it in
to_dict() so the runtime POST /handoff endpoint receives the canonical posture
value.  Paired with HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE."""

HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE: str = (
    "pr3_post533_handoff_envelope_v2_posture_adapter_active"
)
"""Sentinel: from_legacy_handoff_contract() and AgentBridge.build_envelope_v2()
now propagate source_runtime_posture from HandoffContract into HandoffEnvelopeV2
so the canonical v2 envelope always reflects the originating posture.  This
closes the posture-loss gap in the legacy→v2 adapter path (PR-3 main-repo side)."""

NO_POSTURE_SILENT_DROP_POLICY: str = (
    "pr3_post533_no_posture_silent_drop_policy"
)
"""Policy sentinel: source_runtime_posture MUST NOT be silently dropped at any
bridge/gateway/compat boundary.  Every handoff path that receives posture must
carry it forward — either through HandoffContract.source_runtime_posture or
through HandoffEnvelopeV2.source_runtime_posture — without silent reset to
the default.  Declared in PR-3 of the post-533 dual-repo unification track."""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME_URL: str = "http://localhost:9000"
_DEFAULT_TIMEOUT: float = 10.0
_DEDUP_CACHE_MAX_SIZE: int = 1024


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AgentBridgeConfig:
    """Runtime-bridge configuration (read from environment at call-time).

    All attributes can be overridden for testing by constructing the dataclass
    directly instead of calling :func:`AgentBridgeConfig.from_env`.
    """

    runtime_url: str = _DEFAULT_RUNTIME_URL
    timeout: float = _DEFAULT_TIMEOUT
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "AgentBridgeConfig":
        """Build config from environment variables."""
        raw_enabled = os.getenv("GALAXY_RUNTIME_ENABLED", "1").strip().lower()
        enabled = raw_enabled not in ("0", "false", "no")
        url = os.getenv("GALAXY_RUNTIME_URL", _DEFAULT_RUNTIME_URL).strip()
        try:
            timeout = float(os.getenv("GALAXY_RUNTIME_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        except ValueError:
            timeout = _DEFAULT_TIMEOUT
        return cls(runtime_url=url, timeout=timeout, enabled=enabled)


# ---------------------------------------------------------------------------
# Handoff contract
# ---------------------------------------------------------------------------

@dataclass
class HandoffContract:
    """Structured handoff envelope sent to the agent runtime.

    All fields are forwarded as JSON to the runtime's ``POST /handoff``
    endpoint.  Optional fields default to empty / "both" so legacy callers
    that don't populate every field still work.

    PR-1: ``task_id`` is accepted alongside ``trace_id`` so callers that
    construct a TaskEnvelope first can carry the unified identifier through
    the bridge.  Legacy payloads that only provide ``trace_id`` remain
    fully compatible.

    PR-3 (post-533 dual-repo unification): ``source_runtime_posture`` carries
    the canonical source-device participation posture through the handoff
    pipeline so the runtime endpoint can honour posture-aware dispatch rules.
    Valid values are ``"control_only"`` (default) and ``"join_runtime"``.
    """

    trace_id: str
    task: Dict[str, Any]
    capability: str = ""
    exec_mode: str = "both"
    route_mode: str = "direct"
    session: Dict[str, Any] = field(default_factory=dict)
    callback_channel: str = "ws"
    # PR-1: optional task_id from the originating TaskEnvelope
    task_id: str = ""
    # PR-3: source-device runtime participation posture (post-533 dual-repo unification)
    source_runtime_posture: str = "control_only"

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "trace_id": self.trace_id,
            "task": self.task,
            "capability": self.capability,
            "exec_mode": self.exec_mode,
            "route_mode": self.route_mode,
            "session": self.session,
            "callback_channel": self.callback_channel,
            "source_runtime_posture": self.source_runtime_posture,
        }
        if self.task_id:
            d["task_id"] = self.task_id
        return d


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class AgentBridgeMetrics:
    """Simple in-process counters for bridge observability.

    All attributes are plain ``int`` / ``float`` so they can be read without
    importing any external metrics library.
    """

    def __init__(self) -> None:
        self.handoff_attempts: int = 0
        self.handoff_success: int = 0
        self.handoff_failure: int = 0
        self.fallback_count: int = 0
        self.dedup_hit_count: int = 0
        self._latency_sum: float = 0.0
        self._latency_count: int = 0

    def record_latency(self, seconds: float) -> None:
        self._latency_sum += seconds
        self._latency_count += 1

    @property
    def avg_latency_ms(self) -> float:
        if self._latency_count == 0:
            return 0.0
        return (self._latency_sum / self._latency_count) * 1000.0

    def snapshot(self) -> Dict[str, Any]:
        return {
            "handoff_attempts": self.handoff_attempts,
            "handoff_success": self.handoff_success,
            "handoff_failure": self.handoff_failure,
            "fallback_count": self.fallback_count,
            "dedup_hit_count": self.dedup_hit_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


# ---------------------------------------------------------------------------
# Core bridge
# ---------------------------------------------------------------------------

LocalFallback = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
"""Type alias for the local-fallback coroutine.

The coroutine receives the original task dict and must return a result dict.
"""


class AgentBridge:
    """Mediates between the gateway and the downstream agent runtime.

    Parameters
    ----------
    config:
        Bridge configuration.  When ``None``, :meth:`AgentBridgeConfig.from_env`
        is called at construction time.

    Usage::

        bridge = AgentBridge()
        result = await bridge.handoff(
            contract=HandoffContract(trace_id="...", task={...}),
            local_fallback=my_local_executor,
        )
    """

    def __init__(self, config: Optional[AgentBridgeConfig] = None) -> None:
        self._config: AgentBridgeConfig = config or AgentBridgeConfig.from_env()
        self.metrics: AgentBridgeMetrics = AgentBridgeMetrics()
        # trace_id → result  (bounded LRU dedup cache)
        self._dedup_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handoff(
        self,
        contract: HandoffContract,
        local_fallback: Optional[LocalFallback] = None,
    ) -> Dict[str, Any]:
        """Attempt to delegate *contract* to the agent runtime.

        Flow
        ----
        1. Check ``GALAXY_CROSS_DEVICE_ENABLED``; return disabled dict if OFF.
        2. Check bridge enabled flag; stay local if disabled.
        3. Deduplicate by ``trace_id`` (or ``task_id`` when provided by a
           TaskEnvelope-sourced contract); return cached result on hit.
        4. Call runtime; on timeout / error fall back to *local_fallback*.
        5. Cache successful result; update metrics; return result.

        PR-2: When the contract carries a TaskEnvelope-sourced ``task_id``,
        the dedup cache uses ``task_id`` as the primary key (in addition to
        ``trace_id``) to avoid duplicate dispatches within the same envelope.

        Parameters
        ----------
        contract:
            Populated handoff contract for this request.
        local_fallback:
            Async callable ``(task: dict) -> dict`` invoked when the runtime
            is unreachable or times out.  When ``None``, a generic error dict
            is returned instead of a local result.

        Returns
        -------
        dict
            Result dict.  Always has ``"success"`` (bool) and ``"trace_id"``.
            Bridge-originated results additionally have ``"bridge_source"``
            set to ``"runtime"`` or ``"local_fallback"``.
        """
        from galaxy_gateway.cross_device_switch import (
            is_cross_device_enabled,
            make_disabled_response,
        )

        trace_id = contract.trace_id
        # PR-2: use task_id as dedup key when it originates from a TaskEnvelope;
        # fall back to trace_id for legacy contracts that only carry trace_id.
        dedup_key = contract.task_id if contract.task_id else trace_id
        trace_ctx = TraceContext(trace_id=trace_id, span_id=str(uuid.uuid4()))
        gm = get_gateway_metrics()

        # ── 1. Cross-device switch guard ──────────────────────────────────
        if not is_cross_device_enabled():
            return make_disabled_response(trace_id=trace_id)

        # ── 2. Bridge enabled guard ────────────────────────────────────────
        if not self._config.enabled:
            logger.debug(
                "agent_bridge_disabled trace_id=%s; staying local",
                trace_id,
            )
            return await self._run_local_fallback(
                contract.task, local_fallback, trace_id, reason="bridge_disabled"
            )

        # ── 3. Deduplication ───────────────────────────────────────────────
        if dedup_key in self._dedup_cache:
            self.metrics.dedup_hit_count += 1
            logger.info(
                "agent_bridge_dedup_hit trace_id=%s dedup_key=%s",
                trace_id,
                dedup_key,
            )
            return self._dedup_cache[dedup_key]

        # ── 4. Runtime call ────────────────────────────────────────────────
        self.metrics.handoff_attempts += 1
        gm.inc("bridge_handoff_total")
        t_start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                self._call_runtime(contract),
                timeout=self._config.timeout,
            )
            elapsed = time.monotonic() - t_start
            elapsed_ms = elapsed * 1000
            self.metrics.record_latency(elapsed)
            self.metrics.handoff_success += 1
            gm.bridge_latency_ms.observe(elapsed_ms)
            gm.inc("bridge_handoff_success")
            result.setdefault("trace_id", trace_id)
            result["bridge_source"] = "runtime"
            emit_gateway_log(
                "bridge_handoff_ok",
                trace_ctx=trace_ctx,
                latency_ms=round(elapsed_ms, 1),
                capability=contract.capability,
                exec_mode=contract.exec_mode,
                route_mode=contract.route_mode,
            )
            logger.info(
                "agent_bridge_handoff_ok trace_id=%s latency_ms=%.1f",
                trace_id,
                elapsed_ms,
            )
        except (asyncio.TimeoutError, OSError, RuntimeError) as exc:
            elapsed = time.monotonic() - t_start
            elapsed_ms = elapsed * 1000
            self.metrics.record_latency(elapsed)
            self.metrics.handoff_failure += 1
            gm.bridge_latency_ms.observe(elapsed_ms)
            gm.inc("bridge_handoff_failure")
            emit_gateway_log(
                "bridge_handoff_failed",
                trace_ctx=trace_ctx,
                level="warning",
                cause=str(exc),
                latency_ms=round(elapsed_ms, 1),
                capability=contract.capability,
                exec_mode=contract.exec_mode,
                route_mode=contract.route_mode,
            )
            logger.warning(
                "agent_bridge_handoff_failed trace_id=%s error=%s latency_ms=%.1f; falling back",
                trace_id,
                exc,
                elapsed_ms,
            )
            result = await self._run_local_fallback(
                contract.task, local_fallback, trace_id, reason=str(exc)
            )

        # ── 5. Cache and return ────────────────────────────────────────────
        # PR-2: cache by dedup_key (task_id when envelope-sourced, trace_id otherwise).
        self._cache_result(dedup_key, result)
        # PR-31: attach compact Handoff Envelope v2 summary additively (does not
        # affect any existing result field; safe to drop if import fails).
        try:
            from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
            hev2 = from_legacy_handoff_contract(contract)
            result.setdefault("handoff_envelope_v2", hev2.to_compact_summary())
        except Exception:  # noqa: BLE001
            pass
        return result

    async def handoff_from_envelope(
        self,
        envelope: Any,
        *,
        capability: str = "",
        exec_mode: str = "both",
        session: Optional[Dict[str, Any]] = None,
        callback_channel: str = "ws",
        local_fallback: Optional[LocalFallback] = None,
    ) -> Dict[str, Any]:
        """PR-2 primary entry point: delegate a TaskEnvelope to the agent runtime.

        Constructs a :class:`HandoffContract` from *envelope* and calls
        :meth:`handoff`.  This is the preferred path for all new code that
        already holds a :class:`~core.schemas.task_envelope.TaskEnvelope`.

        Legacy callers that build :class:`HandoffContract` manually are
        unaffected — they can continue to use :meth:`handoff` directly.

        Parameters
        ----------
        envelope:
            A :class:`~core.schemas.task_envelope.TaskEnvelope`.
        capability:
            Primary capability required by the task.
        exec_mode:
            "local" | "remote" | "both" (default "both").
        session:
            Session context forwarded to the runtime.
        callback_channel:
            Preferred response channel: "ws" | "webrtc" | "nats".
        local_fallback:
            Fallback coroutine; forwarded to :meth:`handoff`.
        """
        contract = handoff_contract_from_envelope(
            envelope,
            capability=capability,
            exec_mode=exec_mode,
            session=session or {},
            callback_channel=callback_channel,
        )
        return await self.handoff(contract=contract, local_fallback=local_fallback)

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of the current bridge metrics."""
        return self.metrics.snapshot()

    def build_envelope_v2(
        self,
        contract: HandoffContract,
        *,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        source_runtime_id: Optional[str] = None,
        target_runtime_id: Optional[str] = None,
        handoff_policy: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """PR-31: Build a Handoff Envelope v2 from a legacy :class:`HandoffContract`.

        This is the bridge-level helper for callers that want to emit a full
        v2 envelope without performing a runtime handoff.  Returns a
        :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` when the
        contracts package is importable, or ``None`` if not available.

        Parameters
        ----------
        contract:
            The populated legacy bridge contract.
        source_device_id:
            Optional source device identifier to embed in the v2 envelope.
        target_device_id:
            Optional target device identifier to embed in the v2 envelope.
        source_runtime_id:
            Optional source runtime instance identifier.
        target_runtime_id:
            Optional target runtime instance identifier.
        handoff_policy:
            Serialised governance policy dict.
        metadata:
            Arbitrary extra metadata.

        Returns
        -------
        HandoffEnvelopeV2 | None
        """
        try:
            from contracts.handoff_envelope_v2 import from_legacy_handoff_contract, HandoffEnvelopeV2
            envelope: HandoffEnvelopeV2 = from_legacy_handoff_contract(contract)
            if source_device_id:
                envelope = envelope.model_copy(
                    update={
                        "source_device_id": source_device_id,
                        "source": envelope.source.model_copy(update={"device_id": source_device_id}),
                    }
                )
            if target_device_id:
                envelope = envelope.model_copy(
                    update={
                        "target_device_id": target_device_id,
                        "target": envelope.target.model_copy(update={"device_id": target_device_id}),
                    }
                )
            if source_runtime_id:
                envelope = envelope.model_copy(
                    update={
                        "source_runtime_id": source_runtime_id,
                        "source": envelope.source.model_copy(update={"runtime_id": source_runtime_id}),
                    }
                )
            if target_runtime_id:
                envelope = envelope.model_copy(
                    update={
                        "target_runtime_id": target_runtime_id,
                        "target": envelope.target.model_copy(update={"runtime_id": target_runtime_id}),
                    }
                )
            if handoff_policy:
                envelope = envelope.model_copy(update={"handoff_policy": handoff_policy})
            if metadata:
                envelope = envelope.model_copy(update={"metadata": metadata})
            # PR-3: propagate source_runtime_posture from HandoffContract into v2
            # envelope so the canonical envelope always reflects the originating
            # posture (NO_POSTURE_SILENT_DROP_POLICY).
            _contract_posture = getattr(contract, "source_runtime_posture", "control_only") or "control_only"
            if _contract_posture != envelope.source_runtime_posture:
                envelope = envelope.model_copy(
                    update={
                        "source_runtime_posture": _contract_posture,
                        "source": envelope.source.model_copy(
                            update={"source_runtime_posture": _contract_posture}
                        ),
                    }
                )
            return envelope
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_runtime(self, contract: HandoffContract) -> Dict[str, Any]:
        """POST the handoff contract to the configured runtime endpoint.

        Uses ``httpx.AsyncClient`` when available; falls back to
        ``urllib.request`` (sync, wrapped in executor) so the bridge works
        even if *httpx* is not installed.

        Raises
        ------
        OSError
            When the runtime is unreachable (connection refused, DNS failure).
        RuntimeError
            When the runtime returns a non-2xx response.
        """
        base_url = self._config.runtime_url.rstrip("/")
        # Validate that only http/https schemes are used (SSRF prevention).
        import urllib.parse as _urlparse
        parsed = _urlparse.urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise RuntimeError(
                f"Refusing runtime URL with non-HTTP scheme: {parsed.scheme!r}"
            )
        url = f"{base_url}/handoff"
        payload = contract.to_dict()

        try:
            import httpx  # type: ignore

            async with httpx.AsyncClient(timeout=self._config.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"runtime returned HTTP {resp.status_code}"
                    )
                return resp.json()
        except ImportError:
            # httpx not available — fall back to sync urllib in thread
            import json as _json
            import urllib.request as _urllib

            def _sync_post() -> Dict[str, Any]:
                data = _json.dumps(payload).encode()
                req = _urllib.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with _urllib.urlopen(req, timeout=self._config.timeout) as resp:  # noqa: S310
                    return _json.loads(resp.read())

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _sync_post)

    async def _run_local_fallback(
        self,
        task: Dict[str, Any],
        local_fallback: Optional[LocalFallback],
        trace_id: str,
        *,
        reason: str = "unknown",
    ) -> Dict[str, Any]:
        """Invoke *local_fallback* and tag the result with bridge metadata."""
        self.metrics.fallback_count += 1
        gm = get_gateway_metrics()
        gm.inc("bridge_fallback_total")
        trace_ctx = TraceContext(trace_id=trace_id, span_id=str(uuid.uuid4()))
        emit_gateway_log(
            "bridge_fallback",
            trace_ctx=trace_ctx,
            reason=reason,
        )
        logger.info(
            "agent_bridge_fallback trace_id=%s reason=%s",
            trace_id,
            reason,
        )
        if local_fallback is not None:
            try:
                result = await local_fallback(task)
                result.setdefault("trace_id", trace_id)
                result["bridge_source"] = "local_fallback"
                return result
            except Exception as exc:
                logger.error(
                    "agent_bridge_fallback_error trace_id=%s error=%s",
                    trace_id,
                    exc,
                )
        return {
            "success": False,
            "error": "agent_runtime_unavailable",
            "message": f"Agent runtime unavailable and no local fallback ({reason})",
            "trace_id": trace_id,
            "bridge_source": "local_fallback",
        }

    def _cache_result(self, trace_id: str, result: Dict[str, Any]) -> None:
        """Insert into bounded LRU dedup cache, evicting oldest on overflow."""
        if trace_id in self._dedup_cache:
            self._dedup_cache.move_to_end(trace_id)
        else:
            self._dedup_cache[trace_id] = result
            if len(self._dedup_cache) > _DEDUP_CACHE_MAX_SIZE:
                self._dedup_cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge_instance: Optional[AgentBridge] = None


def get_agent_bridge() -> AgentBridge:
    """Return the process-level :class:`AgentBridge` singleton.

    Config is read from environment variables at first call.  In tests,
    replace the singleton with a pre-configured instance::

        from galaxy_gateway.agent_bridge import get_agent_bridge, AgentBridge, AgentBridgeConfig
        import galaxy_gateway.agent_bridge as ab
        ab._bridge_instance = AgentBridge(AgentBridgeConfig(runtime_url="...", timeout=1.0))
    """
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = AgentBridge()
    return _bridge_instance


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def handoff_contract_from_envelope(
    envelope: Any,
    *,
    capability: str = "",
    exec_mode: str = "both",
    session: Optional[Dict[str, Any]] = None,
    callback_channel: str = "ws",
) -> "HandoffContract":
    """Build a :class:`HandoffContract` from a TaskEnvelope (PR-1 helper).

    Extracts ``trace_id``, ``task_id``, ``route_mode``, and the task payload
    from the envelope so that bridge callers that already hold a TaskEnvelope
    don't need to unpack it manually.  Legacy callers that build
    HandoffContract directly are unaffected.

    PR-3 (post-533 dual-repo unification): also extracts
    ``source_runtime_posture`` from the envelope's ``metadata`` dict so that
    posture flows through the entire handoff pipeline without silent reset
    (NO_POSTURE_SILENT_DROP_POLICY).

    Args:
        envelope:         A :class:`~core.schemas.task_envelope.TaskEnvelope`.
        capability:       Primary capability required by the task.
        exec_mode:        Execution mode: "local" | "remote" | "both".
        session:          Session context forwarded to the runtime.
        callback_channel: Preferred response channel: "ws" | "webrtc" | "nats".

    Returns:
        A fully populated :class:`HandoffContract`.
    """
    _meta: Dict[str, Any] = {}
    if hasattr(envelope, "metadata") and isinstance(envelope.metadata, dict):
        _meta = envelope.metadata
    route_mode = _meta.get("route_mode", "direct")
    # PR-3: extract source_runtime_posture from envelope metadata (preserves posture).
    _posture_raw = _meta.get("source_runtime_posture", "control_only") or "control_only"
    _posture = _posture_raw if _posture_raw in ("control_only", "join_runtime") else "control_only"
    task_payload: Dict[str, Any] = {
        "task_id": envelope.task_id,
        "tool_name": envelope.tool_name,
        "args": envelope.args,
        "targets": envelope.targets,
        "source": envelope.source,
    }
    return HandoffContract(
        trace_id=envelope.trace_id,
        task_id=envelope.task_id,
        task=task_payload,
        capability=capability,
        exec_mode=exec_mode,
        route_mode=route_mode,
        session=session or {},
        callback_channel=callback_channel,
        source_runtime_posture=_posture,
    )


__all__ = [
    "AgentBridge",
    "AgentBridgeConfig",
    "AgentBridgeMetrics",
    "HandoffContract",
    "LocalFallback",
    "get_agent_bridge",
    "handoff_contract_from_envelope",
    # PR-3 canonicalization sentinels
    "CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE",
    "HANDOFF_CONTRACT_IS_POSTURE_AWARE",
    "HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE",
    "NO_POSTURE_SILENT_DROP_POLICY",
]
