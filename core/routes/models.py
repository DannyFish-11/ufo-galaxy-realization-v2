"""core/routes/models.py — 模型目录 API（AB 档位 + 能力 + 实时状态）
=====================================================================

面板/克隆界面/config 全部从这里的 catalog 派生，不再各自硬编码。三个端点：

  GET  /api/v1/models/catalog  —— 档位 + 每档模型 + 能力 + 有效 IO（静态目录，
                                  派生自 core.model_catalog）+ 当前档位。
  GET  /api/v1/models/status   —— 实时状态：每个本地模型是否已安装/可用
                                  （探 Ollama /api/tags + /api/show 二次核实）。
                                  与 catalog 分开，让前端可【后台静默刷新】状态而
                                  不重取整份目录，也不阻塞首屏。
  POST /api/v1/models/tier     —— 选定档位（+可选档内主脑）；写 OLLAMA_MODEL、
                                  持久化档位、并对未安装的本地模型触发后台拉取。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.Routes.Models")

router = APIRouter(prefix="/api/v1/models", tags=["models"])


def _ollama_base() -> str:
    raw = os.environ.get("OLLAMA_URL", "http://localhost:11434").strip()
    base = raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
    return base.rstrip("/")


@router.get("/catalog")
async def get_catalog() -> Dict[str, Any]:
    """完整模型目录（档位 + 模型 + 能力 + 有效 IO + 当前档位）。"""
    from core.model_catalog import catalog_snapshot
    snap = catalog_snapshot()
    # 当前主脑（供面板高亮）
    snap["current_main_brain"] = os.environ.get("OLLAMA_MODEL", "")
    return snap


def _probe_installed() -> Dict[str, Dict[str, Any]]:
    """探测本地 Ollama 已安装且【可用】的模型（/api/tags 列名 + /api/show 二次核实）。

    只看 /api/tags 会把"能列名但打不开的残缺 manifest"误判为已装（真机复现过：
    会永久拦住后续重试）。故对每个候选再 /api/show 核实一次。
    """
    import httpx
    from core.model_catalog import choice_order, get_model

    base = _ollama_base()
    installed_names: List[str] = []
    reachable = False
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3.0)
        if r.status_code == 200:
            reachable = True
            installed_names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Ollama /api/tags 不可达: %s", exc)

    out: Dict[str, Dict[str, Any]] = {}
    for tag in choice_order():
        spec = get_model(tag)
        if spec is None or spec.source != "local":
            continue
        root = tag.split(":")[0]
        matched = next(
            (h for h in installed_names
             if h == tag or h.startswith(tag + ":") or h.split(":")[0] == root),
            None,
        )
        status = "absent"
        if matched:
            status = "installed"
            # 二次核实可用性
            try:
                sr = httpx.post(f"{base}/api/show", json={"name": matched}, timeout=5.0)
                if sr.status_code != 200:
                    status = "broken"  # 列名在、打不开 → 当未装
            except Exception:  # noqa: BLE001
                status = "installed"  # 核实失败不武断降级，保留 installed
        out[tag] = {"status": status, "ollama_reachable": reachable, "matched": matched or ""}
    return out


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """实时安装/可用状态（前端后台静默刷新用）。"""
    import asyncio
    installed = await asyncio.to_thread(_probe_installed)
    return {"models": installed}


class TierSelectRequest(BaseModel):
    tier: str
    main_brain: Optional[str] = None  # single 档内可指定；不给则取档内第一个本地模型


@router.post("/tier")
async def select_tier(req: TierSelectRequest) -> Dict[str, Any]:
    """选定档位：持久化 + 写 OLLAMA_MODEL + 对未安装的本地模型后台拉取。"""
    from core.model_catalog import save_tier, tier_models, get_tier

    tier = get_tier(req.tier)
    if tier is None:
        return {"success": False, "error": f"未知档位: {req.tier}"}

    chosen = save_tier(req.tier, main_brain=req.main_brain)

    # 对该档内所有【本地】模型触发后台拉取（缺失才拉，不阻塞）。
    pulled: List[str] = []
    try:
        from core.model_selection import background_pull
        for spec in tier_models(req.tier):
            if spec.source == "local":
                background_pull(spec.tag)
                pulled.append(spec.tag)
    except Exception as exc:  # noqa: BLE001
        logger.debug("档位切换后台拉取触发失败(非致命): %s", exc)

    # 热刷新 LLM 路由，让新主脑即时生效（无需重启）。
    try:
        from core.multi_llm_router import refresh_llm_router
        await refresh_llm_router()
    except Exception:  # noqa: BLE001
        pass

    return {
        "success": True,
        "tier": req.tier,
        "main_brain": chosen,
        "pulling": pulled,
    }
