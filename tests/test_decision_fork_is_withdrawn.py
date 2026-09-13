"""分叉出去的决策,落定之后必须收回来。

`request_human_decision` 把同一条 decision_request 并行分叉给所有连着的手表和手机。
服务端处理了重复回答（first reply wins），**但没有任何东西告诉其余设备撤回通知**。

后果是用户可见的：手表上答完，手机上那条还挂着。点它是 no-op，可手机本地的
ReplyReceiver 会把通知消掉——从用户视角看「答成功了」，实际什么都没发生；更糟的是
他可能在那边给了个不同的答案。

这正是 SIP RFC 3261 §16.7 的 CANCEL-on-fork。这组测试把它钉住。
"""

from __future__ import annotations

import asyncio

import pytest

from core.interaction.decision_withdrawal import (
    DECISION_WITHDRAW_TYPE,
    WithdrawReason,
    branches_to_withdraw,
    build_withdraw_message,
    reason_for_status,
)


# ── 该收哪几支 ────────────────────────────────────────────────────────────────
def test_the_branch_that_answered_is_not_withdrawn():
    # 答了的那台自己就是答案，界面已经翻篇了。SIP 也不把 CANCEL 发给回了 200 的那支。
    assert branches_to_withdraw(["watch", "phone", "pc"], answered_by="watch") == ["phone", "pc"]


def test_all_branches_withdrawn_when_nobody_answered():
    assert branches_to_withdraw(["watch", "phone"], answered_by="") == ["watch", "phone"]


def test_duplicates_and_blanks_are_dropped_order_kept():
    assert branches_to_withdraw(["a", "", "b", "a", "  "], "") == ["a", "b"]


def test_single_device_has_nothing_to_withdraw():
    assert branches_to_withdraw(["watch"], answered_by="watch") == []


# ── 原因是封闭枚举 ────────────────────────────────────────────────────────────
def test_resolved_means_answered_elsewhere():
    assert reason_for_status("resolved") is WithdrawReason.ANSWERED_ELSEWHERE


def test_timeout_variants_all_map_to_timed_out():
    for s in ("timeout", "timed_out", "timeout_cancel", "timeout_default"):
        assert reason_for_status(s) is WithdrawReason.TIMED_OUT, s


def test_unknown_status_is_conservatively_cancelled_not_ignored():
    # 收错的代价是少一条通知；留着的代价是用户对着一条没有意义的通知做决定。
    assert reason_for_status("something_new") is WithdrawReason.CANCELLED
    assert reason_for_status("") is WithdrawReason.CANCELLED


# ── wire 形状 ─────────────────────────────────────────────────────────────────
def test_withdraw_message_carries_only_id_and_reason():
    m = build_withdraw_message("d1", WithdrawReason.ANSWERED_ELSEWHERE)
    assert m["type"] == DECISION_WITHDRAW_TYPE
    assert m["payload"] == {"decision_id": "d1", "reason": "answered_elsewhere"}


def test_withdraw_message_never_carries_the_answer():
    """把答案广播给每一台设备，等于把一次私人决定发给所有人。

    钉的是 payload 的**字段集合**，不是子串——第一版我扫 "answer" 子串，
    结果被合法的原因值 "answered_elsewhere" 命中了。子串检查在这里天然会误报，
    而字段集合是精确的：多一个字段就红。
    """
    m = build_withdraw_message("d1", WithdrawReason.ANSWERED_ELSEWHERE)
    assert set(m["payload"]) == {"decision_id", "reason"}
    assert set(m) == {"type", "payload"}


# ── 端到端:真的走了一遍 HITL 主路径 ───────────────────────────────────────────
def test_request_human_decision_withdraws_the_other_branches():
    """手表答了 → 手机必须收到 decision_withdraw。"""
    from core.interaction import pending_decision_registry as pdr

    sent: list[tuple[str, dict]] = []

    async def _emit(device_id: str, message: dict) -> None:
        sent.append((device_id, message))

    async def _scenario():
        registry = pdr.get_pending_decision_registry()

        async def _answer_on_watch():
            # 等 decision_request 发出去
            for _ in range(200):
                if any(m.get("type") == "decision_request" for _, m in sent):
                    break
                await asyncio.sleep(0.005)
            did = next(m["payload"]["decision_id"] for _, m in sent if m.get("type") == "decision_request")
            registry.resolve(did, selected_option="yes", source="watch")

        task = asyncio.ensure_future(_answer_on_watch())
        outcome = await pdr.request_human_decision(
            title="要不要删掉这个文件",
            summary="",
            options=[{"id": "yes"}, {"id": "no"}],
            devices=["watch", "phone"],
            emit=_emit,
            timeout_s=5.0,
        )
        await task
        return outcome

    outcome = asyncio.run(_scenario())
    assert outcome.selected_option == "yes"

    withdrawals = [(d, m) for d, m in sent if m.get("type") == DECISION_WITHDRAW_TYPE]
    assert len(withdrawals) == 1, f"应当恰好收回一支,实际 {withdrawals}"
    device, msg = withdrawals[0]
    assert device == "phone", "收回的必须是没答的那台"
    assert msg["payload"]["reason"] == WithdrawReason.ANSWERED_ELSEWHERE.value


def test_undelivered_branch_is_not_withdrawn():
    """投递失败的那台不该收到撤回 —— 它本来就没有东西要收。"""
    from core.interaction import pending_decision_registry as pdr

    sent: list[tuple[str, dict]] = []

    async def _emit(device_id: str, message: dict) -> None:
        if device_id == "offline-pc" and message.get("type") == "decision_request":
            raise ConnectionError("设备不在线")
        sent.append((device_id, message))

    async def _scenario():
        registry = pdr.get_pending_decision_registry()

        async def _answer():
            for _ in range(200):
                if any(m.get("type") == "decision_request" for _, m in sent):
                    break
                await asyncio.sleep(0.005)
            did = next(m["payload"]["decision_id"] for _, m in sent if m.get("type") == "decision_request")
            registry.resolve(did, selected_option="yes", source="watch")

        task = asyncio.ensure_future(_answer())
        out = await pdr.request_human_decision(
            title="t",
            summary="",
            options=[{"id": "yes"}],
            devices=["watch", "phone", "offline-pc"],
            emit=_emit,
            timeout_s=5.0,
        )
        await task
        return out

    asyncio.run(_scenario())
    withdrawn = {d for d, m in sent if m.get("type") == DECISION_WITHDRAW_TYPE}
    assert withdrawn == {"phone"}, f"只该收回投递成功且没答的那台,实际 {withdrawn}"
