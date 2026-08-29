"""按作用域分权威:本地的事本地说了算,跨设备的事中心说了算。

这个文件钉的是什么
------------------
"Android 本地状态以谁为准"(路线图 Q4)一直被写成三选一:V2 权威 / Android 权威 /
显式双向同步。三个答案都不对 —— 它们都假设**权威是全局属性**。

同一台设备,单机跑一件事时中心根本不在场(要求"以中心为准"等于让离线设备等一个
不会来的答复,而 OfflineTaskQueue 的存在说明单机是正常形态);在编队里跨设备执行时,
真值链/幂等/受理裁决整套判据都在 V2 侧(让 Android 权威等于把这套判据再搬一份过去,
也就是第二份定义)。

所以权威跟着**作用域**走。这里钉四件事:

A. 四个作用域各判给谁,以及两种迁移语义的分配;
B. "判不出来"不许变成"本地",但迁移那一格降级而不是拒绝 —— 这处**不对称**是这套
   设计里最容易被"顺手统一"掉的地方;
C. transition 沿用上一档,沿用不了就是判不出来;
D. 权威易手留痕。
"""

from __future__ import annotations

import pytest

from core import scope_authority as sa


@pytest.fixture(autouse=True)
def _clean():
    sa.clear_registry()
    yield
    sa.clear_registry()


# ══════════════════════════════════════════════════════════════════════════
# A. 四个作用域各判给谁
# ══════════════════════════════════════════════════════════════════════════


def test_a01_local_scope_is_locally_authoritative():
    v = sa.authority_for("local")
    assert v.authority == "local"
    assert v.accepts_local_writes is True


def test_a02_cross_device_scope_is_center_authoritative():
    v = sa.authority_for("cross_device")
    assert v.authority == "center"
    assert v.accepts_local_writes is False


def test_a03_local_migrates_by_roaming():
    """单机场景要的是"会话跟着人走" —— 源设备移出。"""
    assert sa.authority_for("local").migration == "roaming"


def test_a04_cross_device_migrates_by_sharing():
    """编队场景要的是"几台一起做一件事" —— 源设备保留。"""
    assert sa.authority_for("cross_device").migration == "shared"


def test_a05_the_two_semantics_are_the_only_non_refusing_ones():
    """迁移语义只有这三种取值。多出一种就意味着有人在别处又定义了一遍。"""
    assert set(sa.MIGRATION_SEMANTICS) == {"roaming", "shared", "refused"}


# ══════════════════════════════════════════════════════════════════════════
# B. 判不出来:权威说不出来,但迁移降级而不是拒绝
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("bad", [None, "", "garbage", 42, object()])
def test_b01_unreadable_scope_is_undecidable_not_local(bad):
    """最要紧的一条:判不出来时权威是"说不出来",**不是**"默认本地"。

    静默判成 local 的后果:连接刚抖动、编队刚建立、注册表还没同步 —— 正是这些
    最需要中心仲裁的时刻,权威被自动交给了本地,而且没有任何一处会显示这件事。
    """
    v = sa.authority_for(bad)
    assert v.authority == "undecidable"
    assert v.decided is False
    assert v.accepts_local_writes is False


def test_b02_undecidable_still_allows_migration_but_degraded():
    """迁移那一格**故意**不跟着拒绝。

    作用域判不出来是**常态之一**:没有桌面在场运行时的纯服务端部署里,连续体根本
    不跑,runtime_domain 本来就没值。在一个常态上装拒绝 = 把会话迁移整个关掉。
    """
    v = sa.authority_for(None)
    assert v.may_migrate is True
    assert v.migration == sa.DEGRADED_MIGRATION


def test_b03_the_degraded_semantics_is_the_non_destructive_one():
    """降级要挑不丢东西的那一档。

    漫游会把源设备移出会话(破坏性),共享保留源设备(非破坏性)。判不出来时
    选错方向的代价是**会话从一台设备上消失**,而且没人知道为什么。
    """
    assert sa.DEGRADED_MIGRATION == "shared"
    assert sa.authority_for("cross_device").migration == sa.DEGRADED_MIGRATION


def test_b04_a_degraded_semantics_is_marked_as_such():
    """降级留痕:降级来的语义与判出来的语义必须能分开。

    不标的话,报告里"migration=shared"看起来和真判出跨设备一模一样。
    """
    assert sa.authority_for(None).migration_degraded is True
    assert sa.authority_for("cross_device").migration_degraded is False


def test_b05_the_report_says_plainly_what_undecidable_means():
    report = sa.authority_report()
    assert "不是默认本地" in report["undecidable_means"]


# ══════════════════════════════════════════════════════════════════════════
# C. transition:沿用上一档,沿用不了就说沿用不了
# ══════════════════════════════════════════════════════════════════════════


def test_c01_transition_refuses_migration_for_real():
    """这一格是**真拒绝**,不是降级。

    与 null 不同:transition 的含义是"正在决定要不要扩到跨设备",迁移撞进一个
    正在建立的编队是真实的危险;而且这一档是短暂的 —— 拒绝一次,等它定下来再迁。
    """
    sa.record_scope("s1", "local")
    v = sa.authority_for_session("s1", "transition")
    assert v.migration == "refused"
    assert v.may_migrate is False
    assert v.migration_degraded is False


def test_c02_transition_carries_the_previous_authority():
    sa.authority_for_session("s1", "cross_device")
    v = sa.authority_for_session("s1", "transition")
    assert v.authority == "center"
    assert v.carried_from == "cross_device"


def test_c03_transition_without_a_settled_scope_is_undecidable():
    """第一次见到这个会话就是 transition —— 沿用不了一个从来不存在的东西。

    这一条挡的是"沿用不到就默认 local"那种写法。
    """
    v = sa.authority_for_session("never-seen", "transition")
    assert v.authority == "undecidable"
    assert v.carried_from == ""


def test_c04_transition_does_not_overwrite_the_settled_scope():
    """一次短暂的过渡不能把"之前是哪一档"擦掉,否则沿用就没了依据。"""
    sa.record_scope("s1", "cross_device")
    sa.record_scope("s1", "transition")
    sa.record_scope("s1", None)
    assert sa.settled_scope("s1") == "cross_device"


def test_c05_require_migration_raises_rather_than_returning_false():
    """迁移是**有副作用的动作**:返回值会被忽略,异常不会。

    漏判一次的后果是会话跑到不该去的地方。
    """
    sa.record_scope("s1", "local")
    with pytest.raises(sa.ScopeAuthorityRefused):
        sa.require_migration("s1", "transition")


# ══════════════════════════════════════════════════════════════════════════
# D. 权威易手留痕
# ══════════════════════════════════════════════════════════════════════════


def test_d01_a_scope_flip_is_recorded():
    """一个会话从 local 变 cross_device 的那一刻权威换了人。不记下来,事后就没有
    任何一处能回答"那次冲突发生时谁说了算" —— 而冲突最常发生在交接前后。"""
    sa.record_scope("s1", "local")
    handover = sa.record_scope("s1", "cross_device")
    assert handover is not None
    assert (handover.previous, handover.current) == ("local", "cross_device")
    assert (handover.previous_authority, handover.current_authority) == ("local", "center")


def test_d02_no_flip_no_record():
    """同一档重复上报不算交接 —— 否则账本会被心跳刷满,真交接被淹掉。"""
    sa.record_scope("s1", "local")
    assert sa.record_scope("s1", "local") is None
    assert sa.recent_handovers() == []


def test_d03_the_first_sighting_is_not_a_handover():
    """第一次见到一个会话不是"易手",是"上手"。"""
    assert sa.record_scope("fresh", "cross_device") is None


def test_d04_the_ledger_is_bounded():
    """无界的账本本身就是一次内存泄漏。"""
    for i in range(sa.HANDOVER_LEDGER_MAX + 40):
        sa.record_scope("s1", "local" if i % 2 else "cross_device")
    assert len(sa.recent_handovers(sa.HANDOVER_LEDGER_MAX * 2)) == sa.HANDOVER_LEDGER_MAX


def test_d05_handovers_reach_the_report():
    sa.record_scope("s1", "local")
    sa.record_scope("s1", "cross_device")
    assert sa.authority_report()["handovers_recorded"] == 1


# ══════════════════════════════════════════════════════════════════════════
# E. 真的接在了那两个决策点上 —— 否则就是"看起来接上了,其实没有"
# ══════════════════════════════════════════════════════════════════════════


def test_e01_the_migration_entrypoint_asks_the_judgement():
    import inspect

    from core.routes.sessions import migrate_session_via_canonical_manager

    body = inspect.getsource(migrate_session_via_canonical_manager)
    # 要的是 require_migration(会抛)而不是"取判定再自己看一眼"(返回值会被忽略)。
    assert "require_migration" in body
    assert "roaming" in body, "迁移入口没有按语义分支,那作用域判了也没用"


def test_e02_the_android_reconciliation_ack_carries_the_verdict():
    """Q4 的 V2 那一半:设备要能从 ACK 里知道"此刻我说了不算"。

    这是 Android 切到 delta 模式的依据。老客户端忽略未知字段,向后兼容。
    """
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "galaxy_gateway/android/handlers/reconciliation_signal.py"
    body = src.read_text(encoding="utf-8")
    assert '"scope_authority"' in body
    assert "accepts_local_writes" in body


def test_e03_the_axis_it_stands_on_is_the_existing_one():
    """作用域取值必须来自 RuntimeDomain,不是这里另攒一份。

    另攒一份的表现是:加一档时漏改一处,而两处都不认为自己错了。
    """
    from core.continuum.types import RuntimeDomain

    for domain in RuntimeDomain:
        assert sa.authority_for(domain.value).scope == domain.value


def test_e04_the_diagnostics_endpoint_exists():
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "core/routes/diagnostics.py"
    assert "/api/v1/runtime/scope-authority" in src.read_text(encoding="utf-8")
