"""core/routes/computer_use.py — computer use 闭环的 REST 入口
=================================================================

  POST /api/v1/computer-use/task
    body: {
      "instruction": "打开记事本并输入你好",   # 必填:自然语言任务
      "max_steps": 15,                          # 可选:步数上限(默认 GALAXY_CU_MAX_STEPS)
      "dry_run": false,                         # 可选:true=只规划第一步不执行
      "node_id": "Node_36_UIAWindows"           # 可选:桌面操作节点(白名单校验)
    }
    resp: { success, stop_reason, message, steps: [...] }

  GET /api/v1/computer-use/status → 闭环是否可用(开关 + 感知新鲜度)。

循环本体见 core.computer_use_loop(感知→规划→安全门→执行→再感知)。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Routes.ComputerUse")

router = APIRouter(prefix="/api/v1/computer-use", tags=["computer-use"])

# 与 ui_act 同一约束:node_id 来自不可信请求体,严格白名单形状防路径穿越。
_NODE_ID_RE = re.compile(r"^Node_[A-Za-z0-9_]{1,64}$")


class ComputerUseTaskRequest(BaseModel):
    instruction: str = Field(..., description="自然语言任务")
    max_steps: Optional[int] = Field(default=None, ge=1, le=50)
    dry_run: bool = False
    node_id: str = ""


@router.post("/task")
async def computer_use_task(req: ComputerUseTaskRequest) -> Dict[str, Any]:
    """跑一个 computer use 任务闭环(感知→规划→执行→再感知,直到完成/失败)。"""
    from core.computer_use_loop import run_computer_use_task

    node_id = req.node_id.strip()
    if node_id and not _NODE_ID_RE.match(node_id):
        return {"success": False, "stop_reason": "bad_request", "message": "非法 node_id", "steps": []}

    kwargs: Dict[str, Any] = {"max_steps": req.max_steps, "dry_run": req.dry_run}
    if node_id:
        kwargs["node_id"] = node_id
    return await run_computer_use_task(req.instruction, **kwargs)


@router.get("/status")
async def computer_use_status() -> Dict[str, Any]:
    """闭环可用性:总开关 + 屏幕感知是否有新鲜帧(如实报,不谎报健康)。"""
    from core.computer_use_loop import computer_use_enabled

    screen_fresh = False
    try:
        from core.perception.desktop_perception_store import get_desktop_perception_store

        screen_fresh = bool(get_desktop_perception_store().snapshot_media().get("screen_b64"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("computer-use status 感知探测失败: %s", exc)

    enabled = computer_use_enabled()
    return {
        "enabled": enabled,
        "screen_perception_fresh": screen_fresh,
        "ready": enabled and screen_fresh,
        "hint": (
            ""
            if (enabled and screen_fresh)
            else "需要:GALAXY_COMPUTER_USE 未关 + 桌面覆盖层屏幕采集已授权(有新鲜屏幕帧)"
        ),
    }
