"""
Galaxy Agentic OS — Temporal Workflow Definitions
===================================================

Defines durable, retryable workflows for multi-step agent tasks using the
``temporalio`` Python SDK.  Workflows are executed by the Temporal server
and are automatically persisted / resumed on failure.

Three core workflows:
  1. CodeExecutionWorkflow  — LSP check → sandbox execute → retry on failure
  2. MultiDeviceTaskWorkflow — fan-out to N workers → aggregate results
  3. ToolDiscoveryWorkflow  — detect gap → LLM generate → ACL validate → register

Constraints (see plan 强约束):
  C1  — no DI, direct instantiation
  C5  — configured via ``GALAXY_TEMPORAL_URL``; graceful degradation if unavailable
  C7  — activities return ``{"success": bool, "error": ...}``
  C11 — uses stdlib ``logging`` (matching codebase convention)
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("temporal_workflows")

# Temporal SDK — may not be installed
try:
    from temporalio import activity, workflow
    from temporalio.client import Client as TemporalClient
    from temporalio.worker import Worker as TemporalWorker

    _HAS_TEMPORAL = True
except ImportError:
    _HAS_TEMPORAL = False

    # Stub decorators so the module loads without temporalio
    class _StubModule:
        @staticmethod
        def defn(cls=None, **kw):
            return cls if cls else (lambda c: c)

        @staticmethod
        def run(fn=None, **kw):
            return fn if fn else (lambda f: f)

    class _StubActivity:
        @staticmethod
        def defn(fn=None, **kw):
            return fn if fn else (lambda f: f)

    workflow = _StubModule()  # type: ignore[assignment]
    activity = _StubActivity()  # type: ignore[assignment]
    TemporalClient = None  # type: ignore[assignment,misc]
    TemporalWorker = None  # type: ignore[assignment,misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Activities (individual atomic steps)
# ═══════════════════════════════════════════════════════════════════════════════


@activity.defn(name="validate_task")
async def validate_task_activity(raw: dict) -> dict:
    """Validate a raw task dict through ACL.

    Returns ``{"success": True, "data": <serialized TaskDispatchModel>}``
    or ``{"success": False, "error": ...}``.
    """
    from core.acl import acl
    result = await acl.validate_task_dispatch(raw)
    if result["success"]:
        result["data"] = result["data"].model_dump(mode="json", exclude_none=True)
    return result


@activity.defn(name="dispatch_to_worker")
async def dispatch_to_worker_activity(task_data: dict) -> dict:
    """Publish a validated TaskDispatch to NATS.

    Returns ``{"success": True, "task_id": ...}`` or error dict.
    """
    from core.nats_bus import nats_bus
    from core.schemas.contracts import TaskDispatchModel

    task = TaskDispatchModel.model_validate(task_data)
    result = await nats_bus.publish_task_dispatch(task.target_worker_id, task)
    if result["success"]:
        result["task_id"] = task.task_id
    return result


@activity.defn(name="wait_for_result")
async def wait_for_result_activity(task_id: str, timeout_ms: int = 60_000) -> dict:
    """Subscribe to NATS and wait for a TaskResult matching ``task_id``.

    Returns ``{"success": True, "data": <serialized TaskResultModel>}``
    or ``{"success": False, "error": "timeout"}``.
    """
    from core.nats_bus import nats_bus
    from core.schemas.contracts import TaskStatus

    result_holder: dict = {}
    seen_result_ids: set[str] = set()
    event = asyncio.Event()
    subscription = None
    terminal_statuses = {
        TaskStatus.SUCCESS.value,
        TaskStatus.FAILED.value,
        TaskStatus.TIMEOUT.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.LSP_FAILED.value,
    }

    async def _on_result(data: dict):
        if data.get("task_id") == task_id:
            result_id = str((data.get("metadata") or {}).get("result_id") or "")
            if result_id:
                if result_id in seen_result_ids:
                    return
                seen_result_ids.add(result_id)
            result_holder["data"] = data
            if str(data.get("status", "")) in terminal_statuses:
                event.set()

    sub_result = await nats_bus.subscribe_task_results(_on_result, include_subscription=True)
    if not sub_result.get("success") or sub_result.get("noop"):
        error = sub_result.get("error", "unknown")
        if sub_result.get("noop"):
            error = f"distributed_transport_unavailable:{error}"
        return {"success": False, "error": f"Failed to subscribe: {error}", "task_id": task_id}
    subscription = sub_result.get("subscription")

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_ms / 1000)
        return {"success": True, "data": result_holder["data"]}
    except asyncio.TimeoutError:
        timeout_result = {"success": False, "error": "timeout", "task_id": task_id}
        if result_holder.get("data"):
            timeout_result["last_result"] = result_holder["data"]
        return timeout_result
    except asyncio.CancelledError:
        cancelled = {"success": False, "error": "cancelled", "task_id": task_id}
        if result_holder.get("data"):
            cancelled["last_result"] = result_holder["data"]
        return cancelled
    finally:
        try:
            await nats_bus.unsubscribe(subscription)
        except Exception as exc:
            logger.debug("wait_for_result_activity: unsubscribe failed for %s: %s", task_id, exc)


@activity.defn(name="generate_tool")
async def generate_tool_activity(description: str, context: dict) -> dict:
    """Use LLM to generate an MCP tool script.

    Returns ``{"success": True, "code": <source>, "language": "python"}``
    or error dict.
    """
    try:
        # Use existing LLM infrastructure
        from core.llm_manager import llm_manager

        prompt = (
            f"Generate a Python MCP server script (stdio JSON-RPC 2.0) that "
            f"implements a tool with the following description:\n\n"
            f"{description}\n\n"
            f"Context: {context}\n\n"
            f"Requirements:\n"
            f"- Use sys.stdin/sys.stdout for JSON-RPC communication\n"
            f"- Implement tools/list and tools/call methods\n"
            f"- Include proper error handling\n"
            f"- Output ONLY the Python code, no markdown fences"
        )

        response = await llm_manager.simple_chat(prompt)
        code = response.get("content", "") if isinstance(response, dict) else str(response)

        if not code.strip():
            return {"success": False, "error": "LLM returned empty response"}

        return {"success": True, "code": code.strip(), "language": "python"}

    except Exception as exc:
        return {"success": False, "error": f"Tool generation failed: {exc}"}


@activity.defn(name="test_tool")
async def test_tool_activity(code: str, language: str = "python") -> dict:
    """Test generated tool code in SafeExecutor sandbox.

    Returns ``{"success": True, "result": <ExecutionResult dict>}``
    or error dict.
    """
    try:
        from core.safe_executor import get_safe_executor

        executor = get_safe_executor()
        result = await executor.execute(code, language=language, timeout=10)

        return {
            "success": result.success,
            "result": {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": getattr(result, "exit_code", -1),
                "execution_time_ms": result.execution_time_ms,
            },
            "error": result.error if not result.success else None,
        }
    except Exception as exc:
        return {"success": False, "error": f"Tool test failed: {exc}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow 1: Code Execution (LSP → Sandbox → Retry)
# ═══════════════════════════════════════════════════════════════════════════════


@workflow.defn(name="CodeExecutionWorkflow")
class CodeExecutionWorkflow:
    """Execute code with LSP pre-check and automatic retry on failure.

    Steps:
    1. Validate task via ACL
    2. Dispatch to target worker via NATS
    3. Wait for TaskResult
    4. If LSP_FAILED → retry with fix (up to max_retries)
    5. Return final result
    """

    @workflow.run
    async def run(self, raw_task: dict) -> dict:
        max_retries = raw_task.get("max_retries", 3)

        # Step 1: validate
        validated = await workflow.execute_activity(
            validate_task_activity,
            raw_task,
            start_to_close_timeout=timedelta(seconds=10),
        )
        if not validated["success"]:
            return validated

        task_data = validated["data"]
        timeout_ms = task_data.get("timeout_ms", 60_000)

        for attempt in range(1, max_retries + 2):
            # Step 2: dispatch
            dispatch_result = await workflow.execute_activity(
                dispatch_to_worker_activity,
                task_data,
                start_to_close_timeout=timedelta(seconds=10),
            )
            if not dispatch_result["success"]:
                return dispatch_result

            # Step 3: wait for result
            result = await workflow.execute_activity(
                wait_for_result_activity,
                args=[task_data["task_id"], timeout_ms],
                start_to_close_timeout=timedelta(milliseconds=timeout_ms + 5000),
            )
            if not result["success"]:
                return result

            task_result = result["data"]
            status = task_result.get("status", "")

            # Step 4: check if LSP failed and retryable
            if status == "lsp_failed" and attempt <= max_retries:
                logger.info(
                    f"CodeExecutionWorkflow: LSP failed on attempt {attempt}/{max_retries}, retrying"
                )
                # Generate new task_id for retry
                task_data["task_id"] = str(uuid.uuid4())
                task_data["attempt_number"] = attempt + 1
                continue

            return {"success": True, "data": task_result, "attempts": attempt}

        return {"success": False, "error": "Max retries exceeded"}


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow 2: Multi-Device Task (Fan-Out → Aggregate)
# ═══════════════════════════════════════════════════════════════════════════════


@workflow.defn(name="MultiDeviceTaskWorkflow")
class MultiDeviceTaskWorkflow:
    """Fan-out task dispatch to multiple workers, aggregate results.

    Input: ``{"base_task": <task dict>, "worker_ids": ["w1", "w2", ...]}``
    """

    @workflow.run
    async def run(self, params: dict) -> dict:
        base_task = params.get("base_task", {})
        worker_ids = params.get("worker_ids", [])
        timeout_ms = base_task.get("timeout_ms", 60_000)

        if not worker_ids:
            return {"success": False, "error": "No worker_ids provided"}

        # Validate base task once
        validated = await workflow.execute_activity(
            validate_task_activity,
            base_task,
            start_to_close_timeout=timedelta(seconds=10),
        )
        if not validated["success"]:
            return validated

        # Fan-out: dispatch to each worker
        dispatch_tasks = []
        task_ids = []
        for wid in worker_ids:
            task_copy = dict(validated["data"])
            task_copy["task_id"] = str(uuid.uuid4())
            task_copy["target_worker_id"] = wid
            task_ids.append(task_copy["task_id"])

            dispatch_tasks.append(
                workflow.execute_activity(
                    dispatch_to_worker_activity,
                    task_copy,
                    start_to_close_timeout=timedelta(seconds=10),
                )
            )

        dispatch_results = await asyncio.gather(*dispatch_tasks)

        # Collect results
        result_tasks = []
        for tid in task_ids:
            result_tasks.append(
                workflow.execute_activity(
                    wait_for_result_activity,
                    args=[tid, timeout_ms],
                    start_to_close_timeout=timedelta(milliseconds=timeout_ms + 5000),
                )
            )

        results = await asyncio.gather(*result_tasks, return_exceptions=True)

        # Aggregate
        successes = []
        failures = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                failures.append({"worker_id": worker_ids[i], "error": str(r)})
            elif isinstance(r, dict) and r.get("success"):
                successes.append(r["data"])
            else:
                failures.append({"worker_id": worker_ids[i], "error": r.get("error", "unknown") if isinstance(r, dict) else str(r)})

        return {
            "success": len(failures) == 0,
            "total": len(worker_ids),
            "successes": successes,
            "failures": failures,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow 3: Tool Discovery (Self-Tool-Making)
# ═══════════════════════════════════════════════════════════════════════════════


@workflow.defn(name="ToolDiscoveryWorkflow")
class ToolDiscoveryWorkflow:
    """Detect missing tool → LLM generate → ACL validate → register.

    Input: ``{"tool_description": "...", "context": {...}}``
    """

    @workflow.run
    async def run(self, params: dict) -> dict:
        description = params.get("tool_description", "")
        context = params.get("context", {})

        if not description:
            return {"success": False, "error": "No tool_description provided"}

        # Step 1: Generate tool code via LLM
        gen_result = await workflow.execute_activity(
            generate_tool_activity,
            args=[description, context],
            start_to_close_timeout=timedelta(seconds=60),
        )
        if not gen_result["success"]:
            return gen_result

        code = gen_result["code"]
        language = gen_result.get("language", "python")

        # Step 2: Test in sandbox
        test_result = await workflow.execute_activity(
            test_tool_activity,
            args=[code, language],
            start_to_close_timeout=timedelta(seconds=30),
        )
        if not test_result["success"]:
            return {
                "success": False,
                "error": "Generated tool failed sandbox test",
                "test_result": test_result,
                "generated_code": code,
            }

        # Step 3: Register via MCP Gateway
        # (Registration is handled by the caller — MasterBrain or MCPDynamicGateway)
        return {
            "success": True,
            "code": code,
            "language": language,
            "test_result": test_result,
            "description": description,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Temporal client helper
# ═══════════════════════════════════════════════════════════════════════════════


async def get_temporal_client() -> Optional[Any]:
    """Get a connected Temporal client, or None if unavailable."""
    if not _HAS_TEMPORAL:
        logger.warning("temporal_workflows: temporalio not installed")
        return None

    url = os.environ.get("GALAXY_TEMPORAL_URL", "")
    if not url:
        logger.warning("temporal_workflows: GALAXY_TEMPORAL_URL not set")
        return None

    try:
        client = await TemporalClient.connect(url)
        logger.info(f"temporal_workflows: connected to Temporal at {url}")
        return client
    except Exception as exc:
        logger.error(f"temporal_workflows: connection failed — {exc}")
        return None


async def start_temporal_worker(client: Any, task_queue: str = "galaxy-tasks") -> Optional[Any]:
    """Start a Temporal worker that processes Galaxy workflows."""
    if not _HAS_TEMPORAL or client is None:
        return None

    worker = TemporalWorker(
        client,
        task_queue=task_queue,
        workflows=[
            CodeExecutionWorkflow,
            MultiDeviceTaskWorkflow,
            ToolDiscoveryWorkflow,
        ],
        activities=[
            validate_task_activity,
            dispatch_to_worker_activity,
            wait_for_result_activity,
            generate_tool_activity,
            test_tool_activity,
        ],
    )
    logger.info(f"temporal_workflows: worker started on queue '{task_queue}'")
    return worker
