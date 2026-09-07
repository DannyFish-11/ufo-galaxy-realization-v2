"""原生 computer 工具声明,得真的发得出去。

为什么单独一片
--------------
``core/computer_use_dialects.py`` 能**构造**出 Anthropic 的 computer 工具声明,
但构造出来不等于发得出去。实测下来,把它交给 ``AnthropicAdapter`` 之后:

* ``_convert_tools`` 只认 ``type == "function"``,内建工具**被静默丢掉** ——
  ``tools`` 变成 ``[]``,请求照发,模型只会说话不会动手,而且不报任何错;
* 请求头里从来没有 ``anthropic-beta``,而内建工具少了这个头服务端直接 400。

两条合起来就是典型的"看起来接上了,其实没有"。这一片盯的就是这两条,
以及"认不出的东西被丢掉时必须留痕",别再变回静默。
"""

from __future__ import annotations

import base64
import io
import json
import os
from unittest.mock import patch

import pytest

from core.computer_use_dialects import (
    ANTHROPIC_BUILTIN_TOOL_BETAS,
    DEFAULT_ANTHROPIC_BETA,
    DEFAULT_ANTHROPIC_COMPUTER_TYPE,
    anthropic_betas_for_tools,
    anthropic_tool_for_screenshot,
    anthropic_tool_schema,
    is_anthropic_native_tool,
)
from core.llm_adapters import AnthropicAdapter


def _png_b64(width: int, height: int) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------
# 原生形状的判据
# --------------------------------------------------------------------------


class TestWhatCountsAsNativeShape:
    def test_builtin_computer_tool_is_native(self):
        assert is_anthropic_native_tool(anthropic_tool_schema(1920, 1080)) is True

    def test_a_converted_custom_tool_is_native(self):
        assert is_anthropic_native_tool({"name": "f", "input_schema": {"type": "object"}}) is True

    def test_an_openai_function_tool_is_not_native(self):
        assert is_anthropic_native_tool({"type": "function", "function": {"name": "f"}}) is False

    def test_non_dict_is_not_native(self):
        for junk in ("computer", None, 42, ["computer"]):
            assert is_anthropic_native_tool(junk) is False

    def test_empty_type_does_not_pass_as_native(self):
        """``type: ""`` 不算原生 —— 空不是一种类型。"""
        assert is_anthropic_native_tool({"type": ""}) is False


# --------------------------------------------------------------------------
# beta 旗标:一处权威,认不出就不编
# --------------------------------------------------------------------------


class TestBetaFlags:
    def test_computer_tool_asks_for_its_beta(self):
        tool = anthropic_tool_schema(800, 600)
        assert anthropic_betas_for_tools([tool]) == [DEFAULT_ANTHROPIC_BETA]

    def test_unregistered_type_gets_no_invented_beta(self):
        """没登记的 type 不许编一个旗标出来 —— 编错了照样 400,而且错得更难查。"""
        assert anthropic_betas_for_tools([{"type": "bash_20241022"}]) == []

    def test_function_tools_need_no_beta(self):
        assert anthropic_betas_for_tools([{"type": "function", "function": {"name": "f"}}]) == []

    def test_duplicates_collapse(self):
        tool = anthropic_tool_schema(800, 600)
        assert anthropic_betas_for_tools([tool, tool, tool]) == [DEFAULT_ANTHROPIC_BETA]

    def test_no_tools_no_betas(self):
        assert anthropic_betas_for_tools(None) == []
        assert anthropic_betas_for_tools([]) == []

    def test_registry_is_the_one_authority(self):
        """旗标只在登记表里定义一份。"""
        assert ANTHROPIC_BUILTIN_TOOL_BETAS[DEFAULT_ANTHROPIC_COMPUTER_TYPE] == DEFAULT_ANTHROPIC_BETA


# --------------------------------------------------------------------------
# 这一条是主症状:工具不许被静默丢掉
# --------------------------------------------------------------------------


class TestTheToolActuallySurvivesConversion:
    def test_computer_tool_is_not_dropped(self):
        """改之前这里返回的是 ``[]`` —— 声明了工具,发出去却什么都没有。"""
        tool = anthropic_tool_schema(2560, 1440)
        out = AnthropicAdapter._convert_tools([tool])
        assert out == [tool]

    def test_computer_tool_keeps_its_dimensions(self):
        """尺寸不能在转换里丢 —— 模型是按这个坐标系给点的。"""
        out = AnthropicAdapter._convert_tools([anthropic_tool_schema(2560, 1440)])
        assert out[0]["display_width_px"] == 2560
        assert out[0]["display_height_px"] == 1440

    def test_openai_function_tools_still_translate(self):
        """既有那条路不能因此坏掉。"""
        out = AnthropicAdapter._convert_tools(
            [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
        )
        assert out == [{"name": "f", "description": "", "input_schema": {"type": "object"}}]

    def test_mixed_batch_keeps_both(self):
        tool = anthropic_tool_schema(1024, 768)
        out = AnthropicAdapter._convert_tools([tool, {"type": "function", "function": {"name": "f", "parameters": {}}}])
        assert len(out) == 2
        assert out[0] == tool
        assert out[1]["name"] == "f"

    def test_function_tool_without_a_function_body_is_dropped(self):
        assert AnthropicAdapter._convert_tools([{"type": "function"}]) == []

    def test_none_and_empty_are_fine(self):
        assert AnthropicAdapter._convert_tools(None) == []
        assert AnthropicAdapter._convert_tools([]) == []

    def test_dropping_something_leaves_a_trace(self, caplog):
        """丢掉必须看得见。静默丢弃就是让下一个人再查一遍同样的问题。"""
        with caplog.at_level("WARNING"):
            AnthropicAdapter._convert_tools(["not a dict"])
        assert any("丢弃" in r.getMessage() for r in caplog.records)

    def test_unknown_shape_also_leaves_a_trace(self, caplog):
        with caplog.at_level("WARNING"):
            out = AnthropicAdapter._convert_tools([{"nothing": "recognizable"}])
        assert out == []
        assert caplog.records, "认不出的工具被丢掉了,却没留下任何痕迹"


# --------------------------------------------------------------------------
# 尺寸从截图量,量不出就不声明
# --------------------------------------------------------------------------


class TestDimensionsComeFromTheActualScreenshot:
    def test_measures_the_real_image(self):
        tool, why = anthropic_tool_for_screenshot(_png_b64(1366, 768))
        assert why == ""
        assert (tool["display_width_px"], tool["display_height_px"]) == (1366, 768)

    def test_a_different_size_gives_a_different_declaration(self):
        """不是回一个写死的默认值。"""
        a, _ = anthropic_tool_for_screenshot(_png_b64(800, 600))
        b, _ = anthropic_tool_for_screenshot(_png_b64(2560, 1440))
        assert a["display_width_px"] != b["display_width_px"]

    def test_no_screenshot_declares_nothing(self):
        tool, why = anthropic_tool_for_screenshot("")
        assert tool is None
        assert why, "拒绝了却说不出为什么"

    def test_unreadable_bytes_declare_nothing(self):
        """量不出来时**绝不填默认分辨率** —— 填了就是在保证每一次点击都偏。"""
        tool, why = anthropic_tool_for_screenshot(base64.b64encode(b"not an image").decode())
        assert tool is None
        assert "量不出" in why

    def test_the_reason_is_specific_not_generic(self):
        _, why_empty = anthropic_tool_for_screenshot("")
        _, why_bad = anthropic_tool_for_screenshot(base64.b64encode(b"nope").decode())
        assert why_empty != why_bad, "两种失败给了同一句话,等于没说"


# --------------------------------------------------------------------------
# 闭环这一侧:开关默认关,tool_calls 也能解出动作
# --------------------------------------------------------------------------


class TestTheLoopSide:
    def test_native_tool_is_off_by_default(self):
        from core.computer_use_loop import _native_tool_enabled

        with patch.dict(os.environ, {}, clear=True):
            assert _native_tool_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_switch_accepts_the_usual_truthy_spellings(self, value):
        from core.computer_use_loop import _native_tool_enabled

        with patch.dict(os.environ, {"GALAXY_COMPUTER_USE_NATIVE_TOOL": value}):
            assert _native_tool_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "off", "no", ""])
    def test_switch_stays_off_for_the_rest(self, value):
        from core.computer_use_loop import _native_tool_enabled

        with patch.dict(os.environ, {"GALAXY_COMPUTER_USE_NATIVE_TOOL": value}):
            assert _native_tool_enabled() is False

    def test_tool_calls_become_a_canonical_action(self):
        """路由把 tool_use 归一成 OpenAI 形状后,闭环仍要解得出动作。"""
        from core.computer_use_loop import _parse_tool_calls

        calls = [
            {
                "id": "toolu_1",
                "type": "function",
                "function": {
                    "name": "computer",
                    "arguments": json.dumps({"action": "left_click", "coordinate": [100, 200]}),
                },
            }
        ]
        assert _parse_tool_calls(calls) == {
            "action": "click",
            "x": 100,
            "y": 200,
            "reason": "anthropic:left_click",
        }

    def test_tool_calls_reuse_the_dialect_table(self):
        """动作名映射只有一处 —— ``key`` → ``press_key`` 在这条路上也得成立。"""
        from core.computer_use_loop import _parse_tool_calls

        calls = [
            {
                "function": {
                    "name": "computer",
                    "arguments": json.dumps({"action": "key", "text": "Return"}),
                }
            }
        ]
        action = _parse_tool_calls(calls)
        assert action["action"] == "press_key"
        assert action["key"] == "Return"

    def test_no_tool_calls_is_not_an_error(self):
        from core.computer_use_loop import _parse_tool_calls

        assert _parse_tool_calls(None) is None
        assert _parse_tool_calls([]) is None

    def test_unparseable_arguments_yield_nothing(self):
        """认不出一律 None —— 猜错会在无关位置点一下。"""
        from core.computer_use_loop import _parse_tool_calls

        calls = [{"function": {"name": "computer", "arguments": "{{{"}}]
        assert _parse_tool_calls(calls) is None

    def test_unknown_action_yields_nothing(self):
        from core.computer_use_loop import _parse_tool_calls

        calls = [{"function": {"name": "computer", "arguments": json.dumps({"action": "teleport"})}}]
        assert _parse_tool_calls(calls) is None

    def test_malformed_entries_are_skipped_not_crashed(self):
        from core.computer_use_loop import _parse_tool_calls

        assert _parse_tool_calls(["junk", {"no_function": 1}, {"function": "not a dict"}]) is None
