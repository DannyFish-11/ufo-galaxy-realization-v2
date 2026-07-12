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

# /status 三层延迟防线(真机日志实证驱动):
#   1) stale-while-revalidate:只要有过任何一次结果,请求【立即】返回缓存(过期则
#      标 stale 并拉起一个后台刷新任务),永远不让 HTTP 请求等在探测后面。此前只有
#      "TTL 内直返"——Ollama 冷加载时单次探测可爬到 10s+,TTL(3s)一过,每一批并发
#      轮询都整批排队等完整探测(真机:6 条请求同时 11.4s)。
#   2) 探测本身并行化:此前 /api/show 逐模型【串行】,目录 4 个本地模型 × 2s 超时
#      再加 /api/tags 3s,最坏 11s——正是真机看到的量级。现改 async 并发 gather,
#      最坏 ≈ max(单次超时) 而非求和。
#   3) 总预算封顶:整个探测包 GALAXY_MODELS_PROBE_BUDGET(默认 4s)的 wait_for;
#      超时返回全目录 unknown 态(键集恒等于目录,形状不破),后台继续补真值。
import asyncio as _asyncio
import time as _time

_STATUS_TTL = float(os.environ.get("GALAXY_MODELS_STATUS_TTL", "3.0") or "3.0")
_PROBE_BUDGET = float(os.environ.get("GALAXY_MODELS_PROBE_BUDGET", "4.0") or "4.0")
_status_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_status_lock = _asyncio.Lock()
_refresh_task: Any = None  # 在飞的后台刷新任务(同一时刻至多一个)


def _ollama_base() -> str:
    # ollama 地址解析收口到 core.ollama_endpoint 唯一属主(空值/缺协议头都兜底)。
    from core.ollama_endpoint import resolve_ollama_base_url
    return resolve_ollama_base_url()


@router.get("/catalog")
async def get_catalog() -> Dict[str, Any]:
    """完整模型目录（档位 + 模型 + 能力 + 有效 IO + 当前档位）。"""
    from core.model_catalog import catalog_snapshot
    snap = catalog_snapshot()
    # 当前主脑（供面板高亮）
    snap["current_main_brain"] = os.environ.get("OLLAMA_MODEL", "")
    return snap


def _catalog_placeholder(status: str = "unknown") -> Dict[str, Dict[str, Any]]:
    """全目录占位结果(探测超预算/彻底失败时用):键集恒等于目录本地模型集,
    形状不破(面板与测试都依赖 models 键集 == choice_order 本地项)。"""
    from core.model_catalog import choice_order, get_model
    out: Dict[str, Dict[str, Any]] = {}
    for tag in choice_order():
        spec = get_model(tag)
        if spec is None or spec.source != "local":
            continue
        out[tag] = {"status": status, "ollama_reachable": False, "matched": ""}
    return out


async def _probe_installed_async() -> Dict[str, Dict[str, Any]]:
    """探测本地 Ollama 已安装且【可用】的模型（/api/tags 列名 + /api/show 二次核实）。

    只看 /api/tags 会把"能列名但打不开的残缺 manifest"误判为已装（真机复现过：
    会永久拦住后续重试）。故对每个候选再 /api/show 核实一次——**并行**核实:
    Ollama 冷加载时每个调用都在超时线下爬行,串行会把延迟累加成 10s+。
    """
    import httpx
    from core.model_catalog import choice_order, get_model

    base = _ollama_base()
    installed_names: List[str] = []
    reachable = False
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(f"{base}/api/tags")
            if r.status_code == 200:
                reachable = True
                installed_names = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ollama /api/tags 不可达: %s", exc)

        out: Dict[str, Dict[str, Any]] = {}
        to_verify: List[tuple] = []
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
            out[tag] = {
                "status": "installed" if matched else "absent",
                "ollama_reachable": reachable,
                "matched": matched or "",
            }
            if matched:
                to_verify.append((tag, matched))

        async def _verify(tag: str, matched: str) -> None:
            try:
                sr = await client.post(
                    f"{base}/api/show", json={"name": matched}, timeout=2.0
                )
                if sr.status_code != 200:
                    out[tag]["status"] = "broken"  # 列名在、打不开 → 当未装
            except Exception:  # noqa: BLE001
                pass  # 核实失败不武断降级，保留 installed

        if to_verify:
            await _asyncio.gather(*(_verify(t, m) for t, m in to_verify))
    return out


def _probe_installed() -> Dict[str, Dict[str, Any]]:
    """同步兼容封装(旧调用点/测试仍可用);内部走并行异步探测。"""
    return _asyncio.run(_probe_installed_async())


def _kick_refresh() -> None:
    """拉起(至多一个)后台刷新任务:探测在后台跑,任何 HTTP 请求都不等它。"""
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return
    async def _refresh() -> None:
        global _refresh_task
        try:
            # 后台刷新不阻塞任何请求,预算放宽到前台的 3 倍:Ollama 冷加载爬行时
            # (真机:每个调用都在超时线下爬),前台预算内探不完,后台得能兜住,
            # 否则缓存永远填不上、面板一直显示占位态。探测自身有单调用超时,
            # 天然有界(tags 3s + show 2s 并行 ≈ 最坏 5-6s)。
            data = await _asyncio.wait_for(
                _probe_installed_async(), timeout=_PROBE_BUDGET * 3
            )
            _status_cache["data"] = data
            _status_cache["ts"] = _time.monotonic()
        except Exception as exc:  # noqa: BLE001
            logger.debug("models/status 后台刷新失败/超预算(下次请求再试): %s", exc)
        finally:
            _refresh_task = None
    try:
        _refresh_task = _asyncio.get_running_loop().create_task(_refresh())
    except RuntimeError:  # 无运行中事件循环(同步测试环境)则跳过后台刷新
        _refresh_task = None


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """实时安装/可用状态（前端后台静默刷新用）。

    短 TTL 缓存 + single-flight:窗口(默认 3s)内的重复/并发请求直接返回上次结果,
    不再各自重新探测 Ollama。这样面板高频轮询(且多组件并发)不会把后端拖到每次
    1s+;GALAXY_MODELS_STATUS_TTL 可调缓存时长。
    """
    now = _time.monotonic()
    cached = _status_cache["data"]
    if cached is not None:
        stale = (now - float(_status_cache["ts"])) >= _STATUS_TTL
        if stale:
            _kick_refresh()  # stale-while-revalidate:后台刷,本请求不等
        return {"models": cached, "cached": True, "stale": stale}
    # 首次(进程内从未探测过):唯一一次同步探测,也有总预算封顶
    async with _status_lock:
        cached = _status_cache["data"]
        if cached is not None:  # 等锁期间别的请求已填上
            return {"models": cached, "cached": True}
        try:
            installed = await _asyncio.wait_for(
                _probe_installed_async(), timeout=_PROBE_BUDGET
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("models/status 首次探测超预算(%s),返回占位并后台续探", exc)
            _kick_refresh()
            return {"models": _catalog_placeholder(), "probing": True}
        _status_cache["data"] = installed
        _status_cache["ts"] = _time.monotonic()
        return {"models": installed}


class ProviderVerifyRequest(BaseModel):
    provider: Optional[str] = None   # 提供商名(如 "deepseek");与 env_key 二选一
    env_key: Optional[str] = None    # 或环境变量键(如 "DEEPSEEK_API_KEY"),后端反查


@router.post("/verify-provider")
async def verify_provider(req: ProviderVerifyRequest) -> Dict[str, Any]:
    """真实连通性验证:用该提供商的 default_model 发一次 1-token 试调。

    面板"保存 API Key"之后调这里,把「保存成功」升级成「保存且**能用**」——
    此前保存只代表写进了 .env,Key 错的/网络不通的要等到真正对话失败才暴露,
    用户没法判断"到底好了没有"。试调成本≈零(max_tokens=1),15s 封顶。
    """
    from core.multi_llm_router import PROVIDER_REGISTRY, get_llm_router
    router_ = get_llm_router()

    name = (req.provider or "").strip().lower()
    if not name and req.env_key:
        key = req.env_key.strip()
        if key in ("OLLAMA_URL", "OLLAMA_MODEL"):
            name = "ollama"
        else:
            for entry in PROVIDER_REGISTRY:
                if entry.get("env_key") == key or key in (entry.get("alt_env") or []):
                    name = entry["name"]
                    break
    if not name:
        return {"ok": False,
                "error": f"无法识别提供商(provider={req.provider!r}, env_key={req.env_key!r})"}

    adapter = router_.adapters.get(name)
    cfg = router_.providers.get(name)
    if adapter is None or cfg is None:
        return {"ok": False, "provider": name,
                "error": "提供商未启用——Key 可能没保存成功或路由未刷新"}
    try:
        resp = await _asyncio.wait_for(
            adapter.chat(
                [{"role": "user", "content": "ping"}], cfg.default_model,
                max_tokens=1, temperature=0.0,
            ),
            timeout=15.0,
        )
        return {"ok": True, "provider": name, "model": resp.model,
                "latency_ms": round(float(resp.latency_ms or 0.0), 1)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": name, "error": str(exc)[:300]}


class ModelSyncRequest(BaseModel):
    apply: bool = False                     # False=只出对账报告；True=就地剪失效/补新发现
    only: Optional[List[str]] = None        # 限定 provider（不给则全部可用 provider）
    max_add: int = 20


@router.post("/sync")
async def sync_models(req: ModelSyncRequest) -> Dict[str, Any]:
    """L4 模型名单自动同步:查询各 provider 的 /models 端点，与硬编码的
    ProviderConfig.models 对账（apply=False 只出报告，apply=True 就地剪失效/补新发现/
    修复失效 default_model；不可达的 provider 跳过，不误删其配置）。
    """
    from core.multi_llm_router import get_llm_router
    router_ = get_llm_router()
    return await router_.sync_model_lists(
        apply=req.apply, only=req.only, max_add=req.max_add,
    )


@router.get("/routing-stats")
async def routing_stats() -> Dict[str, Any]:
    """L3 可观测:导出每个 provider 的历史表现 + 当前 bandit 分（反哺决策的实际依据）。"""
    from core.multi_llm_router import get_llm_router
    router_ = get_llm_router()
    return {"stats": router_.routing_stats()}


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
