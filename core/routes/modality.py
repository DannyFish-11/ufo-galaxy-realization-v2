"""core/routes/modality.py — 全模态能力协商的只读观测入口
==========================================================

  GET /api/v1/modality/plan[?tier=A|B][&device_id=...]
    当前(或指定)档位每个模态该走原生/桥接/不可用,及原因。前端"感知·SENSES"
    面板据此如实展示,而不是猜。
  GET /api/v1/modality/matrix
    所有档位 × 全模态的协商矩阵。
  GET /api/v1/modality/devices
    所有已注册设备 × 全模态的协商矩阵 —— 回答"这件事该派给哪台设备"。

协商本体见 core.modality_capability(所有循环自适配的唯一入口)。

关于 device 维
--------------
协商有三维:模型声明 × 服务现实 × **设备硬件**。前两维回答"这套后端能不能做",
第三维回答"这次要在哪台设备上做" —— 同一个模型在桌面上能看能听,到了手表上
就只剩听。不传 device_id 时行为与只有两维时完全一致(不做设备门控)。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger("Galaxy.Routes.Modality")

router = APIRouter(prefix="/api/v1/modality", tags=["modality"])


@router.get("/plan")
async def modality_plan(tier: Optional[str] = None, device_id: Optional[str] = None) -> Dict[str, Any]:
    """当前(或指定)档位、(可选)指定设备上的全模态协商计划。

    ``device_id`` 省略 = 不区分设备(本机),结果与加入设备维之前逐字段相同。
    给了就叠加该设备的硬件门控:后端能做、但设备没申报所需能力时如实降为
    ``unavailable`` 并把 ``limited_by`` 标成 ``device`` —— 这样面板能区分
    "换个模型就能用"和"换台设备才能用",而不必去猜那句中文说的是哪种。
    """
    try:
        from core.modality_capability import asr_bridge_available, negotiate, tts_bridge_available

        plan = negotiate(tier=tier, device=device_id or None)
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
        from core.modality_capability import asr_bridge_available, negotiate, tts_bridge_available
        from core.model_catalog import all_tiers, load_tier

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


@router.get("/devices")
async def modality_device_matrix(tier: Optional[str] = None) -> Dict[str, Any]:
    """所有已注册设备 × 全模态的协商矩阵 —— "这件事该派给哪台设备"。

    档位矩阵回答的是"换模型能得到什么",这个回答的是"换设备能得到什么"。跨设备
    派发要挑一台能看的设备时,看的就是这张表;没有它,中心只能派出去再等超时。

    ``gating_active=false`` 的设备表示它没有申报模态相关能力 —— 那不是"它什么都
    不能做",而是"没人填过它的能力表"。这两件事在面板上必须能分开看,否则会
    误以为设备坏了。
    """
    try:
        from core.modality_capability import device_modality_matrix

        return {"success": True, **device_modality_matrix(tier=tier)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("modality device matrix 协商失败: %s", exc)
        return {"success": False, "error": "modality device matrix failed"}
