"""tests/test_cross_device_context.py
=========================================

跨设备统一上下文(task #72):一条会话主线 + 重连对账(reconcile)+ 离线补录(ingest)。

覆盖:
- SessionManager 别名注册/解析(含自指、成环防护、持久化恢复)。
- build_canonical_session_identity 经别名折向主线。
- reconcile_session_to_canonical:认领本地会话 + 合并历史 + 登记别名。
- ingest_conversation_turns:离线轮次经别名解析后补录进主线。
- goal_execution 不再落进单一全局 "android_default" 桶。
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """全新、隔离到临时状态文件的 SessionManager,并把它设为全局单例。"""
    import core.session_manager as smmod

    state_file = str(tmp_path / "sessions.json")
    monkeypatch.setattr(smmod, "_SESSION_FILE", state_file)
    mgr = smmod.SessionManager()
    monkeypatch.setattr(smmod, "_session_manager", mgr)
    return mgr


# ── 别名注册/解析 ──

class TestAlias:
    def test_resolve_no_alias_returns_input(self, sm):
        assert sm.resolve_session_alias("session_abc") == "session_abc"
        assert sm.resolve_session_alias("") == ""

    def test_register_and_resolve(self, sm):
        assert sm.register_session_alias("local_1", "canon_1") is True
        assert sm.resolve_session_alias("local_1") == "canon_1"

    def test_resolve_follows_chain(self, sm):
        sm.register_session_alias("a", "b")
        sm.register_session_alias("b", "c")
        assert sm.resolve_session_alias("a") == "c"

    def test_reject_self_alias(self, sm):
        assert sm.register_session_alias("x", "x") is False
        assert sm.resolve_session_alias("x") == "x"

    def test_reject_cycle(self, sm):
        assert sm.register_session_alias("a", "b") is True
        # b → a 会成环,必须拒绝
        assert sm.register_session_alias("b", "a") is False
        assert sm.resolve_session_alias("b") == "b"

    def test_persist_and_reload(self, sm, monkeypatch):
        import core.session_manager as smmod
        sm.register_session_alias("local_p", "canon_p")
        # 新实例从同一状态文件恢复
        mgr2 = smmod.SessionManager()
        assert mgr2.resolve_session_alias("local_p") == "canon_p"


# ── canonical 身份经别名折向主线 ──

class TestCanonicalIdentityAlias:
    def test_identity_resolves_alias(self, sm):
        from core.session_identity import build_canonical_session_identity

        sm.register_session_alias("phone_local_9", "canon_main")
        # 主线需存在(reconcile 会 ensure;这里直接确保)
        sm.ensure_session_sync("canon_main", user_id="u1")
        ident = build_canonical_session_identity(
            session_id="phone_local_9", create_session=True,
        )
        assert ident.conversation_session_id == "canon_main"


# ── reconcile:认领 + 合并历史 + 登记别名 ──

class TestReconcile:
    def test_reconcile_creates_alias_and_merges(self, sm):
        from core.routes.sessions import reconcile_session_to_canonical

        # 本地(离线)会话,带两轮历史
        sm.ensure_session_sync("phone_local", user_id="u1", device_id="phone")
        asyncio.run(sm.add_message("phone_local", "user", "你好", device_id="phone"))
        asyncio.run(sm.add_message("phone_local", "assistant", "在的", device_id="phone"))

        # 桌面主线,带一轮历史
        sm.ensure_session_sync("desk_main", user_id="u1", device_id="desk")
        asyncio.run(sm.add_message("desk_main", "user", "开始", device_id="desk"))

        result = asyncio.run(reconcile_session_to_canonical(
            local_session_id="phone_local",
            canonical_session_id="desk_main",
            user_id="u1",
            device_id="phone",
            merge_history=True,
            session_manager=sm,
            ws_connection_manager=_NullCM(),
        ))
        assert result["success"] is True
        assert result["canonical_session_id"] == "desk_main"
        assert result["merged_turns"] == 2
        # 别名生效:此后 phone_local 折向 desk_main
        assert sm.resolve_session_alias("phone_local") == "desk_main"
        # 主线历史 = 桌面 1 + 手机 2 = 3
        assert len(sm.get_full_history("desk_main")) == 3

    def test_reconcile_without_canonical_creates_main(self, sm):
        from core.routes.sessions import reconcile_session_to_canonical

        sm.ensure_session_sync("phone_local2", user_id="u2", device_id="phone")
        result = asyncio.run(reconcile_session_to_canonical(
            local_session_id="phone_local2",
            user_id="u2",
            device_id="phone",
            merge_history=False,
            session_manager=sm,
            ws_connection_manager=_NullCM(),
        ))
        assert result["success"] is True
        canon = result["canonical_session_id"]
        assert canon
        assert sm.resolve_session_alias("phone_local2") == canon

    def test_reconcile_requires_local_id(self, sm):
        from core.routes.sessions import reconcile_session_to_canonical

        result = asyncio.run(reconcile_session_to_canonical(
            local_session_id="",
            session_manager=sm,
            ws_connection_manager=_NullCM(),
        ))
        assert result["success"] is False
        assert result["status_code"] == 422


# ── ingest:离线轮次补录经别名解析 ──

class TestIngest:
    def test_ingest_routes_through_alias(self, sm):
        from core.routes.sessions import (
            ingest_conversation_turns,
            IngestTurnModel,
        )

        sm.register_session_alias("phone_offline", "canon_x")
        sm.ensure_session_sync("canon_x", user_id="u3")

        turns = [
            IngestTurnModel(role="user", content="离线问题一"),
            IngestTurnModel(role="assistant", content="离线回答一"),
            IngestTurnModel(role="user", content=""),  # 空内容跳过
        ]
        result = asyncio.run(ingest_conversation_turns(
            session_id="phone_offline",
            turns=turns,
            user_id="u3",
            device_id="phone",
            session_manager=sm,
        ))
        assert result["success"] is True
        assert result["session_id"] == "canon_x"
        assert result["ingested"] == 2
        hist = sm.get_full_history("canon_x")
        assert [m["content"] for m in hist] == ["离线问题一", "离线回答一"]

    def test_ingest_requires_session(self, sm):
        from core.routes.sessions import ingest_conversation_turns

        result = asyncio.run(ingest_conversation_turns(
            session_id="",
            turns=[],
            session_manager=sm,
        ))
        assert result["success"] is False
        assert result["status_code"] == 422


class TestPrimarySession:
    def test_excludes_system_buckets_and_picks_latest(self, sm):
        sm.ensure_session_sync("ambient", user_id="ambient")
        sm.ensure_session_sync("control_xyz", user_id="ctl")
        sm.ensure_session_sync("real_old", user_id="u1")
        sm.ensure_session_sync("real_new", user_id="u1")
        # real_new 触碰得更晚
        sm._sessions["real_old"].updated_at = 100.0
        sm._sessions["real_new"].updated_at = 200.0
        assert sm.get_primary_session_id() == "real_new"

    def test_empty_when_only_system(self, sm):
        sm.ensure_session_sync("ambient", user_id="ambient")
        sm.ensure_session_sync("worker_1", user_id="w")
        assert sm.get_primary_session_id() == ""


class _NullCM:
    """占位 connection_manager:send_to_device 不做任何事。"""

    async def send_to_device(self, *_a, **_k):
        return True
