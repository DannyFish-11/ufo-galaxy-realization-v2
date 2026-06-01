"""core/skill_registry.py
=========================
Unified Skill Registry (PR-4)

All Skill and MCP tool capabilities are registered here.  Every invocation
flows through :meth:`SkillRegistry.invoke`, which:

  1. Looks up the registered handler (skill / MCP tool).
  2. Validates the :class:`~core.skill_contract.SkillRequest` against the
     contract.
  3. Enforces permission checks via
     :mod:`core.tool_permissions`.
  4. Calls the handler with the supplied inputs.
  5. Wraps the result in a :class:`~core.skill_contract.SkillResponse`.
  6. Emits a structured observability log entry for every call.

Usage
-----
::

    from core.skill_registry import get_skill_registry

    registry = get_skill_registry()

    # Register a skill (normally done once at startup / load time)
    registry.register_skill(
        name="echo",
        handler=lambda **kw: kw,
        metadata={"description": "Echo inputs back"},
    )

    # Invoke via the contract
    from core.skill_contract import SkillRequest
    resp = await registry.invoke(SkillRequest(skill_name="echo", inputs={"msg": "hi"}))
    print(resp.outputs)  # {'msg': 'hi'}
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.skill_contract import (
    SkillErrorCode,
    SkillMetrics,
    SkillRequest,
    SkillResponse,
    validate_skill_request,
)

logger = logging.getLogger("Galaxy.SkillRegistry")


# ---------------------------------------------------------------------------
# Skill metadata
# ---------------------------------------------------------------------------


@dataclass
class SkillEntry:
    """Registry entry for a single skill or MCP-wrapped tool.

    Attributes:
        name: Unique skill name used to look up the entry.
        handler: Async (or sync) callable that executes the skill.
            It receives the ``inputs`` dict unpacked as keyword arguments.
        description: Human-readable summary.
        tags: Free-form classification labels.
        version: Semantic version string.
        source: Where this entry came from (e.g. ``"skill_loader"``,
            ``"mcp_server:filesystem"``).
        permission_tool_name: Tool name forwarded to the permission checker.
            Defaults to *name* when not set.
        metadata: Arbitrary extra metadata.
    """

    name: str
    handler: Callable[..., Any]
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    source: str = ""
    permission_tool_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.permission_tool_name:
            self.permission_tool_name = self.name

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary (for API list endpoints)."""
        return {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "version": self.version,
            "source": self.source,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Single registry for all Skill and MCP tool capabilities.

    Thread-safe for reads (dict lookup).  Registration is expected at
    startup / load time, not under concurrent write pressure.
    """

    def __init__(self) -> None:
        self._skills: Dict[str, SkillEntry] = {}
        # Lazily initialised – avoids circular import at module load time.
        self._permission_checker = None
        logger.info("SkillRegistry initialised")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_skill(
        self,
        name: str,
        handler: Callable[..., Any],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        description: str = "",
        tags: Optional[List[str]] = None,
        version: str = "1.0.0",
        source: str = "",
        permission_tool_name: str = "",
    ) -> SkillEntry:
        """Register a skill handler under *name*.

        If *name* is already registered the entry is **replaced** and a
        warning is logged.

        Args:
            name: Unique skill identifier.
            handler: Async or sync callable that receives the ``inputs``
                dict as keyword arguments.
            metadata: Arbitrary extra metadata dictionary.
            description: Human-readable summary.
            tags: Classification labels.
            version: Semantic version string.
            source: Origin label (e.g. ``"skill_loader"``).
            permission_tool_name: Override for the tool name forwarded to
                :mod:`core.tool_permissions`.

        Returns:
            The newly created :class:`SkillEntry`.
        """
        if name in self._skills:
            logger.warning("SkillRegistry: overwriting existing skill '%s'", name)

        entry = SkillEntry(
            name=name,
            handler=handler,
            description=description,
            tags=list(tags or []),
            version=version,
            source=source,
            permission_tool_name=permission_tool_name or name,
            metadata=dict(metadata or {}),
        )
        self._skills[name] = entry
        logger.debug("SkillRegistry: registered skill '%s' (source=%s)", name, source)
        return entry

    def unregister_skill(self, name: str) -> bool:
        """Remove a skill from the registry.

        Args:
            name: Skill name to remove.

        Returns:
            ``True`` if the skill existed and was removed.
        """
        if name in self._skills:
            del self._skills[name]
            logger.debug("SkillRegistry: unregistered skill '%s'", name)
            return True
        return False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_skill(self, name: str) -> Optional[SkillEntry]:
        """Return the :class:`SkillEntry` for *name*, or ``None``."""
        return self._skills.get(name)

    def list_skills(self) -> List[Dict[str, Any]]:
        """Return serialised metadata for all registered skills."""
        return [entry.to_dict() for entry in self._skills.values()]

    def has_skill(self, name: str) -> bool:
        """Return ``True`` if *name* is registered."""
        return name in self._skills

    def skill_count(self) -> int:
        """Return the number of registered skills."""
        return len(self._skills)

    # ------------------------------------------------------------------
    # Permission helper
    # ------------------------------------------------------------------

    def _get_permission_checker(self):
        """Lazily load the global permission checker."""
        if self._permission_checker is None:
            try:
                from core.tool_permissions import get_tool_permission_checker
                self._permission_checker = get_tool_permission_checker()
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "SkillRegistry: could not load tool_permissions (%s); "
                    "permission checks will be skipped",
                    exc,
                )
        return self._permission_checker

    def _check_permission(
        self,
        entry: SkillEntry,
        req: SkillRequest,
    ) -> Optional[SkillResponse]:
        """Run permission check.

        Returns a failure :class:`SkillResponse` if the call is denied,
        otherwise ``None``.
        """
        checker = self._get_permission_checker()
        if checker is None:
            return None

        try:
            result = checker.check(
                tool_name=entry.permission_tool_name,
                session_id=req.runtime_session_id,
                device_id=req.device_id,
            )
        except Exception as exc:
            logger.debug(
                "SkillRegistry: permission check raised an exception (%s); "
                "allowing by default",
                exc,
            )
            return None

        if not result.allowed:
            logger.warning(
                "SkillRegistry: permission denied for '%s' — %s",
                entry.name,
                result.reason,
            )
            return SkillResponse.failure(
                skill_name=req.skill_name,
                trace_id=req.trace_id,
                code=SkillErrorCode.PERMISSION_DENIED,
                message=f"Permission denied: {result.reason}",
            )

        if getattr(result, "requires_confirmation", False):
            logger.info(
                "SkillRegistry: '%s' requires user confirmation (risk=%s)",
                entry.name,
                getattr(result, "risk_level", "unknown"),
            )
            return SkillResponse.failure(
                skill_name=req.skill_name,
                trace_id=req.trace_id,
                code=SkillErrorCode.PERMISSION_DENIED,
                message=(
                    f"User confirmation required for '{entry.name}' "
                    f"(risk_level={getattr(result, 'risk_level', 'unknown')})"
                ),
                details={"requires_confirmation": True, "risk_level": getattr(result, "risk_level", "")},
            )

        return None

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    async def invoke(self, req: SkillRequest) -> SkillResponse:
        """Invoke a skill via the unified contract.

        Pipeline:
          1. Validate *req* against :func:`~core.skill_contract.validate_skill_request`.
          2. Look up the skill in the registry.
          3. Check permissions.
          4. Call the handler (async or sync).
          5. Wrap the result in a :class:`SkillResponse`.
          6. Emit a structured observability log.

        Args:
            req: The :class:`SkillRequest` describing the invocation.

        Returns:
            A :class:`SkillResponse` – **never raises**.
        """
        metrics = SkillMetrics(started_at=time.time())

        # 1. Contract validation -----------------------------------------
        try:
            validate_skill_request(req)
        except ValueError as exc:
            metrics.finish()
            resp = SkillResponse.failure(
                skill_name=req.skill_name or "<unknown>",
                trace_id=req.trace_id,
                code=SkillErrorCode.INVALID_INPUT,
                message=str(exc),
                metrics=metrics,
            )
            self._emit_log(req, resp)
            return resp

        # 2. Skill lookup ------------------------------------------------
        entry = self._skills.get(req.skill_name)
        if entry is None:
            metrics.finish()
            resp = SkillResponse.failure(
                skill_name=req.skill_name,
                trace_id=req.trace_id,
                code=SkillErrorCode.NOT_FOUND,
                message=f"Skill '{req.skill_name}' is not registered",
                metrics=metrics,
            )
            self._emit_log(req, resp)
            return resp

        # 3. Permission check --------------------------------------------
        denied = self._check_permission(entry, req)
        if denied is not None:
            denied.metrics = metrics
            metrics.finish()
            self._emit_log(req, denied)
            return denied

        # 4. Handler execution ------------------------------------------
        metrics.executor = entry.source or "skill_registry"
        try:
            if inspect.iscoroutinefunction(entry.handler):
                timeout = req.timeout_s
                if timeout is not None:
                    raw_result = await asyncio.wait_for(
                        entry.handler(**req.inputs), timeout=timeout
                    )
                else:
                    raw_result = await entry.handler(**req.inputs)
            else:
                # Sync handler – run in executor to avoid blocking the loop
                loop = asyncio.get_running_loop()
                timeout = req.timeout_s

                def _call() -> Any:
                    return entry.handler(**req.inputs)

                if timeout is not None:
                    raw_result = await asyncio.wait_for(
                        loop.run_in_executor(None, _call), timeout=timeout
                    )
                else:
                    raw_result = await loop.run_in_executor(None, _call)

        except asyncio.TimeoutError:
            metrics.finish()
            resp = SkillResponse.failure(
                skill_name=req.skill_name,
                trace_id=req.trace_id,
                code=SkillErrorCode.TIMEOUT,
                message=f"Skill '{req.skill_name}' timed out after {req.timeout_s}s",
                metrics=metrics,
            )
            self._emit_log(req, resp)
            return resp

        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "SkillRegistry: unhandled exception in handler for '%s'",
                req.skill_name,
                exc_info=True,
            )
            metrics.finish()
            resp = SkillResponse.failure(
                skill_name=req.skill_name,
                trace_id=req.trace_id,
                code=SkillErrorCode.EXECUTION_ERROR,
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                metrics=metrics,
            )
            self._emit_log(req, resp)
            return resp

        # 5. Wrap success -----------------------------------------------
        metrics.finish()
        resp = SkillResponse.success(
            skill_name=req.skill_name,
            trace_id=req.trace_id,
            outputs=raw_result,
            metrics=metrics,
        )
        self._emit_log(req, resp)
        return resp

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def _emit_log(self, req: SkillRequest, resp: SkillResponse) -> None:
        """Emit a structured log entry for every skill call.

        The log record includes all fields required by the observability
        specification:

        * ``skill_name``
        * ``trace_id``
        * ``runtime_session_id``
        * ``device_id`` / ``executor``
        * ``status`` and ``duration_ms``
        """
        status = resp.status.value
        duration_ms = round(resp.metrics.duration_ms, 3)
        executor = resp.metrics.executor
        err_code = resp.first_error.code.value if resp.first_error else ""

        log_level = logging.INFO if resp.ok else logging.WARNING
        logger.log(
            log_level,
            "[skill_call] skill=%s status=%s duration_ms=%.3f trace_id=%s "
            "session=%s device=%s executor=%s error_code=%s",
            req.skill_name,
            status,
            duration_ms,
            req.trace_id,
            req.runtime_session_id,
            req.device_id,
            executor,
            err_code,
        )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_registry_instance: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Return the global :class:`SkillRegistry` singleton.

    The instance is created on first call and reused thereafter.
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = SkillRegistry()
    return _registry_instance


def reset_skill_registry() -> None:
    """Reset the global singleton (intended for tests only)."""
    global _registry_instance
    _registry_instance = None
