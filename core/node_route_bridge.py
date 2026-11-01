"""core/node_route_bridge.py —— 节点的进程内入口接不上时，按节点自己的 HTTP 路由走一遍（第 9 轮）。

通用 fusion 入口（``nodes/*/fusion_entry.py`` 的 ``FusionNode``）在节点模块上找 process / execute / run / handle，
第 8 轮清点：用它的 117 个节点里 112 个一个都没有 —— 进程内调它们一律回「No executable method found」。
它们真正的实现都在自己的 FastAPI 路由里（``@app.post("/click")``、``@app.get("/screen_size")``）。
这里把「动作名」接到「同名的那条路由」：

1. **节点进程在跑**（launcher 拉起的那份，端口在 ``config/unified_ports.yaml``）：HTTP 打它 —— 那是节点真正的
   实例（它的 startup 跑过、状态在它那儿），带内部身份（节点 HTTP 面默认有鉴权）；
2. **没在跑**：节点在本进程里起一个实例 —— 自己的线程、自己的事件循环，startup（lifespan）跑一次，
   之后把节点模块上的 ``app`` 当 ASGI 应用调（:class:`_NodeHost`）。不占后端的事件循环（不少节点的 async 路由里
   调的是同步的 requests）；
3. **认不出那条路由**：照实说「节点 X 没有 Y 这个动作」，列出它有哪些。

**只认确定的，不猜：** 路由最后一段（不含占位符）与动作名相同（下划线与连字符等价），认不出再看处理函数名
（声明了动作白名单的节点按函数名记动作）；占位符都能从参数里取到的才算；同一个名字对上几条
路由时不替调用方选（选错了「列一下」就成了「建一个」），照实列出、请用处理函数名指定。参数放哪儿照 FastAPI 自己对这条路由的登记（``route.dependant``：
路径 / 查询 / 请求体），不按方法猜 —— POST 路由上的普通标量参数在 FastAPI 里是查询参数。

模块级只依赖标准库；httpx / FastAPI 用到时再导入。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.NodeRouteBridge")

#: 通用 fusion 入口找不到可执行方法时回的那句话（nodes/*/fusion_entry.py）
NO_ENTRY = "No executable method found"
#: 只报状态、不动手的路由，不当动作
_NOT_ACTIONS = frozenset({"health", "status", "metrics", "openapi.json", "docs", "redoc"})
_METHOD_ORDER = ("POST", "PUT", "PATCH", "GET", "DELETE")  # 一条路由登记了几个方法时用哪一个
#: 探节点进程在不在跑的连接期限（本机端口，连不上就是没在跑）
CONNECT_TIMEOUT_S = 0.5


def no_entry(result: Any) -> bool:
    """这个结果是不是「通用入口在节点模块上找不到可执行方法」。"""
    return isinstance(result, dict) and result.get("success") is False and result.get("error") == NO_ENTRY


def _norm(name: str) -> str:
    return str(name or "").strip().strip("/").lower().replace("-", "_")


def node_app(node_info: Dict[str, Any]) -> Any:
    """节点模块上的 FastAPI 应用（fusion 入口已经把模块载进来了）；没有就是 ``None``。"""
    holder = node_info.get("instance")
    module = getattr(holder, "instance", None) if holder is not None else node_info.get("module")
    app = getattr(module, "app", None)
    return app if hasattr(app, "routes") else None


def _fields(fields: Any) -> List[str]:
    return [str(getattr(f, "alias", None) or getattr(f, "name", "")) for f in (fields or [])]


def action_routes(app: Any) -> Dict[str, List[Any]]:
    """动作名 → 对得上的路由（只认最后一段不是占位符、也不是只报状态的那些）。"""
    out: Dict[str, List[Any]] = {}
    for route in getattr(app, "routes", []) or []:
        path = str(getattr(route, "path", "") or "")
        methods = getattr(route, "methods", None)
        if not path or not methods or not hasattr(route, "dependant"):
            continue
        literal = [seg for seg in path.strip("/").split("/") if seg and not seg.startswith("{")]
        if not literal or _norm(literal[-1]) in _NOT_ACTIONS:
            continue
        out.setdefault(_norm(literal[-1]), []).append(route)
    return out


def endpoint_routes(app: Any) -> Dict[str, List[Any]]:
    """处理函数名 → 路由。声明了动作白名单的节点按函数名记动作(Node_74 的 ``get_twin`` 是 ``GET /twin``)。"""
    out: Dict[str, List[Any]] = {}
    for route in getattr(app, "routes", []) or []:
        name = getattr(getattr(route, "endpoint", None), "__name__", "")
        if name and getattr(route, "methods", None) and hasattr(route, "dependant") and _norm(name) not in _NOT_ACTIONS:
            out.setdefault(_norm(name), []).append(route)
    return out


def pick_route(app: Any, action: str, params: Dict[str, Any]) -> Tuple[Optional[Any], str, str]:
    """(路由, 方法, 认不出时的原因)。先按路由最后一段认,认不出再按处理函数名认(函数名在一个应用里唯一)。

    同一个名字对上几条路由(``POST /tasks`` 建、``GET /tasks`` 列;``GET`` / ``DELETE /timers/{name}``)时**不替调用方选**:
    选错了,「列一下」就成了「建一个」、「看一眼」就成了「删掉」—— 照实说有哪几条,请用处理函数名指定。
    """
    table = action_routes(app)
    routes = table.get(_norm(action), []) or endpoint_routes(app).get(_norm(action), [])
    usable = [
        (route, next(m for m in _METHOD_ORDER if m in route.methods))
        for route in routes
        if any(m in route.methods for m in _METHOD_ORDER)
        and all(name in params for name in _fields(route.dependant.path_params))
    ]
    if len(usable) == 1:
        return usable[0][0], usable[0][1], ""
    if usable:
        choices = "; ".join(f"{m} {r.path} → {getattr(r.endpoint, '__name__', '?')}" for r, m in usable)
        return None, "", f"动作 {action} 对上了几条路由({choices}),请用后面的处理函数名指定"
    if routes:
        need = sorted({n for r in routes for n in _fields(r.dependant.path_params)})
        return None, "", f"动作 {action} 要的参数没给全(要 {', '.join(need)})"
    known = ", ".join(sorted(table)) or "(没有)"
    return None, "", f"节点没有 {action} 这个动作(它有:{known})"


def build_request(route: Any, params: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[Any]]:
    """(路径, 查询参数, 请求体) —— 照 FastAPI 对这条路由的登记把参数放到该放的地方。"""
    from urllib.parse import quote

    dep = route.dependant
    path = str(route.path)
    taken = set()
    for name in _fields(dep.path_params):
        path = path.replace("{" + name + "}", quote(str(params[name]), safe="")).replace(
            "{" + name + ":path}", quote(str(params[name]), safe="/")
        )
        taken.add(name)
    query = {}
    for name in _fields(dep.query_params):
        if name in params:
            value = params[name]
            query[name] = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
            taken.add(name)
    body_fields = list(dep.body_params or [])
    body: Optional[Any] = None
    if len(body_fields) == 1 and not getattr(getattr(body_fields[0], "field_info", None), "embed", False):
        body = {k: v for k, v in params.items() if k not in taken}  # 单个请求模型:参数就是模型的字段
    elif body_fields:
        body = {n: params[n] for n in _fields(body_fields) if n in params}
    return path, query, body


def _outcome(status: int, text: str) -> Dict[str, Any]:
    try:
        data: Any = json.loads(text) if text else None
    except ValueError:
        data = text
    if 200 <= status < 300:
        if isinstance(data, dict) and data.get("success") is False:
            return {"success": False, "error": str(data.get("error") or data.get("message") or "节点执行失败")}
        return {"success": True, "result": data}
    detail = data.get("detail") if isinstance(data, dict) else data
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)[:300] if detail is not None else ""
    return {"success": False, "error": f"HTTP {status}: {str(detail)[:300] or '节点执行失败'}"}


async def _over_http(url: str, method: str, path: str, query: Dict, body: Any, timeout_s: float) -> Dict[str, Any]:
    import httpx

    from core.internal_auth import internal_headers_for

    timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
    async with httpx.AsyncClient(base_url=url, timeout=timeout, headers=internal_headers_for(url)) as client:
        resp = await client.request(method, path, params=query or None, json=body)
    if resp.status_code == 404 and resp.text.strip() in ('{"detail":"Not Found"}', "Not Found"):
        # 节点模块里明明有这条路由,那个端口上答话的却没有:答话的不是这个节点(端口被别的服务占着)。不信它
        raise LookupError(f"{url} 上答话的不是这个节点")
    return {**_outcome(resp.status_code, resp.text), "via": "http"}


#: 节点 startup(lifespan)最多等多久
STARTUP_TIMEOUT_S = 30.0


def _headers() -> Dict[str, str]:
    from core.auth import ensure_local_token
    from core.internal_auth import internal_auth_headers

    headers = internal_auth_headers()
    if not headers:
        # 节点 HTTP 面一律要令牌;后端启动时会自签一个,但进程内的调用方不该依赖启动顺序 —— 同一套 core.auth,不另造
        ensure_local_token()
        headers = internal_auth_headers()
    return headers


class _NodeHost:
    """一个节点的进程内实例:自己的线程、自己的事件循环,startup(lifespan)跑一次 —— 和节点自己的进程一样。

    40 个节点在 startup 里建它的服务对象(Node_52 的 ``simulator`` 就是);不跑 startup,它们的路由一调就是
    ``'NoneType' object has no attribute ...``。startup 本身失败照实记下,之后的调用照样转过去、让路由自己说。
    后端的事件循环只等一个 future,不陪节点的同步代码一起卡。
    """

    def __init__(self, node_id: str, app: Any) -> None:
        self.node_id = node_id
        self.app = app
        self.startup_error = ""
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, name=f"node-host-{node_id}", daemon=True)
        self._thread.start()
        try:
            asyncio.run_coroutine_threadsafe(self._startup(), self.loop).result(timeout=STARTUP_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — startup 失败:记下,路由照样能调(没起来的那部分照实报错)
            self.startup_error = f"{type(exc).__name__}: {exc}"
            logger.warning("节点 %s 的 startup 没跑成(进程内): %s", node_id, self.startup_error)

    async def _startup(self) -> None:
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()

    async def _request(self, method: str, path: str, query: Dict, body: Any, timeout_s: float) -> Tuple[int, str]:
        import httpx

        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://node.local", timeout=timeout_s, headers=_headers()
        ) as client:
            resp = await client.request(method, path, params=query or None, json=body)
            return resp.status_code, resp.text

    async def call(self, method: str, path: str, query: Dict, body: Any, timeout_s: float) -> Dict[str, Any]:
        fut = asyncio.run_coroutine_threadsafe(self._request(method, path, query, body, timeout_s), self.loop)
        status, text = await asyncio.wait_for(asyncio.wrap_future(fut), timeout_s)
        out = {**_outcome(status, text), "via": "in_process"}
        if not out["success"] and self.startup_error:
            out["error"] = f"{out['error']}(节点 startup 没跑成:{self.startup_error})"
        return out


_HOSTS: Dict[str, _NodeHost] = {}
_HOSTS_LOCK = threading.Lock()


def _host(node_id: str, app: Any) -> _NodeHost:
    """同一个节点只起一个进程内实例(在工作线程里调:第一次要等它的 startup)。"""
    with _HOSTS_LOCK:
        host = _HOSTS.get(node_id)
        if host is None or host.app is not app:
            host = _HOSTS[node_id] = _NodeHost(node_id, app)
        return host


def _node_url(node_id: str) -> str:
    try:
        from core.port_config import get_node_url

        return get_node_url(node_id, host="127.0.0.1")
    except Exception:  # noqa: BLE001 — 端口表里没有:只能进程内
        return ""


async def call_route(
    node_id: str, node_info: Dict[str, Any], action: str, params: Dict[str, Any], *, timeout_s: float = 30.0
) -> Dict[str, Any]:
    """把一次节点调用接到节点自己的路由上。永不抛出;做不成就回 ``{"success": False, "error": 原因}``。"""
    app = node_app(node_info)
    if app is None:
        return {"success": False, "error": f"节点 {node_id} 既没有进程内入口,也没有 HTTP 路由可接"}
    route, method, why = pick_route(app, action, params or {})
    if route is None:
        return {"success": False, "error": f"节点 {node_id}:{why}"}
    path, query, body = build_request(route, params or {})
    url = _node_url(node_id)
    if url:
        try:
            return await _over_http(url, method, path, query, body, timeout_s)
        except Exception as exc:  # noqa: BLE001 — 连不上 = 进程没在跑:进程内调
            import httpx

            if not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, LookupError)):
                return {
                    "success": False,
                    "error": f"节点 {node_id} 的 {method} {path} 没成:{type(exc).__name__}: {exc}",
                }
    try:
        host = await asyncio.to_thread(_host, node_id, app)
        return await host.call(method, path, query, body, timeout_s)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"节点 {node_id} 的 {method} {path} 没成:{type(exc).__name__}: {exc}"}


__all__ = [
    "NO_ENTRY",
    "action_routes",
    "build_request",
    "call_route",
    "endpoint_routes",
    "no_entry",
    "node_app",
    "pick_route",
]
