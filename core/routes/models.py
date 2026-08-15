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
import asyncio as _asyncio  # noqa: E402  分区就地导入(见上方注释)
import time as _time  # noqa: E402  分区就地导入(见上方注释)

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
    """完整模型目录（档位 + 模型 + 能力 + 有效 IO + 当前档位 + 硬件适配诚实评估）。"""
    from core.model_catalog import catalog_snapshot, get_model

    snap = catalog_snapshot()
    # 当前主脑（供面板高亮）
    snap["current_main_brain"] = os.environ.get("OLLAMA_MODEL", "")

    # 硬件适配诚实评估:requires_gpu 的模型在无够格显卡的机器上会被
    # Ollama 静默放到 CPU 上硬爬(首 token 数秒到数十秒)。此前目录里
    # 的 requires_gpu 只是描述文字,运行时无人消费 —— 用户选了 B 档
    # 也得不到任何"会极慢"的告警。这里按真实硬件画像逐模型给出
    # gpu_fit,面板据此如实提示,不假装能跑。
    try:
        from core.hardware_compute_profiler import get_hardware_profiler

        # profile_sync 会 shell 出 nvidia-smi 等探测(冷调用可达数秒),
        # 放线程池执行,不阻塞事件循环(否则拖慢同批所有请求);profiler
        # 自身 30s 缓存,热调用近乎零成本。
        prof = await _asyncio.to_thread(get_hardware_profiler().profile_sync)
        has_gpu = bool(prof.gpus)
        snap["hardware"] = {
            "has_gpu": has_gpu,
            "can_run_local_multimodal": bool(prof.can_run_local_multimodal),
            "max_model_size_mb": int(prof.max_model_size_mb),
            "recommended_quantization": prof.recommended_quantization,
        }
        fits: Dict[str, str] = {}
        for tier in snap.get("tiers", []) or []:
            for m in tier.get("models", []) or []:
                tag = m.get("tag", "")
                spec = get_model(tag)
                if spec is None or spec.source != "local":
                    continue
                if not getattr(spec, "requires_gpu", False):
                    fits[tag] = "ok"
                elif not has_gpu:
                    fits[tag] = "no_gpu"  # 需显卡但没有:CPU 硬爬,如实告警
                elif spec.size_mb_val > prof.max_model_size_mb:
                    fits[tag] = "insufficient_vram"  # 有显卡但装不下:会溢出到内存
                else:
                    fits[tag] = "ok"
        snap["gpu_fit"] = fits
    except Exception as exc:  # 探测失败不阻塞目录,但如实说明未评估
        logger.debug("catalog 硬件探测失败: %s", exc)
        snap["hardware"] = {"has_gpu": None, "probe_error": type(exc).__name__}
        snap["gpu_fit"] = {}
    return snap


def _catalog_placeholder(status: str = "unknown") -> Dict[str, Dict[str, Any]]:
    """全目录占位结果(探测超预算/彻底失败时用):键集恒等于目录本地模型集,
    形状不破(面板与测试都依赖 models 键集 == choice_order 本地项)。"""
    from core.model_catalog import choice_order, get_model

    out: Dict[str, Dict[str, Any]] = {}
    for tag in choice_order():
        spec = get_model(tag)
        if spec is None or spec.source not in ("local", "llama_cpp"):
            continue
        out[tag] = {"status": status, "ollama_reachable": False, "matched": ""}
    return out


def _gguf_status(tag: str) -> Dict[str, Any]:
    """source=llama_cpp 的型号:装没装看**本地 GGUF 文件在不在**,与 Ollama 无关。

    不报它就等于:用户选了带 llama_cpp 推理位的档,面板上那一位**根本不显示**,
    而缺文件只会在真正加载时写一行 error 日志。选完看不出没装,这是静默失败。
    """
    try:
        from core.local_model_backends import LlamaCppBackend  # noqa: PLC0415

        path = LlamaCppBackend()._resolve_model_path(tag)
    except Exception as exc:  # noqa: BLE001
        logger.debug("GGUF 路径解析不可用(%s): %s", tag, exc)
        path = None
    return {
        "status": "installed" if path else "absent",
        # 这一位不经 Ollama,故恒 False —— 不是"Ollama 挂了",是压根不走它。
        "ollama_reachable": False,
        "matched": path or "",
    }


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
            if spec is None:
                continue
            if spec.source == "llama_cpp":
                out[tag] = _gguf_status(tag)
                continue
            if spec.source != "local":
                continue
            root = tag.split(":")[0]
            matched = next(
                (h for h in installed_names if h == tag or h.startswith(tag + ":") or h.split(":")[0] == root),
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
                sr = await client.post(f"{base}/api/show", json={"name": matched}, timeout=2.0)
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
            data = await _asyncio.wait_for(_probe_installed_async(), timeout=_PROBE_BUDGET * 3)
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
            installed = await _asyncio.wait_for(_probe_installed_async(), timeout=_PROBE_BUDGET)
        except Exception as exc:  # noqa: BLE001
            logger.debug("models/status 首次探测超预算(%s),返回占位并后台续探", exc)
            _kick_refresh()
            return {"models": _catalog_placeholder(), "probing": True}
        _status_cache["data"] = installed
        _status_cache["ts"] = _time.monotonic()
        return {"models": installed}


class ProviderVerifyRequest(BaseModel):
    provider: Optional[str] = None  # 提供商名(如 "deepseek");与 env_key 二选一
    env_key: Optional[str] = None  # 或环境变量键(如 "DEEPSEEK_API_KEY"),后端反查


@router.post("/verify-provider")
async def verify_provider(req: ProviderVerifyRequest) -> Dict[str, Any]:
    """真实连通性验证:用该提供商的 default_model 发一次 1-token 试调。

    面板"保存 API Key"之后调这里,把「保存成功」升级成「保存且**能用**」——
    此前保存只代表写进了 .env,Key 错的/网络不通的要等到真正对话失败才暴露,
    用户没法判断"到底好了没有"。试调成本≈零(max_tokens=1),15s 封顶。
    """
    from core.multi_llm_router import PROVIDER_REGISTRY, get_llm_router, wait_llm_router_refresh

    # 保存配置(POST /api/config)现在只【后台调度】路由刷新就立即返回(否则同步
    # 网络探测 >8s 会撞上 Electron 的单次尝试超时,保存悬挂——见 config.py 注释)。
    # 这里是刷新结果的真正消费方:有界等待进行中的刷新完成,保证"保存后立刻
    # 验证"仍能看到新 key 对应的 adapter;8s 等不到就按当前快照如实作答,
    # 不无限悬挂(前端对本请求另有 12s 超时)。
    await wait_llm_router_refresh(timeout=8.0)

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
        return {"ok": False, "error": f"无法识别提供商(provider={req.provider!r}, env_key={req.env_key!r})"}

    adapter = router_.adapters.get(name)
    cfg = router_.providers.get(name)
    if adapter is None or cfg is None:
        return {"ok": False, "provider": name, "error": "提供商未启用——Key 可能没保存成功或路由未刷新"}
    try:
        resp = await _asyncio.wait_for(
            adapter.chat(
                [{"role": "user", "content": "ping"}],
                cfg.default_model,
                max_tokens=1,
                temperature=0.0,
            ),
            timeout=15.0,
        )
        return {
            "ok": True,
            "provider": name,
            "model": resp.model,
            "latency_ms": round(float(resp.latency_ms or 0.0), 1),
        }
    except _asyncio.TimeoutError:
        return {"ok": False, "provider": name, "error": "验证超时(15s)——服务不可达或网络阻断"}
    except Exception as exc:  # noqa: BLE001
        # 不把原始异常串直接回给调用方(CodeQL: 异常可能携带栈/内部信息)。
        # 分类成用户能行动的脱敏文案;完整异常只进服务端日志。
        logger.info("verify-provider %s 试调失败: %s", name, exc)
        try:
            import httpx

            if isinstance(exc, httpx.HTTPStatusError):
                code = exc.response.status_code
                hint = {
                    401: "密钥无效(401)",
                    403: "无权限(403)",
                    404: "接口或模型不存在(404)",
                    429: "限流(429)",
                }.get(code, f"HTTP {code}")
                return {"ok": False, "provider": name, "error": hint}
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "provider": name, "error": f"连接失败({type(exc).__name__})——检查网络/Key/服务地址"}


class ModelSyncRequest(BaseModel):
    apply: bool = False  # False=只出对账报告；True=就地剪失效/补新发现
    only: Optional[List[str]] = None  # 限定 provider（不给则全部可用 provider）
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
        apply=req.apply,
        only=req.only,
        max_add=req.max_add,
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
    from core.model_catalog import get_tier, save_tier, tier_models

    tier = get_tier(req.tier)
    if tier is None:
        return {"success": False, "error": f"未知档位: {req.tier}"}

    chosen = save_tier(req.tier, main_brain=req.main_brain)

    # 资源对齐:算目标档资源 → 驱逐不属于该档的 → 按分配加载。收口在调度器
    # (唯一资源真相源),而不是在路由层各自为政。best-effort:失败不拦截换档。
    try:
        from core.compute_scheduler import get_compute_scheduler

        await get_compute_scheduler().reconcile_tier(req.tier)
    except Exception as exc:  # noqa: BLE001
        logger.debug("档位资源对齐失败(非致命): %s", exc)

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


@router.post("/latency-probe")
async def latency_probe() -> Dict[str, Any]:
    """本地推理一键测速:用 Ollama 自带的 eval 计数算真实 prefill/decode 速度。

    诚实原则:只报实测数字与由此推出的判词,测不了(Ollama 不可达/模型
    未装)就如实说测不了。两次探测:小提示词(测冷/热加载 + decode),
    ~2.4k token 合成长提示词(测规模化 prefill —— 代理回合的延迟大头)。
    """
    import httpx as _httpx

    base = _ollama_base()
    model = os.environ.get("OLLAMA_MODEL", "").strip()
    out: Dict[str, Any] = {"ollama_base": base, "model": model, "stages": {}, "verdicts": []}
    if not model:
        out["verdicts"].append("未选择本地主脑(OLLAMA_MODEL 空)——本测速仅针对本地模型。")
        return out

    async with _httpx.AsyncClient(timeout=90.0) as client:
        # 1) 可达性 + 是否已驻留
        t0 = _time.monotonic()
        try:
            tags = await client.get(f"{base}/api/tags")
            out["stages"]["ollama_reachable_ms"] = round((_time.monotonic() - t0) * 1000, 1)
            tags.raise_for_status()
        except Exception as exc:
            out["stages"]["ollama_reachable_ms"] = None
            logger.debug("latency-probe: ollama 不可达: %s", exc)
            out["verdicts"].append(f"Ollama 不可达({type(exc).__name__})——先确认它在运行,详情见后端日志。")
            return out
        try:
            ps = await client.get(f"{base}/api/ps")
            loaded = [m.get("name", "") for m in (ps.json().get("models") or [])]
            out["stages"]["model_resident"] = any(model in name for name in loaded)
        except Exception:
            out["stages"]["model_resident"] = None

        async def _gen(prompt: str, predict: int) -> Dict[str, Any]:
            r = await client.post(
                f"{base}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": -1,
                    "options": {"num_predict": predict, "temperature": 0.0},
                },
            )
            r.raise_for_status()
            return r.json()

        # 2) 小提示词:加载 + decode 速度
        t0 = _time.monotonic()
        try:
            small = await _gen("用一句话介绍你自己。", 24)
        except Exception as exc:
            logger.debug("latency-probe: 模型调用失败: %s", exc)
            out["verdicts"].append(f"模型调用失败({type(exc).__name__})——模型可能未安装或内存不足,详情见后端日志。")
            return out
        out["stages"]["small_total_ms"] = round((_time.monotonic() - t0) * 1000, 1)
        _ns = 1e9
        decode_tps = (small.get("eval_count") or 0) / max((small.get("eval_duration") or 1) / _ns, 1e-6)
        out["stages"]["decode_tokens_per_s"] = round(decode_tps, 1)
        out["stages"]["load_ms"] = round((small.get("load_duration") or 0) / 1e6, 1)

        # 3) 长提示词(~2.4k token):规模化 prefill —— 代理回合的延迟大头
        long_prompt = ("这是用于测速的填充文本,请忽略其内容。" * 300) + "\n请回复:好"
        t0 = _time.monotonic()
        try:
            big = await _gen(long_prompt, 1)
            out["stages"]["long_total_ms"] = round((_time.monotonic() - t0) * 1000, 1)
            prefill_tokens = big.get("prompt_eval_count") or 0
            prefill_tps = prefill_tokens / max((big.get("prompt_eval_duration") or 1) / _ns, 1e-6)
            out["stages"]["prefill_tokens"] = prefill_tokens
            out["stages"]["prefill_tokens_per_s"] = round(prefill_tps, 1)
        except Exception as exc:
            logger.debug("latency-probe: 长提示词探测失败: %s", exc)
            out["verdicts"].append(f"长提示词探测失败({type(exc).__name__})——大概率内存不足(换页),详情见后端日志。")
            prefill_tps = 0.0

        # 4) 诚实判词
        if decode_tps and decode_tps < 5:
            out["verdicts"].append(
                f"生成速度 {decode_tps:.1f} tok/s:低于可用线(≈5)。最常见原因是内存不足在换页,"
                "或模型对这台 CPU 过大——建议关闭其他占内存程序,或换更小档。"
            )
        elif decode_tps:
            out["verdicts"].append(f"生成速度 {decode_tps:.1f} tok/s:对话可用。")
        if prefill_tps:
            agent_prompt_tokens = 3500  # 代理回合典型规模(系统提示+工具+记忆)
            est = agent_prompt_tokens / prefill_tps
            out["stages"]["est_agent_first_token_s"] = round(est, 1)
            if est > 8:
                out["verdicts"].append(
                    f"预填速度 {prefill_tps:.0f} tok/s → 满配代理回合首字约 {est:.0f}s。"
                    "这就是'怎么都慢'的主因:每回合重发全部工具定义。已启用工具粘滞"
                    "(GALAXY_TOOLS_STICKY)让前缀缓存生效——同一会话第二回合起应显著变快;"
                    "若连【首轮】也想砍,开 GALAXY_TOOLS_JIT=on:热核以外的工具按需逐轮解锁、"
                    "只增不减,首轮仅下发几百 token 而非全量;"
                    "语音实时体验建议叠加云端 API(如 Agnes 免费档)。"
                )
            else:
                out["verdicts"].append(f"预填速度 {prefill_tps:.0f} tok/s:满配代理回合首字约 {est:.1f}s。")
    return out
