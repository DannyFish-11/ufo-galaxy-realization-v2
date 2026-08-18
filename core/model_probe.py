"""core.model_probe — 问，而不是猜：本地装了什么、这个 key 能调什么、填错了没有

为什么要有这个模块
==================
``core.model_catalog`` 的一条记录要填：确切 tag、原生模态声明、权重大小、
**实测运行时显存**、最长上下文、每 1K 上下文的 KV 开销、是不是 MoE。这些数
必须是**量出来的**，模块自己的注释写得很清楚：

    ``runtime_mb_val``：``0`` = 没人量过 → 退回权重大小（即历史行为，**不臆造数字**）

而且它记了臆造的后果：MiniCPM-o 记 6000 → 8 GB 卡上准入判"放得下"，加载到
11 GB 时 OOM，报错还在加载**途中**不在准入处，现场看到的是"模型带不动"。

同样的道理适用于云端那张表：``base_url`` 对不对、``default_model`` 这个名字
今天还在不在、这把 key 到底能调哪些模型 —— 这些都是**可以问出来的事实**，
靠人对着文档抄迟早会漂。

所以本模块一条规矩：**不内置任何"最新最好的模型"清单**。清单从运行时来。

三件事
======
:func:`probe_local_models`
    问 Ollama ``/api/tags`` + ``/api/show``：实际装了什么，各自多大、多长上下文、
    有什么能力（看/听/工具）。

:func:`probe_provider_models`
    问某个云端 provider 的 ``{base_url}/models``：**这把 key 实际能调哪些**。

:func:`audit_provider_catalog`
    把上面两样与 ``multi_llm_router`` 里配置的那张表逐条比对，报出对不上的地方。
    这是"排错"的正路 —— 肉眼看一张十几家、几十个型号的表，看不出 ``kimi-k3``
    是不是真的存在。

边界
====
* **只读**。不装、不拉、不改配置。发现问题只报告，改由人决定。
* **不触网就退化，不报错**。拿不到就如实说"没探到"，与"探到了但是空的"可区分 ——
  前者是环境问题，后者是真的没有。
* **不引入新依赖**。用仓库已有的 ``httpx``，地址走
  ``core.ollama_endpoint.resolve_ollama_base_url``（唯一入口）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ModelProbe")

__all__ = [
    "ProbeOutcome",
    "LocalModelFact",
    "ProviderProbe",
    "CatalogFinding",
    "probe_local_models",
    "probe_provider_models",
    "audit_provider_catalog",
    "format_audit_report",
]

#: 探测结果的三态。**``unreachable`` 与 ``empty`` 必须分开**：前者是"没问到"
#: （服务没起、网络不通、key 没填），后者是"问到了，答案是空的"。混成一个
#: 空列表，会把环境问题报成"你配的模型都不存在"，那是最坏的一种误导。
PROBE_OUTCOMES: Tuple[str, ...] = ("ok", "empty", "unreachable", "unauthorized")

_HTTP_TIMEOUT_S: float = 6.0


@dataclass(frozen=True)
class ProbeOutcome:
    """一次探测的结果与它为什么是这个结果。"""

    status: str
    """见 :data:`PROBE_OUTCOMES`。"""

    detail: str = ""
    """人能读的说明；``status == "ok"`` 时通常为空。"""

    @property
    def reached(self) -> bool:
        """探测本身是否成功（够到了对面）。``empty`` 也算够到了。"""
        return self.status in ("ok", "empty")


@dataclass(frozen=True)
class LocalModelFact:
    """本地实际装着的一个模型 —— 全部字段都来自 Ollama 自己的回答。"""

    tag: str
    size_mb: int = 0
    """磁盘上的权重大小。``0`` = 对面没报。"""

    parameter_size: str = ""
    """如 ``"35B"``，Ollama 的 ``details.parameter_size`` 原文。"""

    quantization: str = ""
    """如 ``"Q4_K_M"``。"""

    context_length: int = 0
    """``model_info`` 里的上下文长度；``0`` = 没报。"""

    capabilities: Tuple[str, ...] = ()
    """Ollama ``/api/show`` 报的能力（如 ``vision`` / ``completion`` / ``tools``）。"""

    healthy: bool = True
    """``/api/show`` 能否打开。

    ``/api/tags`` 里列得出名字**不等于**装好了：失败的拉取会留下能列名、
    打不开的残缺 manifest。``core/model_selection.py`` 为此栽过 —— 只看 tags
    会让坏条目永久拦住后续重试。
    """


@dataclass(frozen=True)
class ProviderProbe:
    """一个 provider 探到的实况。"""

    name: str
    outcome: ProbeOutcome
    models: Tuple[str, ...] = ()
    """对面 ``/models`` 报的模型 id。"""


@dataclass
class CatalogFinding:
    """一条对不上的地方。"""

    provider: str
    kind: str
    """``model_missing`` / ``default_missing`` / ``unreachable`` / ``unauthorized`` / ``untested``。"""

    detail: str
    configured: List[str] = field(default_factory=list)
    available: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "kind": self.kind,
            "detail": self.detail,
            "configured": list(self.configured),
            "available": list(self.available),
        }


# ---------------------------------------------------------------------------
# 本地：Ollama 实际装了什么
# ---------------------------------------------------------------------------


def probe_local_models(base_url: str = "", *, client: Any = None) -> Tuple[ProbeOutcome, List[LocalModelFact]]:
    """问本地 Ollama：**实际装着什么**，各自什么规格。

    Args:
        base_url: 覆盖地址；空则走 ``core.ollama_endpoint.resolve_ollama_base_url``
            （唯一入口，空值/缺协议头都兜底）。
        client: 注入的 httpx 客户端（测试用）。给了就不自己建，也不触网。

    Returns:
        ``(结果, 事实列表)``。``unreachable`` 时列表为空 —— 与"探到了、一个都没装"
        （``empty``）是两件事，别混。

    每一项都再用 ``/api/show`` 核实一次
    -----------------------------------
    ``/api/tags`` 列得出名字**不等于**能用：失败的拉取会留下能列名、打不开的残缺
    manifest。只看 tags 的后果 ``core/model_selection.py`` 已经栽过 —— 坏条目会
    永久拦住后续所有重试。这里把核实结果如实放进 :attr:`LocalModelFact.healthy`，
    不悄悄剔除：一个"装了但打不开"的模型是需要被看见的事实。
    """
    base = (base_url or "").strip()
    if not base:
        try:
            from core.ollama_endpoint import resolve_ollama_base_url  # noqa: PLC0415

            base = resolve_ollama_base_url()
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome("unreachable", f"解析 Ollama 地址失败: {exc}"), []

    http, owned = client, False
    if http is None:
        try:
            import httpx  # noqa: PLC0415

            http = httpx.Client(timeout=_HTTP_TIMEOUT_S)
            owned = True
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome("unreachable", f"httpx 不可用: {exc}"), []

    try:
        try:
            resp = http.get(f"{base}/api/tags")
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome("unreachable", f"{base} 连不上: {type(exc).__name__}"), []
        if resp.status_code != 200:
            return ProbeOutcome("unreachable", f"/api/tags 返回 {resp.status_code}"), []

        try:
            listed = resp.json().get("models") or []
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome("unreachable", f"/api/tags 返回的不是 JSON: {exc}"), []
        if not listed:
            return ProbeOutcome("empty", "Ollama 在跑，但一个模型都没装"), []

        facts: List[LocalModelFact] = []
        for entry in listed:
            tag = str((entry or {}).get("name") or "").strip()
            if not tag:
                continue
            facts.append(_show_one(http, base, tag, entry))
        return ProbeOutcome("ok"), facts
    finally:
        if owned:
            try:
                http.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭探测客户端失败(无妨): %s", exc)


def _show_one(http: Any, base: str, tag: str, listed_entry: Dict[str, Any]) -> LocalModelFact:
    """对一个 tag 调 ``/api/show``，取规格；打不开就标 ``healthy=False``。"""
    size_mb = 0
    try:
        size_mb = int(int(listed_entry.get("size") or 0) / (1024 * 1024))
    except (TypeError, ValueError):
        size_mb = 0

    try:
        r = http.post(f"{base}/api/show", json={"name": tag})
    except Exception as exc:  # noqa: BLE001
        return LocalModelFact(
            tag=tag, size_mb=size_mb, healthy=False, capabilities=(f"show_failed:{type(exc).__name__}",)
        )
    if r.status_code != 200:
        return LocalModelFact(tag=tag, size_mb=size_mb, healthy=False)

    try:
        body = r.json() or {}
    except Exception:  # noqa: BLE001
        return LocalModelFact(tag=tag, size_mb=size_mb, healthy=False)

    details = body.get("details") or {}
    info = body.get("model_info") or {}
    # 上下文长度的键名带着架构前缀（如 ``qwen3.context_length``），架构名各家不同，
    # 所以按后缀找而不是写死键名 —— 写死的话换个架构就恒为 0。
    ctx = 0
    for key, val in info.items():
        if str(key).endswith(".context_length"):
            try:
                ctx = int(val)
                break
            except (TypeError, ValueError):
                continue
    caps = body.get("capabilities") or []
    return LocalModelFact(
        tag=tag,
        size_mb=size_mb,
        parameter_size=str(details.get("parameter_size") or ""),
        quantization=str(details.get("quantization_level") or ""),
        context_length=ctx,
        capabilities=tuple(str(c) for c in caps),
        healthy=True,
    )


# ---------------------------------------------------------------------------
# 云端：这把 key 实际能调哪些
# ---------------------------------------------------------------------------


def probe_provider_models(name: str, cfg: Any, *, client: Any = None) -> ProviderProbe:
    """问某个 provider 的 ``{base_url}/models``：**这把 key 实际能调什么**。

    Args:
        name: provider 名。
        cfg: ``multi_llm_router.ProviderConfig``（需要 ``base_url`` / ``api_key``）。
        client: 注入的 httpx 客户端（测试用）。

    OpenAI 兼容的 ``/models`` 是这批 provider 里最通用的一个口。少数家不提供
    （如 Anthropic 走自己的协议），那时如实报 ``unreachable`` 并说明原因 ——
    **不把"这家没有这个口"说成"你配的模型不存在"**，那会让排错指向完全错误的方向。
    """
    base = str(getattr(cfg, "base_url", "") or "").strip().rstrip("/")
    key = str(getattr(cfg, "api_key", "") or "").strip()
    if not base:
        return ProviderProbe(name, ProbeOutcome("unreachable", "没有 base_url"))
    if not key:
        # key 没填不是错误 —— 这家就是没启用。与"填了但不对"必须分开。
        return ProviderProbe(name, ProbeOutcome("unreachable", "未填 API key（这家没启用）"))

    http, owned = client, False
    if http is None:
        try:
            import httpx  # noqa: PLC0415

            http = httpx.Client(timeout=_HTTP_TIMEOUT_S)
            owned = True
        except Exception as exc:  # noqa: BLE001
            return ProviderProbe(name, ProbeOutcome("unreachable", f"httpx 不可用: {exc}"))

    try:
        try:
            r = http.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        except Exception as exc:  # noqa: BLE001
            return ProviderProbe(name, ProbeOutcome("unreachable", f"{base}/models 连不上: {type(exc).__name__}"))
        if r.status_code in (401, 403):
            return ProviderProbe(name, ProbeOutcome("unauthorized", f"key 被拒（HTTP {r.status_code}）"))
        if r.status_code == 404:
            return ProviderProbe(name, ProbeOutcome("unreachable", "这家没有 /models 口（不代表配置有错）"))
        if r.status_code != 200:
            return ProviderProbe(name, ProbeOutcome("unreachable", f"/models 返回 {r.status_code}"))
        try:
            body = r.json() or {}
        except Exception as exc:  # noqa: BLE001
            return ProviderProbe(name, ProbeOutcome("unreachable", f"/models 返回的不是 JSON: {exc}"))
        ids = [str((m or {}).get("id") or "").strip() for m in (body.get("data") or [])]
        ids = [i for i in ids if i]
        if not ids:
            return ProviderProbe(name, ProbeOutcome("empty", "/models 通了，但一个模型都没报"))
        return ProviderProbe(name, ProbeOutcome("ok"), tuple(ids))
    finally:
        if owned:
            try:
                http.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭探测客户端失败(无妨): %s", exc)


# ---------------------------------------------------------------------------
# 比对：配的那张表 vs 实际能调的
# ---------------------------------------------------------------------------


def audit_provider_catalog(providers: Optional[Dict[str, Any]] = None, *, client: Any = None) -> List[CatalogFinding]:
    """把配置里的 provider 表与实际探到的逐条比对。

    Args:
        providers: ``{name: ProviderConfig}``；省略时从活的路由器取。
        client: 注入的 httpx 客户端（测试用）。

    Returns:
        对不上的地方。**空列表 = 全对上了**，而"一条都没探到"会以 ``untested``
        出现在结果里 —— 那不是"没问题"，是"没验成"，两者不能都表现为空。

    为什么要有这个函数
    ------------------
    provider 表里十几家、几十个型号名。人肉眼看不出 ``kimi-k3`` 今天还在不在、
    ``base_url`` 有没有改版。这些都是**能问出来的事实**，问一次比抄一次可靠。
    """
    if providers is None:
        try:
            from core.multi_llm_router import get_llm_router  # noqa: PLC0415

            providers = dict(get_llm_router().providers)
        except Exception as exc:  # noqa: BLE001
            return [CatalogFinding("(router)", "unreachable", f"取不到路由器：{exc}")]

    findings: List[CatalogFinding] = []
    for name, cfg in sorted(providers.items()):
        if str(getattr(cfg, "source_type", "api")) != "api":
            continue  # 本地那几家走 probe_local_models，不是 /models
        probe = probe_provider_models(name, cfg, client=client)
        configured = [str(m) for m in (getattr(cfg, "models", None) or [])]
        default = str(getattr(cfg, "default_model", "") or "")

        if probe.outcome.status in ("unreachable", "unauthorized"):
            findings.append(
                CatalogFinding(
                    name,
                    "untested" if probe.outcome.status == "unreachable" else "unauthorized",
                    probe.outcome.detail,
                    configured=configured,
                )
            )
            continue

        available = list(probe.models)
        missing = [m for m in configured if m not in available]
        if missing:
            findings.append(
                CatalogFinding(
                    name,
                    "model_missing",
                    f"配了 {len(missing)} 个对面没报的型号：{', '.join(missing)}",
                    configured=missing,
                    available=available,
                )
            )
        if default and default not in available:
            findings.append(
                CatalogFinding(
                    name,
                    "default_missing",
                    f"默认型号 {default!r} 不在对面报的清单里 —— 这家每一次调用都会撞",
                    configured=[default],
                    available=available,
                )
            )
    return findings


def format_audit_report(findings: List[CatalogFinding]) -> str:
    """把比对结果排成人能读的一段。"""
    if not findings:
        return "✅ 全部对上了（或没有可探的 provider）。"
    by_kind: Dict[str, List[CatalogFinding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    order = ("default_missing", "model_missing", "unauthorized", "untested", "unreachable")
    titles = {
        "default_missing": "❌ 默认型号对不上（每次调用都会撞）",
        "model_missing": "⚠️  配了但对面没报的型号",
        "unauthorized": "🔑 key 被拒",
        "untested": "· 没验成（多半是没填 key 或这家没有 /models 口）",
        "unreachable": "· 探测本身失败",
    }
    out: List[str] = []
    for kind in order:
        items = by_kind.get(kind)
        if not items:
            continue
        out.append(titles.get(kind, kind))
        for f in items:
            out.append(f"    {f.provider:<12} {f.detail}")
        out.append("")
    return "\n".join(out).rstrip()
