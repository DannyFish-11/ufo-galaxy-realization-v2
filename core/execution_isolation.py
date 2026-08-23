"""core/execution_isolation.py — 模型生成的代码,跑在多硬的边界里
==================================================================

问题:仓库里已经有一层隔离,但它默认不生效
------------------------------------------
``core.safe_executor.SafeExecutor`` 跑的是**智能体自己写出来的代码**。它的执行策略
写着"优先委托 Node_09_Sandbox,降级到内置 Python 沙箱",而 Node_09 有自带的
``Dockerfile``(``python:3.11-slim`` + 非 root 用户),``core.node_lifecycle.
container_start_node`` 也早就能用 Docker/Podman 把它起起来。

三块拼图齐全,中间断了一根线::

    node09_url = os.environ.get("NODE09_SANDBOX_URL", "")   # 默认空串
    ...
    if self._node09_url:            # 空串 → 假
        ...委托容器...
    # → 直接落到内置:正则挡 pattern + setrlimit + 同一内核的 subprocess

而 ``container_start_node`` 全仓**只有一个调用方** —— 面板上的一个 HTTP 端点,
要人手动去点。也就是说:默认配置下,模型生成的代码跑在**用户自己的内核、自己的
用户身份**下,而仓库里那层容器隔离静静躺着没人用。

这与 ``--n-cpu-moe`` 是同一个形状:能力在、路没接、判据不说实话。

本模块做什么
------------
把"这次执行跑在多硬的边界里"变成**一处可问的判据**,并让结果**自己说**它跑在哪一层。

============  ==============================================================
``container`` Node_09 跑在 Docker/Podman 容器里:独立文件系统/进程/网络命名空间,
              非 root。**默认首选**(只要这台机器有容器运行时 —— Windows 上
              Docker Desktop 同样算)。
``builtin``   正则挡危险 pattern + ``setrlimit`` + 临时目录里 ``subprocess``。
              **同一个内核、同一个用户、文件系统全可读**。它挡得住手滑和低级
              错误,挡不住一次不走运的代码生成。
============  ==============================================================

刻意只有两档
------------
microVM(Firecracker / AgentENV / E2B)是真正更硬的第三档,但**这里不给它留一个空
取值**:一个永远不会被返回的档位,就是又一次"看起来接上了,其实没有"。等真接上那条
路的那一天再加,加的时候连同它的探测一起加。

降级必须响亮,而且必须留在结果里
-------------------------------
容器起不来时回落内置是对的(不能让用户的任务直接失败),但**不能悄悄回落**:
调用方若不知道这次是在裸机上跑的,就会以为自己有边界。所以
:class:`IsolationDecision` 带着 ``degraded`` 与 ``reason``,``SafeExecutor``
把它写进 ``ExecutionResult.isolation``。

为什么不在请求里等容器 build
----------------------------
``container_start_node`` 首次要 build 镜像,那个函数自己给的超时上限是 **1800 秒**。
在一次用户请求里同步等它是不可接受的。所以:**探测是同步的、拉起是后台的** ——
容器还没就绪时这一次如实走 builtin 并标 ``degraded``,后台把它拉起来,后续的执行
就落到容器里。第一次执行拿不到容器边界,这一点写在这里,不藏着。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, Tuple

logger = logging.getLogger("Galaxy.ExecutionIsolation")

#: 隔离档位。**只列真正实现了的那些** —— 见模块头"刻意只有两档"。
ISOLATION_TIERS: Tuple[str, ...] = ("container", "builtin")

#: 这个节点提供代码执行沙箱。名字与 ``nodes/`` 下的目录一致。
SANDBOX_NODE = "Node_09_Sandbox"

#: 用户意愿。``auto`` = 有容器就用容器;``container`` = **没有容器就拒绝执行**
#: (给"绝不让模型生成的代码碰裸机"的人);``builtin`` = 强制内置。
ISOLATION_MODES: Tuple[str, ...] = ("auto", "container", "builtin")


@dataclass(frozen=True)
class IsolationDecision:
    """这一次执行该跑在哪一层,以及为什么。"""

    tier: str = "builtin"
    #: 容器档的 Node_09 地址;builtin 档为空串。
    endpoint: str = ""
    #: 本来该走更硬的一档、实际没走成。**调用方必须能看见这一位。**
    degraded: bool = False
    reason: str = ""
    #: 这台机器上探到的容器运行时名(docker/podman);没有则空串。
    runtime: str = ""

    @property
    def is_isolated(self) -> bool:
        """有没有真正的边界。``builtin`` 一律为假 —— 它跑在同一个内核、同一个用户下。"""
        return self.tier == "container"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "endpoint": self.endpoint,
            "degraded": self.degraded,
            "reason": self.reason,
            "runtime": self.runtime,
            "is_isolated": self.is_isolated,
        }


class IsolationUnavailable(RuntimeError):
    """要求 ``container`` 档但这台机器给不出来 —— 显式拒绝执行,不静默降级。"""


def blocked_reason(runtime: str, *, started: bool) -> str:
    """给不出容器边界时那句**人写的**话。

    单独一个函数,是为了让"给客户端看的文案"与"异常对象"彻底分家:
    ``isolation_report`` 要把这句话放进 HTTP 响应,而 CodeQL 对
    「异常信息流到响应里」是会报的(``core/routes/modality.py`` 里已经有同一条
    处置的先例:异常详情只进服务端日志,不回传给客户端)。

    所以两边**各自调用本函数**得到同一句话,而不是一边 ``str(exc)`` 另一边重写一遍 ——
    前者会把异常文本送出去,后者会让两处措辞漂移。
    """
    if not runtime:
        return "GALAXY_EXECUTION_ISOLATION=container 要求容器边界,但这台机器没装 Docker/Podman"
    if started:
        return f"GALAXY_EXECUTION_ISOLATION=container 要求容器边界,沙箱当前不可达(已在后台用 {runtime} 拉起,稍后重试)"
    return f"GALAXY_EXECUTION_ISOLATION=container 要求容器边界,沙箱容器没起着(装了 {runtime})"


def isolation_mode() -> str:
    """用户意愿;取值非法时按 ``auto``(不因为拼错就把隔离关掉)。"""
    raw = os.environ.get("GALAXY_EXECUTION_ISOLATION", "auto").strip().lower()
    return raw if raw in ISOLATION_MODES else "auto"


def container_runtime_name() -> str:
    """这台机器上可用的容器运行时(docker/podman);没有返回空串。

    判据走 ``core.container_runtime`` —— 那是本仓已有的唯一处,连"两个都装时选哪个"
    的持久化选择都在那边。这里绝不自己 ``which`` 一遍。

    ``interactive=False``:执行路径上不能弹交互提示。
    """
    try:
        from core import container_runtime as cr  # noqa: PLC0415

        return str(cr.resolve_runtime(interactive=False) or "")
    except Exception as exc:  # noqa: BLE001 — 探不出来就是没有
        logger.debug("容器运行时探测失败,按没有处理: %s", exc)
        return ""


def _explicit_endpoint() -> str:
    """人显式指定的 Node_09 地址。给"沙箱跑在别的机器上"的部署。"""
    return os.environ.get("NODE09_SANDBOX_URL", "").strip()


def _node09_port() -> int:
    try:
        from core.port_config import get_node_port  # noqa: PLC0415

        return int(get_node_port(SANDBOX_NODE) or 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Node_09 端口读不出来: %s", exc)
        return 0


def _probe(endpoint: str, *, client: Any = None, timeout: float = 1.5) -> bool:
    """这个地址上真的有一个活着的沙箱吗。探不通一律 False。"""
    if not endpoint:
        return False
    try:
        http = client
        if http is None:
            import httpx  # noqa: PLC0415

            http = httpx.Client(timeout=timeout)
        resp = http.get(f"{endpoint.rstrip('/')}/health")
        return getattr(resp, "status_code", 0) == 200
    except Exception:  # noqa: BLE001 — 探不通就是没就绪
        return False


_start_lock = threading.Lock()
_start_attempted = False


def _kick_off_container(runtime: str) -> None:
    """后台把 Node_09 拉起来。**只尝试一次**,而且不等它。

    不等的理由见模块头:首次 build 的超时上限是 1800 秒,在用户请求里同步等它
    是不可接受的。只试一次的理由:起不来通常是环境问题(没装、没权限、build 失败),
    每次执行都重试一遍只会把每次执行都拖慢,而且日志会被刷满。
    """
    global _start_attempted
    with _start_lock:
        if _start_attempted:
            return
        _start_attempted = True

    def _run() -> None:
        try:
            from core.node_lifecycle import container_start_node  # noqa: PLC0415

            res = container_start_node(SANDBOX_NODE)
            if res.get("ok"):
                logger.info("代码执行沙箱容器已拉起(%s):后续执行将落到容器边界内", runtime)
            else:
                logger.warning(
                    "代码执行沙箱容器拉起失败:%s —— 执行会继续走内置轻量沙箱"
                    "(同一内核、同一用户),这一点会如实记在每次执行结果的 isolation 上",
                    res.get("error", "未知原因"),
                )
        except Exception as exc:  # noqa: BLE001 — 拉起失败不该影响执行本身
            logger.warning("代码执行沙箱容器拉起异常: %s", exc)

    threading.Thread(target=_run, name="sandbox-container-start", daemon=True).start()


def reset_start_attempt() -> None:
    """清掉"已经试过拉起"的标记。给测试用 —— 它是进程级状态。"""
    global _start_attempted
    with _start_lock:
        _start_attempted = False


def resolve_isolation(*, client: Any = None, allow_start: bool = True) -> IsolationDecision:
    """这一次执行该跑在哪一层 —— **判据只此一处**。

    Args:
        client: 探活用的 HTTP 客户端(测试注入)。
        allow_start: 容器没就绪时要不要后台拉起。测试里关掉。

    Raises:
        IsolationUnavailable: 模式是 ``container`` 但这台机器给不出容器边界。
            显式抛而不是降级 —— 那个模式的**全部含义**就是"宁可不跑,也不在裸机上跑"。
    """
    mode = isolation_mode()

    if mode == "builtin":
        return IsolationDecision(
            tier="builtin",
            degraded=False,  # 人明确要求的,不算降级
            reason="GALAXY_EXECUTION_ISOLATION=builtin(人显式指定)",
        )

    # 显式指定的地址优先:那是"沙箱跑在别处"的部署,不需要本机有容器运行时。
    explicit = _explicit_endpoint()
    if explicit and _probe(explicit, client=client):
        return IsolationDecision(tier="container", endpoint=explicit, reason="NODE09_SANDBOX_URL 上的沙箱可达")

    runtime = container_runtime_name()
    port = _node09_port()
    local_endpoint = f"http://127.0.0.1:{port}" if port else ""

    if local_endpoint and _probe(local_endpoint, client=client):
        return IsolationDecision(
            tier="container", endpoint=local_endpoint, runtime=runtime, reason="本机沙箱容器已就绪"
        )

    # 到这里:没有可达的沙箱。
    #
    # started 要如实记:``isolation_report`` 走的是 allow_start=False(体检是只读观测,
    # 不该顺手改变运行时状态),那条路上说"已在后台拉起"就是假话 —— 而这份 reason
    # 正是给人看着判断该动哪里的。
    started = bool(runtime) and allow_start
    if started:
        _kick_off_container(runtime)

    if mode == "container":
        raise IsolationUnavailable(blocked_reason(runtime, started=started))

    if not runtime:
        why = "这台机器没装 Docker/Podman —— 代码将跑在同一个内核、同一个用户下"
    elif started:
        why = f"沙箱容器还没就绪(已用 {runtime} 在后台拉起) —— 这一次跑在同一个内核下"
    else:
        why = f"沙箱容器没起着(装了 {runtime}) —— 代码将跑在同一个内核、同一个用户下"
    return IsolationDecision(tier="builtin", degraded=True, reason=why, runtime=runtime)


def isolation_report(*, client: Any = None) -> Dict[str, Any]:
    """人可读的隔离现状。给面板与 ``scripts/`` 的体检用。

    **不触发后台拉起** —— 体检是只读观测,不该顺手改变运行时状态。
    """
    runtime = container_runtime_name()
    blocked = False
    try:
        decision = resolve_isolation(client=client, allow_start=False)
    except IsolationUnavailable as exc:
        # **异常文本不进响应。** 这份报告是一个 HTTP 端点的返回值,把 str(exc) 放进去
        # 就是"异常信息经响应外泄"(CodeQL 会报,而本仓已有同一条处置的先例:
        # core/routes/modality.py —— 异常详情只进服务端日志)。
        #
        # 客户端拿到的是 blocked_reason() 那句人写的话 —— 与异常里那句**同源**
        # (两边都调它),所以既不外泄也不会措辞漂移。
        logger.warning("执行隔离要求未满足: %s", exc)
        blocked = True
        # allow_start=False 那条路上永远没拉起过,所以 started 恒 False。
        decision = IsolationDecision(
            tier="builtin", degraded=True, reason=blocked_reason(runtime, started=False), runtime=runtime
        )
    return {
        "mode": isolation_mode(),
        "decision": decision.to_dict(),
        "container_runtime": runtime,
        "node09_port": _node09_port(),
        "explicit_endpoint": _explicit_endpoint(),
        #: 这一位替代了原来那个装着异常文本的 error 字段。它是**布尔**:
        #: "要不要拦"是调用方需要的判断,异常的具体措辞不是。
        "blocked": blocked,
    }


EXECUTION_ISOLATION_AUTHORITY: str = (
    "EXECUTION_ISOLATION_V1: core/execution_isolation.py | 模型生成代码跑在多硬的边界里, "
    "判据只此一处. resolve_isolation() → IsolationDecision(tier=container|builtin, "
    "endpoint, degraded, reason). container=Node_09 在 Docker/Podman 容器内(非 root, "
    "独立命名空间); builtin=正则+setrlimit+同内核 subprocess. 容器运行时探测走 "
    "core.container_runtime(唯一处), 容器拉起走 core.node_lifecycle.container_start_node "
    "且**后台异步**(首次 build 上限 1800s, 不能卡在用户请求里). 降级必须带 degraded+reason "
    "并写进 ExecutionResult.isolation. GALAXY_EXECUTION_ISOLATION=container 时显式抛 "
    "IsolationUnavailable 而不降级."
)

__all__ = [
    "ISOLATION_TIERS",
    "ISOLATION_MODES",
    "SANDBOX_NODE",
    "IsolationDecision",
    "IsolationUnavailable",
    "isolation_mode",
    "blocked_reason",
    "container_runtime_name",
    "resolve_isolation",
    "isolation_report",
    "reset_start_attempt",
    "EXECUTION_ISOLATION_AUTHORITY",
]
