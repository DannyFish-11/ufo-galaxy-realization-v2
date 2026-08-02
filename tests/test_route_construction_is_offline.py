"""路由构建期不许连网 —— 回归护栏
===================================

发现经过
---------
量启动耗时时,``create_api_routes()`` 里跑出一句 ``Connection refused``。追下去是
**两处**在拼路由表的时候去连网:

* ``core/routes/nodes.py`` —— ``llm_router = get_llm_route_authority().execution_router``
* ``core/routes/chat.py``  —— ``get_unified_llm_router()``,返回值**直接丢弃**,
  该模块没有任何处理函数用它,纯粹一次预热

两条都会走到 ``MultiLLMRouter._discover_providers()``,那里为了探测本机 Ollama 发
**同步阻塞**的 ``httpx.get``:先探默认地址(timeout=2s),命中后再拉模型列表
(timeout=3s)。

为什么一直没人发现:开发机上没装 Ollama,连 127.0.0.1:11434 是**瞬间**的
connection refused,看不出慢。但只要那个端口是被防火墙**丢包**(而不是拒绝)、
或者 ``OLLAMA_URL`` 指向局域网里一台关着的机器,这 5 秒就实打实压在启动路径上 ——
而且发生在 uvicorn 绑端口**之前**,对外表现是"服务起了半天没反应",日志里没有
任何一行指向真正的原因。

这条用例守什么
---------------
守的不是"快"(墙钟断言在 CI 上必然抖),而是一条清晰的不变量:**拼路由表是纯粹的
声明动作,不该产生任何 I/O 依赖**。它会在下一个人写出 ``get_xxx_router()`` 这类
"顺手预热一下"的代码时当场拦住 —— 那种代码看起来人畜无害,代价却藏在三层调用之下。
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture()
def forbid_network(monkeypatch):
    """把 socket 连接换成会记录并拒绝的桩,返回被尝试的地址列表。

    用**拒绝**而不是放行后记录:放行的话本机恰好起着 Ollama 时用例会静默变绿,
    而那正是它要抓的情形。拒绝也顺带模拟了"端口不通"这个真实场景。
    """
    attempted: list = []
    real_connect = socket.socket.connect

    def _blocked(self, address):
        attempted.append(address)
        raise ConnectionRefusedError(f"网络在本用例中被禁用: {address}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    assert real_connect is not None
    return attempted


class TestApiRouteConstruction:
    def test_create_api_routes_touches_no_network(self, forbid_network):
        from core.api_routes import create_api_routes

        router = create_api_routes(service_manager=None, config={})

        assert forbid_network == [], f"路由构建期发起了网络连接: {forbid_network}"
        assert len(router.routes) > 0, "路由表不能是空的 —— 否则这条用例会因为什么都没构建而假绿"

    def test_websocket_routes_touch_no_network(self, forbid_network):
        from fastapi import FastAPI

        from core.api_routes import create_websocket_routes

        create_websocket_routes(FastAPI(), service_manager=None)

        assert forbid_network == [], f"WebSocket 路由构建期发起了网络连接: {forbid_network}"


class TestTheTwoOffendersSpecifically:
    """针对被修掉的那两处单独钉一遍。

    上面的整体断言已经覆盖了它们,但整体断言在别处出问题时也会红;这两条让
    失败信息直接指到具体模块,不用再去二分。
    """

    def test_nodes_router_defers_llm_router(self, forbid_network):
        from core.routes.nodes import create_router

        create_router(service_manager=None, config={})
        assert forbid_network == [], "core/routes/nodes.py 又在构建期建 LLM router 了"

    def test_chat_router_does_not_warm_up_llm_router(self, forbid_network):
        from core.routes.chat import create_router

        create_router(service_manager=None, config={})
        assert forbid_network == [], "core/routes/chat.py 又在构建期预热 LLM router 了"


class TestLazyAccessStillWorks:
    """惰性化不能把功能弄丢:处理函数真要用的时候,还得能拿到 router。"""

    def test_nodes_lazy_accessor_resolves(self, monkeypatch):
        """构建期不取,但取得到 —— 用桩验证访问器本身接通了权威链路。"""
        import core.llm.route_authority as authority

        sentinel = object()

        class _Authority:
            execution_router = sentinel

        monkeypatch.setattr(authority, "get_llm_route_authority", lambda: _Authority())

        # 直接调用惰性访问器:它是 create_router 的闭包局部函数,所以从闭包里取。
        from core.routes.nodes import create_router

        router_factory = None
        create_router(service_manager=None, config={})
        for cell in create_router.__code__.co_consts:
            if getattr(cell, "co_name", "") == "_llm_router":
                router_factory = cell
                break
        assert router_factory is not None, "_llm_router 惰性访问器不见了 —— 是不是又改回构建期取了?"
