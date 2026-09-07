"""桌面动作解析:一套循环吃多家格式,认不出就说认不出。

``computer_use_loop`` 原来只认本仓自己在 planner prompt 里约定的扁平 JSON。
本地模型按那个 prompt 回话没问题,但厂商自带的 computer use 形状完全不同 ——
Anthropic 走 ``tool_use`` 块、动作在 ``input.action``、坐标是 ``coordinate: [x, y]``
数组,而且动作名也不一样(``key`` / ``mouse_move`` / ``left_click_drag``)。
直接喂给旧解析器**一条都认不出来**。

这组判据钉住三件事:老路一个字没变、新方言真的能翻、以及**认不出时绝不猜**。
"""

import json

import pytest

from core.computer_use_dialects import (
    DEFAULT_ANTHROPIC_BETA,
    DEFAULT_ANTHROPIC_COMPUTER_TYPE,
    DIALECT_ANTHROPIC,
    DIALECT_NATIVE,
    DIALECTS,
    anthropic_tool_schema,
    translate_any,
)
from core.computer_use_loop import ALLOWED_ACTIONS, _parse_action_json


def _tool_use(action_input: dict) -> dict:
    return {"type": "tool_use", "id": "toolu_x", "name": "computer", "input": action_input}


#: 使用者给的那条真实响应,原样保留。
REAL_RESPONSE = {
    "id": "msg_01XFDUDYJgAACzvnptvVerNM",
    "type": "message",
    "role": "assistant",
    "content": [
        {"type": "text", "text": "I'll take a screenshot to see the current state of the screen."},
        {
            "type": "tool_use",
            "id": "toolu_01A09q90qw90lq917835lq9",
            "name": "computer",
            "input": {"action": "screenshot"},
        },
    ],
    "stop_reason": "tool_use",
}


class TestTheOldPathIsUntouched:
    """native 那条路一个字没变 —— 本地模型照旧工作。"""

    def test_flat_json_still_parses(self):
        assert _parse_action_json('{"action":"click","x":1,"y":2}') == {"action": "click", "x": 1, "y": 2}

    def test_markdown_fence_is_still_tolerated(self):
        assert _parse_action_json('```json\n{"action":"done"}\n```') == {"action": "done"}

    def test_native_is_recognised_as_native(self):
        _, dialect, _ = translate_any('{"action":"wait","seconds":1}')
        assert dialect == DIALECT_NATIVE


class TestAnthropicToolUse:
    def test_the_real_response_from_the_docs_is_understood(self):
        action, dialect, why = translate_any(REAL_RESPONSE)
        assert dialect == DIALECT_ANTHROPIC, why
        assert action is not None

    def test_it_works_when_the_payload_is_a_json_string(self):
        """调用方拿到的往往是模型回复**原文**(字符串),不是解析好的 dict。

        第一版只吃 dict,于是这一整家在真正的调用路径上认不出来 —— 自测当场露馅。
        """
        assert _parse_action_json(json.dumps(REAL_RESPONSE)) is not None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"action": "click", "coordinate": [100, 200]}, {"action": "click", "x": 100, "y": 200}),
            ({"action": "left_click", "coordinate": [3, 4]}, {"action": "click", "x": 3, "y": 4}),
            ({"action": "mouse_move", "coordinate": [5, 6]}, {"action": "move", "x": 5, "y": 6}),
            ({"action": "type", "text": "hello"}, {"action": "type", "text": "hello"}),
            ({"action": "key", "key": "Return"}, {"action": "press_key", "key": "Return"}),
        ],
    )
    def test_action_names_and_coordinates_are_translated(self, raw, expected):
        """名字对不上是真会咬人的:``key`` 原样传下去会被白名单拒掉。"""
        action, _, why = translate_any(_tool_use(raw))
        assert action is not None, why
        for k, v in expected.items():
            assert action[k] == v

    def test_drag_carries_both_ends(self):
        action, _, why = translate_any(
            _tool_use({"action": "left_click_drag", "start_coordinate": [1, 2], "coordinate": [3, 4]})
        )
        assert action is not None, why
        assert (action["from_x"], action["from_y"], action["to_x"], action["to_y"]) == (1, 2, 3, 4)

    def test_drag_missing_an_endpoint_is_refused_not_guessed(self):
        action, _, why = translate_any(_tool_use({"action": "left_click_drag", "coordinate": [3, 4]}))
        assert action is None and "start_coordinate" in why

    def test_screenshot_becomes_a_wait_and_that_is_documented(self):
        """``screenshot`` 是"想再看一眼"。本仓的循环每一步都会重新截图,
        所以翻成 wait —— 这是**转义**,必须在源码里写明,不能当等价映射蒙混过去。
        """
        action, _, _ = translate_any(_tool_use({"action": "screenshot"}))
        assert action["action"] == "wait"

        import inspect

        import core.computer_use_dialects as d

        assert "转义" in inspect.getsource(d), "转义没有留痕,以后会有人以为动作丢了"

    def test_every_translated_action_lands_inside_the_whitelist(self):
        """翻出来的动作必须是循环认得的 —— 否则翻了也会被安全门拒掉。"""
        for raw in (
            {"action": "click", "coordinate": [1, 1]},
            {"action": "double_click", "coordinate": [1, 1]},
            {"action": "right_click", "coordinate": [1, 1]},
            {"action": "type", "text": "x"},
            {"action": "key", "key": "a"},
            {"action": "mouse_move", "coordinate": [1, 1]},
            {"action": "left_click_drag", "start_coordinate": [1, 1], "coordinate": [2, 2]},
            {"action": "scroll", "coordinate": [1, 1], "direction": "down", "magnitude": 3},
            {"action": "screenshot"},
        ):
            action, _, why = translate_any(_tool_use(raw))
            assert action is not None, why
            assert action["action"] in ALLOWED_ACTIONS, f"{raw} 翻成了白名单外的 {action['action']}"


class TestItNeverGuesses:
    """认不出就说认不出 —— 猜错会在无关位置点一下,认不出只是这一步不执行。"""

    def test_an_unknown_anthropic_action_is_refused(self):
        action, dialect, why = translate_any(_tool_use({"action": "teleport"}))
        assert action is None
        assert dialect == DIALECT_ANTHROPIC
        assert "teleport" in why

    @pytest.mark.parametrize("junk", ["", "随便说点什么", "{}", "[1,2,3]", '{"foo":"bar"}'])
    def test_garbage_yields_none(self, junk):
        assert _parse_action_json(junk) is None

    def test_a_malformed_coordinate_is_not_coerced(self):
        """``coordinate`` 形状不对时不许硬凑一个点出来。"""
        for bad in ([1], [1, 2, 3], "100,200", None):
            action, _, _ = translate_any(_tool_use({"action": "click", "coordinate": bad}))
            if action is not None:
                assert "x" not in action, f"从 {bad!r} 里凑出了坐标"

    def test_the_reason_is_always_given_when_it_fails(self):
        _, _, why = translate_any("完全认不出的东西")
        assert why, "认不出必须说清是为什么"


class TestTheToolSchemaMatchesTheRealScreen:
    def test_the_declared_size_is_what_you_pass_in(self):
        schema = anthropic_tool_schema(2560, 1440)
        assert schema["display_width_px"] == 2560
        assert schema["display_height_px"] == 1440
        assert schema["name"] == "computer"

    def test_the_versioned_type_is_configurable_not_hardcoded(self):
        """``type`` 是**日期版本化**的,会随上游更新。

        写死一个旧串会拿到旧行为甚至直接报错,所以必须能换。
        """
        assert anthropic_tool_schema(800, 600, tool_type="computer_20990101")["type"] == "computer_20990101"
        assert DEFAULT_ANTHROPIC_COMPUTER_TYPE.startswith("computer_")
        assert DEFAULT_ANTHROPIC_BETA.startswith("computer-use-")

    def test_the_source_warns_about_dpi_mismatch(self):
        """声明尺寸与真实屏幕不一致 → 坐标系统性偏移,而且不会报错。

        这是 Windows DPI 缩放最常见的坑,必须在源码里写明。
        """
        import inspect

        import core.computer_use_dialects as d

        src = inspect.getsource(d.anthropic_tool_schema)
        assert "DPI" in src


class TestTheDialectTableIsOneAuthority:
    def test_every_dialect_declares_both_halves(self):
        for d in DIALECTS:
            assert d.name and d.label
            assert callable(d.detect) and callable(d.translate)

    def test_the_more_specific_dialect_is_tried_first(self):
        """anthropic 的形状比扁平 JSON 更具体,必须先认它 —— 否则会被误判成 native。"""
        names = [d.name for d in DIALECTS]
        assert names.index(DIALECT_ANTHROPIC) < names.index(DIALECT_NATIVE)

    def test_you_can_pin_a_single_dialect_for_diagnosis(self):
        action, dialect, why = translate_any(REAL_RESPONSE, only=DIALECT_NATIVE)
        assert action is None and dialect == "" and "只试了" in why
