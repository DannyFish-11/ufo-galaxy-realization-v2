"""core/egress_guard.py — 这次出站发去了哪儿
==============================================

问题:整个系统说不出"往外发了什么、发去了哪儿"
----------------------------------------------
在这个模块之前,``core/`` 下 ``egress`` / ``outbound`` / ``network_policy`` /
``firewall`` **零命中**。也就是说:一次执行往外连了哪些主机,系统里没有任何一处
说得出来,更没有任何一处能拦。

为什么这一位比它看起来更重要
----------------------------
提示注入最严重的后果通常**不是**"删了文件" —— 那种动静大、好发现。真正难办的是
**数据外泄**,而且形式极其隐蔽:把私有数据编码进一个 URL 的 query string,然后
"顺便"抓一下那个链接;或者写进一次看起来完全正常的 API 调用参数里。

``core.execution_isolation`` 挡住了"模型写的代码能在这台机器上干什么",但它**挡不住
出站** —— 容器里一样能发网络请求。这一位是那道边界的另一半。

三档,以及为什么默认不是最紧的那一档
------------------------------------
==========  ==================================================================
``audit``   **默认**。记账但不拦。
``enforce`` 白名单之外一律拒。
``off``     完全不生效(连记账都不做)。
==========  ==================================================================

默认是 ``audit`` 而不是 ``enforce``,这是个**要说清楚的让步**:这台机器上的合法出站
远不止 provider 调用 —— MCP 服务器、工具抓网页、依赖安装都在出站。带着一份没人整理过
的白名单直接开 ``enforce``,结果是把能用的东西全打死,然后这道闸被整个关掉。

**所以这里必须诚实:``audit`` 档不提供任何保护,它只提供可见性。**
``egress_report()`` 会把这句话如实报出来,绝不让 ``mode=audit`` 看起来像"已防护"
—— 那正是这类闸最常见的失效方式:装着一个不拦的拦截器,然后以为自己安全。

白名单是**推导**出来的,不是另攒一份
------------------------------------
默认白名单来自仓库里已有的唯一处:``PROVIDER_REGISTRY`` 里各家的 ``base_url``
与 ``alt_base_urls``(同一家官方自己的其它同构端点,如智谱的国内/海外双域名)、
``core.weights_admission`` 的权重主机表。这样 ``enforce`` 才是**可用**的 ——
一开始就覆盖了这个程序自己会发起的合法流量,而不是要人从零列。

**运行期被覆盖成的地址不进白名单。** ``base_env``/``base_key`` 能把一家的
``base_url`` 换掉,但白名单只认仓库里写死的官方地址 —— 否则谁能设那个环境变量,
谁就能给自己的主机盖章放行,而那正是 ``core.endpoint_admission`` 要防的路径。
真要走中转,得由人显式写进 ``GALAXY_EGRESS_ALLOW``:那一步的显式性就是这道闸的价值。

自己另攒一份 provider 地址表的话,加一家云厂商就会漏一处,而漏的表现是"某家突然
连不上",没人会想到是这道闸。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("Galaxy.EgressGuard")

#: 三档。``audit`` 默认 —— 见模块头"为什么默认不是最紧的那一档"。
EGRESS_MODES: Tuple[str, ...] = ("audit", "enforce", "off")

#: 记账保留多少条。有界 —— 一个无界的账本本身就是一次内存泄漏。
LEDGER_MAX = 500

#: 本机回环。这些**不是出站**,不该占白名单的位置,也不该刷满账本。
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

_ledger: Deque[Dict[str, Any]] = deque(maxlen=LEDGER_MAX)
_ledger_lock = threading.Lock()


@dataclass(frozen=True)
class EgressDecision:
    """这一次出站的判定。"""

    allowed: bool = False
    host: str = ""
    mode: str = "audit"
    #: 命中的白名单项;没命中为空串。
    matched: str = ""
    #: ``loopback`` / ``private`` / ``allowlist`` / ``audit`` / ``blocked`` /
    #: ``unknown``(判不出来 —— URL 里根本没有主机)。
    kind: str = "unknown"
    reason: str = ""

    @property
    def enforced(self) -> bool:
        """这次判定**是否真的有拦截效力**。

        ``audit`` 档下 ``allowed`` 恒为真,那个真值不代表"审过了没问题"。
        调用方要区分这两件事时问这一位。
        """
        return self.mode == "enforce"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "host": self.host,
            "mode": self.mode,
            "matched": self.matched,
            "kind": self.kind,
            "reason": self.reason,
            "enforced": self.enforced,
        }


class EgressBlocked(RuntimeError):
    """``enforce`` 档下白名单之外的出站 —— 显式拒绝,不静默放行。"""


# ══════════════════════════════════════════════════════════════════════════
# 开关
# ══════════════════════════════════════════════════════════════════════════


def egress_mode() -> str:
    """用户意愿;取值非法时按 ``audit``(不因为拼错就把记账也关掉)。"""
    raw = (os.environ.get("GALAXY_EGRESS_MODE", "audit") or "audit").strip().lower()
    return raw if raw in EGRESS_MODES else "audit"


def private_allowed() -> bool:
    """允不允许连内网地址。默认允许 —— 跨设备编队/mesh 走的就是内网。

    关掉它会把多设备功能打死,所以默认开;但**内网出站一样进账本**,因为
    "把数据发给同一个局域网里的另一台机器"同样是一条外泄路径。
    """
    return (os.environ.get("GALAXY_EGRESS_ALLOW_PRIVATE", "1") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _user_allowlist() -> Tuple[str, ...]:
    raw = os.environ.get("GALAXY_EGRESS_ALLOW", "") or ""
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _provider_hosts() -> Tuple[str, ...]:
    """从 ``PROVIDER_REGISTRY`` 推导出各家的主机名。

    局部 import:``multi_llm_router`` 会反过来用本模块,模块级 import 会成环。
    """
    hosts: List[str] = []
    try:
        from core.multi_llm_router import PROVIDER_REGISTRY  # noqa: PLC0415

        for spec in PROVIDER_REGISTRY:
            # base_url 是这家的默认地址;alt_base_urls 是同一家**官方自己的**其它
            # 同构端点(如智谱的国内/海外双域名)。两者都算"这家的主机" —— 少了
            # 后者,用户按 registry 注释把 base_env 指到官方海外端点,enforce 档
            # 会把一次完全正当的调用拦死。
            #
            # 这里刻意**不**读运行期的 base_url 覆盖值:那等于谁能设环境变量谁就能
            # 给自己的主机放行,而覆盖恰恰是 core.endpoint_admission 要防的那条
            # 窃取路径。白名单只认仓库里写死的官方地址。
            for raw in [spec.get("base_url", ""), *(spec.get("alt_base_urls") or [])]:
                host = host_of(str(raw))
                if host:
                    hosts.append(host)
    except Exception as exc:  # noqa: BLE001 — 推不出来就是这一段为空,不是"允许所有"
        logger.debug("provider 主机表推导失败: %s", exc)
    return tuple(sorted(set(hosts)))


def _weights_hosts() -> Tuple[str, ...]:
    try:
        from core.weights_admission import allowed_hosts  # noqa: PLC0415

        return tuple(allowed_hosts())
    except Exception as exc:  # noqa: BLE001
        logger.debug("权重主机表读不出来: %s", exc)
        return ()


def allowlist() -> Tuple[str, ...]:
    """当前生效的白名单。**推导 + 用户追加**,见模块头。"""
    return tuple(sorted(set(_provider_hosts() + _weights_hosts() + _user_allowlist())))


# ══════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════


#: 合法主机名允许的字符。``:`` 与 ``[]`` 是给 IPv6 字面量留的。
#: 有这一道是因为 ``urlparse("//not a url")`` 会**把整串当主机名交回来** ——
#: 那样账本里会记下一个根本不存在的"主机",报告也就跟着失真。
_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-._:[]")


def host_of(url: str) -> str:
    """从 URL 取主机名。取不出来返回空串(**判不出来**,不是"没有主机")。"""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"//{raw}"
    try:
        host = (urlparse(raw).hostname or "").strip().lower()
    except ValueError as exc:  # noqa: BLE001
        logger.debug("URL 解析不了: %s", exc)
        return ""
    if not host or any(ch not in _HOST_CHARS for ch in host):
        # 长得就不像主机名 —— 当成判不出来,而不是记一个假主机。
        return ""
    return host


def _is_private(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _matches(host: str, entry: str) -> bool:
    """精确匹配,或显式写出的 ``*.example.com`` 通配。

    刻意**不做后缀包含匹配** —— ``evil-openai.com`` 会命中 ``openai.com`` 的
    朴素后缀判断,那种白名单形同虚设。
    """
    if host == entry:
        return True
    if entry.startswith("*."):
        suffix = entry[1:]  # ".example.com"
        return host.endswith(suffix) and len(host) > len(suffix)
    return False


def _record(decision: EgressDecision, purpose: str) -> None:
    """记账。``off`` 档不记 —— 那一档的含义就是"这个模块完全不在场"。"""
    with _ledger_lock:
        _ledger.append(
            {
                "at": time.time(),
                "host": decision.host,
                "purpose": purpose,
                "allowed": decision.allowed,
                "kind": decision.kind,
                "mode": decision.mode,
            }
        )


def evaluate(url: str, *, purpose: str = "") -> EgressDecision:
    """判定一次出站。**唯一判据处**,不抛异常。"""
    mode = egress_mode()
    host = host_of(url)

    if mode == "off":
        return EgressDecision(allowed=True, host=host, mode=mode, kind="unknown", reason="出口闸已关(off)")

    if not host:
        # URL 里根本没有主机:判不出来。**不能当成"没有出站"放过去。**
        decision = EgressDecision(
            allowed=(mode != "enforce"),
            host="",
            mode=mode,
            kind="unknown",
            reason="URL 里取不出主机名 —— 判不出来",
        )
        _record(decision, purpose)
        return decision

    if host in _LOOPBACK_HOSTS:
        # 回环不是出站。不记账,否则本地推理会瞬间刷满账本,把真正的出站淹掉。
        return EgressDecision(allowed=True, host=host, mode=mode, kind="loopback", reason="本机回环,不算出站")

    entries = allowlist()
    for entry in entries:
        if _matches(host, entry):
            decision = EgressDecision(
                allowed=True,
                host=host,
                mode=mode,
                matched=entry,
                kind="allowlist",
                reason=f"命中白名单 {entry}",
            )
            _record(decision, purpose)
            return decision

    if _is_private(host):
        allowed = private_allowed()
        decision = EgressDecision(
            allowed=allowed or mode != "enforce",
            host=host,
            mode=mode,
            kind="private",
            reason=("内网地址(跨设备编队走这条路)" if allowed else "内网地址,且 GALAXY_EGRESS_ALLOW_PRIVATE 已关"),
        )
        _record(decision, purpose)
        return decision

    decision = EgressDecision(
        # audit 档下这里是 True —— 但那**不代表审过了**,见 EgressDecision.enforced。
        allowed=(mode != "enforce"),
        host=host,
        mode=mode,
        kind="blocked" if mode == "enforce" else "audit",
        reason=(f"{host} 不在白名单上" if mode == "enforce" else f"{host} 不在白名单上(audit 档只记账,未拦截)"),
    )
    _record(decision, purpose)
    if mode == "enforce":
        logger.warning("出站被拒: %s(用途: %s)", host, purpose or "未标注")
    return decision


def check_egress(url: str, *, purpose: str = "") -> EgressDecision:
    """判定并在 ``enforce`` 档拦下时抛。给真正要拦的调用点。"""
    decision = evaluate(url, purpose=purpose)
    if not decision.allowed:
        raise EgressBlocked(decision.reason)
    return decision


# ══════════════════════════════════════════════════════════════════════════
# 账本与报告
# ══════════════════════════════════════════════════════════════════════════


def recent(limit: int = 50) -> List[Dict[str, Any]]:
    """最近的出站记录(新的在后)。"""
    with _ledger_lock:
        items = list(_ledger)
    return items[-limit:] if limit > 0 else []


def clear_ledger() -> None:
    """清账本。给测试和"我看过了"之后的手动清理。"""
    with _ledger_lock:
        _ledger.clear()


def egress_report() -> Dict[str, Any]:
    """只读诊断:出口闸此刻的姿态,以及它**有没有实际拦截效力**。"""
    mode = egress_mode()
    entries = allowlist()
    ledger = recent(LEDGER_MAX)
    off_list = [item for item in ledger if item.get("kind") in ("audit", "blocked")]
    return {
        "mode": mode,
        # 这一位是整份报告里最重要的:audit 档下它是 False。
        # 不给这一位,mode=audit 会被读成"已防护"。
        "enforcing": mode == "enforce",
        "protection": (
            "白名单外的出站会被拒"
            if mode == "enforce"
            else ("完全未生效(off)" if mode == "off" else "只记账,不拦截 —— 这一档不提供保护")
        ),
        "allowlist": list(entries),
        "allowlist_size": len(entries),
        "private_allowed": private_allowed(),
        "ledger_size": len(ledger),
        "off_allowlist_recent": off_list[-20:],
    }
