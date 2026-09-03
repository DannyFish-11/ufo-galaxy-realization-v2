"""
Galaxy Configuration API
提供系统配置的全量读取和批量更新，持久化到 .env 文件。
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.API.Config")

router = APIRouter(prefix="/api/config", tags=["config"])

# .env 文件路径
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
# 配置项总表已拆到 core/routes/config_schema_registry.py(纯声明表,1900+ 行)。
# 这里 re-export,既有的 `from core.routes.config import CONFIG_SCHEMA` 不受影响。
from core.routes.config_bundles import CONFIG_BUNDLES  # noqa: E402
from core.routes.config_schema_registry import CONFIG_SCHEMA  # noqa: E402

__all__ = ["CONFIG_BUNDLES", "CONFIG_SCHEMA"]


class ConfigUpdateRequest(BaseModel):
    config: Dict[str, str]


# 面板角标读端点(自 core/routes/system.py 迁入)。迁移原因 —— 鉴权对称性:
# 它原先挂在 system 路由组(整组 Depends(require_auth)),而同路径的写端点
# POST /api/config 在本开放路由组 —— 生产模式(GALAXY_MODE=production 强制
# 开鉴权)下变成"写得进、读不出":Key 保存成功,面板角标读取却 401,永远显示
# "未配置"。读的是掩码状态(布尔 + 非敏感地址),密级不高于写端点,读写必须同权。
_SECRET_MODEL_KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "META_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "SONAR_API_KEY",
    "XAI_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CODING_API_KEY",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY",
    "STEP_API_KEY",
    "MIMO_API_KEY",
    "MISTRAL_API_KEY",
    "AGNES_API_KEY",
    "HF_API_TOKEN",
    "ONEAPI_API_KEY",
    "DEEPSEEK_OCR2_API_KEY",
]
_NON_SECRET_MODEL_KEYS = [
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "ONEAPI_URL",
    "LOCAL_VLLM_URL",
    "OPENAI_API_BASE",
    "ZHIPU_API_BASE",
]


@router.get("")
async def get_frontend_config(request: Request = None):
    """返回前端所需的非敏感配置(密钥只给"是否已配置"布尔,不下发值)。"""
    host = "localhost"
    port = "9000"
    if request:
        host = request.url.hostname or "localhost"
        port = str(request.url.port or 9000)

    def _is_configured(key_name: str) -> bool:
        from core.credential_vault import PLACEHOLDER_PREFIXES

        val = os.getenv(key_name, "")
        return bool(val and not val.lower().startswith(PLACEHOLDER_PREFIXES) and not val.startswith("sk-YOUR"))

    return JSONResponse(
        {
            "api_base_url": f"http://{host}:{port}",
            # 此前指向 ws://…/ws —— 该端点已被移除且有测试钉死"必须不存在"
            # (tests/test_pr1_canonical_device_ingress.py),字段却仍在广播幻影
            # 地址。改为真实存在的桌面在场通道。
            "ws_url": f"ws://{host}:{port}/ws/desktop-presence",
            "status": {
                "openai": _is_configured("OPENAI_API_KEY"),
                "deepseek": _is_configured("DEEPSEEK_API_KEY"),
                "anthropic": _is_configured("ANTHROPIC_API_KEY"),
                "gemini": _is_configured("GEMINI_API_KEY"),
                "groq": _is_configured("GROQ_API_KEY"),
                "openrouter": _is_configured("OPENROUTER_API_KEY"),
                "perplexity": _is_configured("SONAR_API_KEY") or _is_configured("PERPLEXITY_API_KEY"),
                "oneapi": _is_configured("ONEAPI_API_KEY"),
                "ocr": _is_configured("DEEPSEEK_OCR2_API_KEY"),
                "ollama": bool(os.getenv("OLLAMA_URL")),
            },
            "configured": {k: _is_configured(k) for k in _SECRET_MODEL_KEYS},
            "values": {k: os.getenv(k, "") for k in _NON_SECRET_MODEL_KEYS},
        }
    )


@router.get("/all")
async def get_config():
    """获取当前所有配置项（从环境变量 + 默认值合并）— 供「设置」tab 使用的完整明细。

    注意:不是挂在裸路径 GET /api/config —— core/routes/system.py 的精简版
    (仅 api_base_url/ws_url/status)先于本路由注册,会遮蔽同路径同方法的路由,
    导致「设置」tab 拿到的永远是精简版、按 key 查不到任何一项 → 只见左侧分类
    标签、右侧内容空白。故完整明细改挂 /api/config/all,与精简版共存不冲突。
    """
    # OLLAMA_MODEL 的候选项从 catalog 动态派生（单一真相源），而非用 schema 里的空占位。
    dynamic_options: Dict[str, list] = {}
    try:
        from core.model_catalog import local_choice_options

        dynamic_options["OLLAMA_MODEL"] = local_choice_options()
    except Exception:  # noqa: BLE001
        pass

    result = {}
    for key, meta in CONFIG_SCHEMA.items():
        result[key] = {
            "value": os.environ.get(key, meta["default"]),
            "default": meta["default"],
            "type": meta["type"],
            "category": meta["category"],
            "description": meta["description"],
        }
        if key in dynamic_options and dynamic_options[key]:
            result[key]["options"] = dynamic_options[key]
        elif "options" in meta:
            result[key]["options"] = meta["options"]
    return result


@router.post("")
async def update_config(req: ConfigUpdateRequest):
    """批量更新配置（写入环境变量 + .env 文件）"""
    # 修复:之前是"边校验边写 os.environ",遇到批次里某个未知 key 时半途
    # raise——已经处理过的合法 key 已经写进 os.environ(内存态生效),但因为
    # 异常发生在 _write_env_file() 之前,这些改动从未落盘到 .env,重启即丢失,
    # 前端只看到笼统的 400。这里先做一遍完整性校验,全部合法才动手写,
    # 避免"部分生效、部分丢失"的诡异中间态。
    unknown_keys = [k for k in req.config if k not in CONFIG_SCHEMA]
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown config key(s): {', '.join(unknown_keys)}",
        )

    # ── 计算最终值(url 补协议头),此刻【先不碰 os.environ】────────────────
    # 真机复现过:用户填 url 类字段(OLLAMA_URL/ONEAPI_URL 等)时只填 host:port
    # (如 "localhost:11434")没带协议头,原样落盘后 httpx 才炸「missing 'http://'
    # protocol」。在写入这一步就补全,不指望每个消费端自己校验。
    final: Dict[str, str] = {}
    for key, value in req.config.items():
        value = str(value)
        if CONFIG_SCHEMA[key]["type"] == "url":
            stripped = value.strip()
            if stripped and not stripped.startswith(("http://", "https://")):
                value = f"http://{stripped}"
        final[key] = value

    # ── 【先落盘、成功才应用到 os.environ】────────────────────────────────
    # 修复"显示已配置、却又保存失败"的自相矛盾:此前是先写 os.environ(前端 GET
    # /api/config 据 os.getenv 判定"已配置")、再写盘,一旦写盘失败(Windows 上
    # .env 被杀毒/编辑器占用、目录只读),就成了"明明已配置、却报保存失败",
    # 用户根本分不清到底存没存、生没生效。现在颠倒顺序:
    #   落盘成功 → 才把值应用进 os.environ(当次即时生效)、"已配置"随之如实为真;
    #   落盘失败 → os.environ 原封不动、"已配置"保持原状,错误如实说明原因。
    # 于是"已配置"与"保存成功"永远一致:存了就是存了、生效了;没存就没存、没生效。
    #
    # 密钥收敛到唯一密钥库:敏感项走 ConfigService.set_secret → runtime/secrets.env,
    # 不明文落 .env(否则重启时 .env 旧值会盖住 secrets.env,历史"重启丢 key"根因);
    # 写 secrets.env 失败的密钥回落 .env(不丢持久化)。
    _secrets_persisted: set = set()
    try:
        from core.config_schema import classify_key as _classify
        from core.config_service import ConfigService as _CS

        _cs = None
        for _k, _v in final.items():
            if _classify(_k) != "secret":
                continue
            try:
                if _cs is None:
                    _cs = _CS()
                if str(_v).strip():
                    _cs.set_secret(_k, str(_v))
                else:
                    # 空值 = 用户在面板上【清空】了这个密钥。此前这里用
                    # `and str(_v).strip()` 直接把空值跳过了,secrets.env 里的旧值
                    # 就一直留着;而启动时 secrets.env 会被灌回进程环境,于是"删掉
                    # 的密钥重启又活过来"。清空必须真的落到密钥库里去删。
                    _cs.delete_secret(_k)
                _secrets_persisted.add(_k)
            except Exception as _e:  # noqa: BLE001 — 失败则保留 .env 回落
                logger.debug("密钥写入/删除 secrets.env 失败(回落 .env): %s", _e)
    except Exception as exc:  # noqa: BLE001 — ConfigService 不可用 → 全部回落 .env
        logger.debug("密钥收敛不可用(降级为 .env 持久化): %s", exc)

    try:
        _write_env_file_with(final, exclude=_secrets_persisted)
    except OSError as exc:
        # 落盘失败 → os.environ 一个字没动,"已配置"如实保持原状,不制造矛盾。
        raise HTTPException(
            status_code=500,
            detail=f"写入 .env 失败: {exc}(检查文件是否被占用/只读，或目录权限）；本次未改动任何配置",
        ) from exc

    # ── 落盘成功 → 应用到 os.environ(当次即时生效),并做即时联动 ──────────
    os.environ.update(final)

    # 模型选择收敛到唯一门:model_catalog.save_tier 把【档位 + 主脑】写进同一条
    # 记录(runtime/model_state.json)并派生 OLLAMA_MODEL,按模型反推档位并联动。
    if "OLLAMA_MODEL" in final:
        try:
            from core import model_catalog as _mc

            _tag = final["OLLAMA_MODEL"]
            _mc.save_tier(_mc.infer_tier_from_model(_tag), main_brain=_tag)
        except Exception as exc:  # noqa: BLE001
            logger.debug("模型状态联动写入失败(非致命): %s", exc)

    # 自发在场开关改动 → 立刻生效(启动/停止常驻循环),不必重启。
    if "GALAXY_AMBIENT_LOOP" in final:
        try:
            from core.ambient_attention_loop import ambient_loop_enabled, get_ambient_loop

            _loop = get_ambient_loop()
            if ambient_loop_enabled() and not _loop.running:
                await _loop.start()
            elif not ambient_loop_enabled() and _loop.running:
                await _loop.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("ambient 循环即时开关失败(非致命): %s", exc)

    # UnifiedConfig 是进程启动时读一次 .env 就不再变的单例("Dashboard 优先级"
    # 那一层实际读的是它)——本函数只写了 os.environ/.env,从没告诉过它内容
    # 变了。同一进程内一直没炸,纯粹是因为 _get_key() 的兜底第三层直接读
    # os.environ 生效了；但 UnifiedConfig 自己上报的值会一直是启动时的旧值，
    # 直到进程重启。这里保存后顺手 reload 一下，让它也反映最新内容，不再是
    # 一个"名义最高优先级、实际全程失效"的摆设。
    try:
        from core.unified_config import config as _unified_cfg

        _unified_cfg.reload()
    except Exception as exc:  # noqa: BLE001
        # 这里静默 pass 等于让上面那段注释描述的修复悄悄失效:reload 一失败,
        # UnifiedConfig 就继续上报启动时的旧值,而保存接口照样返回成功 ——
        # 正是"名义最高优先级、实际全程失效"的原样复发,且无从排查。
        logger.warning(
            "配置已落盘,但 UnifiedConfig.reload() 失败(%s):该单例将继续上报进程启动时的旧值,直到重启",
            exc,
        )

    # 若改动涉及模型 API（llm 类），热刷新 LLM 路由器，让新填的 key 即时生效（无需重启）。
    # 根因修复(真机"保存悬挂"):此前这里同步 await refresh_llm_router()——内部对
    # Ollama/OneAPI 等做 2~5s/个的真实网络探测,离线机器上整体轻松 >8s,而 Electron
    # 主进程 fetchWithRetry 单次尝试 8s 即 abort 重发,保存请求永远答不完:面板卡死
    # 在「保存中…/仍在保存中,后端可能仍在启动…」直到 60s 预算耗尽;每次 abort 的
    # 断开连接还连锁触发后端 "Cannot call write() when UVStream is closing" 刷屏。
    # 保存路由必须快速返回:此刻配置已落盘、已进 os.environ(持久化真相已成立),
    # 慢的网络探测改为后台调度;需要探测结果的 verify-provider 端点自己有界等待
    # (wait_llm_router_refresh),新 key 依然"保存后即可验证",不牺牲功能。
    refreshed = None
    if any(CONFIG_SCHEMA.get(k, {}).get("category") == "llm" for k in final):
        try:
            from core.multi_llm_router import schedule_llm_router_refresh

            schedule_llm_router_refresh()
            refreshed = "scheduled"
        except Exception:
            refreshed = None

    return {"success": True, "updated": list(final.keys()), "router_refreshed": refreshed}


@router.post("/save")
async def save_config():
    """强制保存当前配置到 .env"""
    _write_env_file()
    return {"success": True}


class ProbeRequest(BaseModel):
    keys: list[str]


def _probe_one(raw: str) -> Dict[str, Any]:
    """对单个地址做同步 TCP 连接探测(在线程池里跑,不阻塞事件循环)。"""
    import socket
    import time as _time
    from urllib.parse import urlsplit

    raw = raw.strip()
    if not raw:
        return {"reachable": False, "latency_ms": None, "error": "未配置"}

    # 补默认 scheme,方便 urlsplit 解析出 host/port(例如 "localhost:4222"
    # 这种没写 scheme 的值)。
    parseable = raw if "://" in raw else f"tcp://{raw}"
    parsed = urlsplit(parseable)
    host = parsed.hostname
    port = parsed.port or {"http": 80, "https": 443, "redis": 6379, "nats": 4222}.get(parsed.scheme)

    if not host or not port:
        return {"reachable": False, "latency_ms": None, "error": f"无法解析地址: {raw}"}

    start = _time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=1.5):
            latency_ms = round((_time.monotonic() - start) * 1000, 1)
            return {"reachable": True, "latency_ms": latency_ms, "error": None}
    except OSError as exc:
        return {"reachable": False, "latency_ms": None, "error": str(exc)}


@router.post("/probe")
async def probe_config_urls(req: ProbeRequest):
    """对「设置」tab 里 type=url 的项做真实连通性探测(TCP 连接,不识别协议)。

    背景:「端口与节点」「网络」「组网」这几个分类之前只是纯文本配置编辑器——
    值本身是真实的(读写 os.environ/.env),但用户在设置页完全看不到"这个地址
    现在到底通不通"，被误认为"没有接真实数据"。这里补一个真正的、非伪造的
    连通性探测:对每个 key 解析出 host:port，尝试建立 TCP 连接(1.5s 超时)，
    成功即视为"可达"，不需要认识每种协议(NATS/Redis/HTTP 等)的具体握手。
    多个 key 用 asyncio.to_thread 并发探测,避免阻塞事件循环、也避免用户等待
    N 个地址依次超时的总时长。
    """
    import asyncio as _asyncio

    to_probe: Dict[str, str] = {}
    results: Dict[str, Dict[str, Any]] = {}
    for key in req.keys:
        meta = CONFIG_SCHEMA.get(key)
        if meta is None or meta.get("type") != "url":
            results[key] = {"reachable": False, "latency_ms": None, "error": "not a url-type key"}
            continue
        to_probe[key] = os.environ.get(key, meta["default"])

    if to_probe:
        probed = await _asyncio.gather(*(_asyncio.to_thread(_probe_one, raw) for raw in to_probe.values()))
        results.update(zip(to_probe.keys(), probed))

    return {"results": results}


def _write_env_file(exclude=None):
    """将所有【非空】配置写入 .env 文件(读 os.environ 现值)。"""
    return _write_env_file_with(None, exclude=exclude)


def _write_env_file_with(overrides=None, exclude=None):
    """将所有【非空】配置写入 .env 文件;overrides 里的键用其新值(而非 os.environ)。

    overrides: {key: 新值} —— 允许在【尚未写入 os.environ】时就把新值落盘,从而做到
    "先落盘、成功再应用 os.environ"(见 update_config)。None 时退化为读 os.environ 现值。

    exclude: 调用方按【本次请求】判定"已写进 canonical 密钥库"的密钥名集合——
    尊重调用方"这次没能存进 secrets.env、需要回落 .env"的显式意图(见下方安全
    修复,这层调用方 exclude 仍然生效,只是不再是唯一防线)。

    关键修复:之前把全部 schema 键(含空值)统统写成 ``KEY=`` 行。空字符串
    一旦被 .env 加载进 os.environ,就会把代码里的默认值顶掉——
    ``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 在
    ``OLLAMA_URL=""`` 存在时返回 ""，不是默认值。真机复现过的一整串症状都
    源于此:LocalBrainManager 拿空 URL ping Ollama(明明在跑却判"服务未响应/
    模型未就绪")、Redis "must specify scheme"、NATS "invalid hostname"。
    现在空值不写入(视同未配置),下次保存时旧 .env 里的空值行也会随全量
    重写被清掉。

    安全修复(密钥明文泄露回归,直接排查"已配置又保存失败"发现):旧版
    ``exclude`` 只是【调用方按本次请求】传入的集合——update_config() 只把
    "这次请求里刚成功写入 secrets.env 的 key"排除掉,对"之前某次请求已经存进
    secrets.env、现在仍躺在 os.environ 里"的密钥毫无防备:全量重写时会把它们
    当普通配置从 os.environ 读出来,原样明文写回 .env——保存任何一个【无关】
    的设置项,都会把所有【已经安全存好】的 API Key 重新泄露进 .env。
    ``/save`` 端点(强制保存)甚至完全没传 exclude,每次点都 100% 泄露全部密钥。
    这不仅是安全回归,也是"已配置但保存失败"的合理成因之一:一个不断被重新
    写入密钥明文的 .env,在 Windows 上更容易被杀毒/同步客户端占用触发 OSError。

    现在无论调用方传不传 exclude,这里都会【自行】额外并上 runtime/secrets.env
    里【当前真实存在】的全部键——不是所有 secret 分类的键(那样会把从未成功
    存进 secrets.env、只能靠 .env 兜底持久化的密钥连 .env 也一并排除掉,变成
    彻底丢失,破坏既有的降级持久化设计),只排除已确认安全落在 secrets.env
    的那些。读取失败(文件不存在/损坏)时保守地不额外排除,不影响本次落盘。
    """
    lines = ["# Galaxy Configuration - Auto-generated by Settings Panel\n"]

    # 按类别分组
    current_category = ""
    _exclude = set(exclude or set())
    try:
        from core.config_store import get_config_store

        _exclude |= set(get_config_store().read_secrets().keys())
    except Exception as exc:  # noqa: BLE001 — 排除集合计算失败不影响本次落盘,保守回落明文
        logger.debug("读取 secrets.env 计算排除集合失败(不影响本次落盘): %s", exc)
    _overrides = overrides or {}
    for key, meta in sorted(CONFIG_SCHEMA.items(), key=lambda x: x[1]["category"]):
        if key in _exclude:
            continue  # 已入 canonical 密钥库,不再明文写 .env
        value = _overrides.get(key, os.environ.get(key, meta["default"]))
        if not str(value).strip():
            continue  # 空值不落盘——否则会把代码默认值顶掉
        if meta["category"] != current_category:
            current_category = meta["category"]
            lines.append(f"\n# --- {current_category.upper()} ---\n")

        desc = meta["description"]
        lines.append(f"# {desc}\n{key}={value}\n")

    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


# 注:曾经这里有一个 _load_env_file()——但全仓库排查确认它从未被任何地方调用过,
# 是一段死代码(容易让人误以为"config.py 会自己加载 .env"从而误删/误改
# main.py 顶部真正生效的 dotenv.load_dotenv() 那段逻辑,造成隐蔽回归)。
# .env → os.environ 的真正加载点在 main.py / unified_launcher.py 顶部
# 的 load_dotenv() 调用,已删除此处死代码。


# ---------------------------------------------------------------------------
# 整档开关 —— 面板上那四个「一个开关管一整片」的档位
# ---------------------------------------------------------------------------
#
# 定义在 core/routes/config_bundles.py 的 CONFIG_BUNDLES(唯一定义处)。
# 这里只负责【现算】它此刻的样子并写回,不重复那份定义。


class BundleUpdateRequest(BaseModel):
    """把某一档设成某个值。``value`` 直接写进这一档的主键。"""

    key: str
    value: str


def _bundle_state(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """现算一档此刻的样子。**每一个数字都是数出来的,没有一个是写死的。**

    - ``value`` / ``type`` / ``options``:主键的当前值与它的控件形态。
      三档的 select 必须原样透出 —— 压成布尔会把中间那档吞掉。
    - ``key_count``:这一档管几个键。
    - ``overrides``:这一档里有几个键被**手动改得偏离了默认**。

    ``overrides`` 是这套设计能不能成立的关键。有键被手改过时,档位必须显示成
    「开 · 有偏离」而不是「开」—— 否则档位说开、底下某个键说关,就是同一个事实
    两处各存一份,而且没人看得见。
    """
    primary = bundle["primary"]
    meta = CONFIG_SCHEMA.get(primary)
    if meta is None:
        # 主键不存在 = 这一档接到了一个不存在的东西上。**说出来**,不要静默跳过:
        # 静默的话面板上会出现一个永远关着、点了也没反应的开关。
        return {
            "key": bundle["key"],
            "name": bundle["name"],
            "note": bundle["note"],
            "category": bundle["category"],
            "primary": primary,
            "unwired": True,
            "reason": f"主键 {primary} 不在 CONFIG_SCHEMA 里",
        }

    in_category = [k for k, m in CONFIG_SCHEMA.items() if m.get("category") == bundle["category"]]
    overrides = sum(1 for k in in_category if k in os.environ and os.environ[k] != CONFIG_SCHEMA[k]["default"])

    state: Dict[str, Any] = {
        "key": bundle["key"],
        "name": bundle["name"],
        "note": bundle["note"],
        "category": bundle["category"],
        "primary": primary,
        "unwired": False,
        "value": os.environ.get(primary, meta["default"]),
        "default": meta["default"],
        "type": meta["type"],
        "key_count": len(in_category),
        "overrides": overrides,
    }
    if "options" in meta:
        state["options"] = meta["options"]
    return state


@router.get("/bundles")
async def get_bundles():
    """面板设置浮层里那几档的当前状态(现算)。"""
    return {"bundles": [_bundle_state(b) for b in CONFIG_BUNDLES]}


@router.post("/bundles")
async def set_bundle(req: BundleUpdateRequest):
    """翻一档 —— 实际写的是这一档的主键,复用 update_config 那条唯一写入路径。

    不另写一遍落盘逻辑:那边已经处理了「先落盘、成功才应用到 os.environ」以及
    url 补协议头这些事,再抄一份必然漂。
    """
    bundle = next((b for b in CONFIG_BUNDLES if b["key"] == req.key), None)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"没有这一档: {req.key}")

    primary = bundle["primary"]
    meta = CONFIG_SCHEMA.get(primary)
    if meta is None:
        raise HTTPException(
            status_code=503,
            detail=f"档位 {req.key} 的主键 {primary} 不在 CONFIG_SCHEMA 里 —— 它没有接上任何东西",
        )

    allowed = meta.get("options")
    if allowed and req.value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{primary} 只接受 {allowed},收到 {req.value!r}",
        )
    if meta["type"] == "boolean" and req.value not in ("true", "false"):
        raise HTTPException(
            status_code=400,
            detail=f"{primary} 是布尔,只接受 'true' / 'false',收到 {req.value!r}",
        )

    await update_config(ConfigUpdateRequest(config={primary: req.value}))
    return {"bundle": _bundle_state(bundle)}
