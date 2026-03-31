"""core/orchestration/reflection.py — Reflection/post-execution reasoning façade.

PR-7: Thin façade over OpenClawd's reflection and trace-building methods.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Orchestration.Reflection")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

REFLECTION_PIPELINE_AUTHORITY = "REFLECTION_PIPELINE_AUTHORITY"

# ---------------------------------------------------------------------------
# ReflectionPipeline
# ---------------------------------------------------------------------------


class ReflectionPipeline:
    """Façade over OpenClawd's reflection and post-execution trace builders."""

    REFLECTION_PIPELINE_AUTHORITY = REFLECTION_PIPELINE_AUTHORITY

    @staticmethod
    def build_mainline_convergence_stamp(
        openclawd_instance: Any,
        **kwargs: Any,
    ) -> Dict:
        """Delegate to ``openclawd_instance._build_mainline_convergence_stamp()``."""
        method = getattr(openclawd_instance, "_build_mainline_convergence_stamp", None)
        if method is None:
            return {}
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("ReflectionPipeline: build_mainline_convergence_stamp failed: %s", exc)
            return {}

    @staticmethod
    def build_execution_trace(
        openclawd_instance: Any,
        **kwargs: Any,
    ) -> Dict:
        """Delegate to ``openclawd_instance._build_execution_trace()``."""
        method = getattr(openclawd_instance, "_build_execution_trace", None)
        if method is None:
            return {}
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("ReflectionPipeline: build_execution_trace failed: %s", exc)
            return {}

    @staticmethod
    def build_production_baseline_summary(
        openclawd_instance: Any,
    ) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._build_production_baseline_summary()``."""
        method = getattr(openclawd_instance, "_build_production_baseline_summary", None)
        if method is None:
            return None
        try:
            return method()
        except Exception as exc:
            logger.warning(
                "ReflectionPipeline: build_production_baseline_summary failed: %s", exc
            )
            return None

    @staticmethod
    def build_decision_timeline_snapshot(
        openclawd_instance: Any,
        **kwargs: Any,
    ) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._build_decision_timeline_snapshot()``."""
        method = getattr(openclawd_instance, "_build_decision_timeline_snapshot", None)
        if method is None:
            return None
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning(
                "ReflectionPipeline: build_decision_timeline_snapshot failed: %s", exc
            )
            return None
