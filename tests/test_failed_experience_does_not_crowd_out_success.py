"""一次失败的尝试，不许把成功的经验挤出召回。

## 这道门挡的是什么

写入那一侧(``core/agent/execution_planner.py:845``)是**无条件写**的:每次执行都
进长期记忆,成功和失败只差一个 tag ——

    tags=["experience", "success" if result.success else "failure"]

而召回那一侧原来是纯语义 ``top_k``,**不看 tag**。于是同一个任务试了五次、失败
四次成功一次,召回的三条很可能全是失败:成功的那条被自己的失败挤出去了。模型看到
的是"这条路走不通"的四份证据和零份反例 —— 然后它会绕开那条其实走得通的路。

这就是那类"记忆投毒"在本仓的**具体形状**。公道地说,本仓不是最糟的那种:正文里
写着「结果[失败]」,模型看得见;``semantic_anchoring`` 也审计过召回内容只作参考、
绝不重新解析成控制流。但**垃圾确实进了账本、而且参与排序**。

## 为什么修召回而不是修写入

失败的经验是有用的 —— "上次在这个界面点那个按钮没反应"正是情景记忆的价值。
不写就没有教训;全滤掉也是。所以是**加权 + 设上限 + 标出来**,不是过滤。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.computer_use_memory import MAX_FAILURE_RECALL, MAX_RECALL, ComputerUseEpisodicMemory


def _hit(text: str, *, tags=None, modality="text"):
    return SimpleNamespace(content=text, modality=modality, metadata={"tags": list(tags or [])})


def _exp(task: str, outcome: str) -> str:
    """与 execution_planner 写进去的那种文本同形。"""
    return f"经验: 任务[{task}] 策略[single] 结果[{outcome}] 要点[...]"


class TestSuccessSurvivesAFloodOfFailures:
    def test_the_one_success_is_not_pushed_out_by_four_failures(self):
        hits = [_hit(_exp("改设置", "失败"), tags=["experience", "failure"]) for _ in range(4)]
        hits.append(_hit(_exp("改设置", "成功"), tags=["experience", "success"]))

        ranked = ComputerUseEpisodicMemory._rank_by_outcome(hits)
        outcomes = [ComputerUseEpisodicMemory._outcome_of(h) for h in ranked]

        assert "success" in outcomes, "四次失败把唯一那次成功挤出去了 —— 模型只会看到「这条路走不通」"
        assert outcomes[0] == "success", "成功的没排在最前"
        assert outcomes.count("failure") <= MAX_FAILURE_RECALL

    def test_failures_are_kept_not_filtered_away(self):
        """全滤掉是另一种错:那等于把教训一起扔了。"""
        hits = [
            _hit(_exp("a", "成功"), tags=["success"]),
            _hit(_exp("b", "失败"), tags=["failure"]),
        ]
        ranked = ComputerUseEpisodicMemory._rank_by_outcome(hits)
        assert any(ComputerUseEpisodicMemory._outcome_of(h) == "failure" for h in ranked), "失败的经验被整个丢掉了"

    def test_the_result_never_exceeds_the_recall_budget(self):
        hits = [_hit(_exp(str(i), "成功"), tags=["success"]) for i in range(20)]
        assert len(ComputerUseEpisodicMemory._rank_by_outcome(hits)) <= MAX_RECALL


class TestTheOutcomeIsReadFromBothPlaces:
    """tags 是权威的那一份,正文里那四个字是后端丢了 tags 之后唯一剩下的信号。"""

    def test_tags_win_when_present(self):
        assert ComputerUseEpisodicMemory._outcome_of(_hit("随便什么", tags=["experience", "failure"])) == "failure"
        assert ComputerUseEpisodicMemory._outcome_of(_hit("随便什么", tags=["experience", "success"])) == "success"

    def test_the_text_is_the_fallback_when_a_backend_dropped_the_tags(self):
        """只看 tags 的话,遇到不保留元数据的后端会整批变成 unknown —— 加权等于没加。"""
        assert ComputerUseEpisodicMemory._outcome_of(_hit(_exp("x", "失败"))) == "failure"
        assert ComputerUseEpisodicMemory._outcome_of(_hit(_exp("x", "成功"))) == "success"

    def test_something_nobody_labelled_is_unknown_not_failure(self):
        """别的链路写进来的、旧数据 —— 它们没有"这次没成"这个信号,不该被当成失败。"""
        assert ComputerUseEpisodicMemory._outcome_of(_hit("上周用户说他喜欢深色主题")) == "unknown"

    def test_unknown_ranks_above_failure_and_below_success(self):
        hits = [
            _hit(_exp("a", "失败"), tags=["failure"]),
            _hit("没标过的一条"),
            _hit(_exp("c", "成功"), tags=["success"]),
        ]
        outcomes = [ComputerUseEpisodicMemory._outcome_of(h) for h in ComputerUseEpisodicMemory._rank_by_outcome(hits)]
        assert outcomes == ["success", "unknown", "failure"]


class TestAFailedExperienceIsLabelledInThePrompt:
    def test_the_prompt_line_says_it_failed(self):
        """模型不该把一次失败的尝试读成一条可照做的经验。

        正文里本来常带「结果[失败]」,但那是写入方的格式约定 —— 别的链路写进来的
        不一定有。标签由召回这一侧统一加。
        """
        text = ComputerUseEpisodicMemory._format_experience([_hit("点了保存按钮没反应", tags=["failure"])])
        assert "[上次失败]" in text

    def test_a_success_is_not_labelled(self):
        text = ComputerUseEpisodicMemory._format_experience([_hit("点保存就成了", tags=["success"])])
        assert "[上次失败]" not in text

    def test_the_screenshot_marker_still_survives(self):
        """加标签不能把原来的模态标记挤掉 —— 那是让模型知道这条背后是真截图。"""
        text = ComputerUseEpisodicMemory._format_experience([_hit("这个界面", tags=["failure"], modality="image")])
        assert "[上次失败]" in text and "[截图]" in text


class TestItOverfetchesOrThereIsNothingToRank:
    def test_recall_asks_for_more_than_it_will_use(self):
        """取够数再筛就没得筛了 —— 这一条钉的是那个前提。"""
        import inspect

        from core.computer_use_memory import RECALL_OVERFETCH

        assert RECALL_OVERFETCH > 1
        src = inspect.getsource(ComputerUseEpisodicMemory.recall_experience)
        assert "RECALL_OVERFETCH" in src, "召回还是只取 MAX_RECALL 个 —— 排序无从谈起"
        assert "_rank_by_outcome" in src, "取回来了却没按结果排"


@pytest.mark.asyncio
async def test_end_to_end_through_the_real_recall_path(monkeypatch):
    """走真正的 recall_experience,不是只测排序函数。"""
    hits = [_hit(_exp("改设置", "失败"), tags=["failure"]) for _ in range(5)]
    hits.append(_hit(_exp("改设置", "成功"), tags=["success"]))

    class _Mem:
        enabled = True

        def recall(self, query, top_k=5):  # noqa: D102
            assert top_k > MAX_RECALL, "没有多取,排序无从谈起"
            return hits[:top_k]

    cum = ComputerUseEpisodicMemory()
    monkeypatch.setattr(cum, "_get_memory", lambda: _Mem())
    monkeypatch.setattr(type(cum), "available", property(lambda self: True))

    text = await cum.recall_experience("改设置")
    assert "结果[成功]" in text, "端到端跑下来,成功的那条还是被挤掉了"
    assert text.count("[上次失败]") <= MAX_FAILURE_RECALL
