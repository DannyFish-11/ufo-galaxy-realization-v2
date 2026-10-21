"""Agent 载体:装在别的电脑 / Linux / 云主机上,用配对码接入,接中心派来的 Agent,在本机把整段目标做完。

跨设备整体方案阶段 5。全程走真的:真的网关(uvicorn + 规范设备入口 + 权威 API,鉴权开着)、真的载体客户端
(``device_client --carrier``:同一个连接层 + 载体执行插件 + 载体上的 Agent,真 WebSocket),配对、对外 A2A、
派桥接 Agent、委派整段目标都是真的。推理加行动循环要的模型经中心(钥匙只在中心);这里把中心的模型换成
照剧本回答的替身,其余不换。代码在 Docker 沙箱里跑的那一条标 slow(要本地有镜像)。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("uvicorn")
pytest.importorskip("websockets")

from tests.test_a_laptop_joins_by_pairing import gateway  # noqa: E402,F401 — 真网关夹具共用一份

_CARRIERS: list = []


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_CARRIER_WORKDIR", str(tmp_path / "carrier-work"))
    from core import a2a_link, phone_bridge

    a2a_link.reset_links()
    phone_bridge.reset_bridges()
    yield
    # DeviceClient.run() 断线后会一直重连;每个测试结束都停掉(同 test_a_laptop_joins_by_pairing)
    while _CARRIERS:
        _CARRIERS.pop().client.stop()


class Carrier:
    """真的载体客户端:DeviceClient(carrier=True) + CarrierExecutor,跑在自己的线程和事件循环里。"""

    def __init__(self, gw, state, executor=None):
        from device_client.client import DeviceClient
        from device_client.executors.carrier import CarrierExecutor

        self.executor = executor or CarrierExecutor()
        port = int(gw.url.rsplit(":", 1)[1])
        self.client = DeviceClient(self.executor, host="127.0.0.1", port=port, state=state, carrier=True)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=lambda: self.loop.run_until_complete(self.client.run()), daemon=True)
        self.thread.start()
        _CARRIERS.append(self)

    def drop_connection(self):
        """断一次线(像网络抖了一下):客户端自己马上重连、重新登记、重新报能力。"""
        asyncio.run_coroutine_threadsafe(self.client._ws.close(), self.loop).result(timeout=5)

    @property
    def device_id(self):
        return self.client.device_id


def _card(gw, did):
    return next((m for m in gw.agent("list", {})["members"] if m["device_id"] == did), {})


def _until(pred, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.1)
    return pred()


def _joined_carrier(gw, executor=None):
    from device_client import pairing as dp

    invite = gw.agent("invite", {"kind": "carrier"})
    assert invite["success"] and "--carrier" in invite["commands"][0], invite
    state: dict = {}
    resp = dp.pair(invite["code"], gw.url, state, name="机房里的 Linux", device_type="linux_server")
    assert resp["success"], resp
    state["candidates"] = []  # 名片里的局域网地址指向配置端口;测试服务器跑在随机端口
    carrier = Carrier(gw, state, executor)
    card = _until(lambda: (c := _card(gw, carrier.device_id)) and c.get("agent_installed") and c)
    assert card, f"载体没装上桥接 Agent:{_card(gw, carrier.device_id)} fatal={carrier.client.fatal}"
    return carrier, card


class _NoSandbox:
    """没有 Docker 的载体(CI 里不一定有),其余是真的 CarrierExecutor。"""

    @staticmethod
    def make():
        from device_client.executors.carrier import CarrierExecutor

        ex = CarrierExecutor()
        ex._sandbox = (False, "没装 Docker(测试)")
        return ex


def test_a_carrier_joins_by_pairing_and_takes_an_agent(gateway):
    carrier, card = _joined_carrier(gateway, _NoSandbox.make())
    assert card["can_take_agent"] is True, "载体报能力时声明了能接 Agent"
    assert card["agent_installed"] is True
    assert card["form"] == "carrier", card["form"]
    actions = {a["name"]: a["does"] for a in card["actions"]}
    assert {"read_file", "write_file", "list_files", "get_status"} <= set(actions)
    assert "run_code" not in actions, "没有沙箱就不报 run_code"
    assert actions["write_file"].startswith("在载体工作目录里写"), "载体自己的动作说明进了设备卡"
    from core.phone_bridge import bridge_state

    assert bridge_state(carrier.device_id)["session_id"] == f"carrier:{carrier.device_id}"


def test_a_whole_goal_given_as_steps_is_done_on_the_carrier(gateway):
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    out = gateway.agent(
        "delegate",
        {
            "device_id": carrier.device_id,
            "goal": "把今天的待办写进 todo.txt 再读出来核对",
            "steps": [
                {"action": "write_file", "params": {"path": "todo.txt", "content": "买菜\n交电费"}},
                {"action": "read_file", "params": {"path": "todo.txt"}},
            ],
            "timeout_s": 30,
        },
    )
    assert out["success"] is True, out
    assert any("交电费" in s.get("observation", "") for s in out["steps"]), out["steps"]
    assert [p.get("action") for p in out["progress"]] == ["write_file", "read_file"], "每做完一步报一次进度"
    assert (carrier.executor._path("todo.txt")).read_text(encoding="utf-8") == "买菜\n交电费"


def test_a_goal_in_plain_words_runs_a_reasoning_loop_on_the_carrier_with_the_centers_model(gateway, monkeypatch):
    import core.multi_llm_router as mlr

    script = [
        SimpleNamespace(
            content="先写文件",
            tool_calls=[
                {"function": {"name": "write_file", "arguments": json.dumps({"path": "hello.txt", "content": "你好"})}}
            ],
        ),
        SimpleNamespace(content="写好了:hello.txt 里是「你好」", tool_calls=None),
    ]
    seen = []

    class _Router:
        async def chat(self, messages, tools=None, **kw):
            seen.append({"messages": messages, "tools": [t["function"]["name"] for t in tools or []]})
            return script[len(seen) - 1]

    monkeypatch.setattr(mlr, "get_llm_router", lambda: _Router())
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    out = gateway.agent(
        "delegate", {"device_id": carrier.device_id, "goal": "在 hello.txt 里写一句你好", "timeout_s": 30}
    )
    assert out["success"] is True, out
    assert out["summary"] == "写好了:hello.txt 里是「你好」"
    assert len(seen) == 2, "两轮都问的中心的模型(钥匙只在中心)"
    assert "write_file" in seen[0]["tools"]
    assert any("[工具 write_file 的结果]" in m["content"] for m in seen[1]["messages"]), "上一轮工具的结果带回去了"
    assert (carrier.executor._path("hello.txt")).read_text(encoding="utf-8") == "你好"


def test_when_the_center_has_no_model_the_carrier_says_so_instead_of_claiming_success(gateway, monkeypatch):
    import core.multi_llm_router as mlr

    class _Router:
        async def chat(self, messages, tools=None, **kw):
            raise RuntimeError("还没有可用的 AI 服务")

    monkeypatch.setattr(mlr, "get_llm_router", lambda: _Router())
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    out = gateway.agent("delegate", {"device_id": carrier.device_id, "goal": "整理一下下载目录", "timeout_s": 30})
    assert out["success"] is False, out
    assert "还没有可用的 AI 服务" in out["error"]


def test_when_the_centers_router_degrades_to_a_notice_the_carrier_does_not_take_it_as_the_answer(gateway, monkeypatch):
    """路由一个模型都调不通时不抛异常、回一句说明(provider="none")—— 那不是目标做完了的总结。"""
    import core.multi_llm_router as mlr
    from core.llm_unavailable_reply import NOTHING_CONFIGURED_REPLY

    class _Router:
        async def chat(self, messages, tools=None, **kw):
            return mlr.LLMResponse(
                content=NOTHING_CONFIGURED_REPLY, provider="none", model="none", input_tokens=0, output_tokens=0
            )

    monkeypatch.setattr(mlr, "get_llm_router", lambda: _Router())
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    out = gateway.agent("delegate", {"device_id": carrier.device_id, "goal": "整理一下下载目录", "timeout_s": 30})
    assert out["success"] is False, out
    assert "还没有可用的 AI 服务" in out["error"]


def test_right_after_a_carrier_reconnects_a_whole_goal_waits_for_its_agent_instead_of_being_refused(gateway):
    """重连后、报能力之前的那一小段:登记换掉了元数据(能接 Agent 的声明还没再报),中心以为 Agent 还装着。
    真后端实测查出:这时交整段目标会被当场拒成「不能接整段目标」。现在等它重新装上再交。"""
    from core.unified.connection_manager import get_unified_connection_manager

    ucm = get_unified_connection_manager()
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    did = carrier.device_id
    carrier.drop_connection()
    assert _until(lambda: not ucm.is_device_connected(did), 10), "断线没被看到"
    assert _until(lambda: ucm.is_device_connected(did), 15), "没有自己连回来"
    # 刚重新登记上(报能力在 0.5 秒后):此刻就交
    out = gateway.agent(
        "delegate",
        {"device_id": did, "goal": "核对", "steps": [{"action": "list_files", "params": {}}], "timeout_s": 30},
    )
    assert out["success"] is True, out


def test_right_after_the_center_restarts_a_reconnecting_carrier_is_waited_for_too(gateway):
    """后端重启:中心不记得它装过 Agent,能接 Agent 的声明要等报能力才到。那半秒里交的整段目标也等它。"""
    from core import a2a_link, phone_bridge
    from core.unified.connection_manager import get_unified_connection_manager

    ucm = get_unified_connection_manager()
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    did = carrier.device_id
    phone_bridge.reset_bridges()  # 中心这边的记忆没了(像进程重启)
    a2a_link.reset_links()
    carrier.drop_connection()
    assert _until(lambda: not ucm.is_device_connected(did), 10)
    assert _until(lambda: ucm.is_device_connected(did), 15)
    out = gateway.agent(
        "delegate",
        {"device_id": did, "goal": "核对", "steps": [{"action": "list_files", "params": {}}], "timeout_s": 30},
    )
    assert out["success"] is True, out


def test_a_single_action_still_goes_straight_to_the_carrier_and_stays_in_its_workdir(gateway):
    carrier, _ = _joined_carrier(gateway, _NoSandbox.make())
    ok = gateway.agent("invoke", {"device_id": carrier.device_id, "action": "get_status", "params": {}})
    assert ok["success"] is True, ok
    out = gateway.agent(
        "invoke", {"device_id": carrier.device_id, "action": "read_file", "params": {"path": "../../etc/passwd"}}
    )
    assert out["success"] is False and "工作目录" in json.dumps(out, ensure_ascii=False), out


def test_a_device_without_a_bridge_agent_is_not_given_whole_goals(gateway):
    """「手和眼」式电脑没声明能接 Agent:不派、不收整段目标,当场说明原因。"""
    from tests.test_a_laptop_joins_by_pairing import _LAPTOPS, Laptop, _pair

    _, state, _ = _pair(gateway)
    laptop = Laptop(gateway, pytest.MonkeyPatch(), state)
    try:
        assert laptop.wait_connected(), laptop.client.fatal
        time.sleep(0.5)
        card = _card(gateway, laptop.client.device_id)
        assert card["can_take_agent"] is False and card.get("agent_installed") is False
        out = gateway.agent("delegate", {"device_id": laptop.client.device_id, "goal": "整理桌面"})
        assert out["success"] is False and "devices__invoke" in out["error"]
    finally:
        while _LAPTOPS:
            _LAPTOPS.pop().client.stop()


def test_without_a_sandbox_the_carrier_does_not_offer_to_run_code(monkeypatch):
    import device_client.executors.carrier as cx

    monkeypatch.setattr(cx.shutil, "which", lambda name: None)
    ex = cx.CarrierExecutor()
    assert "run_code" not in ex.supported_actions()
    out = ex._run_code({"code": "print(1)"})
    assert out["success"] is False and "Docker" in out["error"]
    assert ex.available()[0] is True, "文件与状态照样能用,照样连上"


def test_the_carrier_has_its_own_identity_next_to_a_hands_and_eyes_client(tmp_path, monkeypatch):
    """同一台机器上的「手和眼」式客户端和载体各有各的凭据文件、各是各的设备。"""
    import device_client.__main__ as cli

    monkeypatch.delenv("GALAXY_DEVICE_STATE", raising=False)
    monkeypatch.setattr(cli._dp, "state_path", lambda: str(tmp_path / "device.json"))
    loaded = []
    monkeypatch.setattr(cli._dp, "load_state", lambda path=None: loaded.append(path) or {})
    assert cli.main(["--carrier", "--no-run"]) == 0
    assert loaded == [str(tmp_path / "carrier.json")]


def test_a_reasoning_loop_that_runs_out_of_turns_does_not_claim_success():
    from core.local_agent_runtime import LocalAgentRuntime

    async def tool(name, args):
        return {"success": True, "n": len(args)}

    turn = {"n": 0}

    async def llm(messages, tools):
        turn["n"] += 1
        return {"content": "再看一眼", "tool_calls": [{"name": "get_status", "arguments": {"i": turn["n"]}}]}

    rt = LocalAgentRuntime(tool_executor=tool, llm_chat=llm)
    res = asyncio.run(rt.execute({"manifest_id": "m", "execution_mode": "react", "max_react_turns": 3, "tasks": []}))
    assert res.success is False and "turns" in res.error


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "image", "inspect", "python:3.11-slim"], capture_output=True, timeout=10
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _docker_ready(), reason="需要 Docker 和本地的 python:3.11-slim 镜像")
def test_code_runs_only_in_a_sandbox_without_network():
    from device_client.executors.carrier import CarrierExecutor

    ex = CarrierExecutor()
    ok = ex.execute("run_code", {"language": "python", "code": "print(sum(range(10)))"})
    assert ok["success"] is True and ok["stdout"].strip() == "45", ok
    net = ex.execute(
        "run_code", {"language": "python", "code": "import socket; socket.create_connection(('1.1.1.1', 53), 3)"}
    )
    assert net["success"] is False, "沙箱里不联网"
    slow = ex.execute("run_code", {"language": "sh", "code": "sleep 30", "timeout_s": 2})
    assert slow["success"] is False and "强行停了" in slow["error"], slow
