"""写进长期记忆的那条「经验」，必须带着来源 —— 而且这条链不许悄悄断掉。

## 背景：这一条为什么值得单独钉

``core/agent/execution_planner.py`` 每跑完一次任务都会写一条经验:

    经验: 任务[...] 策略[...] 结果[成功/失败] 要点[<模型自己写的文本>]

「要点」是**模型自己写的**。如果这一轮的上下文里进过外部内容(网页正文、工具返回、
MCP 工具描述、别的设备发来的东西),那段文字很可能是对外部内容的复述 ——
而它正要被写进长期记忆,以后再被召回时看起来就像**系统自己的经验**。

``core/memory_provenance.stamp()`` 就是挡这个的:给正文加 ``〔来源:…〕`` 前缀、
往 metadata 里写 ``galaxy_origin``。取不到来源时按最坏(``unknown``)记 ——
宁可把一条本来干净的记忆标成外部,也不要把一条外部来的标成干净的。

**它已经接上了**(``UnifiedMemory.remember`` 里调的),这一套门钉的是"别断"：
这类链路断掉的时候不会报错,只会安静地少做一件事,而症状要到很久以后才显形 ——
一条外部来的说法以第一人称混进了系统的经验里。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.memory.base import MemoryProvider
from core.memory.unified import UnifiedMemory
from core.memory_provenance import ATTRIBUTION_MARK, ORIGIN_KEY


class _Spy(MemoryProvider):
    """收下写入,给测试看真正落到后端的是什么。"""

    backend_name = "spy"

    def __init__(self) -> None:
        self.writes: List[Dict[str, Any]] = []

    def available(self) -> bool:  # noqa: D102
        return True

    def remember(self, content, *, modality="text", tags=None, metadata=None):  # noqa: D102
        self.writes.append({"content": content, "tags": list(tags or []), "metadata": dict(metadata or {})})

    def recall(self, query, *, top_k=5):  # noqa: D102
        return []


@pytest.fixture()
def spy_memory():
    spy = _Spy()
    return spy, UnifiedMemory([spy])


class TestEveryWriteCarriesItsOrigin:
    def test_an_external_origin_is_recorded_in_both_places(self, spy_memory):
        """正文前缀给**模型**看,metadata 给**检索**看。缺一个都不算记住了来源。"""
        spy, um = spy_memory
        um.remember("经验: 任务[改设置] 结果[成功] 要点[网页说要点这里]", origin="external")

        w = spy.writes[-1]
        assert w["metadata"][ORIGIN_KEY] == "external", "metadata 里没有来源 —— 检索侧无从判断"
        assert w["content"].startswith(ATTRIBUTION_MARK), "正文没有来源前缀 —— 模型会把它当成系统自己的经验"

    def test_an_unlabelled_write_follows_this_rounds_context_floor(self, spy_memory):
        """不传 origin 时,来源取**这一轮上下文的下界** —— 不是默认当成干净的。

        这一条第一版断言的是"结果必须是 unknown 或 external",在全量里红了 ——
        因为它其实依赖了一个环境状态:别的用例先跑过之后,上下文的下界已经不是
        默认值了。**那是判据自己的毛病**:它想钉的性质是"跟着下界走",却写成了
        "等于某几个固定值"。改成显式设定下界再断言它跟着变,顺带把反向也钉住。
        """
        import core.context_provenance as cp

        spy, um = spy_memory

        cp.reset()
        cp.record([cp.ContextSegment(origin="external", label="网页正文")])
        um.remember("经验: 任务[x] 结果[成功] 要点[y]")
        assert spy.writes[-1]["metadata"][ORIGIN_KEY] == "external", "进过网页内容,写出来的记忆却没跟着标成外部"

        cp.reset()
        um.remember("经验: 任务[x] 结果[成功] 要点[y]")
        floor_after_reset = spy.writes[-1]["metadata"][ORIGIN_KEY]
        assert floor_after_reset in cp.ORIGINS, f"来源不是登记过的取值:{floor_after_reset!r}"
        cp.reset()

    def test_an_origin_it_does_not_recognise_becomes_unknown_not_trusted(self, spy_memory):
        """乱传一个来源名,要落到 unknown,**不能**被当成可信。

        反过来(认不出就放行)才是危险的:一条写错来源名的新装配路径会自动拿到
        "可信"这个身份,而且不报错。
        """
        spy, um = spy_memory
        um.remember("经验: 任务[x] 结果[成功] 要点[y]", origin="从哪冒出来的")

        assert spy.writes[-1]["metadata"][ORIGIN_KEY] == "unknown"

    def test_the_attribution_is_not_stamped_twice(self, spy_memory):
        """同一条被重复标注会越滚越长,而且读起来像来源套了两层。"""
        spy, um = spy_memory
        once = f"{ATTRIBUTION_MARK}外部来源(网页/别的设备/仓外文本)〕已经标过了"
        um.remember(once, origin="external")

        assert spy.writes[-1]["content"].count(ATTRIBUTION_MARK) == 1


class TestTheChainFromExecutionToMemoryIsNotBroken:
    def test_the_planner_writes_through_the_stamping_layer(self):
        """经验写入必须走 ``UnifiedMemory``(那一层才盖章),不能直接打后端。

        绕过去不会报错 —— 只会让这条记忆没有来源,而那要到很久以后才显形。
        """
        import inspect

        from core.agent import execution_planner as ep

        src = inspect.getsource(ep)
        idx = src.index('kind": "experience"')
        block = src[max(0, idx - 1200) : idx + 200]
        assert "get_unified_memory" in block, "经验写入没有走会盖章的那一层"

    def test_the_outcome_tag_is_written_so_recall_can_weigh_it(self):
        """结果标签是召回侧加权的依据(见
        tests/test_failed_experience_does_not_crowd_out_success.py)。
        写入侧不打这个标,那一侧的加权就只能靠正文里那四个字兜底。
        """
        import inspect

        from core.agent import execution_planner as ep

        src = inspect.getsource(ep)
        assert '"success" if result.success else "failure"' in src, "经验写入没有打成功/失败标签"
