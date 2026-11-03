"""core/node_actions.py —— 一个节点真有哪些动作、各要什么参数、各是哪一档(第 10 轮,模型的节点工具用)。

一个节点的动作从哪儿来,看它的入口(与统一执行器 ``core.node_invocation`` 真正怎么调它一致,不另立一套):

* **路由型**(125 个里的大多数):通用 fusion 入口在节点模块上找不到 process / execute / run / handle,
  动作接到节点自己的 FastAPI 路由(``core/node_route_bridge.py``)。动作名 = 路由最后一段;同一段对上几条路由的,
  动作名用处理函数名(桥就是这么认的)。参数照 FastAPI 对这条路由的登记(路径 / 查询 / 请求体)。
  入口函数本身就是一条路由的(Node_35 的 ``execute``、Node_55 的 ``process``)也算路由型 —— 它们收的是请求对象,
  通用入口拿 ``(command, **params)`` 去调它们必错。
* **入口型**:节点自己的入口认哪些动作,由入口模块上的 ``actions()`` 照实列出(服务对象型的模板节点从服务上列,
  见 ``nodes/common/service_entry.py``;其余各自手写在分派代码旁边)。

每个动作打一个档(``core/node_action_risk.py``)。``mcp_call`` 这类「按名字调本节点任意工具」的总入口,档 = 本节点
其余动作里最高的那一档(至少「会改东西」)。

这里的函数都是**阻塞的**(要把节点模块载进来):在工作线程里调(``asyncio.to_thread``)。
"""

from __future__ import annotations

import inspect
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.node_action_risk import MODERATE, Grade, grade, higher

logger = logging.getLogger("Galaxy.NodeActions")

#: 通用 fusion 入口在节点模块上按这个顺序找可执行方法(nodes/*/fusion_entry.py 的 FusionNode)
_ENTRY_NAMES = ("process", "execute", "run", "handle")
#: 「按名字调本节点任意一个工具」的总入口
_DISPATCH_ALL = frozenset({"mcp_call"})
#: 节点自己报状态 / 说明的动作,不列给模型
_META = frozenset({"status", "help", "health"})


@dataclass
class NodeAction:
    name: str
    via: str  # "route" | "entry"
    summary: str = ""
    method: str = ""
    path: str = ""
    handler: str = ""
    params: List[Dict[str, Any]] = field(default_factory=list)
    grade: Grade = field(default_factory=lambda: Grade(MODERATE, "会改东西"))

    def required(self) -> List[str]:
        return [str(p.get("name")) for p in self.params if p.get("required")]

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"action": self.name, "summary": self.summary, **self.grade.to_dict()}
        if self.method:
            out["http"] = f"{self.method} {self.path}"
        if self.handler and self.handler != self.name:
            out["handler"] = self.handler
        out["params"] = self.params
        return out


# ── 找节点 ────────────────────────────────────────────────────────────────────


def node_dir(node: str) -> Optional[str]:
    """``Node_23`` / ``23`` / ``Node_23_Time`` / ``Time`` → 目录名 ``Node_23_Time``;认不出(或编号与名字对不上)就是 ``None``。"""
    from core.node_action_risk import node_number
    from core.node_catalog import _num_to_dir

    text = str(node or "").strip()
    table = _num_to_dir()
    if text in table.values():
        return text
    num = node_number(text)
    if num is None:
        hits = [d for d in table.values() if d.split("_", 2)[-1].lower() == text.lower()]
        return hits[0] if len(hits) == 1 else None
    found = table.get(num)
    if found is None or (text.count("_") >= 2 and text != found):  # 编号对、名字不对:不替调用方猜是哪个
        return None
    return found


def _load(dir_name: str) -> Dict[str, Any]:
    from core.routes._helpers import _load_node, nodes_root

    path = os.path.join(nodes_root, dir_name)
    info = _load_node(dir_name, path, os.path.join(path, "fusion_entry.py"))
    if not info:
        raise LookupError(f"节点 {dir_name} 载不进来(fusion_entry 没有可调用的入口)")
    return info


def _entry_target(info: Dict[str, Any]) -> Tuple[Any, Any]:
    """(入口方法, 它所在的对象);通用 fusion 入口找不到方法(或没把 main.py 载成)时方法是 ``None``。"""
    from core.node_route_bridge import main_namespace

    if info.get("type") == "function":
        return info.get("execute"), info.get("module")
    holder = info.get("instance")
    if not hasattr(holder, "instance"):  # 自定义的类实例(Node_15 这种),入口就是它自己的 execute
        return getattr(holder, "execute", None), holder
    target = holder.instance
    if target is None:  # 通用入口没把 main.py 载成:没有入口,只能按路由
        return None, main_namespace(info)
    for name in _ENTRY_NAMES:
        method = getattr(target, name, None)
        if method is not None:
            return method, target
    return None, target


def use_routes_directly(info: Dict[str, Any]) -> bool:
    """通用入口调不了这个节点、该直接按路由调:

    * 通用入口没把 main.py 载成(Node_118:它把路由 ``get_instance(instance_id)`` 当成了工厂);
    * 它找到的「入口」其实是一条路由(Node_35 的 ``execute``、Node_55 的 ``process`` 收的是请求对象,拿
      ``(command, **params)`` 去调必错)。
    """
    from core.node_route_bridge import node_app

    holder = info.get("instance")
    if info.get("type") != "function" and hasattr(holder, "instance") and holder.instance is None:
        return True
    method, _target = _entry_target(info)
    app = node_app(info)
    if method is None or app is None:
        return False
    func = getattr(method, "__func__", method)
    return any(getattr(r, "endpoint", None) is func for r in getattr(app, "routes", []) or [])


def kind(info: Dict[str, Any]) -> str:
    """``"route"``(动作接到节点自己的路由)或 ``"entry"``(节点自己的入口分派)。"""
    if info.get("type") == "function":
        return "entry"
    method, _ = _entry_target(info)
    if method is None or use_routes_directly(info):
        return "route"
    return "entry"


# ── 列动作 ────────────────────────────────────────────────────────────────────


def _field_params(fields: Any, where: str) -> List[Dict[str, Any]]:
    from nodes.common.service_entry import type_text

    out = []
    for f in fields or []:
        info = getattr(f, "field_info", None)
        tp = getattr(info, "annotation", None) or getattr(f, "type_", None)
        out.append(
            {
                "name": str(getattr(f, "alias", None) or getattr(f, "name", "")),
                "in": where,
                "type": type_text(tp),
                "required": bool(getattr(f, "required", False)),
            }
        )
    return out


def _route_params(route: Any) -> List[Dict[str, Any]]:
    from nodes.common.service_entry import model_params

    dep = route.dependant
    params = _field_params(dep.path_params, "path") + _field_params(dep.query_params, "query")
    body = list(dep.body_params or [])
    if len(body) == 1 and not getattr(getattr(body[0], "field_info", None), "embed", False):
        info = getattr(body[0], "field_info", None)
        model = getattr(info, "annotation", None) or getattr(body[0], "type_", None)
        if inspect.isclass(model) and hasattr(model, "model_fields"):
            params += [{**p, "in": "body"} for p in model_params(model)]
        else:
            params += _field_params(body, "body")
    else:
        params += _field_params(body, "body")
    return params


def _summary(endpoint: Any, route: Any = None) -> str:
    text = (getattr(route, "summary", None) or inspect.getdoc(endpoint) or "").strip()
    return text.splitlines()[0][:160] if text else ""


def _route_actions(dir_name: str, app: Any) -> List[NodeAction]:
    from core.node_route_bridge import _METHOD_ORDER, action_routes

    out: List[NodeAction] = []
    for segment, routes in sorted(action_routes(app).items()):
        for route in routes:
            method = next((m for m in _METHOD_ORDER if m in route.methods), "")
            if not method:
                continue
            handler = getattr(route.endpoint, "__name__", "")
            name = segment if len(routes) == 1 else handler
            out.append(
                NodeAction(
                    name=name,
                    via="route",
                    summary=_summary(route.endpoint, route),
                    method=method,
                    path=str(route.path),
                    handler=handler,
                    params=_route_params(route),
                    grade=grade(dir_name, name, method=method, handler=handler),
                )
            )
    return out


def _declared(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """入口模块(或入口对象)上的 ``actions()`` 列出的动作表;没有声明就是 ``None``。"""
    _method, target = _entry_target(info)
    for holder in (target, info.get("module")):
        declare = getattr(holder, "actions", None)
        if callable(declare):
            table = declare()
            if isinstance(table, dict):
                return table
    return None


def _entry_actions(dir_name: str, info: Dict[str, Any]) -> List[NodeAction]:
    table = _declared(info)
    if table is None:
        return []
    out = []
    for name, spec in sorted(table.items()):
        if name in _META:
            continue
        spec = spec if isinstance(spec, dict) else {"summary": str(spec or "")}
        out.append(
            NodeAction(
                name=name,
                via="entry",
                summary=str(spec.get("summary") or "")[:160],
                params=list(spec.get("params") or []),
                grade=grade(dir_name, name),
            )
        )
    return out


def _settle_dispatch_all(actions: List[NodeAction]) -> None:
    """``mcp_call`` 能按名字调本节点任意一个工具:它的档 = 其余动作里最高的(至少「会改东西」)。"""
    top = MODERATE
    for a in actions:
        if a.handler not in _DISPATCH_ALL and a.name not in _DISPATCH_ALL:
            top = higher(top, a.grade.level)
    for a in actions:
        if a.handler in _DISPATCH_ALL or a.name in _DISPATCH_ALL:
            if higher(top, a.grade.level) != a.grade.level:
                a.grade = Grade(top, "按名字调本节点任意一个动作,档随本节点最危险的那个")


_CACHE: Dict[str, Tuple[List[NodeAction], str]] = {}
_CACHE_LOCK = threading.Lock()


def list_actions(dir_name: str) -> Tuple[List[NodeAction], str]:
    """(这个节点的动作, 它们从哪儿来的一句说明)。阻塞:在工作线程里调。载不进来的照实抛 ``LookupError``。"""
    with _CACHE_LOCK:
        hit = _CACHE.get(dir_name)
    if hit is not None:
        return hit
    from core.node_route_bridge import node_app

    info = _load(dir_name)
    if kind(info) == "route":
        from core.node_route_bridge import main_error

        app = node_app(info)
        actions = _route_actions(dir_name, app) if app is not None else []
        why = main_error(info)
        source = (
            "节点自己的 HTTP 路由"
            if actions
            else (f"节点的 main.py 载不进来:{why}" if why else "这个节点既没有入口也没有路由可接")
        )
    else:
        actions = _entry_actions(dir_name, info)
        source = "节点入口声明的动作" if actions else "这个节点的入口没有声明它认哪些动作"
    _settle_dispatch_all(actions)
    with _CACHE_LOCK:
        _CACHE[dir_name] = (actions, source)
    return actions, source


def _last_literal(path: str) -> str:
    from core.node_route_bridge import _norm

    literal = [seg for seg in str(path or "").strip("/").split("/") if seg and not seg.startswith("{")]
    return _norm(literal[-1]) if literal else ""


def _unknown_route_action(action: str, actions: List[NodeAction]) -> str:
    """目录里没有这个名字:是几条路由共用的那一段,就列出那几条与各自的名字;否则列出节点有哪些。"""
    from core.node_route_bridge import _norm

    shared = [a for a in actions if _last_literal(a.path) == _norm(action)]
    if shared:
        choices = "; ".join(f"{a.method} {a.path} → {a.name}" for a in shared)
        return f"动作 {action} 对上了几条路由({choices}),请用后面的名字指定"
    return f"节点没有 {action} 这个动作(它有:{', '.join(a.name for a in actions) or '(没有)'})"


def resolve(dir_name: str, action: str, params: Dict[str, Any]) -> Tuple[Optional[NodeAction], str]:
    """这一次调用落到哪个动作上、是哪一档。与执行器用同一个认法:路由型照 ``pick_route``(按参数),入口型按名字。

    认不出 / 有歧义就是 ``(None, 原因)`` —— 不替调用方猜(调用方据此不执行)。
    """
    from core.node_route_bridge import node_app, pick_route

    actions, _source = list_actions(dir_name)
    info = _load(dir_name)
    if kind(info) == "route":
        app = node_app(info)
        if app is None:
            return None, f"节点 {dir_name} 既没有入口也没有路由可接"
        listed = next((a for a in actions if a.name == action), None) or next(
            (a for a in actions if a.handler == action), None
        )  # 目录里列的名字,或那一行写着的处理函数名(桥也认)
        if listed is None:
            return None, _unknown_route_action(action, actions)
        route, method, why = pick_route(app, action, params)
        if route is None:
            return None, why
        known = next((a for a in actions if a.path == str(route.path) and a.method == method), None)
        if known is not listed:  # 按名字认到的不是目录里列的那一条(不该发生):不执行
            return None, f"动作 {action} 这次落到了 {method} {route.path},与目录里的不是同一条,没有执行"
        handler = getattr(route.endpoint, "__name__", "")
        found = NodeAction(
            name=action,
            via="route",
            summary=known.summary if known else "",
            method=method,
            path=str(route.path),
            handler=handler,
            params=known.params if known else _route_params(route),
            grade=known.grade if known else grade(dir_name, action, method=method, handler=handler),
        )
    else:
        known = next((a for a in actions if a.name == action), None)
        if known is None:
            names = ", ".join(a.name for a in actions) or "(没有声明)"
            return None, f"节点没有声明 {action} 这个动作(它有:{names})"
        found = NodeAction(**{**known.__dict__})
    found.grade = found.grade.at_least(
        grade(dir_name, action, method=found.method, handler=found.handler, params=params)
    )
    return found, ""


def missing_params(found: NodeAction, params: Dict[str, Any]) -> List[str]:
    return [name for name in found.required() if name not in (params or {})]


def reset_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "NodeAction",
    "kind",
    "list_actions",
    "missing_params",
    "node_dir",
    "reset_cache",
    "resolve",
    "use_routes_directly",
]
