"""core/orchestration/execution.py — Execution pipeline façade.

PR-7: Thin façade over OpenClawd's local and remote execution methods.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Orchestration.Execution")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

EXECUTION_PIPELINE_AUTHORITY = "EXECUTION_PIPELINE_AUTHORITY"

# ---------------------------------------------------------------------------
# ExecutionPipeline
# ---------------------------------------------------------------------------


class ExecutionPipeline:
    """Façade over OpenClawd's local and remote execution paths."""

    EXECUTION_PIPELINE_AUTHORITY = EXECUTION_PIPELINE_AUTHORITY

    @staticmethod
    async def run_local(openclawd_instance: Any, **kwargs: Any) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._run_execution()`` for local execution."""
        method = getattr(openclawd_instance, "_run_execution", None)
        if method is None:
            logger.warning("ExecutionPipeline: _run_execution not found")
            return None
        try:
            return await method(**kwargs)
        except Exception as exc:
            logger.warning("ExecutionPipeline: run_local failed: %s", exc)
            return None

    @staticmethod
    async def run_remote(
        openclawd_instance: Any,
        device_id: str,
        message: str,
        **kwargs: Any,
    ) -> Dict:
        """Delegate to OpenClawd's cross-device execution path."""
        method = getattr(openclawd_instance, "_run_cross_device_execution", None)
        if method is None:
            logger.warning("ExecutionPipeline: _run_cross_device_execution not found")
            return {"error": "cross_device_execution_unavailable"}
        try:
            return await method(device_id=device_id, message=message, **kwargs)
        except Exception as exc:
            logger.warning("ExecutionPipeline: run_remote failed: %s", exc)
            return {"error": str(exc)}
