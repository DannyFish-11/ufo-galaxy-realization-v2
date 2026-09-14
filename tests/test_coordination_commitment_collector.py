"""提议发得出去、承诺收得回来 —— 以及**收不回来时不会把派发弄瘫**。

这个文件里最要紧的一条是 ``test_a_fleet_that_never_answers_does_not_kill_dispatch``:
协商这一轮是默认开着的,而现在没有任何一版固件会回 ``execution_commitment``。
如果"全场沉默"被当成"全员拒绝",候选会被清空 —— 一个还没铺开的机制会让所有跨设备
派发静默消失,而用户看到的现象只是"命令没反应"。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from core.coordination_commitment_collector import (
    CommitmentRegistry,
    collect_commitments,
    get_commitment_registry,
    make_commitment_collector,
    reset_silence_backoff,
)
from core.coordination_consensus import Commitment, DeclineReason, narrow_candidates


@pytest.fixture(autouse=True)
def _clean_backoff():
    reset_silence_backoff()
    yield
    reset_silence_backoff()


def _emitter(sink: List[Dict[str, Any]]):
    async def _emit(device_id: str, message: Dict[str, Any]) -> bool:
        sink.append({"device_id": device_id, "message": message})
        return True

    return _emit


# ── 提议真的发出去了,而且带着协议要求的那几样 ────────────────────────────────
def test_every_candidate_gets_a_proposal_carrying_an_id_and_a_ttl():
    sent: List[Dict[str, Any]] = []
    asyncio.run(collect_commitments(["a", "b"], "打开浏览器", emit=_emitter(sent), timeout_s=0.05))

    assert [s["device_id"] for s in sent] == ["a", "b"]
    kinds = {s["message"]["type"] for s in sent}
    assert kinds == {"execution_proposal"}
    pids = {s["message"]["payload"]["proposal_id"] for s in sent}
    assert len(pids) == 1 and next(iter(pids)), "同一轮必须共用一个 proposal_id"
    assert all(s["message"]["payload"]["ttl_ms"] > 0 for s in sent), "承诺必须带有效期"


# ── 沉默 → no_response,而且是中心替它记的 ───────────────────────────────────
def test_silence_becomes_an_explicit_no_response_not_an_assumed_yes():
    out = asyncio.run(collect_commitments(["a"], "x", emit=_emitter([]), timeout_s=0.05))
    assert len(out) == 1
    assert out[0].accepted is False
    assert out[0].decline_reason == DeclineReason.NO_RESPONSE.value


def test_a_device_that_cannot_be_reached_is_recorded_as_no_response_not_not_ready():
    """发不出去是**中心这边**的问题,不是设备说了 not_ready。

    这个区分有后果:全场 no_response 会被放行,全场 not_ready 会清空候选。
    """

    async def _dead(device_id: str, message: Dict[str, Any]) -> bool:
        return False  # 连接管理器的约定:显式 False = 没送出去

    out = asyncio.run(collect_commitments(["a", "b"], "x", emit=_dead, timeout_s=5.0))
    assert {c.decline_reason for c in out} == {DeclineReason.NO_RESPONSE.value}


def test_an_unreachable_fleet_does_not_wait_for_the_timeout():
    """一台都发不出去时,不该白等满一个超时 —— 等它没有任何信息量。

    超时给 5 秒而实测远小于它:若哪天又把发送结果吞掉(历史上就吞过),这条会变红。
    """

    async def _dead(device_id: str, message: Dict[str, Any]) -> bool:
        return False

    loop_t = asyncio.run(_timed(collect_commitments(["a", "b"], "x", emit=_dead, timeout_s=5.0)))
    assert loop_t < 1.0, f"发不出去却等了 {loop_t:.2f}s"


async def _timed(coro) -> float:
    loop = asyncio.get_running_loop()
    t = loop.time()
    await coro
    return loop.time() - t


# ── 收到承诺就唤醒,不必等满超时 ──────────────────────────────────────────────
def test_a_full_house_of_replies_returns_before_the_timeout():
    async def _run():
        sent: List[Dict[str, Any]] = []
        task = asyncio.create_task(collect_commitments(["a", "b"], "x", emit=_emitter(sent), timeout_s=5.0))
        await asyncio.sleep(0)  # 让提议先发出去
        pid = sent[0]["message"]["payload"]["proposal_id"]
        reg = get_commitment_registry()
        for did in ("a", "b"):
            reg.resolve(pid, {"device_id": did, "accepted": True, "valid_until_ms": int(9e18)})
        return await _timed_task(task)

    elapsed, out = asyncio.run(_run())
    assert elapsed < 1.0, f"都回话了还等了 {elapsed:.2f}s"
    assert all(c.accepted for c in out)


async def _timed_task(task):
    loop = asyncio.get_running_loop()
    t = loop.time()
    out = await task
    return loop.time() - t, out


# ── 登记处:只认这一轮问过的设备 ─────────────────────────────────────────────
def test_a_commitment_from_a_device_we_never_asked_is_dropped():
    reg = CommitmentRegistry()
    rnd = reg.open(["a"], proposal_id="p1")
    assert reg.resolve("p1", {"device_id": "ghost", "accepted": True, "valid_until_ms": int(9e18)}) is False
    assert rnd.replies == {}


def test_a_late_reply_for_a_closed_round_is_not_an_error():
    """轮次已收摊时迟到的承诺返回 False 而不是抛 —— 迟到是常态,不是故障。"""
    reg = CommitmentRegistry()
    assert reg.resolve("没有这一轮", {"device_id": "a", "accepted": True}) is False


def test_the_first_reply_wins_and_a_second_one_does_not_overwrite_it():
    reg = CommitmentRegistry()
    reg.open(["a"], proposal_id="p1")
    reg.resolve("p1", {"device_id": "a", "accepted": True, "valid_until_ms": int(9e18)})
    reg.resolve("p1", {"device_id": "a", "accepted": False, "decline_reason": "busy"})
    rnd = reg._rounds["p1"]
    assert rnd.replies["a"].accepted is True


# ── 退避:全场沉默一次之后,不再每次派发都付一遍超时 ──────────────────────────
def test_a_silent_round_puts_the_next_one_on_hold():
    sent: List[Dict[str, Any]] = []
    asyncio.run(collect_commitments(["a"], "x", emit=_emitter(sent), timeout_s=0.05))
    assert len(sent) == 1
    asyncio.run(collect_commitments(["a"], "x", emit=_emitter(sent), timeout_s=0.05))
    assert len(sent) == 1, "退避期内不该再发提议"
    reset_silence_backoff()
    asyncio.run(collect_commitments(["a"], "x", emit=_emitter(sent), timeout_s=0.05))
    assert len(sent) == 2, "退避清掉之后应当恢复"


# ── 和判定层接起来:沉默的舰队不会把派发弄瘫 ─────────────────────────────────
def test_a_fleet_that_never_answers_does_not_kill_dispatch():
    """**这条是整套机制的安全底线。**

    现状:没有任何一版固件会回 execution_commitment。如果沉默 == 拒绝,那么这一轮
    上线的当天,所有多候选跨设备派发都会静默消失。
    """
    silent = asyncio.run(collect_commitments(["a", "b"], "x", emit=_emitter([]), timeout_s=0.05))
    result = narrow_candidates(["a", "b"], silent)
    assert result.outcome == "unchanged"
    assert result.device_ids == ["a", "b"]


def test_but_one_real_refusal_is_still_an_informative_failure():
    """至少有一台**明确**说了不接 —— 那时空候选是有信息的,不是通道坏了。"""
    mixed = [
        Commitment(device_id="a", accepted=False, decline_reason=DeclineReason.BUSY.value),
        Commitment(device_id="b", accepted=False, decline_reason=DeclineReason.NO_RESPONSE.value),
    ]
    result = narrow_candidates(["a", "b"], mixed)
    assert result.outcome == "all_declined"
    assert result.device_ids == []


# ── 工厂给出的收集器就是 narrow_devices 认的那个形状 ─────────────────────────
def test_the_factory_produces_the_shape_narrow_devices_expects():
    sent: List[Dict[str, Any]] = []
    collector = make_commitment_collector(emit=_emitter(sent), timeout_s=0.05)
    out = asyncio.run(collector(["a"], "x"))
    assert [c.device_id for c in out] == ["a"]
    assert len(sent) == 1


# ── 入站接线:网关真的会把 execution_commitment 交给登记处 ────────────────────
def test_the_gateway_actually_routes_execution_commitment_to_the_registry():
    """光有登记处不够 —— 得有人把设备的回话喂进来。

    用 AST 而不是 grep:注释和文档串里出现同一个名字不算接线。这一条如果红了,
    症状会是"设备明明回了话,中心还是当它沉默",而且没有任何报错。
    """
    import ast
    import pathlib

    src = pathlib.Path("galaxy_gateway/websocket_handler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    imported = {
        alias.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and "commitment_collector" in n.module
        for alias in n.names
    }
    assert "get_commitment_registry" in imported, "websocket_handler 没有导入承诺登记处"

    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "execution_commitment" in consts, "网关没有分派 execution_commitment"

    # 不能只查有没有调用过 ``resolve`` —— 本文件里 ``upper_ports.resolve`` 到处都是,
    # 那样查等于没查。查的是:确实在 get_commitment_registry() 的返回值上调 resolve。
    chained = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Call)
        and isinstance(n.func.value.func, ast.Name)
        and n.func.value.func.id == "get_commitment_registry"
    }
    assert "resolve" in chained, "收到承诺却没有 resolve 对应的轮次"


def test_the_gateway_takes_device_id_from_the_connection_not_from_the_payload():
    """承诺的 device_id 以连接为准,不收设备自报的那个。

    收设备自报的会开一个口子:一台设备在 payload 里填另一台的 id,就能替别人接下
    这次任务,或者替别人拒绝 —— 而中心会照着这个假身份去派发。连接上的 device_id
    是握手时定下的,设备改不了。

    顺带还解决一个真问题:手表的 sendCommand 只在信封上带 device_id,内层 payload
    里没有;按 payload 取会得到空串,那条承诺被当成"没问过的设备"丢掉,手表等于还是沉默。
    """
    import ast
    import pathlib
    import textwrap

    src = pathlib.Path("galaxy_gateway/websocket_handler.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_command")
    body = textwrap.dedent(ast.get_source_segment(src, fn) or "")

    # 找到喂给 resolve 的那个字典,确认它的 device_id 被连接上的值覆盖过。
    assigns = [
        n
        for n in ast.walk(ast.parse(body))
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Subscript)
        and isinstance(n.targets[0].slice, ast.Constant)
        and n.targets[0].slice.value == "device_id"
        and isinstance(n.value, ast.Name)
        and n.value.id == "device_id"
    ]
    assert assigns, "承诺的 device_id 没有被连接上的值覆盖 —— 设备可以冒名顶替"
