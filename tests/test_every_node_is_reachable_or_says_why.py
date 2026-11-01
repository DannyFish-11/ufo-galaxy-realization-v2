"""进程内调节点:通用入口接不上时接到节点自己的路由;接不上的照实说为什么(第 9 轮)。

第 8 轮清点:用通用 fusion 入口(``FusionNode``)的 117 个节点里 112 个,模块上没有它认的 process / execute /
run / handle —— 进程内调一律「No executable method found」。它们的实现都在自己的 FastAPI 路由里。
``core/node_route_bridge.py`` 把动作名接到同名的路由:节点进程在跑就 HTTP 打它,没在跑就在本进程里起一个
节点实例(自己的线程与事件循环,startup 跑一次)。

接通之后,节点自己编数据就成了能被调到的谎话 —— 这一轮顺手查出并改掉了五处:没 Key 的天气回写死的「22°C 多云」、
没 psutil 的感知节点回随机的 CPU 占用、自愈节点的恢复动作掷骰子报成功、没 qiskit(甚至有 qiskit)的量子模拟回按
线路名字凑的计数、数字孪生把随机数当设备状态不标出处。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from contextlib import asynccontextmanager

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


# ── 路由怎么认、参数放哪儿(用一个合成的 FastAPI 应用,不依赖任何节点) ──────────────────────────


from pydantic import BaseModel  # noqa: E402


class ClickReq(BaseModel):
    """模块级定义:与节点一样(函数里定义的模型在 postponed annotations 下 FastAPI 解析不到)。"""

    x: int
    y: int


def _app():
    from fastapi import FastAPI

    state = {}

    @asynccontextmanager
    async def lifespan(app):
        state["service"] = "ready"  # 像 40 个节点那样:服务对象在 startup 里建
        yield
        state.clear()

    app = FastAPI(lifespan=lifespan)

    @app.post("/click")
    async def click(req: ClickReq):
        return {"clicked": [req.x, req.y], "service": state.get("service")}

    @app.get("/click")
    async def click_info():
        return {"via": "get"}

    @app.post("/tap")
    async def tap(req: ClickReq):
        return {"tapped": [req.x, req.y], "service": state.get("service")}

    @app.get("/screen_size")
    async def screen_size():
        return {"w": 1, "h": 2}

    @app.get("/timers/{name}")
    async def get_timer(name: str, verbose: bool = False):
        return {"name": name, "verbose": verbose}

    @app.post("/convert")
    async def convert(formula: str):  # POST 上的普通标量参数,FastAPI 里是查询参数
        return {"formula": formula}

    @app.get("/twin")
    async def get_twin():
        return {"twin": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/fails")
    async def fails():
        return {"success": False, "error": "缺 Key"}

    return app


def test_routes_are_matched_by_their_last_segment():
    from core.node_route_bridge import pick_route

    app = _app()
    route, method, _ = pick_route(app, "screen-size", {})
    assert (route.path, method) == ("/screen_size", "GET"), "下划线与连字符等价"


def test_an_ambiguous_name_is_not_resolved_by_guessing():
    """``POST /click`` 与 ``GET /click`` 同名:不替调用方选(选错了「看一眼」就成了「做一次」),请用处理函数名。"""
    from core.node_route_bridge import pick_route

    app = _app()
    route, _, why = pick_route(app, "click", {"x": 1, "y": 2})
    assert route is None and "POST /click → click" in why and "GET /click → click_info" in why
    route, method, _ = pick_route(app, "click_info", {})
    assert (route.path, method) == ("/click", "GET")


def test_a_declared_action_name_matches_the_handler_name():
    from core.node_route_bridge import pick_route

    route, method, _ = pick_route(_app(), "get_twin", {})
    assert (route.path, method) == ("/twin", "GET")


def test_path_placeholders_must_be_given():
    from core.node_route_bridge import pick_route

    app = _app()
    route, _, _ = pick_route(app, "timers", {"name": "a"})
    assert route.path == "/timers/{name}"
    route, _, why = pick_route(app, "timers", {})
    assert route is None and "name" in why


def test_an_unknown_action_lists_what_the_node_has():
    from core.node_route_bridge import pick_route

    route, _, why = pick_route(_app(), "nope", {})
    assert route is None and "tap" in why and "health" not in why, "只报状态的路由不算动作"


def test_parameters_go_where_fastapi_expects_them():
    from core.node_route_bridge import build_request, pick_route

    app = _app()
    route, _, _ = pick_route(app, "tap", {"x": 1, "y": 2})
    assert build_request(route, {"x": 1, "y": 2}) == ("/tap", {}, {"x": 1, "y": 2})
    route, _, _ = pick_route(app, "convert", {"formula": "x+x"})
    assert build_request(route, {"formula": "x+x"}) == ("/convert", {"formula": "x+x"}, None)
    route, _, _ = pick_route(app, "timers", {"name": "a b", "verbose": True})
    assert build_request(route, {"name": "a b", "verbose": True}) == ("/timers/a%20b", {"verbose": True}, None)


def test_the_in_process_host_runs_the_node_startup_once_and_reports_failures(monkeypatch):
    from core import node_route_bridge as bridge

    monkeypatch.setattr(bridge, "_node_url", lambda node_id: "")  # 节点进程没在跑:进程内
    app = _app()
    info = {"type": "instance", "instance": type("F", (), {"instance": type("M", (), {"app": app})})()}

    async def go():
        ok = await bridge.call_route("Node_T1", info, "tap", {"x": 3, "y": 4})
        failed = await bridge.call_route("Node_T1", info, "fails", {})
        bad = await bridge.call_route("Node_T1", info, "tap", {"x": "not-an-int"})
        return ok, failed, bad

    ok, failed, bad = asyncio.run(go())
    assert ok == {"success": True, "result": {"tapped": [3, 4], "service": "ready"}, "via": "in_process"}
    assert failed["success"] is False and failed["error"] == "缺 Key"
    assert bad["success"] is False and "HTTP 422" in bad["error"]
    assert bridge._HOSTS["Node_T1"].startup_error == ""


def test_a_port_held_by_another_service_falls_back_to_in_process(monkeypatch):
    """端口上答话的没有这条路由(FastAPI 的默认 404):那不是这个节点,不信它。"""
    import httpx

    from core import node_route_bridge as bridge

    async def foreign(url, method, path, query, body, timeout_s):
        raise LookupError("不是这个节点")

    monkeypatch.setattr(bridge, "_node_url", lambda node_id: "http://127.0.0.1:1")
    monkeypatch.setattr(bridge, "_over_http", foreign)
    app = _app()
    info = {"module": type("M", (), {"app": app})}
    out = asyncio.run(bridge.call_route("Node_T2", info, "screen_size", {}))
    assert out["via"] == "in_process" and out["result"] == {"w": 1, "h": 2}
    assert httpx  # 只为确认依赖在


def test_a_node_without_routes_says_so():
    from core.node_route_bridge import call_route

    out = asyncio.run(call_route("Node_T3", {"module": object()}, "x", {}))
    assert out["success"] is False and "没有 HTTP 路由可接" in out["error"]


# ── 接到真实节点 ────────────────────────────────────────────────────────────────


def test_the_executor_reaches_a_real_node_through_its_route(monkeypatch):
    from core import node_route_bridge as bridge
    from core.node_invocation import InvocationSource, invoke_node

    monkeypatch.setattr(bridge, "_node_url", lambda node_id: "")
    res = asyncio.run(invoke_node("Node_23_Time", "now", {}, invocation_source=InvocationSource.SYSTEM))
    assert res.success is True, res.error
    assert "No executable method found" not in str(res.result)


def _generic_nodes_without_entry():
    out = []
    for d in sorted((REPO / "nodes").glob("Node_*")):
        fe, mp = d / "fusion_entry.py", d / "main.py"
        if not (fe.exists() and mp.exists()) or '"process", "execute", "run", "handle"' not in fe.read_text("utf-8"):
            continue
        tree = ast.parse(mp.read_text("utf-8"))
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        if "Node" in names or names & {"process", "execute", "run", "handle"}:
            continue
        has_app = "app = FastAPI(" in mp.read_text("utf-8")
        out.append((d.name, has_app))
    return out


def test_every_generic_node_has_routes_the_bridge_can_reach():
    """新加一个用通用入口、又没有 app 的节点,这里会红 —— 进程内它一定调不通。"""
    rows = _generic_nodes_without_entry()
    assert len(rows) >= 100, "清点范围不对"
    assert {n for n, has_app in rows if not has_app} == {"Node_125_MediaGen"}


# ── 接通后查出的编数据,改成照实失败 ────────────────────────────────────────────────


def test_the_weather_node_does_not_make_up_weather(monkeypatch):
    import nodes.Node_24_Weather.main as weather
    from nodes.common.mock_drivers import NotConfigured

    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("USE_MOCK_DRIVERS", raising=False)
    monkeypatch.setattr(weather.weather_manager, "api_key", "")
    for call in (
        lambda: weather.weather_manager.get_current_weather("上海"),
        lambda: weather.weather_manager.get_forecast("上海"),
        lambda: weather.weather_manager.get_air_quality(31.2, 121.5),
        lambda: weather.weather_manager.get_weather_by_coords(31.2, 121.5),
    ):
        with pytest.raises(NotConfigured, match="OPENWEATHER_API_KEY"):
            call()
    monkeypatch.setenv("USE_MOCK_DRIVERS", "true")
    assert weather.weather_manager.get_current_weather("上海")["mock"] is True, "显式要模拟才模拟,而且标出来"


def test_recovery_actions_without_an_implementation_do_not_report_success(monkeypatch):
    import nodes.Node_67_HealthMonitor.main as hm

    monkeypatch.delenv("USE_MOCK_DRIVERS", raising=False)

    async def go():
        monitor = hm.HealthMonitor()
        try:
            return [
                await monitor._execute_recovery("Node_99", action)
                for action in (hm.RecoveryAction.CLEAR_CACHE, hm.RecoveryAction.THROTTLE, hm.RecoveryAction.COLD_REBOOT)
            ]
        finally:
            await monitor.http_client.aclose()

    assert asyncio.run(go()) == [False, False, False]


def test_the_quantum_node_says_when_it_cannot_simulate(monkeypatch):
    import nodes.Node_52_QiskitSimulator.main as q
    from nodes.common.mock_drivers import NotConfigured

    monkeypatch.delenv("USE_MOCK_DRIVERS", raising=False)
    sim = q.QuantumSimulatorService()
    sim.use_qiskit = False
    req = q.SimulationRequest(qasm='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\nh q[0];\n', shots=10)
    with pytest.raises(NotConfigured, match="qiskit"):
        asyncio.run(sim.simulate(req))


def test_the_quantum_node_really_simulates_when_qiskit_is_there():
    pytest.importorskip("qiskit")
    import nodes.Node_52_QiskitSimulator.main as q

    sim = q.QuantumSimulatorService()
    bell = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q -> c;\n'
    out = asyncio.run(sim.simulate(q.SimulationRequest(qasm=bell, shots=400, seed=3)))
    assert set(out.counts) <= {"00", "11"} and sum(out.counts.values()) == 400
    assert out.metadata["simulated"] is False and out.backend_used.startswith("qiskit_statevector")


def test_the_digital_twin_labels_its_states_as_simulated():
    import nodes.Node_74_DigitalTwin.main as twin

    state = twin.DigitalTwinService()._generate_state("Device_001")
    assert state.metadata["simulated"] is True and state.metadata["source"] == "random_simulation"


_FABRICATION_MARKS = ("Using mock data", "返回模拟数据", "using mock simulator", "# 模拟数据", "% success rate")


@pytest.mark.parametrize("main", sorted((REPO / "nodes").glob("Node_*/main.py")), ids=lambda p: p.parent.name)
def test_a_node_only_simulates_when_asked(main):
    """会模拟的节点必须看 ``USE_MOCK_DRIVERS``(nodes/common/mock_drivers.py):缺东西就照实失败。"""
    src = main.read_text("utf-8")
    if any(mark in src for mark in _FABRICATION_MARKS):
        assert "mock_drivers_enabled" in src, f"{main.parent.name} 有模拟数据的分支,却不看 USE_MOCK_DRIVERS"
