"""
windows_client/status_board_v2/config_control.py
=================================================
PR-15: Canonical configuration control surface for Status Board V2.

Upgrades the status board from a read-only projection surface into the
canonical desktop control surface by providing a bounded, safe configuration
entry path that writes through the canonical configuration authority and
triggers runtime hot-reload.

Architecture
------------
Status board input → ConfigControlSurface
                         → ConfigService (canonical authority)
                             → ConfigStore → runtime/config.json
                         → HotReloadConfigManager (hot-reload, if available)
                         → ControlApplyResult (control feedback)

Design constraints
------------------
- **Canonical writes only** — all configuration writes go through
  ``core.config_service.ConfigService``.  No ad-hoc local state is used as
  the source of truth.
- **Bounded operations** — only a small, explicit set of low-risk operations
  is supported: provider enable/disable toggles and routing policy selection.
- **Safe failure** — unknown operations are rejected before any write.
  Invalid values are rejected via ConfigService validation.
- **No secret leakage** — secret values are never included in control
  feedback strings or log output.
- **Hot-reload** — after a successful write, the surface attempts to trigger
  the existing ``HotReloadConfigManager`` to immediately propagate the
  change to runtime subscribers.  If the manager is not available, the
  result clearly says so rather than faking success.
- **Explicit feedback** — every apply action returns a ``ControlApplyResult``
  with success/failure status, reload status, last applied key, and any
  operator-meaningful error reason.

Public API
----------
STATUS_BOARD_CONFIG_CONTROL_AUTHORITY
    Module-level sentinel string.

ControlOperation
    Enum of allowed config operations.

ControlApplyResult
    Structured feedback from an apply action.

ConfigControlSurface
    The main control surface class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.StatusBoardConfigControl")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

STATUS_BOARD_CONFIG_CONTROL_AUTHORITY: str = "ConfigControlSurface"

# ---------------------------------------------------------------------------
# Allowed operations
# ---------------------------------------------------------------------------

class ControlOperation(str, Enum):
    """Bounded set of configuration operations the status board may perform."""

    TOGGLE_PROVIDER = "toggle_provider"
    """Enable or disable a provider by name (e.g. ``openai``, ``anthropic``)."""

    SET_ROUTING_POLICY = "set_routing_policy"
    """Set the native multimodal routing policy (``strict`` | ``prefer`` | ``allow_fallback``)."""

    SET_SERVER_URL = "set_server_url"
    """Set a server/endpoint URL (galaxy_gateway_url, android_ws_url, nats_url, status_board_port)."""

    SET_API_KEY = "set_api_key"
    """Store an API key for a provider via the credential vault / secrets store."""


# ---------------------------------------------------------------------------
# Control feedback
# ---------------------------------------------------------------------------

@dataclass
class ControlApplyResult:
    """
    Structured feedback returned by every apply action on ``ConfigControlSurface``.

    Attributes
    ----------
    succeeded:
        ``True`` when the configuration write completed without error.
    operation:
        The :class:`ControlOperation` value that was attempted.
    last_applied_key:
        Human-readable description of the key/value that was written
        (e.g. ``"providers.openai.enabled → True"``).
        Empty when the operation failed before any write.
    reload_triggered:
        ``True`` when the ``HotReloadConfigManager`` was successfully
        invoked after the write.
    reload_supported:
        ``True`` when the hot-reload manager was reachable.
        ``False`` means the change is persisted but requires a process restart
        to take effect in live runtime subscribers.
    reason:
        Human-readable success or informational message.
    error:
        Non-empty when ``succeeded`` is ``False``; describes the failure
        in operator-meaningful terms.  Never contains secret values.
    """

    succeeded: bool
    operation: str
    last_applied_key: str = ""
    reload_triggered: bool = False
    reload_supported: bool = True
    reason: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "succeeded": self.succeeded,
            "operation": self.operation,
            "last_applied_key": self.last_applied_key,
            "reload_triggered": self.reload_triggered,
            "reload_supported": self.reload_supported,
            "reason": self.reason,
            "error": self.error,
        }

    def render_lines(self) -> list:
        """Return a list of display-ready strings for operator feedback."""
        lines = []
        status_mark = "✓" if self.succeeded else "✗"
        status_label = "APPLIED" if self.succeeded else "REJECTED"
        lines.append(f"  {status_mark}  Config {status_label}  [{self.operation}]")
        if self.last_applied_key:
            lines.append(f"     key : {self.last_applied_key}")
        if self.reload_triggered:
            lines.append("     reload : hot-reload triggered")
        elif not self.reload_supported:
            lines.append("     reload : not available — restart to apply")
        else:
            lines.append("     reload : pending (auto-watch cycle)")
        if self.reason:
            lines.append(f"     info  : {self.reason}")
        if self.error:
            lines.append(f"     error : {self.error}")
        return lines


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_hot_reload_manager():
    """Return the running HotReloadConfigManager singleton, or None."""
    try:
        from core.config_hot_reload import get_existing_manager  # noqa: PLC0415
        return get_existing_manager()
    except Exception:  # pragma: no cover
        return None


def _try_hot_reload(mgr, config_path: str) -> Tuple[bool, bool, str]:
    """
    Attempt to trigger a hot-reload from *config_path*.

    Returns
    -------
    (reload_supported, reload_triggered, message)
    """
    if mgr is None:
        return False, False, "hot-reload manager not initialised; config will take effect on next startup"
    try:
        errors = mgr.load_from_file(config_path)
        if errors:
            return True, False, f"reload attempted but failed: {'; '.join(errors)}"
        return True, True, "runtime hot-reload triggered"
    except Exception as exc:  # pragma: no cover
        return True, False, f"reload raised an exception: {exc}"


# ---------------------------------------------------------------------------
# Control surface
# ---------------------------------------------------------------------------

class ConfigControlSurface:
    """
    Canonical configuration control surface for ``status_board_v2``.

    Provides a bounded, operator-safe path to apply configuration changes
    through the canonical configuration authority (``ConfigService``) and
    trigger runtime hot-reload where available.

    All write operations are delegated to ``ConfigService``.  This class
    does **not** maintain its own configuration state.

    Parameters
    ----------
    service:
        A ``core.config_service.ConfigService`` instance.  Defaults to the
        global singleton from ``get_config_service()``.
    hot_reload_manager:
        An optional ``core.config_hot_reload.HotReloadConfigManager``
        instance.  When ``None`` (the default), the control surface
        attempts to use the existing runtime singleton (if initialised).
        Pass an explicit instance primarily for testing.
    """

    def __init__(
        self,
        service=None,
        hot_reload_manager=None,
    ) -> None:
        if service is None:
            from core.config_service import get_config_service  # noqa: PLC0415
            service = get_config_service()
        self._service = service
        self._hot_reload_manager = hot_reload_manager
        self._last_result: Optional[ControlApplyResult] = None

    # ------------------------------------------------------------------
    # Core apply dispatcher
    # ------------------------------------------------------------------

    def apply(self, operation: ControlOperation, **kwargs) -> ControlApplyResult:
        """
        Apply a bounded configuration operation.

        Parameters
        ----------
        operation:
            A :class:`ControlOperation` enum value.
        **kwargs:
            Operation-specific parameters (see individual ``apply_*`` methods).

        Returns
        -------
        ControlApplyResult
        """
        if operation == ControlOperation.TOGGLE_PROVIDER:
            result = self.apply_toggle(
                provider=kwargs.get("provider", ""),
                enabled=kwargs.get("enabled", True),
            )
        elif operation == ControlOperation.SET_ROUTING_POLICY:
            result = self.apply_routing_policy(
                mode=kwargs.get("mode", ""),
            )
        elif operation == ControlOperation.SET_SERVER_URL:
            result = self.apply_server_url(
                endpoint_name=kwargs.get("endpoint_name", ""),
                url=kwargs.get("url", ""),
            )
        elif operation == ControlOperation.SET_API_KEY:
            result = self.apply_api_key(
                provider=kwargs.get("provider", ""),
                api_key=kwargs.get("api_key", ""),
            )
        else:
            result = ControlApplyResult(
                succeeded=False,
                operation=str(operation),
                error=f"Unknown operation '{operation}'. Allowed: {[o.value for o in ControlOperation]}",
            )
        self._last_result = result
        return result

    # ------------------------------------------------------------------
    # Individual operations
    # ------------------------------------------------------------------

    def apply_toggle(self, provider: str, enabled: bool) -> ControlApplyResult:
        """
        Enable or disable a provider via the canonical configuration authority.

        Parameters
        ----------
        provider:
            Provider name (e.g. ``"openai"``).  Must be a member of
            ``core.config_schema.VALID_PROVIDERS``.
        enabled:
            ``True`` to enable, ``False`` to disable.

        Returns
        -------
        ControlApplyResult
        """
        op = ControlOperation.TOGGLE_PROVIDER.value
        provider = (provider or "").strip()
        if not provider:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error="provider name must be non-empty",
            )
            self._last_result = result
            return result

        try:
            self._service.set_toggle(provider, bool(enabled))
        except ValueError as exc:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=str(exc),
            )
            self._last_result = result
            return result
        except Exception as exc:  # pragma: no cover
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=f"write failed: {exc}",
            )
            self._last_result = result
            return result

        applied_key = f"providers.{provider}.enabled → {bool(enabled)}"
        reload_supported, reload_triggered, reload_reason = self._trigger_reload()

        result = ControlApplyResult(
            succeeded=True,
            operation=op,
            last_applied_key=applied_key,
            reload_triggered=reload_triggered,
            reload_supported=reload_supported,
            reason=reload_reason,
        )
        self._last_result = result
        logger.info(
            "ConfigControlSurface: toggle applied — %s, reload_triggered=%s",
            applied_key,
            reload_triggered,
        )
        return result

    def apply_routing_policy(self, mode: str) -> ControlApplyResult:
        """
        Set the native multimodal routing policy via the canonical config authority.

        Parameters
        ----------
        mode:
            One of ``"strict"`` | ``"prefer"`` | ``"allow_fallback"``.

        Returns
        -------
        ControlApplyResult
        """
        op = ControlOperation.SET_ROUTING_POLICY.value
        mode = (mode or "").strip()
        if not mode:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error="routing policy mode must be non-empty",
            )
            self._last_result = result
            return result

        try:
            self._service.set_native_mm_policy(mode)
        except ValueError as exc:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=str(exc),
            )
            self._last_result = result
            return result
        except Exception as exc:  # pragma: no cover
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=f"write failed: {exc}",
            )
            self._last_result = result
            return result

        applied_key = f"routing.native_multimodal_policy → {mode}"
        reload_supported, reload_triggered, reload_reason = self._trigger_reload()

        result = ControlApplyResult(
            succeeded=True,
            operation=op,
            last_applied_key=applied_key,
            reload_triggered=reload_triggered,
            reload_supported=reload_supported,
            reason=reload_reason,
        )
        self._last_result = result
        logger.info(
            "ConfigControlSurface: routing policy applied — %s, reload_triggered=%s",
            applied_key,
            reload_triggered,
        )
        return result

    def apply_server_url(self, endpoint_name: str, url: str) -> ControlApplyResult:
        """
        Persist a server/endpoint URL to ``runtime/config.json``.

        Parameters
        ----------
        endpoint_name:
            One of ``"galaxy_gateway_url"``, ``"android_ws_url"``,
            ``"nats_url"``, ``"status_board_port"``.
        url:
            The URL or port value.  Must be non-empty.

        Returns
        -------
        ControlApplyResult
        """
        op = ControlOperation.SET_SERVER_URL.value
        endpoint_name = (endpoint_name or "").strip()
        url = (url or "").strip()
        if not endpoint_name:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error="endpoint_name must be non-empty",
            )
            self._last_result = result
            return result
        if not url:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error="url must be non-empty",
            )
            self._last_result = result
            return result

        try:
            self._service.set_endpoint_url(endpoint_name, url)
        except ValueError as exc:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=str(exc),
            )
            self._last_result = result
            return result
        except Exception as exc:  # pragma: no cover
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=f"write failed: {exc}",
            )
            self._last_result = result
            return result

        applied_key = f"endpoints.{endpoint_name} → {url}"
        reload_supported, reload_triggered, reload_reason = self._trigger_reload()

        result = ControlApplyResult(
            succeeded=True,
            operation=op,
            last_applied_key=applied_key,
            reload_triggered=reload_triggered,
            reload_supported=reload_supported,
            reason=reload_reason,
        )
        self._last_result = result
        logger.info(
            "ConfigControlSurface: server URL applied — %s, reload_triggered=%s",
            applied_key,
            reload_triggered,
        )
        return result

    def apply_api_key(self, provider: str, api_key: str) -> ControlApplyResult:
        """
        Store an API key for a provider via the canonical credential vault.

        The key is written to ``runtime/secrets.env`` and never echoed in
        feedback strings or log output.

        Parameters
        ----------
        provider:
            Provider name (e.g. ``"openai"``).
        api_key:
            The API key value.  Must be non-empty.

        Returns
        -------
        ControlApplyResult
        """
        op = ControlOperation.SET_API_KEY.value
        provider = (provider or "").strip()
        api_key = (api_key or "").strip()
        if not provider:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error="provider name must be non-empty",
            )
            self._last_result = result
            return result
        if not api_key:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error="api_key must be non-empty",
            )
            self._last_result = result
            return result

        try:
            self._service.set_provider_api_key(provider, api_key)
        except ValueError as exc:
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=str(exc),
            )
            self._last_result = result
            return result
        except Exception as exc:  # pragma: no cover
            result = ControlApplyResult(
                succeeded=False,
                operation=op,
                error=f"write failed: {exc}",
            )
            self._last_result = result
            return result

        # Do not include the key value in any feedback string.
        applied_key = f"secrets.{provider.upper()}_API_KEY → [stored, value hidden]"

        result = ControlApplyResult(
            succeeded=True,
            operation=op,
            last_applied_key=applied_key,
            reload_triggered=False,
            reload_supported=False,
            reason="API key written to runtime/secrets.env; value is never echoed",
        )
        self._last_result = result
        logger.info(
            "ConfigControlSurface: API key stored for provider '%s'",
            provider,
        )
        return result

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    @property
    def last_result(self) -> Optional[ControlApplyResult]:
        """Return the most recent :class:`ControlApplyResult`, or ``None``."""
        return self._last_result

    def render_feedback(self) -> str:
        """
        Render the most recent control result as a compact display string.

        Returns an empty string when no operation has been applied yet.
        """
        if self._last_result is None:
            return ""
        lines = self._last_result.render_lines()
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trigger_reload(self) -> Tuple[bool, bool, str]:
        """Try to hot-reload runtime config after a write."""
        mgr = self._hot_reload_manager or _get_hot_reload_manager()
        if mgr is None:
            return False, False, "hot-reload manager not initialised; config persisted, takes effect on startup"
        # Resolve canonical config path via the public service property
        config_path: str = ""
        try:
            config_path = self._service.config_path
        except Exception:  # pragma: no cover
            pass
        return _try_hot_reload(mgr, config_path)
