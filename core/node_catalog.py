"""
core/node_catalog.py — 节点目录 + roster(分类静态目录 ⊕ 端口 ⊕ 实时状态)
=================================================================================

面板「端口与节点」页与 /api/v1/nodes/roster 都用它,把三处信息合并成一份可展示、
可排序、可分组的节点名单:

  1. 静态分类   —— config/node_catalog.json(由 scripts/gen_node_catalog.py 从全量
                   审计生成):num / name / type / type_label / runnable / purpose /
                   connector(oauth|key + service)。
  2. 端口       —— core.port_config(读 config/unified_ports.yaml)。
  3. 实时状态   —— core.nodes.node_fabric_registry.NodeFabricRegistry(运行/停止/失败);
                   拿不到时状态为 "unknown",不报错。

全部容错:任一来源缺失都降级,不影响面板加载。
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeCatalog")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CATALOG_PATH = os.path.join(_ROOT, "config", "node_catalog.json")
_NODES_DIR = os.path.join(_ROOT, "nodes")


@lru_cache(maxsize=1)
def _load_catalog() -> Dict[str, Any]:
    try:
        with open(_CATALOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("节点目录加载失败(%s): %s", _CATALOG_PATH, exc)
        return {"type_labels": {}, "count": 0, "nodes": []}


@lru_cache(maxsize=1)
def _num_to_dir() -> Dict[int, str]:
    """扫 nodes/ 目录,建 节点编号 → 实际目录名(如 71 → 'Node_71_MultiDeviceCoordination')。"""
    out: Dict[int, str] = {}
    try:
        for d in os.listdir(_NODES_DIR):
            if not d.startswith("Node_"):
                continue
            parts = d.split("_", 2)  # ['Node', '71', 'Multi...']
            if len(parts) >= 2 and parts[1].isdigit():
                out[int(parts[1])] = d
    except Exception as exc:  # noqa: BLE001
        logger.debug("扫描 nodes/ 目录失败: %s", exc)
    return out


def _port_for(dir_name: str) -> Optional[int]:
    try:
        from core.port_config import get_node_port

        p = get_node_port(dir_name)
        return int(p) if p else None
    except Exception:  # noqa: BLE001
        return None


def _live_status_map() -> Dict[str, str]:
    """节点名(或目录名归一) → 状态字符串。拿不到返回空表(全部 unknown)。"""
    out: Dict[str, str] = {}
    try:
        from core.nodes.node_fabric_registry import get_node_fabric_registry

        reg = get_node_fabric_registry()
        for n in reg.list_nodes():
            info = n.to_dict() if hasattr(n, "to_dict") else (n if isinstance(n, dict) else {})
            nid = str(info.get("node_id") or info.get("name") or "").strip()
            st = info.get("status")
            if nid and st:
                out[nid.lower()] = str(st)
    except Exception as exc:  # noqa: BLE001
        logger.debug("节点实时状态不可用(降级为 unknown): %s", exc)
    return out


def _match_status(dir_name: str, name: str, num: int, live: Dict[str, str]) -> str:
    """在实时状态表里宽松匹配一个节点(按目录名 / 名字 / Node_编号 多种键尝试)。"""
    for key in (dir_name.lower(), name.lower(), f"node_{num}", f"node_{num:02d}"):
        if key in live:
            return live[key]
    # 也匹配"以 Node_编号_ 开头"的注册键
    prefix = f"node_{num}_"
    for k, v in live.items():
        if k.startswith(prefix):
            return v
    return "unknown"


def get_node_roster() -> Dict[str, Any]:
    """合并目录 + 端口 + 实时状态,返回可直接给面板/接口用的 roster。"""
    cat = _load_catalog()
    dirs = _num_to_dir()
    live = _live_status_map()

    nodes: List[Dict[str, Any]] = []
    for entry in cat.get("nodes", []):
        num = entry.get("num")
        name = entry.get("name", "")
        dir_name = dirs.get(num, f"Node_{num}_{name}")
        nodes.append(
            {
                **entry,
                "dir": dir_name,
                "port": _port_for(dir_name),
                "status": _match_status(dir_name, name, num, live),
                "has_dockerfile": os.path.isfile(os.path.join(_NODES_DIR, dir_name, "Dockerfile")),
            }
        )
    nodes.sort(key=lambda n: n.get("num", 0))

    # 按类型分组的计数,供面板分组标题用。
    from collections import Counter

    by_type = Counter(n["type"] for n in nodes)

    return {
        "count": len(nodes),
        "type_labels": cat.get("type_labels", {}),
        "type_counts": dict(by_type),
        "connectors": {
            "oauth": [n for n in nodes if (n.get("connector") or {}).get("kind") == "oauth"],
            "key": [n for n in nodes if (n.get("connector") or {}).get("kind") == "key"],
        },
        "nodes": nodes,
    }
