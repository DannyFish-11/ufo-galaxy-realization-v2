"""新增型号要「真的接通」：登记表、选型表、适配器、面板读到的名单，四处一致。

2026-09-29 新增：claude-opus-5-5、claude-sonnet-5-5（Anthropic）、step-5-preview（阶跃）。

为什么单独测
============
**选型号只读 PROVIDER_MODEL_MAP**，登记表的 ``models`` 目录只是目录 —— 只改目录，运行时等于没加。
这个仓库因此栽过不止一次（见 tests/test_every_catalogued_model_has_a_home.py）。这里钉住的是
"型号真的会被选到"，不是"名字出现在某个列表里"。

另有一个只有真发请求才会暴露的坑：官方文档明说 Sonnet 5.5 对 temperature / top_p / top_k 传非默认值
直接 400，而 AnthropicAdapter 每次都发 temperature。
"""

from __future__ import annotations

import asyncio

from core.llm_adapters import AnthropicAdapter
from core.multi_llm_router import PROVIDER_MODEL_MAP, PROVIDER_REGISTRY, ProviderConfig, TaskType
from core.provider_registry import quirks_for


def _entry(name):
    return next(e for e in PROVIDER_REGISTRY if e["name"] == name)


def test_claude_55_models_are_catalogued_with_the_documented_price_kept():
    e = _entry("anthropic")
    assert "claude-opus-5-5" in e["models"] and "claude-sonnet-5-5" in e["models"]
    # sonnet-5-5 与 sonnet-5 同价 $2/$10，直接升级成 default，cost 不用动
    assert e["default_model"] == "claude-sonnet-5-5"
    assert (e["cost_in"], e["cost_out"]) == (0.002, 0.010)


def test_claude_55_models_are_actually_selected_by_task_type():
    m = PROVIDER_MODEL_MAP["anthropic"]
    assert m[TaskType.REASONING] == "claude-opus-5-5"
    assert m[TaskType.PLANNING] == "claude-opus-5-5"
    assert m[TaskType.CODING] == "claude-sonnet-5-5"
    assert m[TaskType.GENERAL] == "claude-sonnet-5-5"
    assert m[TaskType.FAST_RESPONSE] == "claude-haiku-4-5-20251001"


def test_step_5_preview_is_catalogued_not_default_and_selected_for_heavy_work():
    e = _entry("step")
    assert "step-5-preview" in e["models"]
    assert e["default_model"] != "step-5-preview", "preview 不设为默认"
    # 价格 $1.00 入 / $2.70 出，provider 级 cost 按"往贵了登记"不得低于它
    assert e["cost_in"] >= 0.001 and e["cost_out"] >= 0.0027
    m = PROVIDER_MODEL_MAP["step"]
    for t in (TaskType.REASONING, TaskType.ANALYSIS, TaskType.PLANNING, TaskType.AGENT_CONTROL):
        assert m[t] == "step-5-preview"
    assert m[TaskType.GENERAL] == "step-3.7-flash" and m[TaskType.CODING] == "step-3.7-flash"


def test_sonnet_55_drops_sampling_params_and_other_models_keep_them():
    assert set(quirks_for("claude-sonnet-5-5")["omit_params"]) == {"temperature", "top_p", "top_k"}
    # 带日期快照串也要命中（按前缀）
    assert quirks_for("claude-sonnet-5-5-20260928").get("omit_params")
    assert not quirks_for("claude-opus-5-5")
    assert not quirks_for("claude-sonnet-5")


def _sent_body(model: str) -> dict:
    cfg = ProviderConfig(name="anthropic", api_key="k", base_url="http://x/v1", models=[model], default_model=model)
    adapter = AnthropicAdapter(cfg)
    captured = {}

    class _Resp:
        def json(self):
            return {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    async def _post(url, headers, body):
        captured.update(body)
        return _Resp()

    adapter._post_with_retry = _post
    asyncio.run(adapter.chat([{"role": "user", "content": "hi"}], model, temperature=0.7))
    return captured


def test_anthropic_adapter_does_not_send_temperature_to_sonnet_55():
    assert "temperature" not in _sent_body("claude-sonnet-5-5")


def test_anthropic_adapter_still_sends_temperature_to_other_claude_models():
    assert _sent_body("claude-haiku-4-5-20251001")["temperature"] == 0.7
    assert _sent_body("claude-opus-5-5")["temperature"] == 0.7
