"""焦点栈 —— 契约测试
=======================

要验的是**一段真实对话的形状**,而不是几个孤立方法。所以主用例直接把开头那段
"整理报告 → 插进来看消息 → 行了继续"跑一遍,断言栈在每一步的形状。

其余用例分两类:结构不变量(栈深、淘汰顺序、恢复而非新建),以及"什么时候**不该**
往上下文里塞东西"——后者同样重要,焦点栈每输出一行就占掉一行上下文窗口。
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def _fresh():
    from core.focus_stack import reset_focus_stacks

    reset_focus_stacks()
    yield
    reset_focus_stacks()


@pytest.fixture()
def stack():
    from core.focus_stack import FocusStack

    return FocusStack()


class TestRealConversationShape:
    def test_interrupt_then_resume(self, stack):
        """整理报告 → 插进来看消息 → "行了继续" → 该回到报告。"""
        r1 = stack.observe("帮我把季度报告整理一下")
        assert r1["action"] == "opened"
        assert stack.depth() == 1

        r2 = stack.observe("等一下,先看看老王刚发的那条消息")
        assert r2["action"] == "opened"
        assert stack.depth() == 2
        assert "老王" in stack.current.topic

        # 还在处理消息这件事(共享"老王""消息")
        r3 = stack.observe("老王那条消息先回一句收到")
        assert r3["action"] == "continued"
        assert stack.depth() == 2

        # 纯延续句 —— 依附当前焦点,不新建
        r4 = stack.observe("继续")
        assert r4["action"] == "continued"
        assert stack.depth() == 2

        # 显式回到报告:词法足够像挂起项 → 恢复,而不是开第三件事
        r5 = stack.observe("回到季度报告,把整理的部分接着做")
        assert r5["action"] == "resumed"
        assert stack.depth() == 2, "恢复不该增加栈深"
        assert "报告" in stack.current.topic

    def test_context_message_lists_suspended_items(self, stack):
        stack.observe("帮我把季度报告整理一下")
        stack.observe("等一下,先看看老王刚发的那条消息")

        msg = stack.as_context_message()
        assert msg is not None
        assert "当前焦点" in msg["content"]
        assert "老王" in msg["content"]
        assert "被搁置" in msg["content"]
        assert "报告" in msg["content"]


class TestWhenNotToEmit:
    """焦点栈每输出一行就占一行上下文窗口,没结构可讲时必须闭嘴。"""

    def test_empty_stack_emits_nothing(self, stack):
        assert stack.as_context_message() is None

    def test_single_fresh_focus_emits_nothing(self, stack):
        """只有一件事、才刚开始 —— 轮次历史里已经有了,复述是纯噪声。"""
        stack.observe("帮我把季度报告整理一下")
        assert stack.as_context_message() is None

    def test_single_focus_emits_once_it_has_history(self, stack):
        """同一件事谈了几轮之后就值得点明了 —— 它已经不在最近几轮的表面上。"""
        stack.observe("帮我把季度报告整理一下")
        stack.observe("报告里的营收部分重新算一下")
        assert stack.as_context_message() is not None

    def test_disabled_switch(self, stack, monkeypatch):
        monkeypatch.setenv("GALAXY_FOCUS_STACK_ENABLED", "0")
        assert stack.observe("帮我把季度报告整理一下")["action"] == "ignored"
        assert stack.depth() == 0


class TestEdgeCases:
    def test_continuation_without_any_focus_is_ignored(self, stack):
        """开场就说"继续"—— 没什么可继续的,也不该开一个题为"继续"的焦点。"""
        result = stack.observe("继续")
        assert result["action"] == "ignored"
        assert stack.depth() == 0

    def test_blank_input_ignored(self, stack):
        assert stack.observe("   ")["action"] == "ignored"
        assert stack.depth() == 0

    def test_depth_cap_evicts_the_stalest_suspended_item(self, stack, monkeypatch):
        """超深时丢**最陈旧的挂起项**,不是最早入栈的。

        按入栈顺序丢会把"很早开始、但一直在做"的那件事丢掉 —— 那恰恰最不该丢。
        """
        monkeypatch.setenv("GALAXY_FOCUS_MAX_DEPTH", "3")

        stack.observe("帮我把季度报告整理一下")
        oldest = stack.current
        stack.observe("服务器磁盘快满了扩一下容")
        stalest = stack.current
        stack.observe("下周去上海的机票帮我改签")
        # 回头碰一下最早那件 —— 它就不再是最陈旧的了
        stack.observe("季度报告整理得怎么样了")
        assert stack.current is oldest

        stack.observe("上个月的报销单据帮我审批")
        assert stack.depth() == 3
        topics = [f.topic for f in stack.suspended] + [stack.current.topic]
        assert oldest.topic in topics, "一直在做的那件事被错误淘汰了"
        assert stalest.topic not in topics, "该淘汰的是最久没碰的那件"

    def test_stale_suspended_items_are_evicted(self, stack, monkeypatch):
        stack.observe("帮我把季度报告整理一下")
        stack.observe("服务器磁盘快满了扩一下容")
        assert stack.depth() == 2

        monkeypatch.setenv("GALAXY_FOCUS_STALE_S", "0.01")
        time.sleep(0.02)
        stack.observe("下周去上海的机票帮我改签")

        # 挂起的那件已经陈旧掉出;当前焦点在观察时被换成新的一件。
        assert stack.depth() <= 2
        assert "报告" not in " ".join(f.topic for f in stack.suspended)

    def test_current_focus_is_never_evicted_for_staleness(self, stack, monkeypatch):
        """当前焦点不因"想久了"而消失 —— 它是正在做的事。"""
        stack.observe("帮我把季度报告整理一下")
        monkeypatch.setenv("GALAXY_FOCUS_STALE_S", "0.01")
        time.sleep(0.02)

        stack._evict_stale()
        assert stack.depth() == 1

    def test_drop_current_restores_previous(self, stack):
        stack.observe("帮我把季度报告整理一下")
        stack.observe("服务器磁盘快满了扩一下容")

        stack.drop_current()
        assert stack.depth() == 1
        assert "报告" in stack.current.topic

    def test_unrelated_topic_opens_rather_than_resumes(self, stack):
        """不像任何挂起项就该新开 —— 恢复的门槛比"同题"更高。"""
        stack.observe("帮我把季度报告整理一下")
        stack.observe("看看老王发的消息")
        result = stack.observe("今天北京的天气预报是什么")
        assert result["action"] == "opened"
        assert stack.depth() == 3


class TestKnownLexicalLimits:
    """如实记录纯词法判定够不到的地方 —— 不掩盖,也不为了让它过而去调阈值。

    调阈值到刚好让某一句手写例句通过,得到的是一个没有含义的数字:它会在别的
    句子上以同样不可预测的方式判错,而且没人知道为什么是那个数。所以这里把
    限制**写成断言**:行为一旦变了(不管变好变坏),这条用例都会提醒有人来看。
    """

    def test_anaphora_and_synonyms_are_not_understood(self, stack):
        """用代词/别称指代同一件事时,词法认不出来,会开一个新焦点。

        "那份文件弄好了吗"说的就是刚才那份季度报告,但两句一个共同的词都没有。
        要认出来就得引入语义模型,而这条路径要在**每一轮用户发言**上跑。

        代价是有界的:栈里多一个条目,栈深有上限、陈旧会被淘汰、上下文里多一行。
        **不会**导致错误行为 —— 延续句("继续")依附的始终是当前焦点,不会因为
        多了一个条目就接错事情。
        """
        stack.observe("帮我把季度报告整理一下")
        result = stack.observe("那份文件弄好了吗")

        assert result["action"] == "opened"
        assert stack.depth() == 2

    def test_paraphrase_within_a_topic_is_recognised(self, stack):
        """反过来:换着说法谈同一件事必须被认出来,否则栈会被同一件事塞满。

        "季度报告"→"报告里的营收部分"→"报告结论那段" 用词一直在变,字级 bigram
        ("报告""营收""结论")足以把它们串成一件事;若只用单字或只用 bigram 都做不到
        (前者被"一/下/的"这类高频字淹没,后者换一个字就断)。
        """
        stack.observe("帮我把季度报告整理一下")
        for follow_up in ("报告里的营收部分重新算一下", "季度报告的图表也换个配色", "报告结论那段再润色"):
            assert stack.observe(follow_up)["action"] == "continued", follow_up
        assert stack.depth() == 1, "同一件事被拆成了多个焦点"

    def test_containment_does_not_penalise_a_well_established_focus(self, stack):
        """谈得越久的话题必须**越容易**被认出来,不是越难。

        第一版用对称 Jaccard,焦点的词法指纹随对话累积 → 词集变大 → 并集变大 →
        Jaccard 变小,于是一件谈了十轮的事反而匹配不上了。方向正好反了。
        """
        stack.observe("帮我把季度报告整理一下")
        for extra in ("报告里的营收部分重新算一下", "季度报告的图表也换个配色", "报告结论那段再润色"):
            stack.observe(extra)
        assert stack.depth() == 1, "全程同一件事,不该分裂成多个焦点"

        # 词集已经很大了,一句新的同题发言仍须被判为 continued
        assert stack.observe("季度报告最后再检查一遍")["action"] == "continued"
        assert stack.depth() == 1


#: 真实形态,抄自 core/perception/context_fuser.py —— 注意**里面还嵌着方括号**。
_REAL_MM_SUFFIX = "\n\n[Multimodal context: 1 image(s) [webcam], device=dev-1]"


class TestMachineAnnotationPollution:
    """机器追加的注解不能进词法判断 —— 真跑抓到的,而且症状是"安静地全错"。

    ``core/openclawd.py`` 在把消息交给内核前做 ``f"{message}\\n\\n{fusion_summary}"``,
    于是每一轮用户文本后面都挂着一段 ``[Multimodal context: ...]``,**每轮几乎一样**。
    对靠词法相似度做判断的东西这是毒药:两句毫不相干的话会因为共享这段注解而显得相似。

    实测:不剥的话「季度报告」和「老王的消息」被判成同一件事,栈深停在 1(本该是 2)。
    没有报错、没有日志,只是焦点栈从此再也认不出话题切换。
    """

    def test_topic_switch_is_still_detected_with_annotations(self, stack):
        assert stack.observe("帮我把季度报告整理一下" + _REAL_MM_SUFFIX)["action"] == "opened"
        assert stack.observe("等一下,先看看老王刚发的那条消息" + _REAL_MM_SUFFIX)["action"] == "opened"
        assert stack.depth() == 2, "共享的机器注解把两个不同话题黏成了一个"

    def test_full_conversation_shape_survives_annotations(self, stack):
        """带注解跑一遍完整的打断-恢复,形状必须与不带注解时逐步一致。"""
        stack.observe("帮我把季度报告整理一下" + _REAL_MM_SUFFIX)
        stack.observe("等一下,先看看老王刚发的那条消息" + _REAL_MM_SUFFIX)
        assert stack.observe("继续" + _REAL_MM_SUFFIX)["action"] == "continued"
        assert stack.observe("回到季度报告,把整理的部分接着做" + _REAL_MM_SUFFIX)["action"] == "resumed"
        assert stack.depth() == 2
        assert "报告" in stack.current.topic

    def test_topic_title_has_no_machine_noise(self, stack):
        """标题给人看 —— 注解占掉一半宽度而对人零信息量。

        注解体里有嵌套方括号(``[webcam]``),第一版正则在那个右括号就收尾,
        留下一个孤零零的 ``]`` 挂在标题末尾。这条把嵌套一并钉住。
        """
        stack.observe("帮我把季度报告整理一下" + _REAL_MM_SUFFIX)

        assert stack.current.topic == "帮我把季度报告整理一下"
        assert "]" not in stack.current.topic
        assert "Multimodal" not in stack.current.topic

    def test_user_typed_brackets_are_preserved(self, stack):
        """只剥**已知的机器注解**,不做通用的去方括号 —— 用户真的会打方括号。"""
        stack.observe("把 [重要] 那段标出来" + _REAL_MM_SUFFIX)

        assert "[重要]" in stack.current.topic


class TestRegistry:
    def test_sessions_are_isolated(self):
        from core.focus_stack import get_focus_stack

        get_focus_stack("a").observe("帮我把季度报告整理一下")
        assert get_focus_stack("b").depth() == 0

    def test_same_session_returns_same_stack(self):
        from core.focus_stack import get_focus_stack

        assert get_focus_stack("a") is get_focus_stack("a")


class TestFacadeWiring:
    def test_focus_message_lands_in_unified_context(self, monkeypatch):
        """端到端:焦点栈的结构确实进了喂给模型的 messages,且排在轮次历史之前。"""
        import core.session_memory_facade as facade
        from core.focus_stack import get_focus_stack

        get_focus_stack("s1").observe("帮我把季度报告整理一下")
        get_focus_stack("s1").observe("等一下,先看看老王刚发的那条消息")

        monkeypatch.setattr(
            facade,
            "get_session_context",
            lambda sid, max_turns=10: [{"role": "user", "content": "最近一轮"}],
        )
        messages = facade.build_unified_context_uncached("s1", "继续")

        focus_idx = next(i for i, m in enumerate(messages) if "[焦点栈]" in m.get("content", ""))
        turn_idx = next(i for i, m in enumerate(messages) if m.get("content") == "最近一轮")
        assert focus_idx < turn_idx, "结构必须排在流水之前"
