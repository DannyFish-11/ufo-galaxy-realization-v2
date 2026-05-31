#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capabilities/canonical_dispatcher.py
==========================================
Canonical Capability Dispatcher — PR-001.

This module implements the single canonical execution path for all
tool/capability invocations inside OpenClawd.  It is *not* an authority
center: it owns no routing decisions, no shell state, and no source
registry.  Its only job is to normalize the invocation contract and route
each call to the correct backend adapter.

Authority chain reminder
------------------------
  DesktopPresenceRuntime  — runtime shell
  OpenClawd               — subject decision authority  (owns this dispatcher)
  AgentKernel             — cognition/planning layer
  CanonicalDispatcher     — execution-capability dispatch layer  (this file)
  CommandRouter / DecisionExecutor — manifestation substrate(s)

Supported capability naming patterns
--------------------------------------
  mcp__<server_id>__<tool_name>    — MCP server tool
  mcp__gateway__<tool_name>        — MCP gateway built-in tool
  skill__<skill_id>                — Skill
  node__<node_id>__<action>        — Node capability/action
  github__<action>                 — GitHub addon tool (install/uninstall/list)

Any other prefix is returned as an error with layer=UNKNOWN so that
callers have a stable, predictable contract even for future prefixes.

DispatchResult contract
-----------------------
All public dispatch methods return a :class:`DispatchResult` that can be
serialised to a plain ``dict`` via :meth:`DispatchResult.to_dict`.  This
normalises the latency, layer, and error fields across all backends.

Usage
-----
::

    from core.capabilities import CanonicalDispatcher, DispatchResult

    dispatcher = CanonicalDispatcher(
        device_id="desktop-01",
        session_id="sess-abc",
        trace_id="trace-xyz",
    )
    result: DispatchResult = await dispatcher.dispatch("skill__hello", {})
    print(result.success, result.result)
    # Also available as plain dict:
    print(result.to_dict())
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.CanonicalDispatcher")

# ---------------------------------------------------------------------------
# PR-530: Spine observability hardening sentinel
# ---------------------------------------------------------------------------

#: Confirms that :class:`CanonicalDispatcher` propagates ``trace_id`` and
#: ``request_id`` into every :class:`DispatchResult` so the execution spine
#: (OpenClawd → CanonicalDispatcher → backend) is fully correlated.
#: Also confirms that ``DispatchResult.to_dict()`` exposes those fields so
#: downstream consumers can surface them without importing this module.
CANONICAL_DISPATCHER_SPINE_HARDENED: str = (
    "CANONICAL_DISPATCHER_SPINE_HARDENED_V1: "
    "DispatchResult carries trace_id + request_id; "
    "CanonicalDispatcher propagates both from call-site into result; "
    "to_dict() exposes both fields for downstream observability."
)

# ---------------------------------------------------------------------------
# Capability layer classification
# ---------------------------------------------------------------------------

class CapabilityLayer(str, Enum):
    """Classification of a capability invocation by its naming prefix."""

    MCP = "mcp"            # mcp__<server>__<tool>
    MCP_GW = "mcp_gw"      # mcp__gateway__<tool>
    SKILL = "skill"        # skill__<id>
    NODE = "node"          # node__<id>__<action>
    DEVICE = "device"      # device__<device_id>__<action>
    GITHUB = "github"      # github__<action>
    UNKNOWN = "unknown"    # unrecognised prefix

    @classmethod
    def classify(cls, tool_name: str) -> "CapabilityLayer":
        """Return the CapabilityLayer for *tool_name* based on its prefix."""
        if tool_name.startswith("mcp__gateway__"):
            return cls.MCP_GW
        if tool_name.startswith("mcp__"):
            return cls.MCP
        if tool_name.startswith("skill__"):
            return cls.SKILL
        if tool_name.startswith("node__"):
            return cls.NODE
        if tool_name.startswith("device__"):
            return cls.DEVICE
        if tool_name.startswith("github__"):
            return cls.GITHUB
        return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Normalized dispatch result
# ---------------------------------------------------------------------------

@dataclass
class DispatchResult:
    """Normalized result returned by :class:`CanonicalDispatcher`.

    Fields are a superset of the legacy ``{"success": bool, ...}`` dict so
    that existing consumers can continue to read ``result.success`` /
    ``result.error`` without changes.
    """

    # Core result fields (backward-compatible with legacy dict keys)
    success: bool = True
    result: Any = None
    error: Optional[str] = None

    # Capability metadata
    tool_name: str = ""
    layer: CapabilityLayer = CapabilityLayer.UNKNOWN
    arguments: Dict[str, Any] = field(default_factory=dict)

    # Execution metadata
    latency_ms: float = 0.0
    dispatch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dispatched_at: float = field(default_factory=time.time)

    # Optional pass-through fields from legacy paths
    needs_confirmation: bool = False

    # PR-530: spine-observability correlation fields.
    # ``trace_id`` links this dispatch result back to the originating request
    # that entered OpenClawd (same value as OpenClawd._current_trace_id /
    # runtime_session_id when routed through DesktopPresenceRuntime).
    # ``request_id`` is the per-call dispatch identifier (defaults to
    # dispatch_id for backward compat, but may be overridden with the
    # outer request_id when available).
    trace_id: str = ""
    request_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable plain dict — backward-compatible with
        the legacy ``{"success": bool, "result": ..., "error": ...}`` shape.

        PR-530: ``trace_id`` and ``request_id`` are included so that every
        level of the execution spine (OpenClawd → CanonicalDispatcher →
        backend) surfaces the same correlation identifiers.
        """
        d: Dict[str, Any] = {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "tool_name": self.tool_name,
            "layer": self.layer.value,
            "latency_ms": round(self.latency_ms, 2),
            "dispatch_id": self.dispatch_id,
            "trace_id": self.trace_id,
            "request_id": self.request_id or self.dispatch_id,
        }
        if self.needs_confirmation:
            d["needs_confirmation"] = True
        return d

    def as_legacy_dict(self) -> Dict[str, Any]:
        """Return minimal legacy dict (success / result / error / needs_confirmation)."""
        d: Dict[str, Any] = {"success": self.success}
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
        if self.needs_confirmation:
            d["needs_confirmation"] = True
            d["tool"] = self.tool_name
        return d


# ---------------------------------------------------------------------------
# Canonical dispatcher
# ---------------------------------------------------------------------------

class CanonicalDispatcher:
    """Single canonical execution path for capability/tool invocations.

    This dispatcher is owned by :class:`~core.openclawd.OpenClawd` and must
    not be used as a routing authority or a second decision center.

    Parameters
    ----------
    device_id:
        Optional device context forwarded to skill/MCP backends.
    session_id:
        Optional runtime session ID forwarded to skill/MCP backends.
    trace_id:
        Optional trace ID for observability.
    node_id_to_key:
        Shared mutable mapping ``{node_id: node_key}`` owned by OpenClawd for
        node lookups; ``None`` means node dispatch will always attempt a fresh
        registry lookup.
    tool_permission_checker:
        Optional permission checker (same interface expected by
        ``OpenClawd._tool_permission_checker``).  When provided, every call is
        checked before dispatch.
    """

    def __init__(
        self,
        *,
        device_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        node_id_to_key: Optional[Dict[str, str]] = None,
        tool_permission_checker: Any = None,
    ) -> None:
        self.device_id = device_id
        self.session_id = session_id
        self.trace_id = trace_id
        self._node_id_to_key: Dict[str, str] = node_id_to_key if node_id_to_key is not None else {}
        self._tool_permission_checker = tool_permission_checker

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        # optional per-call overrides
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> DispatchResult:
        """Dispatch a capability invocation and return a :class:`DispatchResult`.

        Parameters
        ----------
        tool_name:
            Canonical tool name in one of the supported patterns.
        arguments:
            Tool arguments dict.
        device_id / session_id / trace_id:
            Per-call context overrides; fall back to instance defaults when
            ``None``.
        """
        _device_id = device_id if device_id is not None else self.device_id
        _session_id = session_id if session_id is not None else self.session_id
        _trace_id = trace_id if trace_id is not None else self.trace_id

        layer = CapabilityLayer.classify(tool_name)
        t0 = time.time()

        # --- permission check ------------------------------------------------
        perm_result = self._check_permission(tool_name, _session_id, _device_id)
        if perm_result is not None:
            return perm_result

        # --- emit pre-dispatch observability event ---------------------------
        self._emit_invoked_event(tool_name, _trace_id, _session_id)

        # --- route to backend ------------------------------------------------
        try:
            if layer in (CapabilityLayer.MCP, CapabilityLayer.MCP_GW):
                result = await self._dispatch_mcp(
                    tool_name, arguments, _device_id, _session_id
                )
            elif layer == CapabilityLayer.SKILL:
                result = await self._dispatch_skill(
                    tool_name, arguments, _device_id, _session_id
                )
            elif layer == CapabilityLayer.NODE:
                result = await self._dispatch_node(tool_name, arguments)
            elif layer == CapabilityLayer.DEVICE:
                result = await self._dispatch_device(tool_name, arguments)
            elif layer == CapabilityLayer.GITHUB:
                result = await self._dispatch_github(tool_name, arguments)
            else:
                result = DispatchResult(
                    success=False,
                    error=f"未知工具前缀: {tool_name}",
                    tool_name=tool_name,
                    layer=layer,
                    arguments=arguments,
                )

        except Exception as exc:
            logger.warning("CanonicalDispatcher: 工具执行失败 [%s]: %s", tool_name, exc)
            self._emit_failed_event(tool_name, str(exc), _trace_id, _session_id)
            result = DispatchResult(
                success=False,
                error=str(exc),
                tool_name=tool_name,
                layer=layer,
                arguments=arguments,
            )

        result.tool_name = tool_name
        result.layer = layer
        result.arguments = arguments
        result.latency_ms = (time.time() - t0) * 1000
        # PR-530: stamp spine-observability correlation fields on every result.
        result.trace_id = _trace_id
        result.request_id = _trace_id or result.dispatch_id
        return result

    # ------------------------------------------------------------------
    # Permission guard
    # ------------------------------------------------------------------

    def _check_permission(
        self,
        tool_name: str,
        session_id: str,
        device_id: str,
    ) -> Optional[DispatchResult]:
        """Return a failed :class:`DispatchResult` if permission is denied,
        or ``None`` when the call is allowed to proceed."""
        if not self._tool_permission_checker:
            return None
        try:
            check = self._tool_permission_checker.check(
                tool_name=tool_name,
                session_id=session_id,
                device_id=device_id,
            )
            if not check.allowed:
                logger.warning("CanonicalDispatcher: 工具调用被拒绝: %s — %s", tool_name, check.reason)
                return DispatchResult(
                    success=False,
                    error=f"权限拒绝: {check.reason}",
                    tool_name=tool_name,
                    layer=CapabilityLayer.classify(tool_name),
                )
            if getattr(check, "requires_confirmation", False):
                return DispatchResult(
                    success=False,
                    error=(
                        f"操作 [{tool_name}] 需要用户确认"
                        f"（风险等级: {getattr(check, 'risk_level', 'unknown')}）"
                    ),
                    needs_confirmation=True,
                    tool_name=tool_name,
                    layer=CapabilityLayer.classify(tool_name),
                )
        except Exception as exc:
            logger.debug("CanonicalDispatcher: 权限检查异常（放行）: %s", exc)
        return None

    # ------------------------------------------------------------------
    # MCP backend adapter
    # ------------------------------------------------------------------

    async def _dispatch_mcp(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        device_id: str,
        session_id: str,
    ) -> DispatchResult:
        """Route an ``mcp__*`` tool call to the correct MCP backend."""
        parts = tool_name.split("__", 2)
        if len(parts) < 3:
            return DispatchResult(
                success=False,
                error=f"无效 MCP 工具名: {tool_name}",
                tool_name=tool_name,
                layer=CapabilityLayer.classify(tool_name),
            )
        server_id, mcp_tool_name = parts[1], parts[2]

        from core.skill_contract import (
            SkillErrorCode,
            SkillMetrics,
            SkillRequest,
            SkillResponse,
        )
        from core.skill_registry import get_skill_registry

        req = SkillRequest(
            skill_name=tool_name,
            inputs=arguments,
            device_id=device_id,
            runtime_session_id=session_id,
            caller="canonical_dispatcher",
        )
        metrics = SkillMetrics(started_at=time.time(), executor=f"mcp:{server_id}")
        registry = get_skill_registry()

        # Gateway built-in tools
        if server_id == "gateway":
            try:
                from core.mcp_gateway import get_mcp_gateway
                gateway = get_mcp_gateway()
                raw = await gateway.execute_tool(mcp_tool_name, arguments)
                metrics.finish()
                registry._emit_log(req, SkillResponse.success(tool_name, req.trace_id, raw, metrics))
                return DispatchResult(success=True, result=raw)
            except Exception as exc:
                metrics.finish()
                registry._emit_log(
                    req,
                    SkillResponse.failure(
                        tool_name, req.trace_id, SkillErrorCode.EXECUTION_ERROR, str(exc), metrics=metrics
                    ),
                )
                return DispatchResult(success=False, error=f"Gateway 工具执行失败: {exc}")

        # Standard MCP server tools
        from core.mcp_loader import mcp_loader
        try:
            raw = await mcp_loader.call_tool(server_id, mcp_tool_name, arguments)
            metrics.finish()
            registry._emit_log(req, SkillResponse.success(tool_name, req.trace_id, raw, metrics))
            return DispatchResult(success=True, result=raw)
        except Exception as exc:
            metrics.finish()
            registry._emit_log(
                req,
                SkillResponse.failure(
                    tool_name, req.trace_id, SkillErrorCode.EXECUTION_ERROR, str(exc), metrics=metrics
                ),
            )
            raise

    # ------------------------------------------------------------------
    # Skill backend adapter
    # ------------------------------------------------------------------

    async def _dispatch_skill(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        device_id: str,
        session_id: str,
    ) -> DispatchResult:
        """Route a ``skill__*`` invocation through the canonical SkillRegistry."""
        skill_id = tool_name[len("skill__"):]

        from core.skill_contract import SkillRequest
        from core.skill_loader import skill_loader as _skill_loader
        from core.skill_registry import get_skill_registry

        registry = get_skill_registry()

        # Lazily register a loader-backed adapter for skills not yet in registry
        if not registry.has_skill(tool_name):
            def _make_adapter(_sid: str):
                async def _adapter(**kwargs: Any) -> Any:
                    return await _skill_loader.execute(_sid, **kwargs)
                return _adapter

            registry.register_skill(
                name=tool_name,
                handler=_make_adapter(skill_id),
                source="skill_loader_lazy",
                description=f"Adapter for skill_loader skill '{skill_id}'",
            )

        req = SkillRequest(
            skill_name=tool_name,
            inputs=arguments,
            device_id=device_id,
            runtime_session_id=session_id,
            caller="canonical_dispatcher",
        )
        resp = await registry.invoke(req)
        if resp.ok:
            return DispatchResult(success=True, result=resp.outputs)
        err = resp.first_error
        return DispatchResult(
            success=False,
            error=err.message if err else "Skill invocation failed",
        )

    # ------------------------------------------------------------------
    # Node backend adapter
    # ------------------------------------------------------------------

    async def _dispatch_node(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> DispatchResult:
        """Route a ``node__*`` invocation through the unified node executor."""
        parts = tool_name.split("__", 2)
        if len(parts) < 3:
            return DispatchResult(success=False, error=f"无效 Node 工具名: {tool_name}")
        node_id, action_name = parts[1], parts[2]

        node_key = self._find_node_key(node_id)
        if not node_key:
            return DispatchResult(success=False, error=f"节点 {node_id} 未在注册表中")

        from core.node_invocation import InvocationSource, invoke_node

        params = arguments.get("params", arguments)
        inv_result = await invoke_node(
            node_key,
            action_name,
            params if isinstance(params, dict) else {},
            invocation_source=InvocationSource.CAPABILITY,
        )
        if inv_result.success:
            return DispatchResult(success=True, result=inv_result.result)
        return DispatchResult(success=False, error=inv_result.error)

    def _find_node_key(self, node_id: str) -> Optional[str]:
        """Look up *node_id* in the in-memory cache then the registry file."""
        if node_id in self._node_id_to_key:
            return self._node_id_to_key[node_id]
        try:
            import json
            import os

            registry_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "config",
                "node_registry.json",
            )
            with open(registry_path, "r", encoding="utf-8") as fh:
                registry = json.load(fh)
            for key, info in registry.get("nodes", {}).items():
                if info.get("id") == node_id:
                    self._node_id_to_key[node_id] = key
                    return key
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # GitHub addon backend adapter
    # ------------------------------------------------------------------

    async def _dispatch_github(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> DispatchResult:
        """Route a ``github__*`` invocation to the GitHub installer service."""
        action = tool_name[len("github__"):]
        try:
            from core.github_installer import get_github_installer

            installer = get_github_installer()

            if action == "install":
                url = arguments.get("url", "")
                if not url:
                    return DispatchResult(
                        success=False,
                        error="github__install requires 'url' argument",
                    )
                raw = await installer.install(
                    url=url,
                    ref=arguments.get("ref"),
                    addon_type=arguments.get("type"),
                    dry_run=bool(arguments.get("dry_run", False)),
                )
                return DispatchResult(success=raw.get("success", False), result=raw)

            elif action == "uninstall":
                name = arguments.get("name", "")
                if not name:
                    return DispatchResult(
                        success=False,
                        error="github__uninstall requires 'name' argument",
                    )
                raw = await installer.uninstall(name)
                return DispatchResult(success=raw.get("success", False), result=raw)

            elif action == "list":
                raw = installer.list_installed()
                return DispatchResult(success=True, result=raw)

            elif action == "status":
                raw = installer.get_status()
                return DispatchResult(success=True, result=raw)

            else:
                return DispatchResult(
                    success=False,
                    error=(
                        f"Unknown github action: '{action}'. "
                        "Valid actions: install, uninstall, list, status."
                    ),
                )
        except Exception as exc:
            logger.warning("CanonicalDispatcher: github__%s failed: %s", action, exc)
            return DispatchResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Device backend adapter (PR-3)
    # ------------------------------------------------------------------

    async def _dispatch_device(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> DispatchResult:
        """Route a ``device__*`` invocation to the device communication layer.

        The canonical name format is ``device__<device_id>__<action>``.
        The call is forwarded to :mod:`core.device_communication` via the
        ``send_command`` path if the device is currently connected, or falls
        back to a structured error response if it is not.

        Parameters
        ----------
        tool_name:
            Canonical tool name (``device__<device_id>__<action>``).
        arguments:
            Arguments dict forwarded verbatim as the command payload.
        """
        parts = tool_name.split("__", 2)
        if len(parts) < 3:
            return DispatchResult(
                success=False,
                error=f"无效 Device 工具名: {tool_name} — 期望 device__<device_id>__<action>",
                tool_name=tool_name,
                layer=CapabilityLayer.DEVICE,
            )
        device_id, action = parts[1], parts[2]

        try:
            from core.device_communication import device_comm

            raw = await device_comm.send_command(device_id, action, arguments)
            return DispatchResult(success=True, result=raw)
        except Exception as exc:
            logger.warning(
                "CanonicalDispatcher: device__%s__%s failed: %s",
                device_id,
                action,
                exc,
            )
            return DispatchResult(
                success=False,
                error=f"设备 '{device_id}' 指令 '{action}' 执行失败: {exc}",
                tool_name=tool_name,
                layer=CapabilityLayer.DEVICE,
            )

    # ------------------------------------------------------------------
    # Capability bus catalog (PR-3)
    # ------------------------------------------------------------------

    def bus_catalog(self) -> Dict[str, Any]:
        """Return a snapshot of the :class:`~core.capability_bus.CapabilityBus`.

        This is a convenience accessor so that callers holding a
        :class:`CanonicalDispatcher` reference can inspect the capability
        universe without importing :mod:`core.capability_bus` directly.

        Returns
        -------
        dict
            The result of :meth:`~core.capability_bus.CapabilityBus.bus_snapshot`
            serialised via :meth:`~core.capability_bus.BusSnapshot.to_dict`.
            Returns ``{"error": ...}`` when the bus is not available.
        """
        try:
            from core.capability_bus import get_capability_bus

            return get_capability_bus().bus_snapshot().to_dict()
        except Exception as exc:
            logger.debug("CanonicalDispatcher.bus_catalog: %s", exc)
            return {"error": str(exc), "total_count": 0}

    # ------------------------------------------------------------------
    # Observability helpers
    # ------------------------------------------------------------------

    def _emit_invoked_event(
        self, tool_name: str, trace_id: str, session_id: str
    ) -> None:
        try:
            from core.state_event_bus import StateEventType, emit as _emit

            _emit(
                StateEventType.SKILL_INVOKED,
                source="canonical_dispatcher",
                payload={"tool_name": tool_name},
                trace_id=trace_id or None,
                runtime_session_id=session_id or None,
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    def _emit_failed_event(
        self, tool_name: str, error: str, trace_id: str, session_id: str
    ) -> None:
        try:
            from core.state_event_bus import StateEventType, emit as _emit

            _emit(
                StateEventType.SKILL_FAILED,
                source="canonical_dispatcher",
                payload={"tool_name": tool_name, "error": error},
                trace_id=trace_id or None,
                runtime_session_id=session_id or None,
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton factory
# ---------------------------------------------------------------------------

_DEFAULT_DISPATCHER: Optional[CanonicalDispatcher] = None


def get_canonical_dispatcher() -> CanonicalDispatcher:
    """Return the module-level default :class:`CanonicalDispatcher` instance.

    Most callers should obtain a contextual dispatcher from
    :class:`~core.openclawd.OpenClawd` rather than using this singleton
    directly.  This factory exists only to support unit tests and lightweight
    integrations that do not have an OpenClawd instance available.
    """
    global _DEFAULT_DISPATCHER
    if _DEFAULT_DISPATCHER is None:
        _DEFAULT_DISPATCHER = CanonicalDispatcher()
    return _DEFAULT_DISPATCHER
