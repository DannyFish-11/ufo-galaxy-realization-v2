"""每个节点该在什么时候被拉起来 —— 125 个,一个不落。

问题
====
:mod:`core.activation_policy` 定义了四档策略(``always_on`` / ``on_demand`` /
``lazy`` / ``shared``),但"哪个节点属于哪一档"这件事只在
``registry/device_node_map.yaml`` 里回答过 —— 而那是一张**设备 → 节点**的表,
只覆盖 11 个设备型节点。剩下 114 个没有任何档位:运行时问"该不该起 Node_101"
根本无从回答。

为什么不是手写 114 条
=====================
一度打算把 114 个节点逐条塞进 ``device_node_map.yaml``。那是错的:那张表的
匹配键是 ``device_type`` / ``transport`` / ``capabilities``,而
``Node_101_CodeEngine`` 这类节点**根本不是设备驱动的** —— 没有任何 device_type
能表达"有人要生成代码"。硬塞进去会造出 114 条永远匹配不上的规则,比没有更糟:
它看起来覆盖了,实际一条也不会触发。

改为**推导**,而不是新开一张表
=============================
仓里已有的元数据足够回答这个问题,``node_dependencies.json`` 自己的
``_startup_tier_model`` 也写着它的原则::

    "Tiers are derived from existing startup_policy and group metadata —
     no new governance authority is introduced."

这里沿用同一条原则。判定顺序(先命中先算):

1. ``registry/device_node_map.yaml`` 里有显式 ``startup`` —— 设备型节点以它为准,
   那是人写的、有匹配条件的真实规则。
2. ``node_dependencies.json`` 的 ``startup_policy == "skip"`` —— 永不启动
   (5 个 ``Node_XX_Reserved`` 占位符 + ``Node_130_AutonomousCoding``)。
3. ``group == "core"`` 且 ``startup_policy == "active"`` —— ``always_on``,系统地基。
4. 其余一律 ``lazy`` —— 首次用到才起,起来后保活。

第 4 条是刻意的默认:**不知道什么时候需要它 ≠ 应该一直开着**。130 个节点全部常驻
既不现实也无必要;而 ``lazy`` 至少保证"真要用的时候它会在"。

覆盖不到的地方要说出来
======================
:func:`activation_policy_coverage` 把"每个磁盘上的节点各自按哪条规则定档"整个吐
出来,让"是不是真的一个不落"成为可验证的事实,而不是一句声明。
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Dict, Optional, Tuple

from core.activation_policy import ActivationPolicy

logger = logging.getLogger(__name__)

__all__ = [
    "NODE_ACTIVATION_POLICY_SENTINEL",
    "resolve_activation_policy",
    "activation_policy_coverage",
]

NODE_ACTIVATION_POLICY_SENTINEL = "NODE_ACTIVATION_POLICY::PER_NODE_TIER_DERIVATION"

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_NODE_DEPS = _REPO_ROOT / "node_dependencies.json"
_NODES_DIR = _REPO_ROOT / "nodes"

#: 判定来源,和返回值一起报出去 —— 出问题时要能说清楚"它为什么是这一档"。
SOURCE_DEVICE_MAP = "device_node_map"
SOURCE_SKIP = "startup_policy:skip"
SOURCE_CORE_GROUP = "group:core"
SOURCE_DEFAULT_LAZY = "default:lazy"


def _load_node_deps() -> Dict[str, dict]:
    try:
        return json.loads(_NODE_DEPS.read_text(encoding="utf-8")).get("nodes", {})
    except Exception as exc:
        logger.warning("读不到 %s(%s)——全部按默认 lazy 处理", _NODE_DEPS.name, exc)
        return {}


def _device_map_startup() -> Dict[str, str]:
    """节点名 → ``device_node_map.yaml`` 里写的 startup 档位。"""
    try:
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        resolver._ensure_loaded()
    except Exception as exc:
        logger.warning("读不到设备映射表(%s)——设备型节点将走默认判定", exc)
        return {}

    out: Dict[str, str] = {}
    for m in resolver._mappings:
        impl = m.get("implementation", {})
        node, startup = impl.get("node"), impl.get("startup")
        if not node or not startup:
            continue
        # 同一个节点可能有多条设备映射(Node_33_ADB 有三条)。它们的 startup 一致时
        # 无所谓;不一致时取**最主动**的那一档,宁可早起也不要该起时起不来。
        prev = out.get(node)
        if prev is None or _rank(startup) > _rank(prev):
            out[node] = startup
    return out


_RANK = {
    ActivationPolicy.ALWAYS_ON.value: 3,
    ActivationPolicy.SHARED.value: 2,
    ActivationPolicy.ON_DEMAND.value: 1,
    ActivationPolicy.LAZY.value: 0,
}


def _rank(startup: str) -> int:
    return _RANK.get(startup, -1)


def resolve_activation_policy(node_name: str) -> Tuple[Optional[ActivationPolicy], str]:
    """``node_name`` 该在什么时候起,以及**依据是什么**。

    Args:
        node_name: 完整节点名,如 ``"Node_33_ADB"``。

    Returns:
        ``(policy, source)``。``policy`` 为 ``None`` 表示**永不启动**
        (``startup_policy: skip``),此时 ``source`` 是 :data:`SOURCE_SKIP`。
        ``source`` 始终说得出这一档是怎么定的 —— 排障时"它为什么没起来"要有答案。
    """
    dev = _device_map_startup().get(node_name)
    if dev:
        try:
            return ActivationPolicy(dev), SOURCE_DEVICE_MAP
        except ValueError:
            logger.warning("设备映射表里 %s 的 startup=%r 不是合法档位,改按默认判定", node_name, dev)

    cfg = _load_node_deps().get(node_name, {})
    if cfg.get("startup_policy") == "skip":
        return None, SOURCE_SKIP

    if cfg.get("group") == "core" and cfg.get("startup_policy", "active") == "active":
        return ActivationPolicy.ALWAYS_ON, SOURCE_CORE_GROUP

    # 不知道什么时候需要它 ≠ 应该一直开着。
    return ActivationPolicy.LAZY, SOURCE_DEFAULT_LAZY


def activation_policy_coverage() -> Dict[str, Dict[str, Optional[str]]]:
    """磁盘上每个节点的档位与判定来源。

    存在的意义是让"一个不落"成为**可验证的事实**:调用方(以及
    ``tests/test_node_activation_policy.py``)据此断言没有节点落在判定之外。
    """
    if not _NODES_DIR.is_dir():
        return {}
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for d in sorted(_NODES_DIR.iterdir()):
        if not (d.is_dir() and (d / "main.py").exists()):
            continue
        policy, source = resolve_activation_policy(d.name)
        out[d.name] = {"policy": policy.value if policy else None, "source": source}
    return out
