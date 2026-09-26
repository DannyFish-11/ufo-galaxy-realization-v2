"""主轴转移认得出来，不靠「恰好收到了那一帧」。

``render.transition_kind`` 是一拍性的：只有转移之后组装的第一份消息带着它。覆盖层
中途才连上、或者那一份恰好丢了，这一拍就整个没了 —— 「做完就散」的那段铺回动画
不演，边光一直收着。所以再给两位**驻留的**：``transition_seq``（转移过几次）与
``last_transition``（最近那次是哪一种）。消费方拿序号跟自己上次见过的比。

另外钉一条：给**单个**新客户端发的快照不许把那一拍用掉 —— 否则新客户端恰好在
转移与广播之间连上时，其余客户端全都收不到这次转移。
"""

from __future__ import annotations

import pytest

from core.lumiv_websocket_bridge import GalaxyPresenceBridge


@pytest.fixture
def bridge(monkeypatch):
    b = GalaxyPresenceBridge.get_instance()
    for name, value in (
        ("_seq_lifecycle", None),
        ("_transition_seq", 0),
        ("_last_transition", "none"),
        ("_previous_lifecycle", None),
        ("_speaking", False),
        ("_current_mode", "static"),
    ):
        monkeypatch.setattr(b, name, value)
    return b


def _render(b: GalaxyPresenceBridge, mode: str, *, consume_edge: bool = True) -> dict:
    b._current_mode = mode
    return b._build_message(consume_edge=consume_edge)["payload"]["render"]


def test_the_first_report_is_a_starting_point_not_a_transition(bridge):
    r = _render(bridge, "static")
    assert r["transition_seq"] == 0
    assert r["last_transition"] == "none"


def test_each_change_counts_once_and_names_itself(bridge):
    _render(bridge, "static")
    r = _render(bridge, "liminal")
    assert (r["transition_seq"], r["last_transition"]) == (1, "emerging")
    r = _render(bridge, "liminal")  # 同档重复广播：不算
    assert r["transition_seq"] == 1
    _render(bridge, "manifest")
    r = _render(bridge, "static")
    assert (r["transition_seq"], r["last_transition"]) == (3, "dissolving")


def test_the_record_outlives_the_one_shot_flag(bridge):
    _render(bridge, "liminal")
    first = _render(bridge, "manifest")
    later = _render(bridge, "manifest")
    assert first["transition_kind"] == "committing"
    assert later["transition_kind"] == "none", "一拍性的那一位只在第一份里"
    assert later["transition_seq"] == first["transition_seq"], "驻留的序号每一份都带着"
    assert later["last_transition"] == "committing"


def test_a_snapshot_for_one_client_does_not_use_up_the_edge(bridge):
    _render(bridge, "liminal")
    snap = _render(bridge, "manifest", consume_edge=False)  # 新客户端恰好这时连上
    broadcast = _render(bridge, "manifest")  # 随后给所有人的那一份
    assert snap["transition_kind"] == "committing"
    assert broadcast["transition_kind"] == "committing", "快照把那一拍用掉了 —— 其余客户端收不到这次转移"
    assert snap["transition_seq"] == broadcast["transition_seq"]


def test_speaking_is_expression_not_a_trip_back_through_liminal(bridge):
    """朗读是对外表达：说话时主轴是 manifest，不会因此多出一次 liminal 往返。"""
    _render(bridge, "manifest")
    bridge._speaking = True
    r = _render(bridge, "static")  # 相位已回静息，话还没说完
    assert r["lifecycle"] == "manifest"
    assert r["last_transition"] != "handoff", "说话把空间重新推开了一遍"
