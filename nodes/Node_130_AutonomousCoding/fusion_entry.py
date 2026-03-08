"""
Node_130_AutonomousCoding - Scheduler fusion entry
Wraps enhancements/coding/autonomous_coding_engine_v2.py for Scheduler discovery.
"""
import os
import sys
import json
import logging
import asyncio

logger = logging.getLogger("Node_130_AutonomousCoding")

_engine = None


def _get_engine():
    """Lazy-init the coding engine."""
    global _engine
    if _engine is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from enhancements.coding.autonomous_coding_engine_v2 import AutonomousCodingEngineV2
        _engine = AutonomousCodingEngineV2(workspace_root=project_root)
        logger.info("AutonomousCodingEngineV2 initialized")
    return _engine


def _run_async(coro):
    """Run async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in async context – schedule and block
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=120)
    else:
        return asyncio.run(coro)


def execute(action: str, params: dict = None) -> dict:
    """Scheduler entry point – dispatch coding actions to the engine."""
    if params is None:
        params = {}

    try:
        if action in ("status", "help"):
            return {
                "node": "Node_130_AutonomousCoding",
                "status": "running",
                "available_actions": [
                    "generate_code", "fix_bug", "write_tests",
                    "optimize", "refactor", "analyze",
                ],
            }

        # Map action → CodingTaskType
        from enhancements.coding.autonomous_coding_engine_v2 import (
            CodingContext,
            CodingTaskType,
        )

        task_type_map = {
            "generate_code": CodingTaskType.FEATURE,
            "feature": CodingTaskType.FEATURE,
            "fix_bug": CodingTaskType.BUG_FIX,
            "bug_fix": CodingTaskType.BUG_FIX,
            "write_tests": CodingTaskType.TEST,
            "test": CodingTaskType.TEST,
            "optimize": CodingTaskType.OPTIMIZE,
            "refactor": CodingTaskType.REFACTOR,
            "document": CodingTaskType.DOCUMENT,
        }

        task_type = task_type_map.get(action)
        if task_type is None:
            return {"success": False, "error": f"Unknown action: {action}. Use one of: {list(task_type_map.keys())}"}

        engine = _get_engine()
        ctx = CodingContext(
            task_type=task_type,
            description=params.get("description", ""),
            target_files=params.get("target_files", []),
            language=params.get("language", "python"),
            workspace_root=params.get("workspace_root", engine.workspace_root),
        )

        result = _run_async(engine.execute_task(ctx))
        return {
            "success": result.success,
            "code_changes": result.code_changes,
            "explanation": result.explanation,
            "quality_score": result.quality_score,
            "errors": result.errors,
            "warnings": result.warnings,
        }

    except Exception as e:
        logger.error(f"Execute {action} failed: {e}")
        return {"success": False, "error": str(e)}


def analyze(params: dict = None) -> dict:
    """Convenience wrapper for code analysis."""
    return execute("analyze", params)
