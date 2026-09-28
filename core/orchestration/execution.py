"""core/orchestration/execution.py — Execution pipeline façade.

PR-7: Thin façade over OpenClawd's local and remote execution methods.
"""

from __future__ import annotations

import logging

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
