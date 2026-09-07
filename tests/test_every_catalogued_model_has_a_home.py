"""目录里的每个型号都必须有归宿:要么会被选中,要么写明为什么不选。

## 这道门挡的是什么

选型号只有一个入口:``select_model_by_complexity`` 读 ``PROVIDER_MODEL_MAP``,
读不到才落 ``default_model``。registry 里那份 ``models`` 列表**从不参与选型** ——
它管的是对账(与上游 /models 比对)、展示、以及"用户显式指名时认不认这个串"。

所以"往 registry 里加一个型号"和"让智能体用上这个型号"是两件事。分开本身没问题,
问题是**分不清哪些是有意分开的**。实测过的后果:

* ``gpt-6-astra`` 进了目录、还为它写了整条 ResponsesAdapter 和怪癖表,
  但它不在选择表里 —— 正常选路下永远选不到,那条传输一次也不会被触发;
* ``gemini-3.8-flash`` 是 registry 里 google 的 ``default_model``,
  而选择表八格全钉在 3.5-flash —— 两处权威对同一件事说了两句不同的话;
* ``glm-5.3-flash`` 落进目录时漏了选择表,zhipu_coding 那一家一格都没有。

三个都是"加了但没接上最后一格",而且三个都静静躺了几天没人发现。这道门让它们喊。
"""

from __future__ import annotations

import pytest

from core.multi_llm_router import FALLBACK_ONLY_MODELS, PROVIDER_MODEL_MAP, TaskType
from core.provider_registry import PROVIDER_REGISTRY


def _reachable(name: str, default: str) -> set:
    """这一家里,路由器**真的可能选中**的型号。"""
    table = PROVIDER_MODEL_MAP.get(name, {})
    out = set(table.values())
    if len(table) < len(TaskType):
        # 有空槽才会落到 default_model;槽位排满时 default 根本轮不到。
        out.add(default)
    return out


@pytest.mark.parametrize("entry", PROVIDER_REGISTRY, ids=lambda e: e["name"])
def test_no_model_is_catalogued_without_a_home(entry):
    name = entry["name"]
    reachable = _reachable(name, entry["default_model"])
    excused = FALLBACK_ONLY_MODELS.get(name, {})
    homeless = [m for m in entry["models"] if m not in reachable and m not in excused]
    assert not homeless, (
        f"「{name}」目录里这些型号既不会被选中、也没说明为什么:{homeless}。"
        "要么给它一个任务槽(PROVIDER_MODEL_MAP),要么写进 FALLBACK_ONLY_MODELS 并说清理由。"
    )


@pytest.mark.parametrize("entry", PROVIDER_REGISTRY, ids=lambda e: e["name"])
def test_the_declared_default_is_a_model_this_vendor_actually_serves(entry):
    """default_model 必须在自家目录里。指着一个不在目录里的串,落到它时必然 404。"""
    assert entry["default_model"] in entry["models"], f"{entry['name']} 的 default_model 不在自己的 models 里"


@pytest.mark.parametrize("entry", PROVIDER_REGISTRY, ids=lambda e: e["name"])
def test_the_selection_table_never_names_a_model_outside_the_catalog(entry):
    """反面:选择表也不能指向目录里没有的型号 —— 那是选中即 404。"""
    table = PROVIDER_MODEL_MAP.get(entry["name"], {})
    catalog = set(entry["models"])
    strays = sorted({m for m in table.values() if m not in catalog})
    assert not strays, f"{entry['name']} 的选择表指向了目录里没有的型号:{strays}"


def test_the_excuse_list_is_not_a_dumping_ground():
    """名单里的每一条都要有**真的理由**,而且必须是目录里真实存在的型号。

    没有这一条,这道门会被一种最省事的方式绕过:把新型号往名单里一填、理由写
    "暂时不用",于是门变绿而事情没做。理由太短就是没写理由。
    """
    catalog = {e["name"]: set(e["models"]) for e in PROVIDER_REGISTRY}
    for provider, entries in FALLBACK_ONLY_MODELS.items():
        assert provider in catalog, f"名单里的「{provider}」不是 registry 里的提供商"
        for model, why in entries.items():
            assert model in catalog[provider], f"{provider} 的名单里写着目录中不存在的型号「{model}」"
            assert len(why.strip()) >= 10, f"{provider}/{model} 的理由太短,写清楚为什么不给它任务槽:「{why}」"


def test_a_model_cannot_be_in_both_places():
    """既排了任务槽又写在"故意不用"名单里,说明有一处是错的 —— 不许两头下注。"""
    for provider, entries in FALLBACK_ONLY_MODELS.items():
        used = set(PROVIDER_MODEL_MAP.get(provider, {}).values())
        both = sorted(set(entries) & used)
        assert not both, f"{provider}:{both} 既在选择表里又在「故意不用」名单里"


def test_the_three_that_were_missed_are_really_wired_now():
    """三个真出过事的型号,逐个钉住 —— 它们是这道门的由来。"""
    assert PROVIDER_MODEL_MAP["openai"][TaskType.REASONING] == "gpt-6-astra"
    google = set(PROVIDER_MODEL_MAP["google"].values())
    assert google == {"gemini-3.8-flash"}, f"google 还没抬到目录里声明的默认档:{google}"
    assert PROVIDER_MODEL_MAP["zhipu_coding"][TaskType.FAST_RESPONSE] == "glm-5.3-flash"


def test_the_registry_default_agrees_with_what_routing_would_pick():
    """一家的 default_model 若与选择表整体口径不一致,是两处权威各说各的。

    只对"选择表八格同值"的那些家断言 —— 那种情形下"这一家用哪个型号"是一个
    确定的答案,它必须与目录里声明的默认值一致。槽位分工不同的家不适用。
    """
    for entry in PROVIDER_REGISTRY:
        table = PROVIDER_MODEL_MAP.get(entry["name"], {})
        picks = set(table.values())
        if len(table) == len(TaskType) and len(picks) == 1:
            only = picks.pop()
            assert only == entry["default_model"], (
                f"{entry['name']}:选择表八格都用 {only},而 registry 说默认是 "
                f"{entry['default_model']} —— 两处权威说了两句不同的话"
            )
