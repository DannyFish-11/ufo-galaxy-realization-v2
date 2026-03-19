"""core.model_role_policy — Model Role Policy (PR-2)
=====================================================

Defines the explicit model role policy that enforces **OpenClawd** as the
sole primary decision authority in the Galaxy system.

Design
------
* **Primary authority**: OpenClawd — the only component allowed to make
  intent-level decisions, select models, and produce execution plans.
* **Orchestration / transport** (E2E, Gateway, TaskOrchestrator, HybridExecutor):
  these components receive a decision from OpenClawd and *execute* it.
  They must **not** re-interpret intent, re-rank plans, or replace the
  decision made by the primary authority.

Public surface
--------------
``ModelRole``          — enum of component roles.
``DecisionAuthority``  — enum of authority levels.
``ModelRolePolicy``    — central policy registry; check and guard helpers.
``get_policy``         — module-level singleton accessor.
``reset_policy``       — reset singleton (tests only).
``assert_primary``     — convenience guard; raises ``PolicyViolationError``
                         when called by a non-primary component.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger("Galaxy.ModelRolePolicy")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ModelRole(str, Enum):
    """Component roles in the Galaxy decision pipeline."""

    PRIMARY      = "primary"       # OpenClawd — sole decision authority
    ORCHESTRATOR = "orchestrator"  # E2E / Gateway — plan scheduling only
    EXECUTOR     = "executor"      # HybridExecutor / WindowsArbiter — action dispatch
    TRANSPORT    = "transport"     # WebSocket / relay — message delivery


class DecisionAuthority(str, Enum):
    """Levels of decision authority."""

    FULL    = "full"     # May perform primary intent resolution + model selection
    EXECUTE = "execute"  # May only execute a pre-formed decision
    RELAY   = "relay"    # May only forward messages unchanged


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PolicyViolationError(RuntimeError):
    """Raised when a non-primary component attempts a primary decision."""


# ---------------------------------------------------------------------------
# Policy registry
# ---------------------------------------------------------------------------

class ModelRolePolicy:
    """Central policy registry for component decision authority.

    Usage::

        from core.model_role_policy import get_policy

        policy = get_policy()

        # Verify that a component is allowed to make primary decisions.
        if not policy.may_decide(ModelRole.ORCHESTRATOR):
            raise PolicyViolationError(...)

        # Log the primary decision authority for a request.
        policy.log_primary_authority("openclawd", trace_id="abc123", model="gpt-4o")
    """

    # Roles permitted to perform full (primary) decision-making.
    _PRIMARY_ROLES: frozenset = frozenset({ModelRole.PRIMARY})

    def __init__(self) -> None:
        # Maps component names → their assigned role.
        self._component_roles: dict[str, ModelRole] = {
            "openclawd":          ModelRole.PRIMARY,
            "e2e_orchestrator":   ModelRole.ORCHESTRATOR,
            "galaxy_gateway":     ModelRole.ORCHESTRATOR,
            "task_orchestrator":  ModelRole.ORCHESTRATOR,
            "hybrid_executor":    ModelRole.EXECUTOR,
            "windows_arbiter":    ModelRole.EXECUTOR,
            "smart_transport":    ModelRole.TRANSPORT,
        }

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_role(self, component: str) -> ModelRole:
        """Return the ``ModelRole`` for *component* (case-insensitive).

        Unknown components are treated as ``EXECUTOR`` (safe default).
        """
        return self._component_roles.get(component.lower(), ModelRole.EXECUTOR)

    def get_authority(self, component: str) -> DecisionAuthority:
        """Return the ``DecisionAuthority`` level for *component*."""
        role = self.get_role(component)
        if role == ModelRole.PRIMARY:
            return DecisionAuthority.FULL
        if role in (ModelRole.ORCHESTRATOR, ModelRole.EXECUTOR):
            return DecisionAuthority.EXECUTE
        return DecisionAuthority.RELAY

    def may_decide(self, component: str) -> bool:
        """Return ``True`` when *component* is authorised to make primary decisions."""
        return self.get_role(component) in self._PRIMARY_ROLES

    # ------------------------------------------------------------------
    # Guard
    # ------------------------------------------------------------------

    def assert_primary(self, component: str, context: str = "") -> None:
        """Raise :class:`PolicyViolationError` if *component* is not primary.

        Args:
            component: Name of the calling component.
            context:   Optional human-readable description of the decision
                       being guarded (used in the error message).

        Raises:
            PolicyViolationError: When the component is not authorised.
        """
        if not self.may_decide(component):
            role = self.get_role(component)
            msg = (
                f"PolicyViolation: '{component}' (role={role.value}) is not "
                f"authorised to make primary decisions."
            )
            if context:
                msg += f" Context: {context}"
            logger.error(msg)
            raise PolicyViolationError(msg)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def log_primary_authority(
        self,
        component: str,
        *,
        trace_id: str = "",
        model: str = "",
        intent: str = "",
        extra: Optional[dict] = None,
    ) -> None:
        """Emit a structured log line recording the primary decision authority.

        This satisfies the acceptance criterion:
          *"Decision logs must clearly indicate the primary model or authority."*

        Args:
            component: Name of the authoritative component (should be
                       ``"openclawd"``).
            trace_id:  Request trace identifier.
            model:     Model/provider name used for this decision.
            intent:    Resolved intent type.
            extra:     Additional key/value pairs for the log record.
        """
        role = self.get_role(component)
        log_data = {
            "event":     "primary_decision_authority",
            "authority": component,
            "role":      role.value,
            "trace_id":  trace_id,
            "model":     model,
            "intent":    intent,
        }
        if extra:
            log_data.update(extra)
        logger.info(
            "primary_decision | authority=%s role=%s trace_id=%s model=%s intent=%s",
            component,
            role.value,
            trace_id,
            model,
            intent,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_policy_instance: Optional[ModelRolePolicy] = None


def get_policy() -> ModelRolePolicy:
    """Return the process-wide :class:`ModelRolePolicy` singleton."""
    global _policy_instance
    if _policy_instance is None:
        _policy_instance = ModelRolePolicy()
    return _policy_instance


def reset_policy() -> None:
    """Reset the singleton — **tests only**."""
    global _policy_instance
    _policy_instance = None


# ---------------------------------------------------------------------------
# Convenience guard (module-level shortcut)
# ---------------------------------------------------------------------------

def assert_primary(component: str, context: str = "") -> None:
    """Module-level shortcut for :meth:`ModelRolePolicy.assert_primary`."""
    get_policy().assert_primary(component, context=context)
