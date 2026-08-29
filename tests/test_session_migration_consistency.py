"""两条会话迁移路径:它们在哪儿一致,在哪儿本来就是两回事。

为什么先测再选
--------------
路线图的 Q3 问的是"规范的会话迁移路径走 ``session_roaming.py`` 还是
``core/routes/sessions.py``"。在回答之前得先知道两条路**现在到底有什么不同** ——
如果不同只是实现细节,那选哪个都是安全的重构;如果不同是语义上的,那先选后改会
把一种语义悄悄抹掉。

测下来是后者:两条路承载的是**两种不兼容的会话模型**,不是同一件事的两种写法。

==============  ==========================  ==============================
                core/routes/sessions.py     galaxy_gateway/session_roaming
==============  ==========================  ==============================
设备模型        多设备 ``session.devices``  单设备 ``session.device_id``
                + ``active_device``
迁移语义        追加目标,**源设备仍在**     独占转移,旧映射被删
中间态          无                          ``SessionState.MIGRATING``
审计            写 audit ledger             只触发 ``_on_migrated`` 回调
返回            dict(含 history_count)      bool
==============  ==========================  ==============================

"源设备仍在 devices 里"与"旧映射被删"是两种产品行为:前者是**跨设备共享**
(一个会话同时挂在几台设备上,只是当前活跃的是某一台),后者是**漫游**
(会话跟着人走,同一时刻只在一台上)。两个都是合理的东西,但它们不是同一个东西。

这个文件把这些差异钉成事实,让 Q3 的选择有依据 —— 而不是靠读代码猜。

本轮修掉的一个真 bug
--------------------
两条路里有一处差异**不是设计分歧,是错的**:REST 那条原来先改状态再推送,而且
把 ``send_to_device`` 的返回值丢掉了。目标设备没收到会话,函数照样返回
``success: True``,中心侧的 ``active_device`` 已经指向目标并落盘。roaming 那条
一直是两阶段提交。B 组钉的就是这件事。
"""

from __future__ import annotations

import asyncio

import pytest

# ══════════════════════════════════════════════════════════════════════════
# 替身:只记下"谁收到了什么",以及可以让某一次推送失败
# ══════════════════════════════════════════════════════════════════════════


class _FakeConnectionManager:
    def __init__(self, fail_for: str = "") -> None:
        self.sent: list[tuple[str, dict]] = []
        self._fail_for = fail_for

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        self.sent.append((device_id, message))
        return device_id != self._fail_for

    def types_for(self, device_id: str) -> list[str]:
        return [m.get("type") for d, m in self.sent if d == device_id]


class _FakeSession:
    def __init__(self, session_id: str, devices: list[str], active: str) -> None:
        self.session_id = session_id
        self.devices = list(devices)
        self.active_device = active
        self.metadata: dict = {}
        self.updated_at = 0.0


class _FakeSessionManager:
    def __init__(self, session: _FakeSession | None) -> None:
        self._session = session
        self.persisted = 0

    def get_session(self, session_id: str):
        if self._session is not None and self._session.session_id == session_id:
            return self._session
        return None

    def get_full_history(self, session_id: str) -> list:
        return [{"role": "user", "content": "hi"}]

    def _persist_state(self) -> None:
        self.persisted += 1


def _migrate(*, session, cm, target="dev-b", source="", context=None):
    from core.routes.sessions import migrate_session_via_canonical_manager

    return asyncio.run(
        migrate_session_via_canonical_manager(
            session_id="s1",
            target_device=target,
            source_device=source,
            context_override=context,
            session_manager=_FakeSessionManager(session),
            ws_connection_manager=cm,
        )
    )


# ══════════════════════════════════════════════════════════════════════════
# A. 两条路的会话模型确实不同 —— 这是 Q3 要选的东西,不是 bug
# ══════════════════════════════════════════════════════════════════════════


def test_a01_rest_path_keeps_the_source_device_in_the_session():
    """REST 那条是**共享**语义:迁移之后源设备仍在 ``devices`` 里。"""
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    result = _migrate(session=session, cm=_FakeConnectionManager(), source="dev-a")

    assert result["success"] is True
    assert "dev-a" in session.devices, "源设备被移出了 —— 那是漫游语义,不是这条路的语义"
    assert "dev-b" in session.devices
    assert session.active_device == "dev-b"


def test_a02_roaming_path_is_single_device_by_construction():
    """roaming 那条是**漫游**语义:会话只认一个 ``device_id``,没有设备列表。

    钉住这条是因为两边字段名不同很容易被读成"实现差异",而它其实是模型差异 ——
    一个字段装不下多设备。
    """
    from galaxy_gateway.session_roaming import Session as RoamingSession

    fields = set(getattr(RoamingSession, "__dataclass_fields__", {}) or {})
    assert "device_id" in fields
    assert "devices" not in fields, "roaming 的会话若有设备列表,两边的模型差异就不成立了"


def test_a03_the_two_paths_report_differently():
    """一个返回 dict、一个返回 bool。调用方没法用同一段代码消费两者 ——
    这也是"两条路"至今没能收敛的原因之一。"""
    import inspect

    from galaxy_gateway.session_roaming import SessionRoamingManager

    sig = inspect.signature(SessionRoamingManager.migrate_session)
    assert sig.return_annotation is bool


# ══════════════════════════════════════════════════════════════════════════
# B. 推送失败时的行为 —— 这一条不是分歧,是错的,已修
# ══════════════════════════════════════════════════════════════════════════


def test_b01_a_failed_push_is_not_reported_as_a_successful_migration():
    """回归:目标设备没收到会话时,不能报成功。

    改前 ``send_to_device`` 的返回值被丢掉,推送失败照样 ``success: True``。
    后果不是"少了条通知" —— 是中心侧认为会话已经在目标设备上、并且落了盘,
    而用户还在源设备上说话。两边都不对,且没有任何一处会报错。
    """
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    cm = _FakeConnectionManager(fail_for="dev-b")
    result = _migrate(session=session, cm=cm, source="dev-a")

    assert result["success"] is False
    assert result["status_code"] == 502


def test_b02_a_failed_push_leaves_the_session_untouched():
    """报失败还不够 —— 状态不能已经被改掉了。

    这一条比上一条更要紧:``success: False`` 但 ``active_device`` 已经指向目标,
    等于把不一致藏进了一个看起来正确的错误返回里。
    """
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    result = _migrate(session=session, cm=_FakeConnectionManager(fail_for="dev-b"), source="dev-a")

    assert result["success"] is False
    assert session.active_device == "dev-a"
    assert "dev-b" not in session.devices


def test_b03_a_failed_push_is_not_persisted():
    """没发生的迁移不该落盘。"""
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    sm = _FakeSessionManager(session)
    from core.routes.sessions import migrate_session_via_canonical_manager

    asyncio.run(
        migrate_session_via_canonical_manager(
            session_id="s1",
            target_device="dev-b",
            source_device="dev-a",
            session_manager=sm,
            ws_connection_manager=_FakeConnectionManager(fail_for="dev-b"),
        )
    )
    assert sm.persisted == 0


def test_b04_the_source_notification_failing_does_not_undo_the_migration():
    """反过来的一半:源设备收不到"你已经不是 active 了"这条通知,**不算迁移失败**。

    会话本体已经在目标设备上了,源设备不知道只是它自己的显示问题。把这一条也当
    失败会造成更糟的结果:一次已经成功的迁移被报成失败,调用方可能重试。
    """
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    result = _migrate(session=session, cm=_FakeConnectionManager(fail_for="dev-a"), source="dev-a")

    assert result["success"] is True
    assert session.active_device == "dev-b"


def test_b05_the_target_gets_the_session_before_state_flips():
    """两阶段提交的顺序:上下文先送到,状态后改。

    顺序反了的话,推送失败那一刻状态已经改了 —— 就回到了 B02 要防的情况。
    """
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    cm = _FakeConnectionManager()
    _migrate(session=session, cm=cm, source="dev-a")

    assert cm.sent, "什么都没发出去"
    first_device, first_msg = cm.sent[0]
    assert first_device == "dev-b"
    assert first_msg["type"] == "session_sync"


def test_b06_roaming_path_already_rolls_back():
    """roaming 那条本来就有两阶段提交 —— 上面补的是让 REST 那条跟它对齐。

    钉住它是为了防反向回归:有人"统一"两条路时把这边的回滚删掉。
    """
    import inspect

    from galaxy_gateway.session_roaming import SessionRoamingManager

    src = inspect.getsource(SessionRoamingManager.migrate_session)
    assert "original_device_id" in src
    assert "回滚" in src


# ══════════════════════════════════════════════════════════════════════════
# C. 一致的部分 —— 收敛时不能弄丢的东西
# ══════════════════════════════════════════════════════════════════════════


def test_c01_a_missing_session_is_404_not_a_silent_no_op():
    result = _migrate(session=None, cm=_FakeConnectionManager())
    assert result["success"] is False
    assert result["status_code"] == 404


def test_c02_a_source_device_outside_the_session_is_refused():
    """源设备不在会话里 = 调用方对会话的认知是错的。放过去会把一个不相关的
    设备写进 devices。"""
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    result = _migrate(session=session, cm=_FakeConnectionManager(), source="dev-x")
    assert result["success"] is False
    assert result["status_code"] == 409


def test_c03_context_override_is_merged_not_replaced():
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    session.metadata["migration_context"] = {"keep": 1}
    _migrate(session=session, cm=_FakeConnectionManager(), source="dev-a", context={"add": 2})
    assert session.metadata["migration_context"] == {"keep": 1, "add": 2}


@pytest.mark.parametrize("device", ["dev-a", "dev-b"])
def test_c04_both_devices_are_told_on_success(device):
    session = _FakeSession("s1", ["dev-a"], "dev-a")
    cm = _FakeConnectionManager()
    _migrate(session=session, cm=cm, source="dev-a")
    assert cm.types_for(device), f"{device} 一条消息都没收到"


# ══════════════════════════════════════════════════════════════════════════
# D. 会话迁移**没有规范面** —— 所以"合并两个 store"不是现在该做的事
# ══════════════════════════════════════════════════════════════════════════


class TestMigrationHasNoCanonicalHome:
    """``session_roaming`` 已在 ``core/orchestration_authority/legacy_paths.py`` 里
    登记为 LEGACY_COMPATIBILITY,声明的规范替代是
    ``core.canonical_session_axis`` + ``core.attached_runtime_session``。

    问题是**那两处都不提供迁移能力**:

    * ``canonical_session_axis`` 是**分类学** —— 会话族、标识符角色、快照。
      它回答"这个 id 是什么身份",不回答"把会话搬到那台设备上"。
    * ``attached_runtime_session`` 是**挂载生命周期** —— attach/detach 状态机。

    两个模块里 ``def migrate_*`` 命中为 0。全仓真正的迁移实现只有三处
    (REST 的 canonical manager、session_roaming、以及网关路由那层委托),
    **一处也不在规范面上**。

    所以那条退役路径当前走不通,而 recommendation 读起来像"去用规范面就行了"。
    这一组把这件事钉成判据 —— 它比"合并两个 store"更要紧:在没有目标形态的情况下
    合并,合出来的东西仍然不是规范面,只是第三个。
    """

    def test_d01_the_legacy_registration_names_a_replacement(self):
        from core.orchestration_authority import legacy_paths

        src = legacy_paths.__file__
        body = open(src, encoding="utf-8").read()
        assert "session_roaming" in body
        assert "canonical_session_axis" in body

    def test_d02_the_named_replacement_does_not_migrate(self):
        """规范替代里没有迁移能力 —— 这是整条退役路径走不通的原因。

        这条会在有人真的把迁移建到规范面上的那天变红,那正是它该响的时候。
        """
        import inspect

        from core import attached_runtime_session, canonical_session_axis

        for mod in (canonical_session_axis, attached_runtime_session):
            names = [n for n in dir(mod) if n.startswith("migrate")]
            assert not names, f"{mod.__name__} 现在有迁移能力了 —— 退役路径可以往前走了,请更新这条判据"
            assert "def migrate_" not in inspect.getsource(mod)

    def test_d03_the_only_migration_implementations_are_the_two_known_ones(self):
        """全仓的迁移实现就这两个真实现(第三处是网关路由层的委托)。

        多出第三个真实现时这条会红 —— 那意味着又有人在别处开了一条迁移路,
        而这正是 Q3 当初要防的。
        """
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(
            ["grep", "-rn", "--include=*.py", "-E", r"^\s*(async )?def migrate_session", "core", "galaxy_gateway"],
            cwd=root,
            capture_output=True,
            text=True,
        ).stdout
        files = {line.split(":")[0] for line in out.splitlines() if line.strip()}
        assert files == {
            "core/routes/sessions.py",
            "galaxy_gateway/session_roaming.py",
            "galaxy_gateway/routes/sessions.py",
        }, f"迁移实现的分布变了: {sorted(files)}"
