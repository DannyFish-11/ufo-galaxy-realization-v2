"""tests/test_launch_desktop_gateway_port.py — 网关端口必须来自唯一权威

原来钉的是什么
--------------
``launch_desktop.py`` 有两个函数：``get_gateway_health_url()``（等待器探哪个端口）
和 ``start_gateway_backend()``（把 ``python main.py`` 作为子进程拉起来当网关）。
两处**各自解析一次端口**，一旦解析口径不一致就会出现最难查的那种故障：
壳按 A 端口连、等待器按 B 端口探 —— "等到了但连不上"。

启动器统一之后变了什么
----------------------
- ``launch_desktop.py`` 已删除；就绪等待语义搬到 ``launcher/gateway.py``，
  函数名是 ``gateway_health_url()``。
- ``start_gateway_backend()`` **没有搬，因为它没有存在的理由了**：它的职责是
  "外层包装器把 main.py 当子进程拉起来当网关"，而现在 ``main.py`` 自己**就是**
  那个网关进程，没有外层包装器了。唯一还需要 spawn 后端的是 Tauri 壳，
  那条在 ``desktop-tauri/src-tauri/src/main.rs`` 里用 Rust 写，不走这条 Python 路径。

所以本文件钉的东西收敛成一条，而且比原来更强：**端口只能来自仓库的那一处权威**
（``core.electron_launch_guard.resolve_gateway_port``）。原来只能证明
``launcher/gateway.py`` 模块里有个同名属性被调用了；现在证明它真的委派给了那处权威
—— 各写各的解析口径这件事，从根上被挡住。
"""

from __future__ import annotations

from launcher import gateway as gw

#: 端口权威的**点分路径**，不是 import 进来的模块对象。
#:
#: 这不是风格问题：``gateway_health_url()`` 每次调用都重新
#: ``from core.electron_launch_guard import resolve_gateway_port``，取的是
#: ``sys.modules`` 里**当下那个**模块对象。而同一次 pytest 进程里别的用例会
#: ``importlib.reload`` 这个模块，于是测试文件顶层 import 拿到的旧对象和运行时
#: 真正被读的那个不是同一个 —— patch 打在旧对象上，运行时读到的还是真实现，
#: 端口落回 ``PORT`` 环境变量的默认 9000。
#:
#: 实测就是这样红的：单独跑这个文件全绿，跟其它用例一起跑三条全红。
#: monkeypatch 的**字符串形式**在打补丁时才去 ``sys.modules`` 解析，天然跟着走。
_PORT_AUTHORITY = "core.electron_launch_guard.resolve_gateway_port"


def test_health_url_port_comes_from_the_repo_port_authority(monkeypatch):
    """健康检查 URL 的端口必须由 ``resolve_gateway_port()`` 决定。

    刻意 patch **权威模块**而不是 ``launcher.gateway`` 上的同名属性：后者只能证明
    "有个叫这名字的东西被调了"，前者才能证明"调的是仓库那一处"。
    """
    called = {"n": 0}

    def _resolve():
        called["n"] += 1
        return 9321

    monkeypatch.setattr(_PORT_AUTHORITY, _resolve)
    assert gw.gateway_health_url().endswith(":9321/health")
    assert called["n"] >= 1, "gateway_health_url() 必须真的去问端口权威，不能自己写死"


def test_health_url_honours_the_host_override(monkeypatch):
    """host 可被调用方覆盖；端口仍然走权威。两者互不干扰。"""
    monkeypatch.setattr(_PORT_AUTHORITY, lambda: 9444)
    assert gw.gateway_health_url("10.0.0.7") == "http://10.0.0.7:9444/health"


def test_readiness_probe_uses_the_same_url_as_the_waiter(monkeypatch):
    """``gateway_is_ready()`` 与 ``wait_for_gateway()`` 必须探同一个 URL。

    这是原文件真正在防的那类故障的核心：两条路径各解析各的端口，就会出现
    "等到了但连不上"。现在它们共用 ``gateway_health_url()`` 一个出口。
    """
    monkeypatch.setattr(_PORT_AUTHORITY, lambda: 9555)
    seen = []

    def _fake_urlopen(url, timeout=None):  # noqa: ARG001
        seen.append(url)
        raise OSError("connection refused")

    monkeypatch.setattr(gw.urllib.request, "urlopen", _fake_urlopen)

    assert gw.gateway_is_ready() is False
    # timeout 给 0 → 一次都不轮询就返回，避免测试真的睡 90 秒。
    assert gw.wait_for_gateway(timeout=0.0) is False
    assert seen and all(u.endswith(":9555/health") for u in seen)


def test_the_retired_wrapper_helper_did_not_come_along():
    """``start_gateway_backend()`` 不该出现在 ``launcher/gateway.py``。

    它是"外层包装器把 main.py 当子进程拉起来"的产物。统一之后没有外层包装器，
    再留一份就等于给"第二条启动路径"留了个入口 —— 那正是这次统一要消掉的东西。
    """
    assert not hasattr(gw, "start_gateway_backend"), "统一之后不该再有把 main.py 当子进程拉起的助手"
