"""core/orchestration/planning.py — Planning pipeline façade.

PR-7: Thin façade over OpenClawd's planning methods.  Delegates all heavy
lifting back to the OpenClawd instance so that behaviour is fully preserved.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Orchestration.Planning")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

PLANNING_PIPELINE_AUTHORITY = "PLANNING_PIPELINE_AUTHORITY"

# ---------------------------------------------------------------------------
# PlanningPipeline
# ---------------------------------------------------------------------------


class PlanningPipeline:
    """Façade over OpenClawd's planning and intent-profile builders."""

    PLANNING_PIPELINE_AUTHORITY = PLANNING_PIPELINE_AUTHORITY

    @staticmethod
    def build_execution_plan(openclawd_instance: Any, **kwargs: Any) -> Any:
        """Delegate to ``openclawd_instance._build_execution_plan()``."""
        method = getattr(openclawd_instance, "_build_execution_plan", None)
        if method is None:
            logger.warning("PlanningPipeline: _build_execution_plan not found")
            return None
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("PlanningPipeline: build_execution_plan failed: %s", exc)
            return None

    @staticmethod
    def build_unified_control_plan(openclawd_instance: Any, **kwargs: Any) -> Dict:
        """Delegate to ``openclawd_instance._build_unified_control_plan()``."""
        method = getattr(openclawd_instance, "_build_unified_control_plan", None)
        if method is None:
            logger.warning("PlanningPipeline: _build_unified_control_plan not found")
            return {}
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("PlanningPipeline: build_unified_control_plan failed: %s", exc)
            return {}

    @staticmethod
    def determine_execution_path(
        openclawd_instance: Any,
        state_continuum: Any,
        device_id: str,
    ) -> str:
        """Delegate to ``openclawd_instance._determine_execution_path()``."""
        method = getattr(openclawd_instance, "_determine_execution_path", None)
        if method is None:
            logger.warning("PlanningPipeline: _determine_execution_path not found")
            return "none"
        try:
            return method(state_continuum, device_id)
        except Exception as exc:
            logger.warning("PlanningPipeline: determine_execution_path failed: %s", exc)
            return "none"

    @staticmethod
    def build_intent_profile(
        openclawd_instance: Any,
        **kwargs: Any,
    ) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._build_intent_profile()``."""
        method = getattr(openclawd_instance, "_build_intent_profile", None)
        if method is None:
            logger.warning("PlanningPipeline: _build_intent_profile not found")
            return None
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("PlanningPipeline: build_intent_profile failed: %s", exc)
            return None
