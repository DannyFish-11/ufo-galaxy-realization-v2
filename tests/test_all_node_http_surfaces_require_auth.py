"""**每一个**节点的 HTTP 面都要有身份认证,而且内部调用方都要带上身份。

## 为什么是"每一个"

此前 124 个节点里只有 9 个装了认证(还是上一轮刚装的),其余 115 个的 HTTP 面
**任何人都能直接调**。挑几个敏感的装上不成立:一个能读密钥库的节点(Node_03)、
一个能跑代码的节点(Node_101),和能点鼠标的节点一样不该裸奔。

## 两条守卫是一对,少一条都会出事

  · 只装服务端 → 内部调用方被自己的系统 401,功能当场断;
  · 只改调用方 → 认证根本没装上。

所以这里同时钉住两侧。上一轮修 device_control_service 就是因为漏了第二条
(它直接打 Node_92 的 /click,零 Authorization)。
"""

from __future__ import annotations

import ast
import glob
import os
import re

import pytest

#: 节点间/对节点的 URL 长这样。
_URL_MARK = re.compile(r"STATE_MACHINE_URL|NODE_\d+_URL|node_urls|node_url|localhost:8\d{3}|http://node-")
_VERBS = {"post", "get", "put", "delete"}

#: 存活探针 —— 认证豁免,所以调用它不需要带身份。
_EXEMPT_PATHS = ("/health", "/healthz", "/readyz")


def _node_mains():
    for f in sorted(glob.glob("nodes/Node_*/main.py")):
        src = open(f, encoding="utf-8").read()
        if "FastAPI(" in src:
            yield f, src


def _installs_auth(src: str) -> bool:
    """源码里有没有**真的调用** ``install_node_auth(...)``。

    最初这里写的是 ``"install_node_auth" in src`` —— 那个子串光靠
    ``from nodes.common.node_auth import install_node_auth`` 这一行就满足了。
    删掉调用、留着导入,守卫照样是绿的。实测过:抽掉 Node_50 的那次调用,
    这条没红。查调用,不查名字。
    """
    try:
        tree = ast.parse(src)
    except Exception:  # noqa: BLE001
        return False
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "install_node_auth"
        for n in ast.walk(tree)
    )


def test_every_node_with_an_http_app_installs_auth():
    """有 FastAPI app 的节点,一个都不能漏。

    这一条也是给**将来**的:新增节点时忘了装,在这里变红。当初 115 个节点没装,
    而没有任何测试发现得了 —— 它们工作得好好的,只是谁都能调。
    """
    naked = [f for f, src in _node_mains() if not _installs_auth(src)]
    assert not naked, f"这些节点的 HTTP 面没装认证({len(naked)} 个): {naked[:10]}"


def test_the_installed_count_matches_the_app_count():
    """装的数量和有 app 的数量必须相等 —— 防止"装了但装错了 app"。"""
    total = sum(1 for _ in _node_mains())
    installed = sum(1 for _, src in _node_mains() if _installs_auth(src))
    assert installed == total, f"{total} 个节点有 HTTP app,只有 {installed} 个装了认证"


def _internal_calls_without_auth():
    """扫出"打内部地址但没带身份"的调用点。"""
    out = []
    for root in ("nodes", "core", "galaxy_gateway", "launcher"):
        for dp, _, fns in os.walk(root):
            if "__pycache__" in dp:
                continue
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dp, fn)
                try:
                    src = open(p, encoding="utf-8").read()
                    tree = ast.parse(src)
                except Exception:  # noqa: BLE001 — 读不了/语法不对的文件不在本条职责内
                    continue
                if not _URL_MARK.search(src):
                    continue
                has_auth = "internal_headers_for" in src or "internal_auth_headers" in src
                for n in ast.walk(tree):
                    if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                        continue
                    if n.func.attr not in _VERBS or not n.args:
                        continue
                    # os.environ.get("STATE_MACHINE_URL") / dict.get(...) 不是请求。
                    recv = ast.get_source_segment(src, n.func.value) or ""
                    if "environ" in recv or "getenv" in recv or recv.endswith("config"):
                        continue
                    seg = ast.get_source_segment(src, n.args[0]) or ""
                    if not _URL_MARK.search(seg):
                        continue
                    if any(e in seg for e in _EXEMPT_PATHS):
                        continue
                    if not has_auth:
                        out.append(f"{p}:{n.lineno}  {seg[:60]}")
    return out


def test_every_internal_caller_carries_a_token():
    """打节点端点的调用方都要带身份,否则会在自己的系统里被 401。

    豁免 ``/health`` 等探针 —— 那些路径本身就免认证(compose 的 healthcheck
    是裸 curl,不带令牌)。
    """
    missing = _internal_calls_without_auth()
    assert not missing, "这些内部调用没带身份:\n  " + "\n  ".join(missing)


def test_the_token_never_goes_to_an_external_host():
    """令牌按**目标地址**决定带不带。

    仓里同一个 httpx 客户端既打节点、也打 OpenAI / GitHub。在客户端构造处无条件
    挂 Authorization,等于把内部令牌送给第三方 —— 那不是加固,是凭据外泄。
    """
    from core.internal_auth import is_internal_url

    for internal in (
        "http://localhost:8036/click",
        "http://127.0.0.1:8000/node/register",
        "http://node-36-uiawindows:8036/x",
        "http://galaxy-gateway:9000/a",
    ):
        assert is_internal_url(internal), internal

    for external in (
        "https://api.openai.com/v1/chat/completions",
        "https://api.github.com/repos/x/y",
        "https://export.arxiv.org/api/query",
        "http://10.0.0.5/x",
        "",
    ):
        assert not is_internal_url(external), external


def test_an_unrecognised_host_is_treated_as_external():
    """判不准时**不带**令牌。

    宁可让调用方收到 401（一个明确现象），也不要把令牌发给一个没认出来的主机。
    """
    from core.internal_auth import internal_headers_for

    assert internal_headers_for("http://some-random-host/x") == {}


def test_the_contract_doc_matches_the_exempt_table():
    """文档里那张豁免表必须和代码一致。

    这份文档是"新增节点照着做"的依据。它写错的后果不是碍事,是**误导**:
    照着一张假表去判断哪些端点公开,判断的是不存在的东西。
    """
    import pathlib

    from nodes.common.node_auth import DEFAULT_EXEMPT

    doc = pathlib.Path("docs/NODE_HTTP_SECURITY_CONTRACT.md").read_text(encoding="utf-8")
    for path in DEFAULT_EXEMPT:
        assert path in doc, f"豁免路径 {path} 没写进契约文档"
    # 反向:文档里列的也不能是代码里没有的
    import re

    block = re.search(r"```\n(/health.*?)\n```", doc, re.S)
    assert block, "契约文档里找不到豁免表"
    for tok in block.group(1).split():
        if tok.startswith("/"):
            assert tok in DEFAULT_EXEMPT, f"文档列了 {tok},但代码的豁免表里没有"


def test_auth_is_installed_on_the_node_s_actual_app_object():
    """光有调用不够,还得装**对对象**。

    有几个节点的 app 不叫 ``app``:``Node_25_GoogleSearch`` 是实例属性 ``self._app``,
    ``Node_125_MediaGen`` 叫 ``_health_app``,``Node_03/05/19`` 在 ``if HAS_FASTAPI:``
    的缩进块里构造。装到一个不存在或不对的名字上,中间件不会生效,而**节点照常跑**——
    没有任何现象。
    """
    bad = []
    for f, src in _node_mains():
        tree = ast.parse(src)
        app_names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                fn = n.value.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name and "FastAPI" in name:
                    for t in n.targets:
                        app_names.add(ast.get_source_segment(src, t) or "")
        installed_on = {
            ast.get_source_segment(src, n.args[0]) or ""
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "install_node_auth" and n.args
        }
        if app_names and not (installed_on & app_names):
            bad.append(f"{f}: 装在 {sorted(installed_on)},而 app 是 {sorted(app_names)}")
    assert not bad, "认证装错了对象:\n  " + "\n  ".join(bad)
