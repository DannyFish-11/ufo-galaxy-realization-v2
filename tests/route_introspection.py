"""tests/route_introspection.py — FastAPI 路由结构内省的统一助手
================================================================

FastAPI 0.137+ 把 ``include_router`` 改成了懒挂载:``app.routes`` 里不再是
摊平的 ``APIRoute``,而是 ``_IncludedRouter``(path=None),真实路由藏在
``effective_route_contexts()`` 里(``_EffectiveRouteContext``,带完整
path / methods / dependant / dependencies)。

请求匹配(TestClient 发请求)不受影响;受影响的是所有做【结构内省】的
测试——扁平遍历 ``app.routes`` 找路径/方法/依赖会一无所获。此类测试统一
从这里拿摊平视图,不再各写各的遍历。旧版 FastAPI(无懒挂载)下本助手
退化为原样遍历,双版本兼容。
"""
from __future__ import annotations

from typing import Any, Iterator


def iter_flat_routes(app_or_router: Any) -> Iterator[Any]:
    """摊平产出 app/router 的全部路由。

    - 普通 ``APIRoute`` / ``WebSocketRoute`` 原样产出;
    - ``_IncludedRouter``(FastAPI 0.137+ 懒挂载)递归展开为
      ``_EffectiveRouteContext``——鸭子类型上等价于 APIRoute
      (有 path / methods / dependant / endpoint / dependencies)。
    """
    for route in getattr(app_or_router, "routes", []) or []:
        if hasattr(route, "effective_route_contexts"):
            yield from route.effective_route_contexts()
        else:
            yield route


def find_route(app_or_router: Any, path: str, method: str | None = None) -> Any:
    """按路径(可选按方法)找路由;找不到返回 None。"""
    for route in iter_flat_routes(app_or_router):
        if getattr(route, "path", None) != path:
            continue
        if method is None:
            return route
        if method.upper() in (getattr(route, "methods", None) or set()):
            return route
    return None


def route_paths(app_or_router: Any) -> set:
    """全部路由路径集合(WebSocket 路由也计入)。"""
    return {
        p for p in (getattr(r, "path", None) for r in iter_flat_routes(app_or_router))
        if p
    }
