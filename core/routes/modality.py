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
        # 安全:异常详情只进服务端日志,不回传给客户端(CodeQL: information exposure)。
        logger.warning("modality plan 协商失败: %s", exc)
        return {"success": False, "error": "modality negotiation failed"}


@router.get("/matrix")
async def modality_matrix() -> Dict[str, Any]:
    """所有档位 × 全模态的协商矩阵——A 档/B 档各模态怎么走一目了然。

    直接回答"两档都要考虑":同一份自适配逻辑,A 档(Gemma:说走 TTS 桥)与
    B 档(MiniCPM-o:说原生)每个模态的 native/bridge/unavailable 并排呈现。
    """
    try:
        from core.model_catalog import all_tiers, load_tier
        from core.modality_capability import asr_bridge_available, negotiate, tts_bridge_available

        active = load_tier()
        tiers = []
        for t in all_tiers():
            key = getattr(t, "key", "") or getattr(t, "name", "")
            tiers.append(
                {
                    "tier": key,
                    "label": getattr(t, "label", "") or getattr(t, "name", ""),
                    "active": key == active,
                    "plan": negotiate(tier=key).to_dict(),
                }
            )
        return {
            "success": True,
            "active_tier": active,
            "tiers": tiers,
            "bridges": {"asr": asr_bridge_available(), "tts": tts_bridge_available()},
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("modality matrix 协商失败: %s", exc)
        return {"success": False, "error": "modality matrix failed"}
