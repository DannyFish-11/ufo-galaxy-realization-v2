"""记忆的根 —— 新对话必须接到已有的那条记忆上,而不是每次自成一套。

背景在 core/memory_thread.py 的模块头:这个仓库的记忆分六层,五层已经连续,
只有对话那一层不是 —— 每开一次新对话就自成一根,和别的 AI 产品一样。血缘字段
(parent_id / root_id / branch_label / forked_from_chunk)早就在且落盘,
fork_session() 也写好了,缺的只有一条「什么时候算接着上次」的判据。

这份测试按要紧程度排:

1. **四个构造点每一个都真的接上了。** SessionManager 里有四处在 Session(...),
   判据漏掉任何一处,表现都是「有些对话接上了、有些没接上」—— 没人会立刻发现。
   这一组排第一,而且四条分开写,不合并:合并之后一条挂了看不出是哪一处。
2. 认不出人的时候**不硬接**,而且这一档要与「没有上一条」分得开。
3. 血缘活得过重启。
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from core import session_manager as sm_mod
from core.memory_thread import (
    BASIS_MEANS,
    MEMORY_THREAD_AUTHORITY,
    THREAD_BASES,
    ThreadDecision,
    is_identifying_owner,
    resolve_thread,
)
from core.session_manager import Session, SessionManager


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """一个落盘位置隔离的 SessionManager —— 不碰开发机上的真实会话文件。"""
    monkeypatch.setattr(sm_mod, "_SESSION_FILE", str(tmp_path / "sessions.json"))
    return SessionManager()


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════════════
# 一、四个构造点 —— 每一个单独钉
# ══════════════════════════════════════════════════════════════════════════


def test_construction_point_1_create_session(sm):
    """异步 create_session → _create_session_locked。"""
    first = _run(sm.create_session("alice", "dev1"))
    second = _run(sm.create_session("alice", "dev1"))
    assert second.root_id == first.root_id, "第二次 create_session 没接上第一条"
    assert second.parent_id == first.id
    assert second.metadata["memory_thread_basis"] == "continued"


def test_construction_point_2_ensure_session_async(sm):
    """异步 ensure_session —— **这是「用户开了个新对话」的主路径**。

    面板/客户端生成一个新的 conversation id 打进来,走的就是这条。改造之前它
    每次都自成一根,于是「每一个对话历史都是新开的」。
    """
    first = _run(sm.create_session("bob", "dev1"))
    nxt = _run(sm.ensure_session("session_brand_new", user_id="bob"))
    assert nxt.root_id == first.root_id, "新对话没接上 —— 主路径漏了"
    assert nxt.parent_id == first.id
    assert nxt.metadata["memory_thread_basis"] == "continued"


def test_construction_point_3_ensure_session_sync(sm):
    """同步 ensure_session_sync —— build_canonical_session_identity 走这条。"""
    first = sm.get_or_create_session_sync("carol", "dev1")
    nxt = sm.ensure_session_sync("session_sync_new", user_id="carol")
    assert nxt.root_id == first.root_id
    assert nxt.parent_id == first.id
    assert nxt.metadata["memory_thread_basis"] == "continued"


def test_construction_point_4_get_or_create_session_sync(sm):
    """同步 get_or_create_session_sync 的**创建**分支。

    平时它命中活跃会话直接返回;只有活跃映射指向一条**已经不在** ``_sessions``
    里的会话时才走到构造 —— 也就是会话被淘汰之后的那一刻。用这个真实场景验它。
    """
    first = sm.get_or_create_session_sync("dave", "dev1")
    # 模拟淘汰:会话对象没了,活跃映射还指着它
    sm._sessions.pop(first.id)

    made = sm.get_or_create_session_sync("dave", "dev1")
    assert made.id != first.id, "应该走到构造分支"
    assert made.root_id == first.root_id, "会话被淘汰之后记忆就断了"
    assert made.metadata["memory_thread_basis"] == "continued_root_only"
    assert made.parent_id == "", "上一条已经不在了,链上就该少这一环,不能编一个出来"


def test_root_survives_session_eviction_but_says_the_chain_is_broken(sm):
    """根记得住,链断了一环 —— 两件事要能分开。

    SessionManager 现在**不淘汰会话**:MAX_SESSIONS = 100 声明在那儿,全仓没有
    任何地方执行它。所以这一档平时不该出现。但那个意图摆着,哪天有人真去实现
    淘汰,没有这条兜底的话记忆会在那一刻无声地断回一堆岛,而且什么都不会报错。
    """
    a = sm.get_or_create_session_sync("heidi", "dev1")
    sm._sessions.pop(a.id)
    b = sm.ensure_session_sync("conv_after_evict", user_id="heidi")

    assert b.root_id == a.root_id
    assert b.metadata["memory_thread_basis"] == "continued_root_only"
    # 与「链完整」明确不同档:BASIS_MEANS 里两条话不一样,人看得出少了什么。
    assert BASIS_MEANS["continued_root_only"] != BASIS_MEANS["continued"]


def test_remembered_root_survives_a_restart(tmp_path, monkeypatch):
    """owner→根 这张表也要落盘,否则重启一次兜底就没了。"""
    monkeypatch.setattr(sm_mod, "_SESSION_FILE", str(tmp_path / "s.json"))
    first = SessionManager()
    a = first.get_or_create_session_sync("ivan", "dev1")

    revived = SessionManager()
    revived._sessions.pop(a.id)  # 重启 + 淘汰
    b = revived.ensure_session_sync("after", user_id="ivan")
    assert b.root_id == a.root_id
    assert b.metadata["memory_thread_basis"] == "continued_root_only"


def test_all_four_points_go_through_one_authority():
    """四处都得调 _apply_thread —— 判据只能有一份。

    这一条查的是源码本身:构造点旁边没有 _apply_thread 就是漏了,而漏掉的那处
    在运行时只表现为「这类对话接不上」,单看行为不容易归因到具体哪一处。
    """
    src = open(sm_mod.__file__, encoding="utf-8").read()
    assert src.count("self._apply_thread(") == 4, "Session 构造点与 _apply_thread 调用数对不上"
    assert src.count("Session(\n") >= 4


# ══════════════════════════════════════════════════════════════════════════
# 二、连成一条线
# ══════════════════════════════════════════════════════════════════════════


def test_three_separate_conversations_are_one_memory(sm):
    """这就是整件事要的效果。"""
    a = _run(sm.create_session("erin", "dev1"))
    b = _run(sm.ensure_session("conv_2", user_id="erin"))
    c = _run(sm.ensure_session("conv_3", user_id="erin"))

    assert a.root_id == b.root_id == c.root_id
    thread = sm.sessions_in_thread(a.root_id)
    assert [s.id for s in thread] == [a.id, b.id, c.id], "线上的会话要按时间升序"
    assert sm.thread_root_of(c.id) == a.root_id


def test_thread_root_of_unknown_returns_empty_not_itself(sm):
    """查不到返回空串,**不是**返回它自己 —— 「不知道」与「它自成一根」是两回事。

    混掉的话,面板拿一个查错的 id 会画出一条并不存在的新线。
    """
    assert sm.thread_root_of("no_such_session") == ""
    assert sm.sessions_in_thread("") == []


# ══════════════════════════════════════════════════════════════════════════
# 三、认不出人的时候不硬接
# ══════════════════════════════════════════════════════════════════════════


def test_synthetic_session_owner_never_joins_anything(sm):
    """owner 是拿会话自己的 id 现编的(session::<id>),它不标识任何人。

    用它接线的话,判据看起来一直在工作(每次都「新建一根」),实际上从来没有
    能力接上任何东西 —— 正是本仓反复栽的那个坑。
    """
    x = _run(sm.ensure_session("s1"))  # 无 user_id → owner = session::s1
    y = _run(sm.ensure_session("s2"))
    assert x.user_id.startswith("session::")
    assert x.root_id != y.root_id, "认不出人却硬接上了"
    assert x.metadata["memory_thread_basis"] == "owner_not_identifying"


def test_owner_not_identifying_is_distinct_from_no_prior():
    """两档要分开:前者是「这条路根本没有身份可依」,后者是「这确实是第一条」。

    要人做的事不同,混成一档就看不出该去修哪个。
    """
    a = resolve_thread("session::abc", None)
    b = resolve_thread("alice", None)
    assert a.basis == "owner_not_identifying"
    assert b.basis == "no_prior"
    assert BASIS_MEANS[a.basis] != BASIS_MEANS[b.basis]


def test_device_owner_still_counts_as_identity():
    """device::<id> 认不出人但认得出设备 —— 是当前拿得到的最好身份,可以接。"""
    assert is_identifying_owner("device::abc") is True
    assert is_identifying_owner("session::abc") is False
    assert is_identifying_owner("") is False


# ══════════════════════════════════════════════════════════════════════════
# 四、判据本身(纯函数)
# ══════════════════════════════════════════════════════════════════════════


def test_explicit_new_root_wins_over_everything():
    prev = Session(id="prev", user_id="alice")
    d = resolve_thread("alice", prev, new_root=True)
    assert d.basis == "new_root_requested"
    assert d.root_id == "" and d.parent_id == ""


def test_broken_previous_session_does_not_produce_an_empty_root():
    """上一条残缺时另起一根 —— 挂到空根上会把后来每一条都吸进去。"""

    class _Broken:
        id = ""
        root_id = ""

    d = resolve_thread("alice", _Broken())
    assert d.basis == "no_prior"
    assert d.root_id == ""


def test_previous_without_root_id_falls_back_to_its_own_id():
    class _Old:
        id = "old_session"
        root_id = ""

    d = resolve_thread("alice", _Old())
    assert d.basis == "continued"
    assert d.root_id == "old_session"


def test_a_session_is_never_its_own_previous(sm):
    """自己不能当自己的上一条 —— 那会造出一个自指的 parent_id。"""
    s = sm.get_or_create_session_sync("frank", "dev1")
    sm._apply_thread(s, "frank")
    assert s.parent_id != s.id
    assert s.root_id == s.id


@pytest.mark.parametrize("basis", THREAD_BASES)
def test_every_basis_has_a_meaning(basis):
    assert basis in BASIS_MEANS and BASIS_MEANS[basis].strip()


def test_decision_records_authority_in_metadata():
    d = ThreadDecision(root_id="r", parent_id="p", basis="continued")
    meta = d.to_metadata()
    assert meta["memory_thread_authority"] == MEMORY_THREAD_AUTHORITY
    assert meta["memory_thread_root"] == "r"
    assert d.continued is True


# ══════════════════════════════════════════════════════════════════════════
# 五、活得过重启
# ══════════════════════════════════════════════════════════════════════════


def test_lineage_survives_a_restart(tmp_path, monkeypatch):
    """血缘落盘并读得回来 —— 否则重启一次,记忆又断成岛。"""
    state = str(tmp_path / "sessions.json")
    monkeypatch.setattr(sm_mod, "_SESSION_FILE", state)

    first = SessionManager()
    a = _run(first.create_session("grace", "dev1"))
    b = _run(first.ensure_session("conv_after", user_id="grace"))
    assert a.root_id == b.root_id

    assert os.path.exists(state)
    raw = json.loads(open(state, encoding="utf-8").read())
    assert raw["sessions"][b.id]["root_id"] == a.root_id

    revived = SessionManager()
    assert revived.thread_root_of(b.id) == a.root_id
    assert len(revived.sessions_in_thread(a.root_id)) == 2

    # basis 与 parent 也要活过重启 —— /api/v1/memory/thread 读的就是 metadata 里
    # 那一位,它掉了的话端点会把每条会话都报成 "unrecorded"。
    survived = revived.get_session(b.id)
    assert survived is not None
    assert survived.parent_id == a.id
    assert (survived.metadata or {}).get("memory_thread_basis") == "continued"

    # 重启之后再开一条,仍然接在同一条线上。
    c = _run(revived.ensure_session("conv_after_restart", user_id="grace"))
    assert c.root_id == a.root_id, "重启之后接不上 —— 记忆还是断的"


def test_thread_root_table_does_not_grow_for_anonymous_sessions(sm):
    """``session::<id>`` 那类 owner 每个会话一个、永远不会被第二条会话复用。

    给它们记根的话,那张表会随匿名会话数无界增长,而且记下的每一条都永远用不上。
    """
    for i in range(5):
        _run(sm.ensure_session(f"anon_{i}"))
    assert sm._user_thread_root == {}, f"给合成 owner 记了根: {sm._user_thread_root}"

    # 认得出人的照记不误
    _run(sm.create_session("judy", "dev1"))
    assert "judy" in sm._user_thread_root


def test_apply_thread_survives_a_manager_built_without_init():
    """绕过 ``__init__`` 造出来的 SessionManager 也必须能用。

    本类存在这样的构造路径:``tests/test_cp_phase4.py`` 里的
    ``SessionManager.__new__(SessionManager)`` 只手工设它当时知道的几个字段。

    这条是回归防护,不是洁癖:加 ``_user_thread_root`` 那一版直接
    ``self._user_thread_root.get(...)``,于是四个构造点全部对这个新属性产生硬依赖,
    CI 上 test_cp_phase4 的四条会话迁移用例当场 AttributeError。报错看起来像那些
    调用点的错,其实是**加属性的人**的错 —— 既有调用点不可能知道要设一个还不存在
    的字段。

    所以 _apply_thread 一律 getattr 取状态。下一次再加实例属性时,这条会替他挡住。
    """
    bare = SessionManager.__new__(SessionManager)
    bare._sessions = {}
    bare._user_active_session = {}
    bare._persist_state = lambda: None  # type: ignore[assignment]
    # 刻意**不设** _user_thread_root —— 模拟"加属性之前写的那些构造点"

    s = Session(id="s_bare", user_id="kate")
    bare._apply_thread(s, "kate")
    assert s.root_id == "s_bare"
    assert s.metadata["memory_thread_basis"] == "no_prior"

    # 而且它会把表懒建出来,接着第二条就能接上
    s2 = Session(id="s_bare_2", user_id="kate")
    bare._sessions[s.id] = s
    bare._user_active_session["kate"] = s.id
    bare._apply_thread(s2, "kate")
    assert s2.root_id == s.root_id
    assert s2.metadata["memory_thread_basis"] == "continued"
