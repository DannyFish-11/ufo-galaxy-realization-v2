"""tests/test_attachment_identity_fusion.py
================================================

域5 · 会话身份融合:runtime_attachment_session_id 的唯一铸造权威是
AttachedSessionRegistry;attached_runtime_session(生命周期投影)【接收】id,
绝不各自铸 id。此前注册链先写投影(自铸/留空)再写 registry(另铸)——同一设备
在两个存储里挂不同 id(双权威分歧)。
"""
from __future__ import annotations

import pytest

import core.attached_runtime_session as fork
import core.attached_runtime_session_registry as reg


@pytest.fixture(autouse=True)
def _iso():
    fork.reset_attached_runtime_session_runtime()
    reg.reset_session_registry()
    yield
    fork.reset_attached_runtime_session_runtime()
    reg.reset_session_registry()


def test_fork_reuses_registry_id_when_caller_has_none():
    entry = reg.register_session("dev-1", posture="join_runtime")
    rec = fork.attach_runtime_session("dev-1", source_runtime_posture="join_runtime")
    assert entry.runtime_attachment_session_id
    assert rec.runtime_attachment_session_id == entry.runtime_attachment_session_id


def test_fork_respects_explicit_id():
    reg.register_session("dev-2", posture="join_runtime")
    rec = fork.attach_runtime_session(
        "dev-2", source_runtime_posture="join_runtime",
        runtime_attachment_session_id="explicit-xyz",
    )
    assert rec.runtime_attachment_session_id == "explicit-xyz"


def test_fork_without_registry_entry_keeps_old_behavior():
    rec = fork.attach_runtime_session("dev-3", source_runtime_posture="join_runtime")
    # registry 无此设备 → 不注入,保持旧行为(具体值由投影自身语义决定,只须不抛)
    assert rec.attachment_state is not None


def test_no_divergence_registry_first_then_fork():
    """注册链顺序(registry 先铸 → 投影接收)下,两存储 id 恒一致。"""
    entry = reg.register_session("dev-4", posture="join_runtime")
    rec = fork.attach_runtime_session(
        "dev-4", source_runtime_posture="join_runtime",
        runtime_attachment_session_id=entry.runtime_attachment_session_id,
    )
    assert rec.runtime_attachment_session_id == entry.runtime_attachment_session_id
    again = reg.lookup_session_by_device("dev-4")
    assert again.runtime_attachment_session_id == rec.runtime_attachment_session_id
