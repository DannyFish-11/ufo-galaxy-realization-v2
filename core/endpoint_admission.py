"""core/endpoint_admission.py — 这家 provider 的地址还是我登记过的那个吗
========================================================================

问题:改掉一个地址,密钥和全部对话内容一起换个地方送
--------------------------------------------------
``core.multi_llm_router._register_from_registry`` 允许用环境变量(``base_env``,
如 ``OPENAI_API_BASE``)或面板短键(``base_key``)**覆盖** ``PROVIDER_REGISTRY``
里写死的 ``base_url``::

    override = self._get_key(base_key) if base_key else ""
    if not override and base_env:
        override = os.environ.get(base_env, "")
    if override:
        base = override          # ← 从此这家的请求全发去新地址

这个能力本身是**必要的**:国内大量用户走中转/relay(one-api 之类),没有它这个程序
在很多环境里根本用不了。但它同时也是一条完整的窃取路径 —— 换掉地址,``api_key``
和每一次对话的全文都会照常发过去,而且**一切看起来都正常工作**。

在这个模块之前,系统里没有任何一处说得出"我现在连的地址是不是原厂的"。

这道闸做什么、不做什么
----------------------
**做**:把"这家现在连的是不是登记地址"变成一处可问的判据,并让它出现在诊断面上。
覆盖了就明说覆盖了,以及覆盖成了什么。

**不做**:默认不拦。中转是主流用法,默认拦会把大量用户直接打死,而**一道被关掉的
闸比没有闸更糟** —— 它还在报告里显示"已启用"。

真正的拦截由 ``core.egress_guard`` 承担:地址被改到白名单外的主机时,``enforce``
档会拦下来。两道闸各司其职 —— 这一道回答"是不是原厂",那一道回答"这个主机准不准
出站"。把两件事塞进一个判据,结果是两边都说不准。

``GALAXY_ALLOW_ENDPOINT_OVERRIDE=0`` 给"绝不走中转"的部署:那一档下覆盖直接失效,
回落到登记地址,并留痕。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("Galaxy.EndpointAdmission")

#: 判定取值。``unknown`` = 这个 provider 不在注册表里,**说不出**它的登记地址 ——
#: 与"没被改过"必须可区分。
ENDPOINT_VERDICTS: Tuple[str, ...] = ("canonical", "overridden", "unknown")


@dataclass(frozen=True)
class EndpointAdmission:
    """这家 provider 当前连的地址,以及它是不是登记的那个。"""

    verdict: str = "unknown"
    provider: str = ""
    #: 注册表里写死的地址;查不到为空串。
    canonical: str = ""
    #: 实际会用的地址,**已脱敏**(只到 ``scheme://host[:port]``)—— 这个字段会进
    #: HTTP 响应,而覆盖值来自凭证库且可能带 userinfo。见 :func:`redact_url`。
    effective: str = ""
    #: 覆盖是从哪儿来的:``env`` / ``panel`` / 空串(没被覆盖)。
    source: str = ""
    reason: str = ""

    @property
    def is_canonical(self) -> bool:
        """连的是不是原厂地址。``unknown`` 一律为假 —— 说不出来就不算数。"""
        return self.verdict == "canonical"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "provider": self.provider,
            "canonical": self.canonical,
            "effective": self.effective,
            "source": self.source,
            "reason": self.reason,
            "is_canonical": self.is_canonical,
        }


def redact_url(url: str) -> str:
    """只保留 ``scheme://host[:port]``,给**任何要把这个地址显示出去**的地方用。

    为什么必须有这一道
    ------------------
    覆盖值来自 ``MultiLLMRouter._get_key(base_key)`` —— 那是**凭证库的访问器**,
    与 API key 同一个存储。而 base_url 本身也可以带 userinfo::

        https://user:token@relay.example.com/v1

    整串此前既进日志,又经 ``reason`` / ``effective`` 进了
    ``GET /api/v1/security/connection-provenance`` 的**响应体**。CodeQL 报的是
    前者(clear-text logging),而后者更重:那是给外部看的。

    脱敏之后诊断价值一点没少 —— 要判断的是"它指向哪台主机",而 host 就够了;
    userinfo、path、query 对这个判断没有贡献,只有泄露风险。

    与 ``core.execution_isolation.blocked_reason`` 同款处置:**日志与响应共用同一个
    函数**,而不是一边打全串、另一边自己再截一遍 —— 后者迟早会漂移,而漂移的方向
    总是"某一条路径上把全串漏出去了"。
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = (parsed.hostname or "").strip()
        if not host:
            return "(地址里没有主机名)"
        scheme = f"{parsed.scheme}://" if parsed.scheme else ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{scheme}{host}{port}"
    except ValueError as exc:  # noqa: BLE001
        logger.debug("地址解析不了: %s", exc)
        # 与空串区分:空串是"没有地址",这是"有地址但读不出来"。
        return "(地址解析不了)"


def override_allowed() -> bool:
    """允不允许覆盖 provider 地址。默认允许 —— 见模块头。"""
    raw = (os.environ.get("GALAXY_ALLOW_ENDPOINT_OVERRIDE", "1") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _registry() -> List[Dict[str, Any]]:
    """局部 import:``multi_llm_router`` 会反过来用本模块,模块级会成环。"""
    try:
        from core.multi_llm_router import PROVIDER_REGISTRY  # noqa: PLC0415

        return list(PROVIDER_REGISTRY)
    except Exception as exc:  # noqa: BLE001 — 读不出来就是判不出来,不是"没被改"
        logger.debug("PROVIDER_REGISTRY 读不出来: %s", exc)
        return []


def _spec_for(provider: str) -> Dict[str, Any]:
    for spec in _registry():
        if str(spec.get("name", "")) == provider:
            return spec
    return {}


def canonical_base_url(provider: str) -> str:
    """注册表里写死的地址。查不到返回空串(**判不出来**)。

    判据走 ``PROVIDER_REGISTRY`` —— 那是本仓唯一一份 provider 地址表。
    在这里另抄一份的话,加一家云厂商就会漏一处,而漏的表现是"这家永远显示被改过"。
    """
    return str(_spec_for(provider).get("base_url", ""))


def evaluate(provider: str, effective: str, *, source: str = "") -> EndpointAdmission:
    """判定一家 provider 的地址。**唯一判据处**,不抛异常。"""
    canonical = canonical_base_url(provider)
    effective_clean = (effective or "").strip()

    # 比较用**全串**(尾斜杠之外的任何差异都算被改过),但存进判定对象、进而进
    # HTTP 响应的一律脱敏 —— 覆盖值来自凭证库且可能带 userinfo,见 redact_url。
    shown = redact_url(effective_clean)

    if not canonical:
        return EndpointAdmission(
            verdict="unknown",
            provider=provider,
            effective=shown,
            source=source,
            reason=f"{provider} 不在 PROVIDER_REGISTRY 里,说不出它的登记地址",
        )

    if effective_clean.rstrip("/") == canonical.rstrip("/"):
        return EndpointAdmission(
            verdict="canonical",
            provider=provider,
            canonical=canonical,
            effective=shown,
            reason="连的是登记地址",
        )

    return EndpointAdmission(
        verdict="overridden",
        provider=provider,
        canonical=canonical,
        effective=shown,
        source=source,
        reason=(f"{provider} 的地址被覆盖为 {shown}(登记地址是 {canonical})——" "密钥与对话全文都会发往这个地址"),
    )


def resolve_base_url(provider: str, canonical: str, override: str, *, source: str = "") -> str:
    """覆盖生效与否的**唯一决定处**,给 ``_register_from_registry`` 调。

    返回真正该用的地址。``GALAXY_ALLOW_ENDPOINT_OVERRIDE=0`` 时覆盖不生效,回落到
    登记地址并留痕 —— **不静默忽略**,否则用户会以为中转配上了却查不出为什么没走。
    """
    override_clean = (override or "").strip()
    if not override_clean:
        return canonical

    # 日志里只出脱敏后的地址,见 redact_url:覆盖值来自凭证库,且可能带 userinfo。
    if not override_allowed():
        logger.warning(
            "provider %s 的地址覆盖被拒(GALAXY_ALLOW_ENDPOINT_OVERRIDE=0):" "忽略 %s,回落到登记地址 %s",
            provider,
            redact_url(override_clean),
            redact_url(canonical),
        )
        return canonical

    logger.info(
        "provider %s 的地址已被覆盖为 %s(登记地址 %s,来源 %s)——" "密钥与对话全文都会发往这个地址",
        provider,
        redact_url(override_clean),
        redact_url(canonical),
        source or "未标注",
    )
    return override_clean


def endpoint_report(effective: Dict[str, str] | None = None) -> Dict[str, Any]:
    """只读诊断:哪几家的地址不是原厂的。

    ``effective`` 是 ``{provider: 实际地址}``;不传时**从环境变量推**当前会生效的
    覆盖 —— 那样这个端点在路由还没起来时也能回答问题。
    """
    resolved: Dict[str, str] = {}
    if effective is not None:
        resolved = dict(effective)
    else:
        for spec in _registry():
            name = str(spec.get("name", ""))
            base = str(spec.get("base_url", ""))
            base_env = spec.get("base_env")
            if base_env:
                base = (os.environ.get(str(base_env), "") or "").strip() or base
            resolved[name] = base

    decisions = [evaluate(name, url, source="env").to_dict() for name, url in resolved.items()]
    overridden = [d for d in decisions if d["verdict"] == "overridden"]
    return {
        "override_allowed": override_allowed(),
        "total": len(decisions),
        "overridden_count": len(overridden),
        # 只列被改过的:全列出来会让真正要看的那几条淹掉。
        "overridden": overridden,
        "unknown": [d["provider"] for d in decisions if d["verdict"] == "unknown"],
    }
