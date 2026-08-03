"""tests/test_api_surface_parity.py — 两个 app 的 API 面不许再各走各的。

问题是什么
----------
本仓有两个客户端可见的 FastAPI 应用,而且**都配在 9000 端口**:

* 权威层 —— ``unified_launcher`` 组装的 ``core.api_routes`` + ``core.health_check``;
  两处文档都写着"core/api_routes.py 是 Galaxy 的唯一权威 API 入口"。
* ``galaxy_gateway.app``。

实测(把两个 app 各自组装出来逐条比对)发现那句话当时不成立:

    权威层 354 条 / gateway 59 条 / 两边都有 18 条 / **只在 gateway 41 条**

也就是说"跑哪个入口"决定了那 41 个能力存不存在,而客户端无从分辨。手机端那三条
恒判失败的检查(``/api/v1/health``、``/api/v1/config``、``/api/v1/devices/list``)
正是撞在这上面 —— 它们在 gateway 上有,在实际跑的那个 app 上没有。

已经做了什么
------------
把**确属独有**的六个 router 并进了权威层(Linux Agent、Sandbox、同步状态、
Gateway v5、LLM 统计、网关指标),41 → 17。并入时跳过已存在的 (路径, 方法),
避免制造一批被遮蔽的死路由。

剩下的 17 条**没有**并进去,因为它们不是漏挂,是**重复族** —— 同一件事有两套做法。
最典型的是设备配对:两套实现、两套词汇(``/api/v1/pair/*`` vs ``/api/v1/pairing/*``),
把两套一起挂上去只会让一个 app 里出现两个配对系统。保留哪一套是产品决定。
每一条的具体理由记在 ``config/api_surface_parity.json``。

这份测试盯什么
--------------
盯**它不再变长**。台账是债的记账,和 wiring / file-complexity 的基线是同一个思路:
存量记下来,新增才判失败。新写一条只挂在 gateway 上的路由 —— 那正是今天这批
漂移的产生方式 —— 会在这里变红。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "config" / "api_surface_parity.json"

#: 已并入权威层的路由 —— 每条都实测过**能答**(见 test_merged_routes_actually_respond)。
#: 想再往里加,先确认它不依赖 galaxy_gateway 的 app.state。
MERGED_ROUTES = (
    ("/api/v1/agents/linux/servers", "Linux Agent"),
    ("/api/v1/agents/sandbox/status", "Sandbox"),
    ("/sync/status", "同步状态"),
    ("/api/v5/health", "Gateway v5"),
    ("/api/v1/pairing/pending", "设备准入审批"),
    ("/api/v1/config", "客户端配置发现"),
    # 403 cross_device_disabled 是它自己的策略应答,不是"跑不起来" ——
    # 对照组 llm/health 在同样的挂法下是 503 Service not ready。
    ("/api/v1/webrtc/endpoint", "WebRTC 端点发现"),
)


def _surfaces():
    """真组装两个 app,取各自的 openapi 路径集合。

    不读源码猜 —— 路由是运行时挂上去的(``try/except`` 里的可选 router、
    装饰器注册、动态 include),静态数出来的数字和实际跑起来的不是一回事。
    今天这批漂移能被发现,靠的正是"真组装出来比一比"。
    """
    os.environ.setdefault("GALAXY_NATS_ENABLED", "false")
    from fastapi import FastAPI

    from core.api_routes import create_api_routes

    authoritative = FastAPI()
    authoritative.include_router(create_api_routes(service_manager=None, config=None))
    try:
        from core.health_check import create_health_routes

        health_router, _ = create_health_routes(service_manager=None, config=None)
        authoritative.include_router(health_router)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"健康检查层挂不上,权威面就是残的:{exc}")

    from galaxy_gateway.app import app as gateway

    return set(authoritative.openapi()["paths"]), set(gateway.openapi()["paths"])


@pytest.fixture(scope="module")
def surfaces():
    return _surfaces()


class TestLedgerIsWellFormed:
    def test_ledger_exists_and_every_entry_has_a_reason(self):
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        entries = data["gateway_only"]
        assert entries, "台账为空 —— 要么真的对齐了(那就把这条测试改成断言空),要么台账没生成"
        for e in entries:
            assert e["path"].startswith("/"), e
            assert len(e["reason"]) > 20, f"{e['path']} 的理由太短,写清楚为什么还没并进去"

    def test_no_entry_claims_to_be_unclassified(self):
        """ "未分类"是允许暂存的状态,但不该长期存在 —— 它意味着没人回答过那个问题。"""
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        unclassified = [e["path"] for e in data["gateway_only"] if "未分类" in e["reason"]]
        assert not unclassified, f"这些路径还没人回答『该并进权威层还是网关独有』:{unclassified}"

    def test_every_entry_names_a_core_equivalent(self):
        """每条『不搬』都必须点名 core 侧的替代能力。

        "不搬"这个结论只有在 core 侧确实有替代时才成立。不写替代的话,台账
        表达的其实是"先放着",而放着的东西没人会回来看 —— 这份台账存在的
        全部意义就是不让那种事发生。
        """
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        missing = [e["path"] for e in data["gateway_only"] if not e.get("core_equivalent")]
        assert not missing, (
            f"这些条目没写 core 侧的对应能力:{missing}\n"
            "要么补上对应路径,要么说明它确实无可替代 —— 那样它就该被搬进权威层,而不是留在台账里。"
        )


@pytest.mark.slow
class TestNotPortingIsStillJustified:
    """『这 13 条不搬』依赖一个前提:core 侧已经有替代。前提没了就该重新决定。

    没有这条用例,台账里那些 core_equivalent 就只是**写下来的断言**:
    哪天 core 把 /api/v1/tasks 改名或删掉,台账照旧写着"core 已有对应",
    而实际上那个能力在统一启动器上已经消失了,谁也不会知道。
    """

    def test_named_core_equivalents_all_exist_on_the_authoritative_surface(self, surfaces):
        authoritative, _gateway = surfaces
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        broken = []
        checked = 0
        for entry in data["gateway_only"]:
            for equivalent in entry.get("core_equivalent") or []:
                checked += 1
                if equivalent not in authoritative:
                    broken.append(f"{entry['path']} 声称的替代 {equivalent} 在权威面上不存在")
        assert checked > 0, "一条 core_equivalent 都没查到 —— 这条用例又变成恒绿了"
        assert not broken, (
            "台账里『core 侧已有对应能力』这个前提不再成立:\n  "
            + "\n  ".join(broken)
            + "\n\n前提没了,『不搬』就不再是结论。要么修好 core 侧那条,"
            "要么重新决定该不该把网关那条搬进权威层 —— 不要只是把这里的路径改掉。"
        )


@pytest.mark.slow
class TestSurfaceParity:
    def test_gateway_only_paths_do_not_grow(self, surfaces):
        """只在 gateway 上的路径不许比台账更多。

        变多 = 有人新写了一条只挂在网关上的路由。那正是今天这批漂移的产生方式:
        它不会让任何测试变红,只会让"跑哪个入口"重新变得要紧。
        """
        authoritative, gateway = surfaces
        recorded = {e["path"] for e in json.loads(LEDGER.read_text(encoding="utf-8"))["gateway_only"]}
        actual = gateway - authoritative
        new = sorted(actual - recorded)
        assert not new, (
            f"出现了台账之外的『只在 gateway 上』路径({len(new)} 条):{new}\n"
            "要么把它并进 core/api_routes.py 的权威层(首选),"
            "要么加进 config/api_surface_parity.json 并写明为什么不能并。"
        )

    def test_resolved_entries_are_reported(self, surfaces):
        """台账里已经不再分叉的条目要被看见,好收敛台账。不判失败 —— 那是好事。"""
        authoritative, gateway = surfaces
        recorded = {e["path"] for e in json.loads(LEDGER.read_text(encoding="utf-8"))["gateway_only"]}
        resolved = sorted(recorded - (gateway - authoritative))
        if resolved:
            print(f"\n📉 台账里有 {len(resolved)} 条已不再分叉,可以删掉:{resolved}")

    def test_authoritative_is_the_bigger_surface(self, surfaces):
        """权威层必须是更大的那一面 —— 否则"权威"两个字就是空话。"""
        authoritative, gateway = surfaces
        assert len(authoritative) > len(gateway) * 4, (
            f"权威层 {len(authoritative)} 条、网关 {len(gateway)} 条 —— " "权威层不再明显更全,说明有大量能力被挪出去了"
        )

    def test_the_merged_routers_actually_landed(self, surfaces):
        """并进来的 router 真的在权威层上。

        并入写在 try/except 里(单个可选路由缺席不该阻断整层),
        所以"没抛错"不等于"挂上了" —— 必须按路径查。
        """
        authoritative, _ = surfaces
        for path, label in MERGED_ROUTES:
            assert path in authoritative, f"{label} 没并进权威层(缺 {path})"

    def test_merged_routes_actually_respond(self):
        """并进来的路由必须**真的能答**,不是只存在。

        这一条是补上去的,因为第一版只查"路径在不在" —— 而那正是本仓一路在批的弱断言。
        实测代价:第一版把 galaxy_gateway.routes.llm 与 .health 也并了进来,路径检查
        全绿,起服务真打一遍才发现两条恒 503:

            /api/v1/llm/stats  → 503 {"detail": "LLM Router not available"}
            /api/v1/health     → 503 {"detail": "Service not ready"}

        原因是那两个 router 的处理函数取 galaxy_gateway 那个 app 的 app.state,
        而权威层不跑它的 lifespan。"存在但永远不生效"正是本仓一路在清的东西,
        而一个只查存在性的对齐测试会把它记成"已解决"。

        用 TestClient 直接打,不起进程 —— 要验的是依赖能不能解析,不是端口能不能连。
        """
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.api_routes import create_api_routes

        os.environ.setdefault("GALAXY_NATS_ENABLED", "false")
        app = FastAPI()
        app.include_router(create_api_routes(service_manager=None, config=None))
        client = TestClient(app, raise_server_exceptions=False)

        dead = []
        for path, label in MERGED_ROUTES:
            resp = client.get(path)
            # 503 = 依赖没解析出来(通常就是 app.state 缺席);404 = 压根没挂上。
            # 其余码都算"活着" —— 401/422 说明路由在,只是这次请求不满足条件。
            if resp.status_code in (404, 503):
                dead.append(f"{label} {path} -> {resp.status_code} {resp.text[:60]}")
        assert not dead, (
            "这些并进来的路由存在但不生效:\n  "
            + "\n  ".join(dead)
            + "\n它们多半依赖 galaxy_gateway 的 app.state。搬迁前要先解耦,"
            "否则只是把一条死路由从一个 app 搬到另一个 app。"
        )

    #: 已知的重复注册白名单 —— **现在是空的**。
    #:
    #: 曾经有一条 ("/metrics", "GET"):core/routes/monitoring.prometheus_metrics(先注册、
    #: 生效)与 core/health_check 里的 JSON 版本(后注册、永不命中)。那条已经删掉了 ——
    #: 不是改路径,而是删:/metrics 是给 Prometheus 抓取端的,必须是 text/plain 的
    #: exposition 格式,而 JSON 版即使"赢"了也是错的那个赢。那份 JSON 指标没有丢,
    #: check_deep() 里嵌着同一个 get_system_metrics(),走 /health/deep 拿得到。
    #:
    #: 留成空集合而不是删掉这个字段:下一条重复出现时,加进来要写理由,
    #: 而"为什么它可以重复"这个问题本身就是这道守卫的价值。
    KNOWN_SHADOWED: set = set()

    def test_merge_did_not_create_shadowed_duplicates(self):
        """并入不该把权威层已有的路径再注册一遍。

        FastAPI 允许重复路径,匹配时先注册的赢 —— 后来那条永远不会被命中,
        成为一条看不见的死路由。而"存在但从不生效"正是本仓一路在清的那类东西。

        这条用例此前是**恒绿的**,值得记下来
        ------------------------------------
        它原先直接遍历 ``app.routes`` 取 ``route.path``。而新版 FastAPI 的
        ``include_router`` 不再把子路由摊平,顶层拿到的是一串 ``_IncludedRouter``
        包装对象,它们的 ``.path`` 全是 ``None`` —— 于是这条用例每次比较的都是
        ``(None, None)``,永远发现不了任何重复。

        代价是实打实的:为了 WebRTC 端点并入 ``galaxy_gateway.routes.chat`` 时,
        它带的 ``POST /api/v1/chat`` 与 ``core.routes.chat`` 撞车,被原样追加,
        成了一条死路由 —— 而这条本该拦住它的用例照样是绿的。**生产代码里
        "跳过已存在"的那段逻辑也栽在同一件事上**(见 gateway_surface_merge)。

        所以现在走 ``iter_path_methods`` 递归展开,与生产代码用同一个函数 ——
        两边一起对或一起错,不会再出现"守卫看的是另一棵树"。
        """
        os.environ.setdefault("GALAXY_NATS_ENABLED", "false")
        from fastapi import FastAPI

        from core.api_routes import create_api_routes
        from core.gateway_surface_merge import iter_path_methods

        app = FastAPI()
        app.include_router(create_api_routes(service_manager=None, config=None))

        pairs = list(iter_path_methods(app.routes))
        # 先自证这次真的看到了路径 —— 否则下面"没有重复"只是又一次恒绿。
        assert len(pairs) > 100, f"只展开出 {len(pairs)} 条 (路径, 方法),递归展开没生效,这条用例又变成恒绿了"
        assert any(p == "/api/v1/chat" for p, _ in pairs), "展开结果里连 /api/v1/chat 都没有,说明取到的不是真实路由树"

        seen, dupes = set(), []
        for path, method in pairs:
            if method == "HEAD":  # FastAPI 给每条 GET 自动配的,不是重复注册
                continue
            if (path, method) in seen and (path, method) not in self.KNOWN_SHADOWED:
                dupes.append(f"{method} {path}")
            seen.add((path, method))
        assert not dupes, (
            f"权威层里有重复注册(后者永远不会被命中):{sorted(set(dupes))}\n"
            "要么别并这个 router,要么让 gateway_surface_merge 跳过这条 (路径, 方法)。"
        )
