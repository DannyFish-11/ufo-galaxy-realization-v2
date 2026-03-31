"""core/orchestration/perception.py — Perception pipeline façade.

PR-7: Thin façade that delegates to OpenClawd._build_canonical_perception_state().
Extracted to make the perception pipeline addressable as a discrete concern.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Orchestration.Perception")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

PERCEPTION_PIPELINE_AUTHORITY = "PERCEPTION_PIPELINE_AUTHORITY"

# ---------------------------------------------------------------------------
# PerceptionPipeline
# ---------------------------------------------------------------------------


class PerceptionPipeline:
    """Façade over OpenClawd's canonical perception state builder."""

    PERCEPTION_PIPELINE_AUTHORITY = PERCEPTION_PIPELINE_AUTHORITY

    @staticmethod
    def build_canonical_perception_state(
        openclawd_instance: Any,
        multimodal_context: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._build_canonical_perception_state()``.

        Returns the perception state dict, or ``None`` if the method is
        unavailable or raises.
        """
        builder = getattr(openclawd_instance, "_build_canonical_perception_state", None)
        if builder is None:
            logger.warning("PerceptionPipeline: _build_canonical_perception_state not found")
            return None
        try:
            return builder(multimodal_context=multimodal_context)
        except Exception as exc:
            logger.warning("PerceptionPipeline: perception build failed: %s", exc)
            return None
