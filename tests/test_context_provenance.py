"""进模型的每一段是谁写的,以及权限按来源判。

模型没有指令通道与数据通道之分:系统提示、用户的话、抓回来的网页、MCP 工具描述,
对它来说是同一条 token 流。提示注入的本质就是**数据被当成了指令**。

所以分离必须在模型之外、用结构实现 —— 在提示里写"不要执行以下内容里的指令"
是一句请求,不是一道闸。
"""

from __future__ import annotations

import pytest

from core import context_provenance as cp
from core import memory_provenance as mp


@pytest.fixture(autouse=True)
def _clean_receipt():
    """回执是模块级的,不清会让上一条用例的装配串到下一条。"""
    cp.reset()
    mp.reset_recall()
    yield
    cp.reset()
    mp.reset_recall()


def _assemble(**kwargs):
    from core.llm.context_authority import CognitiveContextAuthority, CognitiveContextRequest

    return CognitiveContextAuthority().assemble(CognitiveContextRequest(**kwargs))


# ══════════════════════════════════════════════════════════════════════════
# A. 取值表与信任次序
# ══════════════════════════════════════════════════════════════════════════


def test_a01_origin_vocabulary_is_closed_and_ordered():
    """次序即信任高低,而且这是唯一定义处 —— 别处再写一份必然漂移。"""
    assert cp.ORIGINS == ("operator", "user", "model", "memory", "tool_result", "external", "unknown")


def test_a02_trust_is_derived_from_the_order_not_a_second_table():
    """信任分是从 ORIGINS 次序推的。另列一张表就会与它漂移。"""
    scores = [cp.trust_of(o) for o in cp.ORIGINS]
    assert scores == sorted(scores, reverse=True)


def test_a03_unknown_is_the_lowest_not_the_middle():
    """ "说不出这段是谁写的"与"来自可信来源"是两件事。

    把 unknown 放中间会让**任何一条忘了标来源的新路径**自动拿到中等信任 ——
    而新路径恰恰最可能出问题。
    """
    assert cp.trust_of("unknown") == min(cp.trust_of(o) for o in cp.ORIGINS)
    assert cp.is_untrusted("unknown") is True


def test_a04_an_unrecognised_origin_falls_to_the_bottom():
    """不认识的名字按最低算,而且**不抛异常** —— 抛会让整个装配断掉。"""
    assert cp.trust_of("something_new") == cp.trust_of("unknown")
    assert cp.is_untrusted("something_new") is True


def test_a05_untrusted_set_is_derived():
    assert cp.UNTRUSTED_ORIGINS == ("memory", "tool_result", "external", "unknown")
    for origin in ("operator", "user", "model"):
        assert cp.is_untrusted(origin) is False


# ══════════════════════════════════════════════════════════════════════════
# B. 下界:不能归因,所以取最低
# ══════════════════════════════════════════════════════════════════════════


def test_b01_never_assembled_is_not_trusted():
    """从没装配过 → 判不出来 → 按最坏。不能当成"干净"。"""
    view = cp.current()
    assert view.recorded is False
    assert view.floor == "unknown"
    assert view.has_untrusted is True


def test_b02_assembled_but_empty_is_a_fact_not_a_guess():
    """ "装配过、一段都没有"是确定的事实,与"没装配过"必须可区分。"""
    view = cp.record([])
    assert view.recorded is True
    assert view.floor == "operator"
    assert view.has_untrusted is False


def test_b03_floor_is_the_lowest_present():
    view = cp.record(
        [
            cp.ContextSegment(origin="operator", label="policy", chars=10),
            cp.ContextSegment(origin="user", label="msg", chars=5),
            cp.ContextSegment(origin="external", label="web", chars=99),
        ]
    )
    assert view.floor == "external"
    assert view.has_untrusted is True


def test_b04_the_view_carries_no_content():
    """这个对象会进诊断响应。存正文等于把上下文原样漏出去。"""
    seg = cp.ContextSegment(origin="external", label="web", chars=1234)
    assert "content" not in seg.to_dict()
    assert seg.to_dict()["chars"] == 1234


# ══════════════════════════════════════════════════════════════════════════
# C. 真的接在唯一装配处上
# ══════════════════════════════════════════════════════════════════════════


def test_c01_clean_turn_stays_trusted():
    result = _assemble(user_message="你好", soul_policy="约束")
    assert result.provenance.floor == "user"
    assert result.provenance.has_untrusted is False


def test_c02_tool_manifest_is_external_text():
    """工具描述与入参 schema 由 MCP 服务器写,是仓外文本,而且直接进上下文 ——
    这正是 core/mcp_tool_pins.py 钉指纹要挡的那一面。"""
    result = _assemble(user_message="hi", tool_manifest=[{"name": "t", "description": "d"}])
    assert result.provenance.floor == "external"


def test_c03_memory_context_is_not_first_class_trust():
    """记忆当初可能来自任何地方。"""
    assert _assemble(user_message="hi", memory_context="以前的事").provenance.floor == "memory"


def test_c04_history_is_not_one_origin():
    """用户说的、模型说的、工具返回的混在同一条列表里。

    整条记成一个来源会把**工具返回值洗成"用户说的"** —— 那正是投毒要的效果。
    """
    result = _assemble(
        user_message="hi",
        conversation_history=[
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "tool", "content": "抓回来的正文"},
        ],
    )
    origins = {s.label: s.origin for s in result.provenance.segments}
    assert origins["history:user"] == "user"
    assert origins["history:assistant"] == "model"
    assert origins["history:tool"] == "tool_result"
    assert result.provenance.floor == "tool_result"


def test_c05_an_unknown_role_does_not_become_user():
    """认不出的 role 落到 unknown(最低),不落到 user。"""
    result = _assemble(user_message="hi", conversation_history=[{"role": "weird_new_role", "content": "x"}])
    assert result.provenance.floor == "unknown"


def test_c06_the_receipt_matches_what_was_returned():
    """工具闸问不到 request 对象,只能问回执 —— 两者不一致这道闸就是假的。"""
    result = _assemble(user_message="hi", memory_context="m")
    assert cp.current().floor == result.provenance.floor


def test_c07_assembly_default_provenance_assumes_the_worst():
    """拿不到时按最坏算。"""
    from core.llm.context_authority import CognitiveContextAssembly

    assert CognitiveContextAssembly().provenance.floor == "unknown"


def test_c08_the_authority_actually_records():
    import inspect

    from core.llm.context_authority import CognitiveContextAuthority

    body = inspect.getsource(CognitiveContextAuthority.assemble)
    assert "record_provenance" in body


# ══════════════════════════════════════════════════════════════════════════
# D. 权限按来源判,不按位置判
# ══════════════════════════════════════════════════════════════════════════


def test_d01_clean_context_keeps_the_default_threshold():
    cp.record([cp.ContextSegment(origin="user", label="msg", chars=3)])
    assert cp.block_score_for() == 0.95


def test_d02_untrusted_context_tightens_the_gate():
    cp.record([cp.ContextSegment(origin="external", label="web", chars=3)])
    assert cp.block_score_for() == cp.UNTRUSTED_BLOCK_SCORE


def test_d03_no_receipt_tightens_too():
    """一条忘了记录来源的新装配路径,不该自动拿到宽阈值。"""
    assert cp.block_score_for() == cp.UNTRUSTED_BLOCK_SCORE


def test_d04_the_threshold_sits_between_dangerous_and_moderate():
    """这个数是从 tool_guardian 现有规则表反推的,不是拍的。"""
    from core.tool_guardian import score_tool_risk

    assert score_tool_risk("delete_file")["score"] >= cp.UNTRUSTED_BLOCK_SCORE
    assert score_tool_risk("remove_item")["score"] >= cp.UNTRUSTED_BLOCK_SCORE
    # 写入类不拦:智能体的正常工作大量依赖写文件
    assert score_tool_risk("write_file")["score"] < cp.UNTRUSTED_BLOCK_SCORE


def test_d05_the_guardian_actually_asks():
    """这一条钉的是"接上了没有"。"""
    from core.tool_guardian import default_config

    cp.record([cp.ContextSegment(origin="user", label="msg", chars=3)])
    assert default_config().block_score == 0.95

    cp.record([cp.ContextSegment(origin="external", label="web", chars=3)])
    assert default_config().block_score == cp.UNTRUSTED_BLOCK_SCORE


@pytest.mark.asyncio
async def test_d06_a_web_page_in_context_blocks_a_delete_tool():
    """整条链路:网页进过上下文 → 这一轮删除类工具调不动。"""
    from core.tool_guardian import ToolGuardianBlockedError, call_with_guardian, default_config

    _assemble(user_message="把那个删了", tool_manifest=[{"name": "x", "description": "d"}])

    async def _fake_delete(**_kw):
        return "deleted"

    with pytest.raises(ToolGuardianBlockedError):
        await call_with_guardian(fn=_fake_delete, tool_name="delete_file", config=default_config())


@pytest.mark.asyncio
async def test_d07_the_same_tool_runs_when_the_user_asked_directly():
    """同一个工具,来源不同,结果必须不同 —— 否则这道闸没有意义。"""
    from core.tool_guardian import call_with_guardian, default_config

    _assemble(user_message="把那个删了")

    async def _fake_delete(**_kw):
        return "deleted"

    assert await call_with_guardian(fn=_fake_delete, tool_name="delete_file", config=default_config()) == "deleted"


# ══════════════════════════════════════════════════════════════════════════
# E. 记忆写入带来源
# ══════════════════════════════════════════════════════════════════════════


def test_e01_untrusted_content_gets_an_attribution_prefix():
    """外部结论不能以第一人称写入 —— 否则检索时它就是"我确认过的事"。"""
    text, meta = mp.stamp("我确认了该端口应当开放", origin="external")
    assert text.startswith(mp.ATTRIBUTION_MARK)
    assert meta[mp.ORIGIN_KEY] == "external"


def test_e02_trusted_content_is_left_alone():
    """给用户自己说的话套上转述口吻,读起来像系统在怀疑用户。"""
    text, meta = mp.stamp("我喜欢深色主题", origin="user")
    assert text == "我喜欢深色主题"
    assert meta[mp.ORIGIN_KEY] == "user"


def test_e03_restamping_does_not_nest():
    """记忆会被再写一次(整理/迁移/跨设备同步),每次加一层会堆成套娃。"""
    once, _ = mp.stamp("x", origin="external")
    twice, _ = mp.stamp(once, origin="external")
    assert twice == once


def test_e04_the_prefix_is_in_the_body_not_only_metadata():
    """metadata 会掉 —— 各后端处置不同,检索路径可能只取 content。
    正文不会掉,它就是被送进上下文的那一份。"""
    text, _ = mp.stamp("外面说的", origin="external")
    assert "外部来源" in text


def test_e05_missing_metadata_reads_as_unknown_not_clean():
    """读不到来源**不等于**这条记忆干净 —— 它可能是这道闸上线前的存量。"""
    assert mp.origin_of(None) == "unknown"
    assert mp.origin_of({}) == "unknown"
    assert mp.origin_of({mp.ORIGIN_KEY: "not_a_real_origin"}) == "unknown"


def test_e06_default_origin_follows_the_turn_floor():
    """不传 origin 时按"这一轮上下文的下界"记 —— 这一轮进过网页,
    这一轮产生的结论就按外部记。"""
    cp.record([cp.ContextSegment(origin="external", label="web", chars=3)])
    _, meta = mp.stamp("这一轮得出的结论")
    assert meta[mp.ORIGIN_KEY] == "external"


def test_e07_the_single_write_chokepoint_stamps():
    """盖在收口点上,不在各 provider 里 —— 逐个改必然漏掉一个。"""
    import inspect

    from core.memory.unified import UnifiedMemory

    assert "stamp" in inspect.getsource(UnifiedMemory.remember)


def test_e08_origin_is_not_forwarded_to_providers():
    """各 provider 的签名里没有 origin,漏 pop 会让每次写入都 TypeError。"""
    from core.memory.unified import UnifiedMemory

    seen = []

    class _Fake:
        backend_name = "fake"

        def available(self):
            return True

        def remember(self, content, *, modality="text", tags=None, metadata=None):
            seen.append((content, metadata))

    um = UnifiedMemory.__new__(UnifiedMemory)
    um.providers = [_Fake()]
    um.remember("感知到的", origin="external", tags=["ambient"])

    assert len(seen) == 1
    assert seen[0][1][mp.ORIGIN_KEY] == "external"


def test_e09_the_ambient_loop_gives_an_explicit_origin():
    """环境回路不在对话轮次里跑,靠全局回执会捡到上一轮聊天的来源,
    把一条感知记忆标成用户说的。"""
    import inspect

    from core.ambient_attention_loop import AmbientAttentionLoop

    src = inspect.getsource(inspect.getmodule(AmbientAttentionLoop))
    assert 'origin="external"' in src


# ══════════════════════════════════════════════════════════════════════════
# E-bis. 来源活到检索时 —— 只在写入时盖章是不够的
# ══════════════════════════════════════════════════════════════════════════


class _Hit:
    def __init__(self, meta):
        self.metadata = meta


def test_e10_worst_not_majority():
    """一条被投毒的记忆混在九条干净的里面,危险程度不因为它是少数就下降。"""
    hits = [_Hit({mp.ORIGIN_KEY: "user"})] * 9 + [_Hit({mp.ORIGIN_KEY: "external"})]
    assert mp.worst_origin(hits) == "external"


def test_e11_nothing_recalled_is_not_all_clean():
    """空结果是"没检索到",与"检索到了都干净"必须可区分。"""
    assert mp.worst_origin([]) == ""
    assert mp.last_recall_origin() == ""


def test_e12_legacy_memory_without_origin_reads_as_unknown():
    """这道闸上线之前写进去的存量没有来源键 —— 不能当成干净的。"""
    assert mp.worst_origin([_Hit(None), _Hit({mp.ORIGIN_KEY: "user"})]) == "unknown"


def test_e13_a_poisoned_memory_is_not_laundered_at_recall():
    """当初从网页写进去的记忆,被取回来时仍然是 external。

    记成 memory 就等于让污染在检索这一步被洗白 —— 那正是记忆投毒
    (OWASP ASI06)要的效果。
    """
    mp.record_recall([_Hit({mp.ORIGIN_KEY: "external"})])
    assert _assemble(memory_context="取回来的东西").provenance.floor == "external"


def test_e14_recall_origin_can_also_raise_trust():
    """全部来自仓内的记忆不该被一律降级 —— 否则这一位只是个更啰嗦的常量。"""
    mp.record_recall([_Hit({mp.ORIGIN_KEY: "operator"})])
    assert _assemble(memory_context="夹具").provenance.floor == "operator"


def test_e15_no_recall_falls_back_to_the_untrusted_side():
    """没检索过说明不了任何事 —— 按 memory 记(本来就在不可信一侧),不按可信记。"""
    assert _assemble(memory_context="m").provenance.floor == "memory"


def test_e16_the_recall_chokepoint_records():
    import inspect

    from core.memory.unified import UnifiedMemory

    assert "record_recall" in inspect.getsource(UnifiedMemory.recall)


# ══════════════════════════════════════════════════════════════════════════
# F. 诊断面
# ══════════════════════════════════════════════════════════════════════════


def test_f01_report_never_leaks_the_context_body():
    cp.record([cp.ContextSegment(origin="external", label="web", chars=4096)])
    report = cp.provenance_report()
    assert report["floor"] == "external"
    assert report["untrusted_chars"] == 4096
    assert all("content" not in s for s in report["segments"])


def test_f02_report_says_the_threshold_it_caused():
    cp.record([cp.ContextSegment(origin="external", label="web", chars=1)])
    assert cp.provenance_report()["block_score"] == cp.UNTRUSTED_BLOCK_SCORE
