"""三态生命周期的性质测试：不挑几个例子，把状态空间走一遍。

借自 AFK-surf/Comma 的做法 —— 它用 TLA+ 给协议建模、让模型检查器把所有交错走一遍；这里
没有上 TLA+，但转移表本来就是数据，状态空间小到可以**穷举**。三层：

1. **转移表本身**：代码里的表与 ``docs/PHASE_TRANSITION_TABLE.md`` 逐行一致；主轴上每一次
   真实的转移都有性质、没有一对状态是「说不清」的；
2. **桥上穷举**：所有长度 ≤ 3 的 (主轴, 说话, 动手) 序列 + 一条长随机游走，每一步都核对
   一组不变量（转移序号、驻留的最近转移、一拍性的那一位、说话把静默抬到表达、停止键只在动手时有）；
3. **叫停**：请求停在任何一个阶段（还在想 / 已落手 / 正在动手）被叫停，都落回干净的静默。

写这份测试时更正了我自己先前的一句话：「第三态只能经消散退出」**只对副轴成立**
（continuum 的 manifest 唯一出口是 receding）。主轴上第三态有两个合法出口 ——
``handoff``（做完接着下一轮，回阈限）与 ``dissolving``（做完就散，回静默）。
"""

from __future__ import annotations

import asyncio
import itertools
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest

import core.lumiv_websocket_bridge as bridge_mod
import core.stop_key as stop_key
from core.desktop_presence_runtime import DesktopPresenceRuntime, TriState
from core.lumiv_websocket_bridge import GalaxyPresenceBridge
from core.phase_contract import (
    FORBIDDEN_TRANSITIONS,
    LIFECYCLE_STATES,
    PHASE_TRANSITIONS,
    RENDER_PHASES,
    TRANSITION_KIND_OF,
    TRANSITION_KINDS,
    transition_kind_of,
)

_DOC = Path(__file__).resolve().parents[1] / "docs" / "PHASE_TRANSITION_TABLE.md"


# ── 1. 转移表本身 ──────────────────────────────────────────────────────────


def _doc_pairs(section: str) -> Set[Tuple[str, str]]:
    """文档里某一节（Allowed / Forbidden）表格的 (from, to) 行。"""
    text = _DOC.read_text(encoding="utf-8")
    head = text.index(f"## {section} Transitions")
    nxt = text.find("\n## ", head + 5)
    body = text[head : nxt if nxt > 0 else len(text)]
    return set(re.findall(r"^\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|", body, flags=re.M))


def test_the_allowed_table_in_code_is_the_one_in_the_doc():
    code = {(a, b) for a, targets in PHASE_TRANSITIONS.items() for b in targets}
    assert code == _doc_pairs("Allowed"), "代码里的允许表与文档不一致 —— 有一边改了、另一边没跟"


def test_the_forbidden_table_in_code_is_the_one_in_the_doc():
    assert set(FORBIDDEN_TRANSITIONS) == _doc_pairs("Forbidden")


def test_nothing_is_both_allowed_and_forbidden_and_every_phase_is_known():
    allowed = {(a, b) for a, targets in PHASE_TRANSITIONS.items() for b in targets}
    assert not allowed & set(FORBIDDEN_TRANSITIONS)
    for a, b in allowed | set(FORBIDDEN_TRANSITIONS):
        assert a in RENDER_PHASES and b in RENDER_PHASES


def test_on_the_continuum_axis_manifest_can_only_recede_and_every_phase_has_a_way_out():
    assert PHASE_TRANSITIONS["manifest"] == ("receding",)
    for phase in RENDER_PHASES:
        assert PHASE_TRANSITIONS[phase], f"{phase} 没有任何出口 —— 状态机会卡死在那儿"
    # 从 formless 出发，沿允许的边能走到每一个相位（没有孤岛）。
    seen, todo = {"formless"}, ["formless"]
    while todo:
        for nxt in PHASE_TRANSITIONS[todo.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    assert seen == set(RENDER_PHASES)


def test_on_the_main_axis_every_real_move_has_a_kind_and_staying_put_has_none():
    for a, b in itertools.permutations(LIFECYCLE_STATES, 2):
        kind = transition_kind_of(a, b)
        assert kind in TRANSITION_KINDS and kind != "none", f"{a}→{b} 没有性质 —— 渲染端不知道该编排什么"
    for s in LIFECYCLE_STATES:
        assert transition_kind_of(s, s) == "none"
    assert transition_kind_of(None, "manifest") == "none", "本进程第一次报主轴不是一次转移"
    assert set(TRANSITION_KIND_OF.values()) <= set(TRANSITION_KINDS)


def test_the_two_exits_of_the_third_state_are_told_apart():
    exits = {b for (a, b) in TRANSITION_KIND_OF if a == "manifest"}
    assert exits == {"liminal", "silent"}
    assert transition_kind_of("manifest", "liminal") == "handoff"
    assert transition_kind_of("manifest", "silent") == "dissolving"


# ── 2. 桥上穷举 ────────────────────────────────────────────────────────────

_MODES = ("static", "liminal", "manifest")
#: (主轴模式, 在说话, 在动手)
_STATES: List[Tuple[str, bool, bool]] = list(itertools.product(_MODES, (False, True), (False, True)))
_LIFE_OF_MODE = {"static": "silent", "liminal": "liminal", "manifest": "manifest"}


@pytest.fixture
def bridge(monkeypatch):
    b = GalaxyPresenceBridge.get_instance()
    # 不让感知的现取拖慢穷举（每次 ~毫秒级）；与本测试要核的性质无关。
    import core.phase_contract as pc

    monkeypatch.setattr(pc, "last_perception_status", lambda: None)
    return b


def _reset(b: GalaxyPresenceBridge) -> None:
    b._seq_lifecycle = None
    b._transition_seq = 0
    b._last_transition = "none"
    b._previous_lifecycle = None


def _apply(b: GalaxyPresenceBridge, state: Tuple[str, bool, bool]) -> None:
    mode, speaking, acting = state
    b._current_mode = mode
    b._speaking = speaking
    b._acting_sessions = frozenset({"rs-1"}) if acting else frozenset()


def _walk(b: GalaxyPresenceBridge, states: List[Tuple[str, bool, bool]], key: str) -> List[Dict[str, Any]]:
    """走一遍；每一步先取一份给单个新客户端的快照（不许用掉那一拍），再取广播。"""
    out: List[Dict[str, Any]] = []
    _reset(b)
    for state in states:
        _apply(b, state)
        snap = b._build_message(consume_edge=False)["payload"]["render"]
        render = b._build_message()["payload"]["render"]
        for field in ("transition_kind", "transition_seq", "last_transition", "lifecycle"):
            assert snap[field] == render[field], f"快照与随后的广播在 {field} 上说了两件事: {states}"
        out.append(render)
    return out


def _check(states: List[Tuple[str, bool, bool]], renders: List[Dict[str, Any]], key: str) -> None:
    for i, (state, r) in enumerate(zip(states, renders)):
        mode, speaking, acting = state
        life = r["lifecycle"]
        ctx = f"序列 {states} 第 {i} 步"
        assert life in LIFECYCLE_STATES, ctx
        # 说话把**静默**抬到表达（朗读是对外表达，念出声时屏幕不该说「我睡着了」）；但它不改
        # 真正在阈限里的主轴 —— 那会把沙盘空间在推演中途收掉。第一版写成「说话 ⇒ manifest」，
        # 穷举第一步就撞出 (阈限, 说话) 这一格：不变量写粗了，设计没错
        # （tests/test_presence_ipc_port_and_speaking_phase.py 早就钉着这一条）。
        want_life = "manifest" if (speaking and mode == "static") else _LIFE_OF_MODE[mode]
        assert life == want_life, f"主轴不对 —— {ctx}"
        assert r["acting"] is acting, ctx
        assert r["stop_key"] == (key if acting else ""), f"停止键只在动手、且占到了时才有 —— {ctx}"
        if r["stop_key"]:
            assert r["acting"], ctx
        if i == 0:
            assert (r["transition_seq"], r["transition_kind"], r["last_transition"]) == (0, "none", "none"), ctx
            continue
        prev = renders[i - 1]
        changed = life != prev["lifecycle"]
        assert r["transition_seq"] == prev["transition_seq"] + (1 if changed else 0), f"序号只在主轴变了时加一 —— {ctx}"
        if changed:
            want = transition_kind_of(prev["lifecycle"], life)
            assert r["last_transition"] == want and r["transition_kind"] == want, ctx
        else:
            assert r["last_transition"] == prev["last_transition"], f"驻留的最近转移不该自己变 —— {ctx}"
            assert r["transition_kind"] == "none", f"一拍性的那一位只在转移后的第一份里 —— {ctx}"


@pytest.mark.parametrize("key", ["Esc", ""])
def test_every_sequence_of_up_to_three_states_keeps_the_invariants(bridge, monkeypatch, key):
    monkeypatch.setattr(bridge_mod, "_stop_key_label", lambda: key)
    checked = 0
    for length in (1, 2, 3):
        for seq in itertools.product(_STATES, repeat=length):
            states = list(seq)
            _check(states, _walk(bridge, states, key), key)
            checked += 1
    assert checked == 12 + 12**2 + 12**3, "穷举没走全"


def test_a_long_random_walk_keeps_the_invariants_too(bridge, monkeypatch):
    monkeypatch.setattr(bridge_mod, "_stop_key_label", lambda: "Esc")
    rng = random.Random(20260926)
    states = [rng.choice(_STATES) for _ in range(3000)]
    _check(states, _walk(bridge, states, "Esc"), "Esc")


async def test_the_phase_going_silent_ends_that_sessions_acting(bridge, monkeypatch):
    """回到静息的会话不可能还在动手 —— tick 在静默时已经停了，不会再送 false 来。"""
    import types

    async def _no_broadcast(*_a, **_k):
        return None

    monkeypatch.setattr(bridge, "_broadcast_state", _no_broadcast)
    monkeypatch.setattr(bridge_mod, "_stop_key_label", lambda: "Esc")
    _reset(bridge)
    bridge._acting_sessions = frozenset({"rs-1", "rs-2"})
    bridge._current_mode = "manifest"
    bridge._on_phase_silent(types.SimpleNamespace(runtime_session_id="rs-1"))
    assert bridge._acting_sessions == frozenset({"rs-2"}), "只清这一个会话，别的会话还在动手"
    bridge._on_phase_silent(types.SimpleNamespace(runtime_session_id="rs-2"))
    render = bridge._build_message(consume_edge=False)["payload"]["render"]
    assert render["acting"] is False and render["stop_key"] == ""


# ── 3. 叫停：在任何一个阶段叫停，都落回干净的静默 ─────────────────────────


@pytest.fixture
def journal(tmp_path, monkeypatch):
    from core.action_journal import get_action_journal, reset_action_journal

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    reset_action_journal()
    yield get_action_journal()
    reset_action_journal()


@pytest.mark.parametrize("stage", ["thinking", "committed", "acting"])
async def test_stopping_at_any_stage_lands_in_a_clean_silence(stage, journal, monkeypatch):
    from core.action_journal import journaled
    from core.liminal_activity import _current_runtime_session, acting, commit_to_manifest

    keys: List[str] = []
    monkeypatch.setattr(stop_key, "acquire", lambda cb: keys.append("acquire"))
    monkeypatch.setattr(stop_key, "release", lambda: keys.append("release"))

    rt = DesktopPresenceRuntime()
    held: Dict[str, Any] = {}
    reached = asyncio.Event()

    async def _dispatch(*_a, **_k):
        held["session"] = _current_runtime_session.get()
        if stage == "thinking":
            reached.set()
            await asyncio.sleep(3600)
        commit_to_manifest()
        if stage == "committed":
            reached.set()
            await asyncio.sleep(3600)
        with acting("computer_use"), journaled("computer_use", "click", {"x": 1, "y": 2}):
            reached.set()
            await asyncio.sleep(3600)

    rt._dispatch = _dispatch
    caller = asyncio.create_task(rt.handle_request("干点事", source="chat"))
    await asyncio.wait_for(reached.wait(), 5)

    session = held["session"]
    assert session.tristate is (TriState.LIMINAL if stage == "thinking" else TriState.MANIFEST), "没停在预期的阶段"
    await rt.stop_current_activity(reason="hotkey")
    result = await asyncio.wait_for(caller, 5)

    assert result["stopped"] is True and result["tristate"] == "silent"
    assert session.tristate is TriState.SILENT, "叫停之后会话没有回到静默"
    assert session.acting is False and session.acting_reason == ""
    assert session.runtime_session_id not in rt._active_sessions, "会话还挂在活跃表里"
    assert rt._inflight_registry() == {}
    assert keys.count("acquire") == keys.count("release") == (1 if stage == "acting" else 0), f"叫停键没还干净: {keys}"
    assert bool(result["unknown_actions"]) is (stage == "acting"), "只有动手阶段才有「结果不明」的那一步"
    assert session._tick_running is False, "continuum 的 tick 还在跑"
