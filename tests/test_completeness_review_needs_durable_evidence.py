"""治理自评不许把"进程内存里有人写过一笔"当成"真实跨仓证据流过了"。

## 修的是什么

``core/dual_repo_system_completeness_review.py::_assess_cross_repo_evidence()``
里有一条"运行时激活检查",原先读的是**进程内存**::

    eco = get_device_ecosystem_summary()
    runtime_cross_repo_activated = eco["total_devices_with_snapshot"] > 0

也就是说,只要同一进程里有人调用过 ``absorb_device_state_snapshot()``,系统就
宣布"真实跨仓证据流已经发生"。实测(改之前)::

    干净进程                        快照数 0 → evidence_gap
    absorb_device_state_snapshot()  快照数 1 → complete      ← 一个假快照就够

后果:**任何一条无关测试的夹具数据都能把治理结论翻成 complete**。CI 分片里正是
如此 —— 同一分片内先跑的测试往 store 里写过快照,自评随即变成 complete,而
``test_final_integrated_audit_verdict.py::TestCrossCheck::
test_I03_cross_repo_evidence_gap_consistent`` 如实报红(两个不同提交、两种不同
分片组成都复现;本地单独跑则通过 —— 典型的顺序依赖)。

这直接违反该模块自己写在文件头的设计原则第 2 条:**"Fail-conservative — never
silently optimistic"**。

## 为什么不是"改测试让它绿"

一开始最省事的做法是让相关测试各自 reset 那个 store。那是**掩盖**:生产侧的
自评仍然可以被任何一次内存写入糊弄,只是 CI 恰好不再撞上而已。真正的问题是
判据本身选错了证据源。

## 修法(所有者在 A/B/C 三条里选的 A)

改为以 ``core.android_participant_evidence_ingress`` 的**落盘产物**为准:它读
Android 侧生成的 ``android_participant_evidence.json``,带 schema 校验(authority
哨兵、契约版本、字段类型)与时效检查(过期视同缺失)。没跑过真实跨仓流程就不可能
凭空出现,具备「证据」应有的可持久、可追溯属性。

判为"已激活"只认 ``ready`` / ``recovered``;``degraded`` / ``unavailable`` /
``missing_evidence`` / ``malformed_evidence`` 一律不算 —— 保守优先。
"""

from __future__ import annotations

import json
import time

import pytest

import core.android_device_state_store as device_state_store
import core.android_participant_evidence_ingress as evidence_ingress
from core.dual_repo_system_completeness_review import (
    CompletenessDimension,
    CompletenessLabel,
    build_completeness_review,
)


def _cross_repo_label() -> CompletenessLabel:
    report = build_completeness_review()
    entry = report.get_dimension(CompletenessDimension.cross_repo_evidence)
    assert entry is not None, "cross_repo_evidence 维度不见了 —— 守卫失效,先修守卫"
    return entry.label


@pytest.fixture(autouse=True)
def clean_device_state_store():
    """跑完把进程内的设备状态存储清干净。

    本文件为了复现问题**必须**往那个全局 store 里写假数据 —— 如果不清理,就等于
    亲手制造这个文件正要消灭的那种跨用例污染。
    """
    yield
    device_state_store.reset_android_device_state_store()


@pytest.fixture
def durable_evidence(tmp_path, monkeypatch):
    """造一份**合法且新鲜**的落盘证据产物,并把 ingress 指向它。

    返回一个 ``write(**overrides)`` 函数,便于按需改字段造出不同状态。
    """
    path = tmp_path / "android_participant_evidence.json"

    def write(**overrides) -> None:
        payload = {
            "authority": evidence_ingress.EXPECTED_AUTHORITY_SENTINEL,
            "schema_version": evidence_ingress.ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION,
            "generated_at": time.time(),
            "is_operational": True,
            "audit_event_count": 3,
            "participant_status": "ready",
        }
        payload.update(overrides)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ANDROID_PARTICIPANT_EVIDENCE_PATH", str(path))
    return write


# ── 核心回归:内存里的假数据不算证据 ────────────────────────────────────


def test_in_memory_snapshot_does_not_prove_cross_repo_flow():
    """**这条是本文件存在的理由。**

    往进程内的设备状态存储塞一个快照(任何测试夹具都能做到),不得让治理自评
    认为"真实跨仓证据流已经发生"。
    """
    before = _cross_repo_label()
    assert before != CompletenessLabel.complete, f"前置条件不成立:干净进程下就已经是 {before},说明环境里有真证据产物"

    device_state_store.absorb_device_state_snapshot(
        "fake-device-from-an-unrelated-test",
        {"snapshot_version": 1, "timestamp": time.time(), "capabilities": []},
    )
    assert (
        device_state_store.get_device_ecosystem_summary().get("total_devices_with_snapshot", 0) > 0
    ), "前置条件不成立:假快照没写进去,这条用例就什么都没验到"

    assert _cross_repo_label() != CompletenessLabel.complete, (
        "一个内存里的假设备快照就把 cross_repo_evidence 翻成了 complete —— " "治理自评又变回 silently optimistic 了"
    )


# ── 正向:真的落盘证据必须仍然被认 ──────────────────────────────────────


def test_durable_ready_evidence_does_prove_cross_repo_flow(durable_evidence):
    """修复不能是"把判据永远改成 False"。

    没有这条,上面那条用一句 ``runtime_cross_repo_activated = False`` 就能通过
    —— 那等于偷偷把这一维**永远**钉死在不完整,和修复不是一回事。
    """
    durable_evidence()

    assert (
        _cross_repo_label() == CompletenessLabel.complete
    ), "存在合法、新鲜、ready 的落盘证据产物时,这一维应当判为 complete"


@pytest.mark.parametrize(
    "overrides,why",
    [
        ({"participant_status": "unavailable", "is_operational": False, "audit_event_count": 0}, "参与方明确不可用"),
        ({"authority": "WRONG_AUTHORITY_SENTINEL"}, "authority 哨兵不匹配 → 产物不可信"),
        ({"schema_version": "0.0.0-not-a-real-version"}, "契约版本不匹配 → 产物不可信"),
        ({"generated_at": 0}, "产物过于陈旧 → 视同缺失"),
    ],
)
def test_evidence_that_is_not_ready_does_not_count(durable_evidence, overrides, why):
    """保守优先:产物存在 ≠ 证据成立。

    不可信(哨兵/版本不对)、已过期、或参与方自陈不可用,都不能算"真实跨仓证据流
    发生过"。
    """
    durable_evidence(**overrides)

    assert _cross_repo_label() != CompletenessLabel.complete, f"{why},却仍被判为 complete"


def test_missing_evidence_artifact_does_not_count(tmp_path, monkeypatch):
    """产物根本不存在时,当然不算。"""
    monkeypatch.setenv("ANDROID_PARTICIPANT_EVIDENCE_PATH", str(tmp_path / "does-not-exist.json"))

    assert _cross_repo_label() != CompletenessLabel.complete


# ── 守卫自检 ────────────────────────────────────────────────────────────


def test_assessment_no_longer_reads_the_in_memory_store():
    """结构层:判据里不该再出现那个内存 store 的读法。

    上面几条都是行为断言 —— 如果哪天有人把内存判据**加回去**并与落盘判据取
    "或",行为断言在有真产物的环境下**依然全绿**,而漏洞已经回来了。这条把
    源码层面钉住。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "dual_repo_system_completeness_review.py").read_text(
        encoding="utf-8"
    )
    # 只看代码,不看注释 —— 注释里如实记录了旧写法,那是有意保留的病历。
    code_lines = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)

    assert "total_devices_with_snapshot" not in code, (
        "cross_repo_evidence 的判据又读回进程内存里的设备快照计数了 —— "
        "那是任何代码路径都能写的瞬时状态,不能当治理证据"
    )
