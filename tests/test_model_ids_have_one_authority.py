"""「有哪些型号」这件事只准有一份答案,而且不准留已退役的串。

## 修的是什么

2026-09-04 复核云端型号时,发现同一件事在仓库里有**三份**手写答案:

1. ``core.multi_llm_router.PROVIDER_REGISTRY``          —— 真权威,维护得很仔细
2. ``core.model_topology.inventory_from_config._PROVIDER_DEFAULT_MODEL``
   —— 停在 2024 年(gpt-4o / claude-3-5-sonnet-20241022 / gemini-1.5-pro)
3. ``core.opencode_engine.OpenCodeEngine.get_supported_models``
   —— 同样停在 2024 年,而且**是活的**:Node_117_OpenCode 的 server 把它当接口
   对外提供

后两份都含 ``deepseek-chat``。那个型号 **2026-07-24 15:59 UTC 已彻底退役**
(api-docs.deepseek.com/updates),再调就是 404。

三份清单没有一份会报错。它们烂掉的方式是本仓最怕的那种:注册成功、选路成功,
一直到真发请求那一刻才失败,而那时用户看到的只是"模型没回话"。

## 这道门的两颗牙

**一、派生是真的派生。** 不是比对"现在两边碰巧相等"—— 那种断言在两边同时被
改错时照样绿。这里换掉 registry 的内容,再看下游会不会跟着变:不跟着变,就说明
它自己还藏着一份。

**二、退役名单里的串不准出现在可执行代码里。** 注释和 docstring 里可以写
(要记录"这个为什么被删",不然下一个人会好心加回来),但不能是活的字面量。
"""

import ast
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[1] / "core"

# 已确认退役的型号 —— 每条都要带退役日期与一手出处,不然过两年没人知道能不能删。
_RETIRED_MODEL_IDS = {
    "deepseek-chat": "2026-07-24 15:59 UTC 退役 · api-docs.deepseek.com/updates",
    "deepseek-reasoner": "2026-07-24 15:59 UTC 退役 · api-docs.deepseek.com/updates",
}


def _live_string_literals(path: Path):
    """文件里**可执行的**字符串字面量。docstring 不算,注释根本不进 AST。

    这条区分是必须的:改掉一个死型号之后,要在原地写清楚"它去哪了",而那段说明
    必然逐字提到那个串。按原文扫会把说明判成违规,于是人被逼着删掉说明 ——
    本会话已经栽过两次同形状的坑(api-surface 扫描器、settings_inventory 的门),
    这里一开始就按 AST 扫。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


@pytest.mark.parametrize("retired,provenance", sorted(_RETIRED_MODEL_IDS.items()))
def test_no_retired_model_id_survives_in_live_code(retired: str, provenance: str) -> None:
    offenders = []
    for path in _CORE.rglob("*.py"):
        for lineno, value in _live_string_literals(path):
            if value == retired:
                offenders.append(f"{path.relative_to(_CORE.parent)}:{lineno}")
    assert not offenders, (
        f"型号 {retired!r} 已经退役({provenance}),但这些地方还把它当活的用:{offenders}。"
        "留着它不会报错,只会让路由选中一个必然 404 的型号。"
    )


def test_topology_default_model_is_derived_not_stored(monkeypatch) -> None:
    """拓扑层的「厂商默认型号」必须现从 registry 取。"""
    from core.model_topology import inventory_from_config as mod

    fake = [{"name": "deepseek", "default_model": "sentinel-not-a-real-model"}]
    monkeypatch.setattr("core.multi_llm_router.PROVIDER_REGISTRY", fake)

    got = mod._default_model_for("deepseek")
    assert got == "sentinel-not-a-real-model", (
        f"换掉 registry 之后拓扑层仍然回答 {got!r} —— 说明它自己存了一份型号表。"
        "「某厂商默认用哪个型号」只该有 PROVIDER_REGISTRY 一个答案。"
    )


def test_opencode_supported_models_are_derived_not_stored(monkeypatch) -> None:
    """OpenCode 对外提供的型号清单必须现从 registry 取。"""
    from core.opencode_engine import OpenCodeEngine

    fake = [{"name": "deepseek", "models": ["sentinel-only"], "default_model": "sentinel-only"}]
    monkeypatch.setattr("core.multi_llm_router.PROVIDER_REGISTRY", fake)

    got = OpenCodeEngine.get_supported_models(object())
    assert got.get("deepseek") == ["sentinel-only"], (
        f"换掉 registry 之后 OpenCode 仍然回答 {got.get('deepseek')!r} —— 它自己存了一份。"
        "这份清单是对外接口(Node_117_OpenCode/server.py),存旧了外部调用方也跟着错。"
    )
    assert "ollama" in got, "本机 Ollama 那一行不该被一起derive掉 —— 它不在 registry 里,是另一件事"


def test_every_registry_entry_declares_a_default_that_it_also_lists() -> None:
    """default_model 必须是这条 provider 自己 models 里的一个。

    写错了不会报错,只会让默认那条路直接 404 —— 与上面退役型号是同一种失败。
    """
    from core.multi_llm_router import PROVIDER_REGISTRY

    broken = []
    for spec in PROVIDER_REGISTRY:
        models = spec.get("models") or []
        default = spec.get("default_model")
        if models and default and default not in models:
            broken.append(f"{spec['name']}: default={default!r} 不在 models={models}")
    assert not broken, "这些 provider 的默认型号不在自己的型号表里:" + "; ".join(broken)


class TestTheAggregatorPathDoesNotInventModels:
    """聚合器(OneAPI)问不出型号时,不准编一个出来。

    这条与上面那几条是同一个病的另一面。上面管的是"仓库里写死的型号表别分岔";
    这里管的是**运行时动态发现**那条路 —— 它同样能凭空造出型号:

        default_model = models[0] if models else "gpt-4o"   # ← 改动前

    网关明明没有 gpt-4o,这一家也照样注册成功、照样进候选池,直到真发请求才失败。
    而且发现失败只写了一条 ``logger.debug`` —— 降级不留痕等于没降级。

    「一个型号都问不出来」跟「这个网关有 gpt-4o」是两件完全不同的事。编一个出来
    就是把它们抹成一样。
    """

    def test_discovery_failure_returns_empty_not_a_guess(self, monkeypatch, tmp_path) -> None:
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter.__new__(MultiLLMRouter)  # 不跑 __init__,只测这一个方法
        # 让 config/api_config.json 那一路也读不到东西,单独考察"发现失败"这一支。
        monkeypatch.chdir(tmp_path)
        got = MultiLLMRouter._discover_oneapi_models(router, "http://127.0.0.1:1", "sk-not-a-placeholder")
        assert got == [] or all("gpt-4o" != m for m in got), (
            f"发现失败时返回了 {got} —— 里面不该有任何凭空造出来的型号串。"
            "调用方要靠「空表」区分「发现失败」与「真的发现了型号」。"
        )

    def test_unreachable_gateway_is_not_registered_and_says_so(self, monkeypatch, caplog) -> None:
        import logging

        from core.multi_llm_router import MultiLLMRouter

        monkeypatch.setenv("ONEAPI_URL", "http://127.0.0.1:1/")
        monkeypatch.setenv("ONEAPI_API_KEY", "sk-real-looking-key-not-a-placeholder")

        with caplog.at_level(logging.WARNING, logger="Galaxy.LLMRouter"):
            router = MultiLLMRouter()

        assert "oneapi" not in router.providers, (
            "问不出任何型号却把 oneapi 注册进去了 —— 它会带着一个编出来的型号进候选池,"
            "选中就必然失败,而失败发生在真发请求那一刻。"
        )
        assert any("一个型号都问不出来" in r.message for r in caplog.records), (
            "没注册就算了,还得说出来为什么。降级不留痕等于没降级 —— " "用户只会看到「这家怎么不见了」。"
        )
