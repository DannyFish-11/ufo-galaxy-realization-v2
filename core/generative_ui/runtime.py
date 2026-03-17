"""
Galaxy — Generative UI Runtime (PR-5)
======================================

Provides :class:`GenerativeUIRuntime`, the server-side façade that combines
:class:`~core.generative_ui.surface_selector.SurfaceSelector` with
:class:`~core.generative_ui.widget_schema.SurfaceSpec` to produce a
ready-to-serialise UI surface descriptor for every response.

The runtime is intentionally thin — it delegates all mapping logic to
:class:`~core.generative_ui.surface_selector.SurfaceSelector` so that the
mapping table remains the single source of truth.

Typical server usage::

    runtime = GenerativeUIRuntime()
    spec = runtime.render_surface(interaction_envelope)
    # Attach spec.to_dict() to the API response payload.

No external dependencies — stdlib only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

from core.generative_ui.surface_selector import SurfaceSelector
from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType

logger = logging.getLogger(__name__)


class GenerativeUIRuntime:
    """Server-side generative UI runtime.

    Selects the appropriate :class:`~core.generative_ui.widget_schema.SurfaceSpec`
    for a given :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
    and exposes it for downstream clients.

    The runtime is stateless except for the :class:`SurfaceSelector` it holds,
    which is itself stateless.  A single shared instance is sufficient.

    Attributes:
        selector: The :class:`SurfaceSelector` used for mode → surface mapping.
    """

    def __init__(self) -> None:
        self.selector = SurfaceSelector()

    def render_surface(
        self,
        interaction_envelope: Union[Any, Dict[str, Any], None] = None,
        *,
        fallback_mode: str = "chat",
    ) -> SurfaceSpec:
        """Return the :class:`SurfaceSpec` for the given *interaction_envelope*.

        This is the primary entry point.  The result's :meth:`SurfaceSpec.to_dict`
        can be embedded directly in an API response payload.

        Args:
            interaction_envelope: An
                :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
                instance, a plain dict, or ``None``.  When ``None`` the runtime
                falls back to *fallback_mode*.
            fallback_mode: Mode string used when no envelope (or no mode) is
                present (default ``"chat"``).

        Returns:
            A :class:`SurfaceSpec` ready for serialisation.
        """
        try:
            spec = self.selector.select_surface(
                interaction_envelope, mode=fallback_mode
            )
        except Exception as exc:
            logger.warning("GenerativeUIRuntime.render_surface error: %s", exc)
            spec = SurfaceSpec(surface_type=SurfaceType.CHAT_PANEL)
        return spec

    def render_surface_dict(
        self,
        interaction_envelope: Union[Any, Dict[str, Any], None] = None,
        *,
        fallback_mode: str = "chat",
    ) -> Dict[str, Any]:
        """Convenience wrapper returning :meth:`SurfaceSpec.to_dict`.

        Args:
            interaction_envelope: See :meth:`render_surface`.
            fallback_mode: See :meth:`render_surface`.

        Returns:
            A JSON-serialisable dict with ``surface_type``, ``title``,
            ``layout_hints``, and ``fallback_surface`` keys.
        """
        return self.render_surface(
            interaction_envelope, fallback_mode=fallback_mode
        ).to_dict()


# ---------------------------------------------------------------------------
# Module-level singleton — avoids repeated instantiation at call sites
# ---------------------------------------------------------------------------

_runtime: Optional[GenerativeUIRuntime] = None


def get_generative_ui_runtime() -> GenerativeUIRuntime:
    """Return the process-level :class:`GenerativeUIRuntime` singleton."""
    global _runtime
    if _runtime is None:
        _runtime = GenerativeUIRuntime()
    return _runtime


__all__ = ["GenerativeUIRuntime", "get_generative_ui_runtime"]
