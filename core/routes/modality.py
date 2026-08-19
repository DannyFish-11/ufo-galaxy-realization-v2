"""core/routes/modality.py — 全模态能力协商的只读观测入口
==========================================================

  GET /api/v1/modality/plan[?tier=A|B][&device_id=...]
    当前(或指定)档位每个模态该走原生/桥接/不可用,及原因。前端"感知·SENSES"
    面板据此如实展示,而不是猜。
  GET /api/v1/modality/matrix
    所有档位 × 全模态的协商矩阵。
  GET /api/v1/modality/devices
    所有已注册设备 × 全模态的协商矩阵 —— 回答"这件事该派给哪台设备"。
  GET /api/v1/modality/providers
    所有云端 provider × 全模态的声明矩阵 —— 回答"这件事该交给哪一家"。

协商本体见 core.modality_capability(所有循环自适配的唯一入口)。

关于 device 维与 locus 维
------------------------
协商有四维:模型声明 × 服务现实 × **设备硬件** × **推理归属**。第三维回答"这次要在
哪台设备上做" —— 同一个模型在桌面上能看能听,到了手表上就只剩听。第四维回答"这次
由谁来想" —— 本地档位没有视觉模型、而这一轮交给一家能看的云端时,视觉是可用的。

两个维度都是**不传就完全等同于没有它**:不传 device_id 不做设备门控,不传 locus
按本地那份能力源算。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger("Galaxy.Routes.Modality")

router = APIRouter(prefix="/api/v1/modality", tags=["modality"])


@router.get("/plan")
async def modality_plan(
    tier: Optional[str] = None,
    device_id: Optional[str] = None,
    locus: Optional[str] = None,
) -> Dict[str, Any]:
    """当前(或指定)档位、(可选)指定设备、(可选)指定推理归属上的全模态协商计划。

    ``device_id`` 省略 = 不区分设备(本机),结果与加入设备维之前逐字段相同。
    给了就叠加该设备的硬件门控:后端能做、但设备没申报所需能力时如实降为
    ``unavailable`` 并把 ``limited_by`` 标成 ``device`` —— 这样面板能区分
    "换个模型就能用"和"换台设备才能用",而不必去猜那句中文说的是哪种。

    ``locus`` 省略 = 按本地档位算。给一家 provider 名则改用那一家的模态声明当能力源,
    此时 ``limited_by`` 会报 ``provider``(得换一家)而不是 ``serving``(开个环境变量
    就行)—— 后者对云端毫无意义,报出来只会让人去开一个根本不存在的开关。
    """
    try:
        from core.modality_capability import asr_bridge_available, negotiate, tts_bridge_available

        plan = negotiate(tier=tier, device=device_id or None, locus=locus or None)
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


@router.get("/providers")
async def modality_provider_matrix() -> Dict[str, Any]:
    """所有云端 provider × 全模态的声明矩阵 —— "这件事该交给哪一家"。

    与 ``/devices`` 对称:那张表回答"换台设备能得到什么",这张回答"换一家能得到
    什么"。``native`` 一栏只数**原生**支持的家,不数走桥的 —— 桥跑在本机,与选哪家
    无关;这份名单要回答的是"换哪家能省掉那道桥"。

    ``declared=false`` 表示这一格是从 ``PROVIDER_REGISTRY`` 已有字段**派生**的,
    可被真机探测(``scripts/probe_models.py``)推翻;``true`` 是 spec 里显式写死的。
    这两件事在面板上必须能分开看,否则无从知道哪些结论还没被验证过。
    """
    try:
        from core.provider_modality import provider_modality_matrix

        return {"success": True, **provider_modality_matrix()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("modality provider matrix 协商失败: %s", exc)
        return {"success": False, "error": "modality provider matrix failed"}
