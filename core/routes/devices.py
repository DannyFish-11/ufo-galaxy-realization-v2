"""
Galaxy - Device Routes
============================

Routes:
  POST   /api/v1/devices/register              - 注册设备
  POST   /api/v1/devices/status                - 更新设备状态
  GET    /api/v1/devices                       - 列出所有设备
  GET    /api/v1/devices/discover              - 按条件发现设备
  GET    /api/v1/devices/{device_id}           - 获取设备详情
  POST   /api/v1/devices/{device_id}/heartbeat - 设备心跳
  DELETE /api/v1/devices/{device_id}           - 注销设备
  POST   /api/v1/devices/cross-device          - 跨设备协同任务
  POST   /api/v1/devices/{device_id}/command   - 单设备命令 (AIP v3.0)
  POST   /api/v1/devices/parallel              - 并行多设备命令
  POST   /api/v1/devices/discover-active       - 触发主动设备发现
  GET    /api/v1/devices/{device_id}/telemetry  - 设备遥测数据
  POST   /api/v1/devices/transfer              - 跨设备文件传输
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.routes._shared import (
    connection_manager,
    registered_devices,
    node_status_cache,
    _save_registered_devices,
    broadcast_event,
)
from core.routes._models import DeviceRegisterRequest, DeviceStatusUpdate
from core.unified.device_manager import get_unified_device_manager

logger = logging.getLogger("Galaxy.API")


def _sync_device_to_capability_registry(device_info: Dict) -> int:
    """PR88: 将单个设备的能力同步注册到 CapabilityRegistry。

    每次设备注册时调用，确保新设备能力立即作为可调用工具出现在 capability bus 中。
    返回同步的能力条目数量。
    """
    count = 0
    try:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()

        device_id = device_info.get("device_id", "")
        d_name = device_info.get("device_name", device_id)
        d_type = device_info.get("device_type", "unknown")
        caps = device_info.get("capabilities", [])

        for cap in caps:
            if isinstance(cap, str):
                cap_name = cap
            elif isinstance(cap, dict):
                cap_name = cap.get("name", "")
            else:
                logger.warning(
                    "_sync_device_to_capability_registry: 设备 %s 中存在未知类型能力 %r，已跳过",
                    device_id, type(cap),
                )
                continue
            if not cap_name:
                continue
            key = f"gateway__{device_id}__{cap_name}"
            reg.register(CapabilityItem(
                name=key,
                description=f"[Gateway:{d_name}({d_type})] 设备能力: {cap_name}",
                source="gateway",
                source_id=str(device_id),
                available=True,
                metadata={"device_name": d_name, "device_type": d_type},
            ))
            count += 1
    except Exception as exc:
        logger.debug("_sync_device_to_capability_registry 失败: %s", exc)
    return count


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create device management routes router."""
    router = APIRouter()

    @router.post("/api/v1/devices/register")
    async def register_device(req: DeviceRegisterRequest):
        """注册设备

        事实源（SSOT）: UnifiedDeviceManager (UDM)。
        registered_devices 作为只读兼容缓存保留，不再是主数据源。
        """
        # Explicit pre-validation: device_id must be a non-empty string.
        # Although Pydantic enforces `device_id: str`, an empty string is still
        # technically valid at the model level, so we add a guard here to return
        # a clear 400 before any deeper processing (including AIPMessage build).
        if not req.device_id or not req.device_id.strip():
            raise HTTPException(
                status_code=400,
                detail="device_id is required and must not be empty",
            )
        device_info = {
            "device_id": req.device_id,
            "device_type": req.device_type,
            "device_name": req.device_name or f"Device-{req.device_id[:8]}",
            "capabilities": req.capabilities,
            "os_version": req.os_version,
            "app_version": req.app_version,
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "registered",
        }

        # ── SSOT: 写入 UnifiedDeviceManager ──────────────────────────────
        try:
            get_unified_device_manager().register_device_from_dict(req.device_id, device_info)
            logger.info(
                "设备已写入 UDM (SSOT): %s (%s)", req.device_id, req.device_type,
                extra={"event": "rest_register_udm", "device_id": req.device_id},
            )
        except Exception as exc:
            logger.error(
                "UDM 写入失败（设备注册继续）: %s — %s", req.device_id, exc,
                extra={"event": "rest_register_udm_error", "device_id": req.device_id},
            )

        # ── 兼容缓存：保留 registered_devices 供遗留代码只读使用 ──────────
        registered_devices[req.device_id] = device_info
        _save_registered_devices(registered_devices)

        logger.info("设备注册: %s (%s)", req.device_id, req.device_type)

        # 设备注册后立即同步能力到 CapabilityRegistry，使新设备成为可调用工具
        synced_caps = _sync_device_to_capability_registry(device_info)
        if synced_caps:
            logger.info(
                "设备 %s 已同步 %d 个能力到 CapabilityRegistry", req.device_id, synced_caps,
            )

        # PR4: 广播实时事件 — 通知 Dashboard/Windows UI 有新设备注册
        try:
            await broadcast_event("device_update", {
                "action": "register",
                "device_id": req.device_id,
                "device_name": device_info["device_name"],
                "device_type": req.device_type,
                "capabilities": req.capabilities,
            })
            if synced_caps:
                await broadcast_event("capability_update", {
                    "source": "device_register",
                    "device_id": req.device_id,
                    "synced_count": synced_caps,
                })
        except Exception as _bc_err:
            logger.debug("设备注册广播事件失败（不影响注册）: %s", _bc_err)

        return JSONResponse({
            "success": True,
            "device_id": req.device_id,
            "message": "设备注册成功",
            "server_version": "3.0.0",
            "available_nodes": list(node_status_cache.keys())[:20],
        })

    @router.post("/api/v1/devices/status")
    async def update_device_status(req: DeviceStatusUpdate):
        """更新设备状态"""
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[req.device_id]["status_detail"] = req.status

            # 广播状态更新
            await connection_manager.broadcast_status({
                "type": "device_status_update",
                "device_id": req.device_id,
                "status": req.status,
                "timestamp": datetime.now().isoformat()
            })

            return {"success": True}
        raise HTTPException(status_code=404, detail="设备未注册")

    @router.get("/api/v1/devices")
    async def list_devices():
        """列出所有设备（SSOT: UDM，兼容缓存补充遗留条目）"""
        try:
            udm = get_unified_device_manager()
            udm_devices = {d.device_id: d for d in udm.list_devices()}
        except Exception:
            udm_devices = {}

        # 以 UDM 为主，registered_devices 补充 UDM 中不存在的遗留条目
        merged: Dict = {}
        for did, info in registered_devices.items():
            merged[did] = {
                **info,
                "online": did in connection_manager.active_devices,
            }
        for did, dev in udm_devices.items():
            dev_dict = {
                "device_id": did,
                "device_name": dev.device_name,
                "device_type": dev.device_type,
                "status": dev.status,
                "capabilities": dev.capabilities,
                "metadata": dev.metadata,
                "registered_at": dev.registered_at.isoformat() if dev.registered_at else None,
                "last_seen": dev.last_heartbeat.isoformat() if dev.last_heartbeat else None,
                "online": did in connection_manager.active_devices or dev.is_online(),
            }
            merged[did] = dev_dict

        devices = list(merged.values())
        return JSONResponse({"devices": devices, "total": len(devices)})

    @router.get("/api/v1/devices/discover")
    async def discover_devices(
        device_type: Optional[str] = Query(None, description="按设备类型过滤（如 android_phone）"),
        capability: Optional[str] = Query(None, description="按能力过滤（如 GUI_SCREENSHOT）"),
        status: Optional[str] = Query(None, description="按状态过滤（registered / online / offline）"),
    ):
        """发现设备（按类型、能力、状态过滤）"""
        devices = []
        for did, info in registered_devices.items():
            is_online = did in connection_manager.active_devices
            # 类型过滤
            if device_type and info.get("device_type") != device_type:
                continue
            # 状态过滤
            effective_status = "online" if is_online else info.get("status", "registered")
            if status and effective_status != status:
                continue
            # 能力过滤
            if capability:
                caps = info.get("capabilities", [])
                if capability not in caps:
                    continue
            devices.append({**info, "online": is_online})
        return JSONResponse({"devices": devices, "total": len(devices)})

    @router.get("/api/v1/devices/{device_id}")
    async def get_device(device_id: str):
        """获取设备详情（优先从 UDM 读取）"""
        # 优先从 UDM (SSOT) 读取
        try:
            udm_dev = get_unified_device_manager().get_device(device_id)
            if udm_dev is not None:
                info = {
                    "device_id": udm_dev.device_id,
                    "device_name": udm_dev.device_name,
                    "device_type": udm_dev.device_type,
                    "status": udm_dev.status,
                    "capabilities": udm_dev.capabilities,
                    "metadata": udm_dev.metadata,
                    "registered_at": udm_dev.registered_at.isoformat() if udm_dev.registered_at else None,
                    "last_seen": udm_dev.last_heartbeat.isoformat() if udm_dev.last_heartbeat else None,
                    "online": device_id in connection_manager.active_devices or udm_dev.is_online(),
                }
                return JSONResponse(info)
        except Exception:
            pass

        # 遗留缓存兜底
        if device_id in registered_devices:
            info = registered_devices[device_id]
            info["online"] = device_id in connection_manager.active_devices
            return JSONResponse(info)

        raise HTTPException(status_code=404, detail="设备未找到")

    @router.get("/api/v1/devices/{device_id}/runtime-contract")
    async def get_device_runtime_contract(device_id: str):
        """PR-29: Return the canonical Registered Runtime Device contract.

        This read-only endpoint normalises the device into the
        :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
        contract and returns it as JSON.  Existing device endpoints are not
        modified; this is purely additive.
        """
        from contracts.registered_runtime_device import (
            from_udm_device,
            from_device_registry_record,
            RegisteredRuntimeDevice,
        )

        # Prefer UDM SSOT
        try:
            udm_dev = get_unified_device_manager().get_device(device_id)
            if udm_dev is not None:
                contract: RegisteredRuntimeDevice = from_udm_device(udm_dev)
                return JSONResponse(contract.to_dict())
        except Exception:
            pass

        # Fall back to legacy device registry
        try:
            from core.device_registry import device_registry as _dr
            legacy_dev = _dr.get(device_id)
            if legacy_dev is not None:
                contract = from_device_registry_record(legacy_dev)
                return JSONResponse(contract.to_dict())
        except Exception:
            pass

        # Final fall-back: build minimal contract from registered_devices cache
        if device_id in registered_devices:
            raw = registered_devices[device_id]
            from contracts.registered_runtime_device import build_registered_runtime_device
            contract = build_registered_runtime_device(
                device_id=device_id,
                device_name=str(raw.get("device_name", "")),
                platform=str(raw.get("device_type", "unknown")),
                device_type=str(raw.get("device_type", "")),
                capabilities=list(raw.get("capabilities", [])),
                status=str(raw.get("status", "offline")),
                metadata={k: v for k, v in raw.items() if k not in (
                    "device_id", "device_name", "device_type", "capabilities", "status"
                )},
            )
            return JSONResponse(contract.to_dict())

        raise HTTPException(status_code=404, detail="设备未找到")

    @router.post("/api/v1/devices/{device_id}/heartbeat")
    async def device_heartbeat(device_id: str):
        """设备心跳接口（REST 方式）

        Android 客户端可通过此端点上报心跳，服务端更新 ``last_seen`` 并广播在线状态。
        WebSocket 心跳由 ``/ws/device/{device_id}`` 通道处理（推荐）。
        """
        # SSOT: check UDM first, fall back to legacy cache for backward compat
        udm = get_unified_device_manager()
        udm_dev = None
        try:
            udm_dev = udm.get_device(device_id)
        except Exception:
            pass
        if udm_dev is None and device_id not in registered_devices:
            raise HTTPException(status_code=404, detail="设备未注册")

        # SSOT: 写入 UDM 心跳（优先）
        try:
            udm.heartbeat(device_id)
        except Exception as exc:
            logger.warning("UDM heartbeat 同步失败: %s — %s", device_id, exc)

        # 兼容缓存更新
        if device_id in registered_devices:
            registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[device_id]["status"] = "registered"

        await connection_manager.broadcast_status({
            "type": "device_heartbeat",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
        })

        return JSONResponse({"success": True, "device_id": device_id})

    @router.delete("/api/v1/devices/{device_id}")
    async def unregister_device(device_id: str):
        """注销设备（从注册表中移除）

        设备断开后可调用此端点彻底注销。若设备仍有活跃 WebSocket 连接，
        该连接不会被强制关闭；重连时设备需重新注册。
        """
        # SSOT: check UDM first, fall back to legacy cache for backward compat
        udm = get_unified_device_manager()
        udm_dev = None
        try:
            udm_dev = udm.get_device(device_id)
        except Exception:
            pass
        if udm_dev is None and device_id not in registered_devices:
            raise HTTPException(status_code=404, detail="设备未注册")

        # SSOT: 从 UDM 注销（优先）
        try:
            udm.unregister_device(device_id)
        except Exception as exc:
            logger.warning("UDM unregister 同步失败: %s — %s", device_id, exc)

        # 兼容缓存清理
        if device_id in registered_devices:
            del registered_devices[device_id]
            _save_registered_devices(registered_devices)

        await connection_manager.broadcast_status({
            "type": "device_unregistered",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
        })

        # PR4: 广播统一 device_update 事件，UI 可据此移除设备卡片
        try:
            await broadcast_event("device_update", {
                "action": "unregister",
                "device_id": device_id,
            })
        except Exception as _bc_err:
            logger.debug("设备注销广播事件失败: %s", _bc_err)

        logger.info("设备注销: %s", device_id)
        return JSONResponse({"success": True, "device_id": device_id})

    # ─────── 跨设备协同 ─────────

    class CrossDeviceRequest(BaseModel):
        command: str
        context: Dict = Field(default_factory=dict)

    @router.post("/api/v1/devices/cross-device")
    async def cross_device_task(req: CrossDeviceRequest):
        """跨设备协同任务（剪贴板同步、文件传输、媒体控制等）"""
        try:
            from galaxy_gateway.cross_device_coordinator import cross_device_coordinator
            result = await cross_device_coordinator.execute_cross_device_task(
                req.command, req.context
            )
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"跨设备任务失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    # ─────── 单设备命令 (AIP v3.0) ─────────

    class DeviceCommandRequest(BaseModel):
        command: str = Field(..., description="命令名称")
        params: Dict = Field(default_factory=dict, description="命令参数")
        timeout: int = Field(default=30, description="超时秒数")

    @router.post("/api/v1/devices/{device_id}/command")
    async def send_device_command(device_id: str, req: DeviceCommandRequest):
        """发送 AIP v3.0 格式命令到单个设备"""
        if device_id not in registered_devices:
            raise HTTPException(status_code=404, detail="设备未注册")

        command_id = str(uuid.uuid4())[:8]
        message = {
            "version": "3.0",
            "message_id": command_id,
            "type": "CONTROL_COMMAND",
            "device_id": device_id,
            "payload": {
                "command": req.command,
                "params": req.params,
            },
            "timestamp": datetime.now().isoformat(),
        }

        sent = await connection_manager.send_to_device(device_id, message)
        if sent:
            return JSONResponse({
                "success": True,
                "command_id": command_id,
                "device_id": device_id,
                "message": f"命令 {req.command} 已发送",
            })

        return JSONResponse({
            "success": False,
            "command_id": command_id,
            "error": "设备离线或发送失败",
        }, status_code=503)

    # ─────── 并行多设备命令 ─────────

    class ParallelCommandItem(BaseModel):
        device_id: str
        command: str
        params: Dict = Field(default_factory=dict)

    class ParallelCommandRequest(BaseModel):
        commands: List[ParallelCommandItem]
        timeout: int = Field(default=30, description="整体超时秒数")

    @router.post("/api/v1/devices/parallel")
    async def parallel_device_commands(req: ParallelCommandRequest):
        """并行发送命令到多个设备"""
        async def _send_one(item: ParallelCommandItem):
            cmd_id = str(uuid.uuid4())[:8]
            msg = {
                "version": "3.0",
                "message_id": cmd_id,
                "type": "CONTROL_COMMAND",
                "device_id": item.device_id,
                "payload": {"command": item.command, "params": item.params},
                "timestamp": datetime.now().isoformat(),
            }
            try:
                sent = await connection_manager.send_to_device(item.device_id, msg)
                return {"device_id": item.device_id, "command_id": cmd_id, "sent": sent}
            except Exception as e:
                return {"device_id": item.device_id, "command_id": cmd_id, "sent": False, "error": str(e)}

        results = await asyncio.gather(
            *[_send_one(cmd) for cmd in req.commands],
            return_exceptions=True,
        )

        processed = []
        for r in results:
            if isinstance(r, Exception):
                processed.append({"error": str(r), "sent": False})
            else:
                processed.append(r)

        return JSONResponse({
            "success": True,
            "total": len(req.commands),
            "results": processed,
        })

    # ─────── 主动设备发现 ─────────

    @router.post("/api/v1/devices/discover-active")
    async def trigger_device_discovery():
        """触发主动设备发现（mDNS/UPnP 扫描）"""
        try:
            from core.device_orchestrator import get_device_orchestrator
            orchestrator = get_device_orchestrator()
            devices = await orchestrator.discover_devices()
            return JSONResponse({
                "success": True,
                "discovered": devices if isinstance(devices, list) else [],
                "message": "设备发现完成",
            })
        except ImportError:
            # Fallback: 返回已注册设备
            devices = []
            for did, info in registered_devices.items():
                devices.append({
                    "device_id": did,
                    "device_type": info.get("device_type", "unknown"),
                    "device_name": info.get("device_name", did),
                    "online": did in connection_manager.active_devices,
                })
            return JSONResponse({
                "success": True,
                "discovered": devices,
                "message": "使用注册表回退（device_orchestrator 不可用）",
            })
        except Exception as e:
            logger.error(f"设备发现失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    # ─────── 设备遥测 ─────────

    @router.get("/api/v1/devices/{device_id}/telemetry")
    async def get_device_telemetry(device_id: str):
        """获取设备遥测数据（CPU、内存、电量等）"""
        if device_id not in registered_devices:
            raise HTTPException(status_code=404, detail="设备未注册")

        info = registered_devices[device_id]
        telemetry = {
            "device_id": device_id,
            "online": device_id in connection_manager.active_devices,
            "last_seen": info.get("last_seen"),
            "status": info.get("status", "unknown"),
            "metrics": info.get("metrics", {}),
            "capabilities": info.get("capabilities", []),
        }
        return JSONResponse(telemetry)

    # ─────── 跨设备文件传输 ─────────

    class FileTransferRequest(BaseModel):
        source_device: str = Field(..., description="源设备 ID")
        target_device: str = Field(..., description="目标设备 ID")
        file_path: str = Field(..., description="源设备上的文件路径")
        target_path: str = Field(default="", description="目标设备上的保存路径（空则使用默认）")

    @router.post("/api/v1/devices/transfer")
    async def transfer_file(req: FileTransferRequest):
        """跨设备文件传输"""
        for did in [req.source_device, req.target_device]:
            if did not in registered_devices:
                raise HTTPException(status_code=404, detail=f"设备 {did} 未注册")

        transfer_id = str(uuid.uuid4())[:8]
        transfer_msg = {
            "version": "3.0",
            "message_id": transfer_id,
            "type": "FILE_TRANSFER",
            "device_id": req.source_device,
            "payload": {
                "source_device": req.source_device,
                "target_device": req.target_device,
                "file_path": req.file_path,
                "target_path": req.target_path,
            },
            "timestamp": datetime.now().isoformat(),
        }

        sent = await connection_manager.send_to_device(req.source_device, transfer_msg)
        return JSONResponse({
            "success": sent,
            "transfer_id": transfer_id,
            "source": req.source_device,
            "target": req.target_device,
            "file": req.file_path,
            "message": "传输请求已发送" if sent else "源设备离线",
        })

    return router
