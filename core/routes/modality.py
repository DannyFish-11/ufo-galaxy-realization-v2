"""core/routes/modality.py — 全模态能力协商的只读观测入口
==========================================================

  GET /api/v1/modality/plan[?tier=A|B]
    当前(或指定)档位每个模态该走原生/桥接/不可用,及原因。前端"感知·SENSES"
    面板据此如实展示,而不是猜。

协商本体见 core.modality_capability(所有循环自适配的唯一入口)。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger("Galaxy.Routes.Modality")

router = APIRouter(prefix="/api/v1/modality", tags=["modality"])


@router.get("/plan")
async def modality_plan(tier: Optional[str] = None) -> Dict[str, Any]:
    """当前(或指定)档位的全模态协商计划:看/听/说/看视频各自 native/bridge/unavailable。"""
    try:
        from core.modality_capability import asr_bridge_available, negotiate, tts_bridge_available

        plan = negotiate(tier=tier)
        return {
            "success": True,
            "plan": plan.to_dict(),
            "bridges": {"asr": asr_bridge_available(), "tts": tts_bridge_available()},
        }
    except Exception as exc:  # noqa: BLE001 — 观测端点不该因协商异常而 500
        logger.debug("modality plan 协商失败: %s", exc)
        return {"success": False, "error": str(exc)}
