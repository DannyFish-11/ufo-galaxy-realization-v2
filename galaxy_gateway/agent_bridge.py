"""
Agent Bridge — Runtime Handoff Layer (Round 5)
===============================================

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
    """

    trace_id: str
    task: Dict[str, Any]
    capability: str = ""
    exec_mode: str = "both"
    route_mode: str = "direct"
    session: Dict[str, Any] = field(default_factory=dict)
    callback_channel: str = "ws"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "task": self.task,
            "capability": self.capability,
            "exec_mode": self.exec_mode,
            "route_mode": self.route_mode,
            "session": self.session,
            "callback_channel": self.callback_channel,
        }


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
        3. Deduplicate by ``trace_id``; return cached result on hit.
        4. Call runtime; on timeout / error fall back to *local_fallback*.
        5. Cache successful result; update metrics; return result.

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
        if trace_id in self._dedup_cache:
            self.metrics.dedup_hit_count += 1
            logger.info(
                "agent_bridge_dedup_hit trace_id=%s",
                trace_id,
            )
            return self._dedup_cache[trace_id]

        # ── 4. Runtime call ────────────────────────────────────────────────
        self.metrics.handoff_attempts += 1
        t_start = time.monotonic()

        try:
            result = await asyncio.wait_for(
                self._call_runtime(contract),
                timeout=self._config.timeout,
            )
            elapsed = time.monotonic() - t_start
            self.metrics.record_latency(elapsed)
            self.metrics.handoff_success += 1
            result.setdefault("trace_id", trace_id)
            result["bridge_source"] = "runtime"
            logger.info(
                "agent_bridge_handoff_ok trace_id=%s latency_ms=%.1f",
                trace_id,
                elapsed * 1000,
            )
        except (asyncio.TimeoutError, OSError, RuntimeError) as exc:
            elapsed = time.monotonic() - t_start
            self.metrics.record_latency(elapsed)
            self.metrics.handoff_failure += 1
            logger.warning(
                "agent_bridge_handoff_failed trace_id=%s error=%s latency_ms=%.1f; falling back",
                trace_id,
                exc,
                elapsed * 1000,
            )
            result = await self._run_local_fallback(
                contract.task, local_fallback, trace_id, reason=str(exc)
            )

        # ── 5. Cache and return ────────────────────────────────────────────
        self._cache_result(trace_id, result)
        return result

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of the current bridge metrics."""
        return self.metrics.snapshot()

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

__all__ = [
    "AgentBridge",
    "AgentBridgeConfig",
    "AgentBridgeMetrics",
    "HandoffContract",
    "LocalFallback",
    "get_agent_bridge",
]
