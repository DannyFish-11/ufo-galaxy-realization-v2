"""
UFO Galaxy - Twin Commander Routes
====================================

Full CRUD and control API for the Digital Twin Engine.

Routes:
  GET    /api/v1/twin/status                     - 全局孪生状态
  POST   /api/v1/twin/create                     - 创建孪生体
  GET    /api/v1/twin/{twin_id}                  - 获取孪生体详情
  DELETE /api/v1/twin/{twin_id}                  - 删除孪生体
  POST   /api/v1/twin/{twin_id}/couple           - 耦合到物理设备
  POST   /api/v1/twin/{twin_id}/decouple         - 解耦
  POST   /api/v1/twin/{twin_id}/switch-mode      - 切换耦合模式
  POST   /api/v1/twin/{twin_id}/simulate         - 模拟操作
  GET    /api/v1/twin/{twin_id}/drift            - 漂移报告
  GET    /api/v1/twin/{twin_id}/predict          - 预测未来状态
  POST   /api/v1/twin/scenario                   - 批量场景模拟
"""

import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.auth import require_auth

logger = logging.getLogger("UFO-Galaxy.API")


# ── Request Models ──

class TwinCreateRequest(BaseModel):
    device_id: str
    device_type: str = "generic"
    initial_state: Optional[Dict] = None
    drift_threshold: float = 0.1


class TwinSimulateRequest(BaseModel):
    action: str
    params: Dict = Field(default_factory=dict)


class TwinSwitchModeRequest(BaseModel):
    mode: str  # coupled / decoupled / hybrid


class TwinScenarioRequest(BaseModel):
    actions: list  # [{"device_id": ..., "action": ..., "params": {...}}]


# ── Router ──

def create_router(service_manager=None, config=None) -> APIRouter:
    """Create twin commander routes."""
    router = APIRouter()

    def _get_engine():
        from core.digital_twin_engine import get_digital_twin_engine
        return get_digital_twin_engine()

    @router.get("/api/v1/twin/status")
    async def twin_global_status():
        """全局孪生引擎状态"""
        try:
            engine = _get_engine()
            return JSONResponse(engine.get_global_state())
        except Exception as e:
            return JSONResponse({"error": str(e), "twins": {}})

    @router.post("/api/v1/twin/create")
    async def twin_create(req: TwinCreateRequest, auth: dict = Depends(require_auth)):
        """创建数字孪生体"""
        engine = _get_engine()

        # 检查是否已存在
        existing = engine.get_twin_by_device(req.device_id)
        if existing:
            return JSONResponse({
                "success": False,
                "error": f"设备 {req.device_id} 已有孪生体: {existing.twin_id}",
            }, status_code=409)

        twin = engine.create_twin(
            device_id=req.device_id,
            device_type=req.device_type,
            initial_state=req.initial_state,
            drift_threshold=req.drift_threshold,
        )

        return JSONResponse({
            "success": True,
            "twin_id": twin.twin_id,
            "device_id": twin.device_id,
            "device_type": twin.device_type,
            "status": twin.status.value,
        })

    @router.get("/api/v1/twin/{twin_id}")
    async def twin_detail(twin_id: str):
        """获取孪生体详情"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")
        return JSONResponse(twin.get_state())

    @router.delete("/api/v1/twin/{twin_id}")
    async def twin_delete(twin_id: str, auth: dict = Depends(require_auth)):
        """删除孪生体"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        # 先解耦再删除
        await twin.decouple()
        engine.twins.pop(twin_id, None)
        engine._by_device.pop(twin.device_id, None)

        return JSONResponse({"success": True, "deleted": twin_id})

    @router.post("/api/v1/twin/{twin_id}/couple")
    async def twin_couple(twin_id: str, auth: dict = Depends(require_auth)):
        """耦合到物理设备（使用 device_communication）"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        try:
            from core.device_communication import device_comm

            async def state_fetcher():
                conn = device_comm.get_connection(twin.device_id)
                if conn:
                    return conn.get("last_state", {})
                return {}

            from core.digital_twin_engine import CouplingMode
            await twin.couple(state_fetcher, mode=CouplingMode.COUPLED)
            return JSONResponse({
                "success": True,
                "twin_id": twin_id,
                "coupling_mode": twin.coupling_mode.value,
                "status": twin.status.value,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": f"耦合失败: {str(e)}",
            }, status_code=500)

    @router.post("/api/v1/twin/{twin_id}/decouple")
    async def twin_decouple(twin_id: str, auth: dict = Depends(require_auth)):
        """解耦"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        await twin.decouple()
        return JSONResponse({
            "success": True,
            "twin_id": twin_id,
            "coupling_mode": twin.coupling_mode.value,
        })

    @router.post("/api/v1/twin/{twin_id}/switch-mode")
    async def twin_switch_mode(
        twin_id: str, req: TwinSwitchModeRequest,
        auth: dict = Depends(require_auth),
    ):
        """切换耦合模式"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        from core.digital_twin_engine import CouplingMode
        mode_map = {
            "coupled": CouplingMode.COUPLED,
            "decoupled": CouplingMode.DECOUPLED,
            "hybrid": CouplingMode.HYBRID,
        }
        new_mode = mode_map.get(req.mode.lower())
        if not new_mode:
            raise HTTPException(status_code=400, detail=f"无效模式: {req.mode}")

        await twin.switch_mode(new_mode)
        return JSONResponse({
            "success": True,
            "twin_id": twin_id,
            "coupling_mode": twin.coupling_mode.value,
        })

    @router.post("/api/v1/twin/{twin_id}/simulate")
    async def twin_simulate(twin_id: str, req: TwinSimulateRequest):
        """模拟操作"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        result = await twin.simulate_action(req.action, req.params)
        return JSONResponse({
            "twin_id": result.twin_id,
            "action": result.action,
            "predicted_state": result.predicted_state,
            "success_probability": result.success_probability,
            "risks": result.risks,
            "side_effects": result.side_effects,
        })

    @router.get("/api/v1/twin/{twin_id}/drift")
    async def twin_drift_report(twin_id: str):
        """漂移报告"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        return JSONResponse({
            "twin_id": twin_id,
            "drift_threshold": twin.drift_threshold,
            "drift_history": [
                {
                    "twin_id": d.twin_id,
                    "drifted_properties": d.drifted_properties,
                    "max_drift": d.max_drift,
                    "severity": d.severity,
                }
                for d in twin.drift_history[-20:]  # 最近 20 条
            ],
        })

    @router.get("/api/v1/twin/{twin_id}/predict")
    async def twin_predict(twin_id: str, steps: int = 5):
        """预测未来状态"""
        engine = _get_engine()
        twin = engine.get_twin(twin_id)
        if not twin:
            raise HTTPException(status_code=404, detail=f"孪生体不存在: {twin_id}")

        predictions = await twin.predict_future_state(steps=steps)
        return JSONResponse({
            "twin_id": twin_id,
            "predictions": predictions,
        })

    @router.post("/api/v1/twin/scenario")
    async def twin_scenario(req: TwinScenarioRequest, auth: dict = Depends(require_auth)):
        """批量场景模拟"""
        engine = _get_engine()
        results = await engine.simulate_scenario(req.actions)
        return JSONResponse({
            "results": [
                {
                    "twin_id": r.twin_id,
                    "action": r.action,
                    "predicted_state": r.predicted_state,
                    "success_probability": r.success_probability,
                    "risks": r.risks,
                    "side_effects": r.side_effects,
                }
                for r in results
            ]
        })

    return router
