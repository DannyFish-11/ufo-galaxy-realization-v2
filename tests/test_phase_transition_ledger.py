"""三态转移耐久账 —— 它记的东西必须真能回答「这三天它是什么样子」。

背景见 core/phase_transition_ledger.py 的模块头:查「每 3 天一张记忆卡片」的原料时
发现三态一处都不落盘,于是那张卡上关于三态的每一句都只能是编的。

这份测试盯三件事,按要紧程度排:

1. **发送端真的接上了** —— RuntimeSession.advance 会写账。本仓这半年在
   「接收端建好了、发送端没接」上栽过五次,所以这一条排第一。
2. **不可知 ≠ 安静** —— epoch 边界那一段是问不出来的,不能被读成"它安静着"。
3. 转移性质来自契约那一份,不是这里另写的第二张表。
"""

from __future__ import annotations

import json
import time

import pytest

from core import phase_transition_ledger as ledger
from core.phase_contract import transition_kind_of


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path):
    original = ledger.LEDGER_PATH
    ledger.reset_for_tests(str(tmp_path / "phase_transitions.jsonl"))
    yield
    ledger.reset_for_tests(original)


def _lines():
    try:
        with open(ledger.LEDGER_PATH, "r", encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]
    except FileNotFoundError:
        return []


# ══════════════════════════════════════════════════════════════════════════
# 一、发送端 —— 最要紧的一条
# ══════════════════════════════════════════════════════════════════════════


def test_runtime_session_advance_actually_writes():
    """RuntimeSession.advance 是全仓**唯一**的三态转移点,账必须挂在那儿。

    挂在别处(比如某个路由、某个 handler)都会漏:相位是从多条入口推进的。
    这一条如果红了,说明账本又变成了一个没人喂的接收端。
    """
    from core.desktop_presence_runtime import RuntimeSession, TriState

    session = RuntimeSession(source="test")
    session.advance(TriState.LIMINAL)

    recs = _lines()
    transitions = [r for r in recs if r["kind"] == "transition"]
    assert transitions, "advance() 没有落账 —— 账本没有生产调用方"
    assert transitions[-1]["to"] == "liminal"
    assert transitions[-1]["from"] == "silent"


def test_advance_survives_a_broken_ledger():
    """落账失败绝不能把相位推进搞挂 —— 相位是主体的主干。"""
    from core.desktop_presence_runtime import RuntimeSession, TriState

    ledger.reset_for_tests("/proc/nonexistent-dir-for-test/x.jsonl")
    session = RuntimeSession(source="test")
    session.advance(TriState.LIMINAL)  # 不抛就是通过
    assert session.tristate is TriState.LIMINAL


# ══════════════════════════════════════════════════════════════════════════
# 二、不可知 ≠ 安静 —— 这个模块存在的一半理由
# ══════════════════════════════════════════════════════════════════════════


def test_epoch_marker_is_written_before_the_first_transition():
    ledger.record_transition("silent", "liminal")
    recs = _lines()
    assert recs[0]["kind"] == "epoch_open"
    assert recs[0]["epoch"] == ledger.EPOCH_ID
    assert recs[1]["kind"] == "transition"


def test_two_epochs_mark_a_gap_that_a_quiet_stretch_does_not():
    """同一 epoch 内隔很久 = **安静**(相位已知);epoch 变了 = **不可知**。

    把两者混成一个,卡片就会把"关机三天"写成"安静了三天"。
    """
    ledger.record_transition("silent", "liminal")
    ledger.record_transition("liminal", "manifest")
    first_epoch = ledger.EPOCH_ID

    # 模拟重启:换 epoch,进程内状态清零
    ledger.EPOCH_ID = "second000000"
    ledger._epoch_written = False
    ledger.record_transition("silent", "liminal")

    recs = [r for r in _lines() if r["kind"] == "transition"]
    epochs = [r["epoch"] for r in recs]
    assert epochs[:2] == [first_epoch, first_epoch], "同一进程内的两笔 epoch 必须相同"
    assert epochs[2] != first_epoch, "重启之后必须能看出 epoch 换了 —— 那一段是不可知的"


def test_empty_read_declares_that_it_is_not_proof_of_nothing():
    """读到空必须自带这句声明,否则下一个人会把空读成「什么都没发生」。"""
    assert ledger.read_window(0.0, 1.0) == []
    status = ledger.ledger_status()
    assert "不等于" in status["empty_means"]


def test_status_declares_the_known_blind_spot():
    """启动了却没转移过的进程不留痕 —— 这个盲点必须写在状态里,不能只写在注释里。"""
    assert "不知道" in ledger.ledger_status()["known_blind_spot"]


# ══════════════════════════════════════════════════════════════════════════
# 三、判据只有一份
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "frm,to",
    [
        ("silent", "liminal"),
        ("liminal", "manifest"),
        ("manifest", "liminal"),
        ("manifest", "silent"),
        ("liminal", "silent"),
        ("silent", "manifest"),
    ],
)
def test_transition_kind_comes_from_the_contract(frm, to):
    """转移性质用 phase_contract 那一份算。在这里另写一张表,两张迟早对不上,
    而对不上的那天没有人会发现。"""
    ledger.record_transition(frm, to)
    rec = [r for r in _lines() if r["kind"] == "transition"][-1]
    assert rec["transition_kind"] == transition_kind_of(frm, to)


# ══════════════════════════════════════════════════════════════════════════
# 四、读与留存
# ══════════════════════════════════════════════════════════════════════════


def test_read_window_is_half_open_and_sorted():
    now = time.time()
    ledger.record_transition("silent", "liminal")
    recs = ledger.read_window(now - 60, now + 60)
    assert [r["kind"] for r in recs] == ["epoch_open", "transition"]
    ats = [r["at"] for r in recs]
    assert ats == sorted(ats)

    # 窗口外读不到
    assert ledger.read_window(now - 7200, now - 3600) == []


def test_write_failures_are_counted_not_swallowed_silently():
    """降级要留痕:吞掉异常可以,吞得无声不行。"""
    ledger.reset_for_tests("/proc/nonexistent-dir-for-test/x.jsonl")
    assert ledger.record_transition("silent", "liminal") is False
    assert ledger.ledger_status()["write_failures"] >= 1


def test_corrupt_lines_do_not_break_reading():
    ledger.record_transition("silent", "liminal")
    with open(ledger.LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write("{ 这不是 json\n")
    ledger.record_transition("liminal", "manifest")
    recs = ledger.read_window(0, time.time() + 60)
    assert len([r for r in recs if r["kind"] == "transition"]) == 2
