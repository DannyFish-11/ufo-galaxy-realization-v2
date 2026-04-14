"""
Galaxy - Command Routes
=============================

**Architecture role: ROUTE ADAPTER SURFACE — no orchestration authority**
--------------------------------------------------------------------------
This module is a **route adapter surface**.  Its responsibility is to
validate and translate HTTP requests, then forward them into the canonical
execution chain via ``CommandRouter.route_envelope()``.

Canonical chain for command dispatch::

    POST /api/v1/command/*   ← you are here (route adapter — no authority)
        → CommandRouter.route_envelope()  ← canonical orchestration authority
            → DeviceRouter.send_command_to_device()  ← canonical dispatch authority
                → device / transport

This module MUST NOT contain orchestration logic, device selection, or
dispatch decisions.  Any new command feature should be added to
``CommandRouter`` (orchestration) or ``DeviceRouter`` (dispatch).

Routes:
  POST /api/v1/command/unified                      - 统一命令端点 (多目标 sync/async)
  GET  /api/v1/command/unified/{request_id}/status  - 查询统一命令状态
  POST /api/v1/command                              - 命令路由引擎分发
  GET  /api/v1/command/{request_id}                 - 查询命令状态
  DELETE /api/v1/command/{request_id}               - 取消命令
  GET  /api/v1/command                              - 命令路由引擎统计
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from core.routes._shared import (
    connection_manager,
    command_results,
)
from core.routes._helpers import nodes_root
from core.node_invocation import invoke_node, InvocationSource
from core.routes._models import (
    CommandStatus,
    TargetResult,
    UnifiedCommandRequest,
)
from core.schemas.task_envelope import envelope_from_command_request

try:
    from core.auth import require_auth
except ImportError:
    async def require_auth():
        return {"authenticated": True, "dev_mode": True}

logger = logging.getLogger("Galaxy.API")

# ── Node_71 MDCE URL helper ─────────────────────────────────────────────────

def _get_node71_url() -> str:
    """Return the base URL for Node_71 (Multi-Device Coordination Engine)."""
    try:
        from core.port_config import get_node_port
        port = get_node_port("Node_71_MultiDeviceCoordination")
    except Exception:
        port = 8071
    host = os.getenv("NODE_71_HOST", "localhost")
    return f"http://{host}:{port}"


async def _delegate_to_mdce(
    request_id: str,
    req: "UnifiedCommandRequest",
    created_at: str,
) -> Optional["JSONResponse"]:
    """Delegate a multi-device command to Node_71 MDCE.

    Posts the command to the MDCE task-creation endpoint and returns the
    result wrapped in the same envelope structure used by the local path so
    callers cannot tell the difference.  Returns ``None`` when Node_71 is
    unreachable so the caller can fall back to local fan-out.
    """
    import httpx

    node71_url = _get_node71_url()
    payload = {
        "task_type": "parallel",
        "command": req.command,
        "params": req.params or {},
        "targets": req.targets,
        "timeout": req.timeout,
        "request_id": request_id,
    }
    try:
        async with httpx.AsyncClient(timeout=float(req.timeout) + 5) as client:
            resp = await client.post(f"{node71_url}/tasks", json=payload)
            resp.raise_for_status()
            mdce_result = resp.json()
    except (httpx.HTTPError, httpx.TransportError, OSError, ValueError) as exc:
        logger.warning(
            "Node_71 MDCE delegation failed (request_id=%s): %s -- falling back to local dispatch",
            request_id, exc,
        )
        return None

    return JSONResponse({
        "request_id": request_id,
        "status": CommandStatus.QUEUED,
        "created_at": created_at,
        "mdce": True,
        "mdce_task_id": mdce_result.get("task_id"),
        "message": "Multi-device command delegated to Node_71 MDCE.",
    })


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create command routing and unified command routes router."""
    router = APIRouter()

    # ── Unified Command endpoint helpers ───────────────────────────────────

    async def execute_command_on_target(
        target: str, command: str, params: Dict[str, Any], timeout: int
    ) -> TargetResult:
        """在单个目标上执行命令 — 使用 send_command_and_wait 实现 request-response"""
        started_at = datetime.now(timezone.utc).isoformat()

        try:
            if target not in connection_manager.active_devices:
                return TargetResult(
                    status=CommandStatus.FAILED,
                    output=None,
                    error="Target device not connected",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat()
                )

            result = await connection_manager.send_command_and_wait(
                device_id=target,
                command=command,
                params=params,
                timeout=float(timeout)
            )

            if "error" in result:
                return TargetResult(
                    status=CommandStatus.FAILED,
                    output=None,
                    error=result["error"],
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat()
                )

            return TargetResult(
                status=CommandStatus.DONE,
                output=result,
                error=None,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat()
            )

        except Exception as e:
            logger.error(f"执行命令失败 (target={target}): {e}")
            return TargetResult(
                status=CommandStatus.FAILED,
                output=None,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat()
            )

    def _build_canonical_envelope(req: UnifiedCommandRequest, request_id: str):
        metadata: Dict[str, Any] = {}
        if len(req.targets) > 1:
            # Multi-target execution must remain on the canonical cross-device
            # substrate path under CommandRouter.route_envelope().
            metadata["cross_device"] = "true"

        return envelope_from_command_request(
            command=req.command,
            targets=req.targets,
            params=req.params,
            source="api",
            mode=req.mode,
            timeout=float(req.timeout),
            request_id=request_id,
            metadata=metadata,
        )

    def _route_result_to_target_payload(
        req: UnifiedCommandRequest,
        route_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        success = bool(route_result.get("success"))
        result_payload = route_result.get("result")
        error_message = route_result.get("error_message")
        status = CommandStatus.DONE if success else CommandStatus.FAILED

        if (
            isinstance(result_payload, dict)
            and isinstance(result_payload.get("results"), list)
        ):
            mapped: Dict[str, Any] = {}
            for entry in result_payload["results"]:
                if not isinstance(entry, dict):
                    continue
                target_id = str(entry.get("device_id") or entry.get("target") or "")
                if not target_id:
                    continue
                entry_success = bool(entry.get("success"))
                mapped[target_id] = TargetResult(
                    status=CommandStatus.DONE if entry_success else CommandStatus.FAILED,
                    output=entry.get("result"),
                    error=entry.get("error_message"),
                    started_at=route_result.get("started_at") or datetime.now(timezone.utc).isoformat(),
                    completed_at=route_result.get("completed_at") or datetime.now(timezone.utc).isoformat(),
                ).model_dump()
            if mapped:
                return mapped

        return {
            target: TargetResult(
                status=status,
                output=result_payload,
                error=error_message,
                started_at=route_result.get("started_at") or datetime.now(timezone.utc).isoformat(),
                completed_at=route_result.get("completed_at") or datetime.now(timezone.utc).isoformat(),
            ).model_dump()
            for target in req.targets
        }

    async def _execute_via_canonical_route(
        req: UnifiedCommandRequest,
        request_id: str,
        created_at: str,
    ) -> Dict[str, Any]:
        envelope = _build_canonical_envelope(req, request_id)
        logger.info(
            "统一命令进入 canonical spine: trace_id=%s task_id=%s command=%s targets=%s mode=%s",
            envelope.trace_id, envelope.task_id, req.command, req.targets, req.mode,
        )
        route_result = await command_router.route_envelope(envelope)

        completed_at = datetime.now(timezone.utc).isoformat()
        route_success = bool(route_result.get("success"))
        status = CommandStatus.DONE if route_success else CommandStatus.FAILED
        results_payload = _route_result_to_target_payload(req, route_result)

        command_results[request_id]["status"] = status
        command_results[request_id]["completed_at"] = completed_at
        command_results[request_id]["results"] = results_payload
        command_results[request_id]["canonical_route"] = route_result
        return {
            "status": status,
            "completed_at": completed_at,
            "results": results_payload,
            "canonical_route": route_result,
        }

    @router.post("/api/v1/command/unified")
    async def unified_command(
        req: UnifiedCommandRequest,
        auth: dict = Depends(require_auth)
    ):
        """
        统一命令端点 - 支持多目标、sync/async 模式、超时控制
        """
        request_id = req.request_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        if req.mode not in ["sync", "async"]:
            raise HTTPException(status_code=400, detail="Invalid mode. Must be 'sync' or 'async'")

        if not req.targets:
            raise HTTPException(status_code=400, detail="Targets list cannot be empty")

        command_results[request_id] = {
            "request_id": request_id,
            "command": req.command,
            "targets": req.targets,
            "params": req.params,
            "mode": req.mode,
            "status": CommandStatus.QUEUED,
            "created_at": created_at,
            "completed_at": None,
            "results": {}
        }

        if req.mode == "sync":
            command_results[request_id]["status"] = CommandStatus.RUNNING
            execution = await _execute_via_canonical_route(req, request_id, created_at)
            return JSONResponse({
                "request_id": request_id,
                "status": execution["status"],
                "created_at": created_at,
                "completed_at": execution["completed_at"],
                "results": execution["results"],
            })

        else:
            async def execute_async():
                """后台执行任务"""
                try:
                    command_results[request_id]["status"] = CommandStatus.RUNNING
                    execution = await _execute_via_canonical_route(req, request_id, created_at)

                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": execution["status"],
                        "created_at": created_at,
                        "completed_at": execution["completed_at"],
                        "results": execution["results"],
                    })

                except Exception as e:
                    logger.error(f"异步命令执行失败: {e}")
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.FAILED
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {
                        target: TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(e),
                            started_at=created_at,
                            completed_at=completed_at
                        ).model_dump()
                        for target in req.targets
                    }

                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": CommandStatus.FAILED,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "results": command_results[request_id]["results"]
                    })

            asyncio.create_task(execute_async())

            return JSONResponse({
                "request_id": request_id,
                "status": CommandStatus.QUEUED,
                "created_at": created_at,
                "message": (
                    "Command queued for async execution. "
                    "Use GET /api/v1/command/{request_id}/status to check status."
                ),
            })

    @router.get("/api/v1/command/unified/{request_id}/status")
    async def get_unified_command_status(
        request_id: str,
        auth: dict = Depends(require_auth)
    ):
        """查询异步统一命令执行状态和结果"""
        if request_id not in command_results:
            raise HTTPException(status_code=404, detail="Command not found")

        result = command_results[request_id]

        return JSONResponse({
            "request_id": result["request_id"],
            "status": result["status"],
            "created_at": result["created_at"],
            "completed_at": result["completed_at"],
            "results": result["results"]
        })

    # ── Command Router endpoints ────────────────────────────────────────────

    from core.command_router import get_command_router

    async def _on_command_status_change(cmd_result):
        """命令状态变更 → WebSocket 推送"""
        try:
            await connection_manager.push_command_result(cmd_result.to_dict())
        except Exception as e:
            logger.error(f"Command result push failed: {e}")

    command_router = get_command_router(on_status_change=_on_command_status_change)

    async def _command_node_executor(target: str, command: str, params: dict):
        """命令路由 → 节点执行桥接 (unified executor)"""
        # Check if target is a connected device (not a node directory)
        target_node_dir = os.path.join(nodes_root, target)
        if not os.path.isdir(target_node_dir):
            # Check for fuzzy node match before falling back to device
            found_as_node = False
            for name in os.listdir(nodes_root):
                if name.startswith(target) or target in name:
                    found_as_node = True
                    break
            if not found_as_node:
                if target in connection_manager.active_devices:
                    sent = await connection_manager.send_to_device(target, {
                        "type": "command",
                        "command": command,
                        "params": params,
                    })
                    return {"sent_to_device": target, "success": sent}
                return {"error": f"Target {target} not found"}

        result = await invoke_node(
            target,
            command,
            params,
            invocation_source=InvocationSource.COMMAND,
        )
        if result.success:
            return result.result if result.result is not None else {"success": True}
        return {"error": result.error, "success": False}

    command_router.set_executor(_command_node_executor)

    @router.post("/api/v1/command")
    async def dispatch_command(
        req: UnifiedCommandRequest,
        auth: dict = Depends(require_auth),
    ):
        """Alias of /api/v1/command/unified routed through the same canonical spine."""
        return await unified_command(req, auth)

    @router.get("/api/v1/command/{request_id}/status")
    async def get_command_unified_status(
        request_id: str,
        auth: dict = Depends(require_auth),
    ):
        """查询统一命令执行状态（支持 async 提交后的状态轮询）"""
        if request_id not in command_results:
            raise HTTPException(status_code=404, detail=f"Command {request_id} not found")
        result = command_results[request_id]
        return JSONResponse({
            "request_id": result["request_id"],
            "status": result["status"],
            "created_at": result["created_at"],
            "completed_at": result.get("completed_at"),
            "results": result.get("results", {}),
        })

    @router.get("/api/v1/command/{request_id}")
    async def get_command_status(request_id: str):
        """查询命令执行状态和聚合结果（命令路由引擎）"""
        result = await command_router.get_result(request_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Command {request_id} not found")
        return JSONResponse(result.to_dict())

    @router.delete("/api/v1/command/{request_id}")
    async def cancel_command(request_id: str):
        """取消正在执行的命令"""
        cancelled = await command_router.cancel(request_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Command not found or already completed")
        return JSONResponse({"success": True, "message": f"Command {request_id} cancelled"})

    @router.get("/api/v1/command")
    async def command_stats():
        """获取命令路由引擎统计"""
        return JSONResponse(command_router.get_stats())

    return router
