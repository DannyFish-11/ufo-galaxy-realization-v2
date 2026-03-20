"""
windows_client/status_board_v2/__init__.py
==========================================
Status Board V2 — public surface.

This package provides a **read-only** desktop status board that consumes
the :class:`~core.projection.RuntimeProjection` produced by the server and
visualises:

- Tri-state phase (silent / liminal / manifest)       → PhaseSurface
- Runtime domain (local / cross_device / transition)  → DomainSurface
- Model topology weights (top-N by weight)            → TopologySurface
- Active devices and execution stage                  → DeviceSurface
- Presence/coherence/tendency metrics                 → MetricsSurface
- Liminal spatial projection dimensions               → LiminalSurface

READ-ONLY GUARANTEE
-------------------
This package NEVER:
- Accepts chat input
- Sends commands to the system
- Triggers any actions

All command execution remains in::

    windows_aip_client.py → WindowsExecutionArbiter.route_command()
"""

from .app import main, run, StatusBoardV2App
from .projection_reader import ProjectionReader
from .liminal_surface import LiminalSurface

__all__ = [
    "main",
    "run",
    "StatusBoardV2App",
    "ProjectionReader",
    "LiminalSurface",
]
