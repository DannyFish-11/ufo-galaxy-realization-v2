"""**每一个对外开 HTTP 面的 app,要么装了认证,要么在这里写明为什么没装。**

## 这条为什么必须按"有没有 app",而不是按"在不在 nodes/ 下"

上一轮把 125 个节点全接上了认证,守卫也是按 ``nodes/Node_*/main.py`` 扫的。
于是 ``core/device_status_api.py`` 整个被漏掉 —— 而它由
``launcher/core_services.py`` 用 ``uvicorn ... --host 0.0.0.0`` 真起着,开的还是
``POST /devices/register``、``DELETE /devices/{device_id}``、
``PUT /devices/{device_id}/status`` 这些**写**接口。

按目录圈范围就会这样一直漏下去(这个坑在 ``tests/conftest.py`` 的
``_no_desktop_surface_in_tests`` 里已经踩过一次,那次的结论也是"判据是套件级的")。
所以这条的判据是:**代码里有没有 ``FastAPI(...)``**。

## 豁免必须带理由

下面那张表是**允许没有认证的清单**,每一条都要写清为什么。加一个新的 app 而不装认证,
只有两个去处:装上,或者在这张表里说出理由。**不允许**第三种"什么都不做还能绿"。
"""

import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 认得出来的"装上了认证"的调用名。
_AUTH_CALLS = {"install_node_auth", "install_service_auth"}
#: 认得出来的"装上了认证"的中间件类名(``add_middleware(X)`` 的 X)。
_AUTH_MIDDLEWARE = {"BearerAuthMiddleware"}

#: 允许没有认证的文件 → 理由。
EXEMPT = {
    # 这个 app 只是为了把 OpenAPI schema dump 出来,构造完就 .openapi(),从不 serve。
    "scripts/gen_ts_types.py": "只用来导出 OpenAPI schema,不 serve",
    # 它把一段"测试用服务器"的源码**写成字符串**交给子进程,自己不起服务。
    "scripts/behavior_smoke.py": "写出一段临时 smoke server 的源码,自身不 serve",
    # 本文件验的东西自己就要起 app。
    "scripts/live_node_security_check.py": "安全检查脚本自己起的探针 app",
    # 只读监控面 + Prometheus 抓取端点(/metrics)。要求令牌会打断抓取,
    # 而这是个纯只读面;它也没有出现在任何部署编排里。要接的话得连抓取侧一起改。
    "health_monitor.py": "只读监控面 + /metrics 抓取端点;改它要连抓取侧一起改,单独接会打断抓取",
    # 节点模板:它自己不是一个跑着的服务,而是新节点的起点 —— 它**装了**认证,
    # 这里列出来只是因为下面的扫描会把它当成一个 app。
}


#: 这些文件必须装上认证(扫描到 FastAPI 就要求),列出来是为了让"扫到了几个"可被看见。
def _iter_app_files():
    for path in sorted(glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(path, ROOT)
        if rel.startswith(("tests/", "external/", ".git/", "nodes/")):
            continue  # nodes/ 由 tests/test_all_node_http_surfaces_require_auth.py 专管
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        if "FastAPI(" not in src:
            continue
        yield rel, src


def _creates_app(tree) -> bool:
    return any(
        isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == "FastAPI"
        for n in ast.walk(tree)
    )


#: 逐条 ``Depends`` 时可以不带鉴权的路径 —— 和节点侧的豁免表同一个道理。
_ROUTE_EXEMPT = {"/favicon.ico", "/health", "/healthz", "/readyz", "/health/live", "/health/ready"}

_ROUTE_DECORATORS = {"get", "post", "put", "delete", "patch", "websocket"}


def _routes(tree):
    """产出 ``(方法, 路径, 这条有没有 Depends(require_auth))``。"""
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            f = d.func if isinstance(d, ast.Call) else d
            attr = getattr(f, "attr", None)
            if attr not in _ROUTE_DECORATORS:
                continue
            path = "?"
            if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant):
                path = str(d.args[0].value)
            yield attr.upper(), path, "require_auth" in ast.unparse(n.args)


def _installs_auth(tree) -> bool:
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = getattr(n.func, "id", getattr(n.func, "attr", None))
        if name in _AUTH_CALLS:
            return True
        if name == "add_middleware" and n.args:
            first = n.args[0]
            if getattr(first, "id", getattr(first, "attr", None)) in _AUTH_MIDDLEWARE:
                return True

    # 逐条 ``Depends(require_auth)`` 也算 —— 但**必须每条都有**。
    #
    # 只要"文件里出现过一次 Depends(require_auth)"就放行是不行的:
    # ``launcher/services.py`` 正是那个样子 —— ``/api/status`` 挂了,
    # 紧挨着的 ``/api/services`` 没挂,而两条返回的是同一份
    # ``service_manager.get_status()``。受保护的内容从没设防的那扇门原样出去。
    routes = [r for r in _routes(tree) if r[1] not in _ROUTE_EXEMPT]
    return bool(routes) and all(has for _, _, has in routes)


class TestEveryAppIsAccountedFor:
    def test_no_unauthenticated_http_surface_appears_silently(self):
        offenders = []
        for rel, src in _iter_app_files():
            if rel in EXEMPT:
                continue
            tree = ast.parse(src)
            if not _creates_app(tree):
                continue
            if not _installs_auth(tree):
                offenders.append(rel)
        assert offenders == [], (
            "这些文件建了 FastAPI app 却没装认证。装上(install_node_auth / "
            f"BearerAuthMiddleware),或者在 EXEMPT 里写明理由: {offenders}"
        )

    def test_the_scan_is_not_vacuous(self):
        """扫到的 app 文件得有一定数量 —— 否则上一条会因为"一个都没扫到"而空转。"""
        found = [rel for rel, _ in _iter_app_files()]
        assert len(found) >= 10, f"只扫到 {len(found)} 个 app 文件,扫描大概坏了: {found}"

    def test_every_exemption_still_points_at_a_real_file(self):
        """豁免表不该留着已经不存在的路径 —— 那种条目会静静地失效。"""
        missing = [rel for rel in EXEMPT if not os.path.exists(os.path.join(ROOT, rel))]
        assert missing == [], f"豁免表里这些文件已经不在了: {missing}"

    def test_every_exemption_has_a_reason(self):
        blank = [rel for rel, why in EXEMPT.items() if not (why or "").strip()]
        assert blank == [], f"这些豁免没写理由: {blank}"


class TestTheKnownLiveServicesAreCovered:
    """点名钉住几个:它们是真的被 launcher / uvicorn 起着的。"""

    def test_device_status_api_is_authenticated(self):
        src = open(os.path.join(ROOT, "core/device_status_api.py"), encoding="utf-8").read()
        assert _installs_auth(ast.parse(src)), (
            "core/device_status_api.py 由 launcher/core_services.py 用 "
            "uvicorn --host 0.0.0.0 起着,并开着 /devices/register 等写接口"
        )

    def test_the_node_template_is_authenticated(self):
        src = open(os.path.join(ROOT, "templates/node_template/main.py"), encoding="utf-8").read()
        assert _installs_auth(ast.parse(src)), "模板少一行,等于每个新节点默认裸奔"

    def test_the_node_generator_emits_authentication(self):
        src = open(os.path.join(ROOT, "scripts/generate_tool_nodes.py"), encoding="utf-8").read()
        assert "install_node_auth" in src, "生成器写出来的节点也要带上这一层"
