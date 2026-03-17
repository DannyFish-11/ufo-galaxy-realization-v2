"""
Galaxy — Generative UI Runtime (PR-5)
======================================

Provides the server-side surface selection logic and a minimal runtime
descriptor that Windows / Android / Dashboard clients can use to adapt
their rendered UI surface in response to an :class:`~core.schemas.interaction_envelope.InteractionEnvelope`.

Public API::

    from core.generative_ui import GenerativeUIRuntime, SurfaceSelector, SurfaceType

Sub-modules
-----------
* :mod:`core.generative_ui.widget_schema` — :class:`SurfaceType` enum and
  :class:`SurfaceSpec` descriptor.
* :mod:`core.generative_ui.surface_selector` — :class:`SurfaceSelector` with
  the :func:`~SurfaceSelector.select_surface` mapping method.
* :mod:`core.generative_ui.runtime` — :class:`GenerativeUIRuntime` façade.
"""

from core.generative_ui.widget_schema import SurfaceType, SurfaceSpec
from core.generative_ui.surface_selector import SurfaceSelector
from core.generative_ui.runtime import GenerativeUIRuntime

__all__ = [
    "SurfaceType",
    "SurfaceSpec",
    "SurfaceSelector",
    "GenerativeUIRuntime",
]
