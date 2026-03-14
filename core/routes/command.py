"""
Galaxy - Command Routes
=============================

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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from core.routes._shared import (
    connection_manager,
    command_results,
)
from core.routes._helpers import nodes_root, _load_node, _execute_node
from core.routes._models import (
    CommandDispatchRequest,
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

        # Build a TaskEnvelope for consistent trace_id propagation
        envelope = envelope_from_command_request(
            command=req.command,
            targets=req.targets,
            params=req.params,
            source="api",
            mode=req.mode,
            timeout=float(req.timeout),
            request_id=request_id,
        )

        logger.info(
            "收到统一命令: trace_id=%s task_id=%s command=%s targets=%s mode=%s",
            envelope.trace_id, envelope.task_id, req.command, req.targets, req.mode,
        )

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

            tasks = [
                execute_command_on_target(target, req.command, req.params, req.timeout)
                for target in req.targets
            ]

            try:
                target_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=req.timeout
                )

                results = {}
                for target, result in zip(req.targets, target_results):
                    if isinstance(result, Exception):
                        results[target] = TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(result),
                            started_at=created_at,
                            completed_at=datetime.now(timezone.utc).isoformat()
                        )
                    else:
                        results[target] = result

                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.DONE
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    k: v.model_dump() for k, v in results.items()
                }

                return JSONResponse({
                    "request_id": request_id,
                    "status": CommandStatus.DONE,
                    "created_at": created_at,
                    "completed_at": completed_at,
                    "results": command_results[request_id]["results"]
                })

            except asyncio.TimeoutError:
                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.FAILED
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    target: TargetResult(
                        status=CommandStatus.FAILED,
                        output=None,
                        error="Execution timeout",
                        started_at=created_at,
                        completed_at=completed_at
                    ).model_dump()
                    for target in req.targets
                }

                raise HTTPException(status_code=408, detail="Command execution timeout")

        else:
            async def execute_async():
                """后台执行任务"""
                try:
                    command_results[request_id]["status"] = CommandStatus.RUNNING

                    tasks = [
                        execute_command_on_target(target, req.command, req.params, req.timeout)
                        for target in req.targets
                    ]

                    target_results = await asyncio.gather(*tasks, return_exceptions=True)

                    results = {}
                    for target, result in zip(req.targets, target_results):
                        if isinstance(result, Exception):
                            results[target] = TargetResult(
                                status=CommandStatus.FAILED,
                                output=None,
                                error=str(result),
                                started_at=created_at,
                                completed_at=datetime.now(timezone.utc).isoformat()
                            )
                        else:
                            results[target] = result

                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.DONE
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {
                        k: v.model_dump() for k, v in results.items()
                    }

                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": CommandStatus.DONE,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "results": command_results[request_id]["results"]
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
                "message": "Command queued for async execution. Use GET /api/v1/command/{request_id}/status to check status."
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

    from core.command_router import (
        CommandRequest, CommandMode,
        get_command_router,
    )

    async def _on_command_status_change(cmd_result):
        """命令状态变更 → WebSocket 推送"""
        try:
            await connection_manager.push_command_result(cmd_result.to_dict())
        except Exception as e:
            logger.error(f"Command result push failed: {e}")

    command_router = get_command_router(on_status_change=_on_command_status_change)

    async def _command_node_executor(target: str, command: str, params: dict):
        """命令路由 → 节点执行桥接"""
        target_node_dir = os.path.join(nodes_root, target)
        if not os.path.isdir(target_node_dir):
            for name in os.listdir(nodes_root):
                if name.startswith(target) or target in name:
                    target_node_dir = os.path.join(nodes_root, name)
                    target = name
                    break

        if not os.path.isdir(target_node_dir):
            if target in connection_manager.active_devices:
                sent = await connection_manager.send_to_device(target, {
                    "type": "command",
                    "command": command,
                    "params": params,
                })
                return {"sent_to_device": target, "success": sent}
            return {"error": f"Target {target} not found"}

        fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
        if not os.path.exists(fusion_entry):
            return {"error": f"Target {target} has no fusion_entry.py"}

        node_instance = _load_node(target, target_node_dir, fusion_entry)
        if not node_instance:
            return {"error": f"Failed to load target {target}"}

        return await _execute_node(node_instance, command, params)

    command_router.set_executor(_command_node_executor)

    @router.post("/api/v1/command")
    async def dispatch_command(
        req: UnifiedCommandRequest,
        auth: dict = Depends(require_auth),
    ):
        """
        统一命令分发接口（支持多目标 sync/async 模式，兼容 UnifiedCommandRequest 格式）

        - sync: 同步等待所有目标返回
        - async: 立即返回 request_id，后台执行
        """
        # Check for device-level autonomous agent
        try:
            from core.device_agent_manager import DeviceAgentManager
            dam = DeviceAgentManager()
            device_agents = dam.get_all_agents()
            # If target device has an active agent, delegate to it
            for target_id in (req.targets or []):
                if target_id in device_agents:
                    agent = device_agents[target_id]
                    if agent.is_connected:
                        logger.info(f"Delegating command to DeviceAgent for {target_id}")
        except Exception:
            pass  # DeviceAgentManager not available, use standard routing

        if req.mode not in ("sync", "async"):
            raise HTTPException(status_code=400, detail="Invalid mode. Must be 'sync' or 'async'")

        if not req.targets:
            raise HTTPException(status_code=400, detail="Targets list cannot be empty")

        request_id = req.request_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        # Build a TaskEnvelope for consistent trace_id propagation
        envelope = envelope_from_command_request(
            command=req.command,
            targets=req.targets,
            params=req.params,
            source="api",
            mode=req.mode,
            timeout=float(req.timeout),
            request_id=request_id,
        )

        logger.info(
            "收到命令: trace_id=%s task_id=%s command=%s targets=%s mode=%s",
            envelope.trace_id, envelope.task_id, req.command, req.targets, req.mode,
        )

        command_results[request_id] = {
            "request_id": request_id,
            "command": req.command,
            "targets": req.targets,
            "params": req.params,
            "mode": req.mode,
            "status": CommandStatus.QUEUED,
            "created_at": created_at,
            "completed_at": None,
            "results": {},
        }

        if req.mode == "sync":
            command_results[request_id]["status"] = CommandStatus.RUNNING

            tasks = [
                execute_command_on_target(target, req.command, req.params, req.timeout)
                for target in req.targets
            ]

            try:
                target_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=req.timeout,
                )

                results = {}
                for target, result in zip(req.targets, target_results):
                    if isinstance(result, Exception):
                        results[target] = TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(result),
                            started_at=created_at,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    else:
                        results[target] = result

                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.DONE
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {k: v.model_dump() for k, v in results.items()}

                return JSONResponse({
                    "request_id": request_id,
                    "status": CommandStatus.DONE,
                    "created_at": created_at,
                    "completed_at": completed_at,
                    "results": command_results[request_id]["results"],
                })

            except asyncio.TimeoutError:
                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.FAILED
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    target: TargetResult(
                        status=CommandStatus.FAILED,
                        output=None,
                        error="Execution timeout",
                        started_at=created_at,
                        completed_at=completed_at,
                    ).model_dump()
                    for target in req.targets
                }
                raise HTTPException(status_code=408, detail="Command execution timeout")

        else:  # async mode
            async def _execute_async():
                try:
                    command_results[request_id]["status"] = CommandStatus.RUNNING
                    tasks = [
                        execute_command_on_target(target, req.command, req.params, req.timeout)
                        for target in req.targets
                    ]
                    target_results = await asyncio.gather(*tasks, return_exceptions=True)
                    results = {}
                    for target, result in zip(req.targets, target_results):
                        if isinstance(result, Exception):
                            results[target] = TargetResult(
                                status=CommandStatus.FAILED,
                                output=None,
                                error=str(result),
                                started_at=created_at,
                                completed_at=datetime.now(timezone.utc).isoformat(),
                            )
                        else:
                            results[target] = result
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.DONE
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {k: v.model_dump() for k, v in results.items()}
                except Exception as e:
                    logger.error(f"异步命令执行失败: {e}")
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.FAILED
                    command_results[request_id]["completed_at"] = completed_at

            asyncio.create_task(_execute_async())

            return JSONResponse({
                "request_id": request_id,
                "status": CommandStatus.QUEUED,
                "created_at": created_at,
                "message": f"Command queued. Use GET /api/v1/command/{request_id}/status to check status.",
            })

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
