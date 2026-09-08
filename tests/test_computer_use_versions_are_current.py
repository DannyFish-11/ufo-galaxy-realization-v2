"""版本串、两代响应形状、以及"模型看的是截图,手点的是屏幕"。

这一片存在的理由
----------------
上一版这里默认 ``computer_20241022`` —— 2024 年 10 月的最初 beta。到 2026-09
它已经落后两代:少 ``scroll`` / ``wait`` / ``triple_click`` 一堆动作,而且**能跑**,
只是少一半能力,不报任何错。默认值指向一个早就不该用的版本,比没有默认值更糟。

2026-09 的事实(照抄官方文档):

* ``computer_toolset_20260801`` —— 最新,声明就一行,**不带 beta 头**,
  塞 ``name`` / ``display_*`` 会被 ``invalid_request_error`` 拒掉;
  响应里动作名是 ``tool_use`` 的 ``name``(成员工具),``input`` 里**没有 action**,
  块上另带 ``toolset_name``。
* ``computer_20251124`` / ``20250124`` / ``20241022`` —— 老路径,必须带 beta 头
  和屏幕尺寸;动作名在 ``input.action``,坐标是 ``coordinate: [x, y]``。
* OpenAI Responses —— ``{"type": "computer"}``,不带头;响应是 ``computer_call``,
  ``actions`` 是**有序数组**,坐标是扁平的 ``x`` / ``y``。

坐标那条是两家都用加粗写的:坐标在**你回传的那张截图**的像素空间里,
原点左上,**API 不替你换算**。
"""

from __future__ import annotations

import base64
import io
import json

import pytest

from core.computer_use_dialects import (
    ANTHROPIC_TOOL_VERSIONS,
    COORD_SPACE_FIELD,
    COORD_SPACE_SCREEN,
    COORD_SPACE_SCREENSHOT,
    DEFAULT_ANTHROPIC_COMPUTER_TYPE,
    DIALECT_ANTHROPIC,
    DIALECT_ANTHROPIC_TOOLSET,
    DIALECT_OPENAI,
    LEGACY_ANTHROPIC_COMPUTER_TYPE,
    SHAPE_ACTION_IN_INPUT,
    SHAPE_TOOLSET_MEMBER,
    anthropic_beta_for_type,
    anthropic_betas_for_tools,
    anthropic_tool_for_screenshot,
    anthropic_tool_schema,
    map_action_to_screen,
    measure_screenshot,
    translate_sequence,
)


def _one(payload, **kw):
    """取序列里的第一个动作 —— 一次只给一个动作的方言,清单长度本来就是 1。

    方言层的唯一出口是 :func:`translate_sequence`(OpenAI 一次可能给好几步,
    只取第一个就是在静默丢动作)。这些用例盯的是"认不认得出、翻得对不对",
    所以在这里收一下窄口,省得每条都写 ``[0]``。
    """
    actions, dialect, why = translate_sequence(payload, **kw)
    return (actions[0] if actions else None), dialect, why


def _png_b64(w: int, h: int) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------
# 版本登记表
# --------------------------------------------------------------------------


class TestTheVersionTable:
    def test_the_default_is_the_newest_generation(self):
        assert DEFAULT_ANTHROPIC_COMPUTER_TYPE == "computer_toolset_20260801"

    def test_the_two_year_old_default_is_gone(self):
        """20241022 还能用,但**不能再是默认** —— 它缺一半动作且不报错。"""
        assert DEFAULT_ANTHROPIC_COMPUTER_TYPE != "computer_20241022"
        assert LEGACY_ANTHROPIC_COMPUTER_TYPE != "computer_20241022"

    def test_old_versions_stay_usable(self):
        """平台没上 toolset 的还要退回去,所以老条目不能删。"""
        for old in ("computer_20251124", "computer_20250124", "computer_20241022"):
            assert old in ANTHROPIC_TOOL_VERSIONS

    @pytest.mark.parametrize(
        "tool_type,beta",
        [
            ("computer_toolset_20260801", None),
            ("computer_20251124", "computer-use-2025-11-24"),
            ("computer_20250124", "computer-use-2025-01-24"),
            ("computer_20241022", "computer-use-2024-10-22"),
        ],
    )
    def test_each_version_knows_its_beta(self, tool_type, beta):
        assert ANTHROPIC_TOOL_VERSIONS[tool_type].beta == beta

    def test_no_header_needed_is_not_the_same_as_never_heard_of_it(self):
        """两者都"没有 beta 值",但意思相反 —— 混起来会让没登记的新版本串
        被当成"不用带头"发出去,然后收到一个指向 beta 名字的 400。"""
        assert anthropic_beta_for_type("computer_toolset_20260801") == (None, True)
        assert anthropic_beta_for_type("computer_29991231") == (None, False)

    def test_an_unregistered_type_leaves_a_trace(self, caplog):
        with caplog.at_level("WARNING"):
            anthropic_betas_for_tools([{"type": "computer_29991231"}])
        assert any("登记" in r.getMessage() for r in caplog.records)

    def test_function_tools_do_not_trip_the_warning(self, caplog):
        with caplog.at_level("WARNING"):
            anthropic_betas_for_tools([{"type": "function", "function": {"name": "f"}}])
        assert not caplog.records


# --------------------------------------------------------------------------
# 两代的声明形状根本不同
# --------------------------------------------------------------------------


class TestDeclarationShape:
    def test_the_toolset_declaration_is_one_line(self):
        assert anthropic_tool_schema() == {"type": "computer_toolset_20260801"}

    @pytest.mark.parametrize("field", ["name", "display_width_px", "display_height_px", "display_number"])
    def test_the_toolset_declaration_carries_no_forbidden_field(self, field):
        """塞这些会被 invalid_request_error 拒掉。"""
        assert field not in anthropic_tool_schema()

    def test_zoom_can_be_turned_off_through_configs(self):
        tool = anthropic_tool_schema(enable_zoom=False)
        assert tool["configs"] == {"zoom": {"enabled": False}}

    def test_zoom_config_is_absent_by_default(self):
        assert "configs" not in anthropic_tool_schema()

    def test_the_legacy_declaration_still_carries_dimensions(self):
        tool = anthropic_tool_schema(1280, 720, tool_type=LEGACY_ANTHROPIC_COMPUTER_TYPE)
        assert tool["name"] == "computer"
        assert (tool["display_width_px"], tool["display_height_px"]) == (1280, 720)

    def test_the_legacy_path_refuses_to_invent_a_resolution(self):
        """猜一个分辨率 = 保证每一次点击都偏。宁可报错。"""
        with pytest.raises(ValueError):
            anthropic_tool_schema(tool_type=LEGACY_ANTHROPIC_COMPUTER_TYPE)

    def test_an_unregistered_version_is_refused_not_guessed(self):
        with pytest.raises(ValueError):
            anthropic_tool_schema(tool_type="computer_29991231")

    def test_the_toolset_needs_no_screenshot_to_declare(self):
        """新版不声明尺寸,所以量不出图也不该拦住它。"""
        tool, why = anthropic_tool_for_screenshot("")
        assert tool == {"type": "computer_toolset_20260801"}
        assert why == ""

    def test_the_legacy_path_still_needs_a_measurable_screenshot(self):
        tool, why = anthropic_tool_for_screenshot("", tool_type=LEGACY_ANTHROPIC_COMPUTER_TYPE)
        assert tool is None
        assert why

    def test_shapes_are_recorded_per_version(self):
        assert ANTHROPIC_TOOL_VERSIONS[DEFAULT_ANTHROPIC_COMPUTER_TYPE].shape == SHAPE_TOOLSET_MEMBER
        assert ANTHROPIC_TOOL_VERSIONS[LEGACY_ANTHROPIC_COMPUTER_TYPE].shape == SHAPE_ACTION_IN_INPUT


# --------------------------------------------------------------------------
# toolset 的响应:动作名在 name,input 里没有 action
# --------------------------------------------------------------------------


def _toolset(name, **inp):
    return {"type": "tool_use", "id": "toolu_1", "name": name, "toolset_name": "computer", "input": inp}


class TestToolsetResponses:
    def test_the_member_name_is_the_action(self):
        action, dialect, _ = _one(_toolset("left_click", coordinate=[405, 157]))
        assert dialect == DIALECT_ANTHROPIC_TOOLSET
        assert action == {"action": "click", "reason": "anthropic_toolset:left_click", "x": 405, "y": 157}

    def test_toolset_wins_over_the_legacy_dialect(self):
        """两者都是 tool_use 块,toolset 只是多一个字段。老方言先接住的话,
        会报"input 里没有 action" —— 一句指向错误方向的报错。"""
        _, dialect, _ = _one(_toolset("type", text="hi"))
        assert dialect == DIALECT_ANTHROPIC_TOOLSET

    def test_a_response_without_toolset_name_still_goes_to_the_legacy_dialect(self):
        _, dialect, _ = _one(
            {"type": "tool_use", "name": "computer", "input": {"action": "left_click", "coordinate": [1, 2]}}
        )
        assert dialect == DIALECT_ANTHROPIC

    @pytest.mark.parametrize(
        "member,expected",
        [
            ("left_click", "click"),
            ("right_click", "right_click"),
            ("double_click", "double_click"),
            ("mouse_move", "move"),
            ("type", "type"),
            ("key", "press_key"),
            ("wait", "wait"),
        ],
    )
    def test_members_map_to_canonical_actions(self, member, expected):
        action, _, _ = _one(_toolset(member, coordinate=[1, 2], text="t", key="k"))
        assert action["action"] == expected

    def test_screenshot_becomes_a_short_wait(self):
        """本仓循环每一步都会重新截图,所以"再看一眼"等一拍即可。转义,不是等价映射。"""
        action, _, _ = _one(_toolset("screenshot"))
        assert action["action"] == "wait"
        assert action["seconds"] == 0.5

    def test_drag_needs_both_ends(self):
        action, _, _ = _one(_toolset("left_click_drag", start_coordinate=[1, 2], coordinate=[3, 4]))
        assert (action["from_x"], action["from_y"], action["to_x"], action["to_y"]) == (1, 2, 3, 4)

    def test_drag_without_a_start_is_refused(self):
        action, _, why = _one(_toolset("left_click_drag", coordinate=[3, 4]))
        assert action is None
        assert "start_coordinate" in why

    def test_members_this_repo_cannot_execute_say_so(self, monkeypatch):
        """ "上游有、本仓没有"跟"没见过这个名字"是两回事 ——
        前者该改本仓,后者该查上游,指向的下一步不同。

        这七个成员(middle_click / triple_click / hold_key / left_mouse_down /
        left_mouse_up / cursor_position / zoom)**现在都补齐了**,所以这里不再钉
        具体清单 —— 钉了的话下次补齐一个就要改一次测试。真正要守住的是
        **登记成 None 时会说"本仓不支持"**这个能力本身:下一代上游加新成员时还要用。
        """
        import core.computer_use_dialects as d

        table = dict(d._TOOLSET_MEMBER_ACTION)
        table["some_future_member"] = None
        monkeypatch.setattr(d, "_TOOLSET_MEMBER_ACTION", table)

        action, _, why = _one(_toolset("some_future_member"))
        assert action is None
        assert "本仓" in why

    @pytest.mark.parametrize(
        "member",
        [
            "middle_click",
            "triple_click",
            "hold_key",
            "left_mouse_down",
            "left_mouse_up",
            "cursor_position",
            "zoom",
        ],
    )
    def test_the_seven_are_no_longer_refused(self, member):
        """反过来钉一遍:这七个曾经只能跳过,现在必须真的翻得出来。"""
        action, _, why = _one(_toolset(member, coordinate=[1, 2], text="k", region=[0, 0, 9, 9]))
        assert action is not None, why

    def test_an_unknown_member_is_not_guessed(self):
        action, _, why = _one(_toolset("teleport"))
        assert action is None
        assert "不认识" in why


# --------------------------------------------------------------------------
# OpenAI computer_call:有序数组,一个都不许丢
# --------------------------------------------------------------------------

REAL_OPENAI = {
    "output": [
        {
            "type": "computer_call",
            "call_id": "call_002",
            "actions": [
                {"type": "click", "button": "left", "x": 405, "y": 157},
                {"type": "type", "text": "penguin"},
            ],
            "status": "completed",
        }
    ]
}


class TestOpenAIComputerCall:
    def test_the_documented_example_is_recognised(self):
        actions, dialect, why = translate_sequence(REAL_OPENAI)
        assert dialect == DIALECT_OPENAI
        assert why == ""
        assert len(actions) == 2

    def test_every_action_survives(self):
        """actions 是有序数组,只取第一个就是在静默丢动作 ——
        界面被改了一半,模型下一轮看到的画面对不上它以为的状态。"""
        actions, _, _ = translate_sequence(REAL_OPENAI)
        assert [a["action"] for a in actions] == ["click", "type"]
        assert actions[1]["text"] == "penguin"

    def test_coordinates_are_flat_not_an_array(self):
        actions, _, _ = translate_sequence(REAL_OPENAI)
        assert (actions[0]["x"], actions[0]["y"]) == (405, 157)

    def test_call_id_is_carried_so_it_can_be_returned(self):
        """回传 computer_call_output 时 call_id 必须原样带回。"""
        actions, _, _ = translate_sequence(REAL_OPENAI)
        assert all(a["call_id"] == "call_002" for a in actions)

    def test_right_button_is_a_different_action_here(self):
        actions, _, _ = translate_sequence(
            {"type": "computer_call", "actions": [{"type": "click", "button": "right", "x": 1, "y": 2}]}
        )
        assert actions[0]["action"] == "right_click"

    def test_a_button_this_repo_cannot_press_is_refused(self):
        actions, _, why = translate_sequence(
            {"type": "computer_call", "actions": [{"type": "click", "button": "middle", "x": 1, "y": 2}]}
        )
        assert actions == []
        assert "middle" in why

    def test_one_bad_action_stops_the_whole_batch(self):
        """顺序执行的语义下跳掉中间一步,后面几步作用在错误的界面状态上 ——
        比什么都不做危险。"""
        actions, _, why = translate_sequence(
            {
                "type": "computer_call",
                "actions": [{"type": "click", "x": 1, "y": 2}, {"type": "teleport"}],
            }
        )
        assert actions == []
        assert "第 2 个" in why

    def test_keypress_without_a_known_field_is_not_invented(self):
        """上游没公开字段级 schema,取不到就说取不到 —— 不替它编一个键名。"""
        actions, _, why = translate_sequence({"type": "computer_call", "actions": [{"type": "keypress"}]})
        assert actions == []
        assert "字段" in why

    def test_keypress_with_a_keys_array_works(self):
        actions, _, _ = translate_sequence(
            {"type": "computer_call", "actions": [{"type": "keypress", "keys": ["ctrl", "c"]}]}
        )
        assert actions[0]["key"] == "ctrl+c"

    def test_drag_uses_the_path_ends(self):
        actions, _, _ = translate_sequence(
            {
                "type": "computer_call",
                "actions": [{"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 5, "y": 6}, {"x": 9, "y": 9}]}],
            }
        )
        a = actions[0]
        assert (a["from_x"], a["from_y"], a["to_x"], a["to_y"]) == (1, 2, 9, 9)

    def test_drag_without_a_usable_path_is_refused(self):
        actions, _, why = translate_sequence({"type": "computer_call", "actions": [{"type": "drag"}]})
        assert actions == []
        assert why


class TestSequenceIsTheOneExit:
    def test_single_action_dialects_return_a_one_item_list(self):
        actions, dialect, _ = translate_sequence('{"action": "click", "x": 1, "y": 2}')
        assert dialect == "native"
        assert len(actions) == 1

    def test_unrecognised_gives_an_empty_list_and_a_reason(self):
        actions, dialect, why = translate_sequence("总之不是动作")
        assert actions == []
        assert dialect == ""
        assert why

    def test_translate_any_agrees_with_the_first_of_the_sequence(self):
        one, d1, _ = _one(REAL_OPENAI)
        many, d2, _ = translate_sequence(REAL_OPENAI)
        assert d1 == d2
        assert one == many[0]


# --------------------------------------------------------------------------
# 坐标空间 —— 模型看的是截图,手点的是屏幕
# --------------------------------------------------------------------------


class TestCoordinateSpace:
    def test_same_size_needs_no_conversion(self):
        out, why = map_action_to_screen(
            {"action": "click", "x": 5, "y": 6}, shot_size=(100, 100), screen_size=(100, 100)
        )
        assert (out["x"], out["y"]) == (5, 6)
        assert out[COORD_SPACE_FIELD] == COORD_SPACE_SCREEN
        assert why == ""

    def test_a_downscaled_screenshot_is_mapped_back(self):
        """截图缩过却不换算,每一次点击都按同一个比例偏,而且不报错。"""
        out, why = map_action_to_screen(
            {"action": "click", "x": 640, "y": 360}, shot_size=(1280, 720), screen_size=(2560, 1440)
        )
        assert (out["x"], out["y"]) == (1280, 720)
        assert "1280x720" in why and "2560x1440" in why

    def test_drag_endpoints_are_mapped_too(self):
        out, _ = map_action_to_screen(
            {"action": "drag", "from_x": 1, "from_y": 2, "to_x": 3, "to_y": 4},
            shot_size=(100, 100),
            screen_size=(200, 400),
        )
        assert (out["from_x"], out["from_y"], out["to_x"], out["to_y"]) == (2, 8, 6, 16)

    def test_unknown_screen_size_is_not_assumed_to_be_one_to_one(self):
        """假设 1:1 然后闷头点,错了也看不出来是坐标的事。"""
        out, why = map_action_to_screen({"action": "click", "x": 5, "y": 6}, shot_size=(100, 100), screen_size=None)
        assert (out["x"], out["y"]) == (5, 6)
        assert out[COORD_SPACE_FIELD] == COORD_SPACE_SCREENSHOT
        assert why

    def test_unknown_shot_size_is_also_flagged(self):
        out, why = map_action_to_screen({"action": "click", "x": 5, "y": 6}, shot_size=None, screen_size=(100, 100))
        assert out[COORD_SPACE_FIELD] == COORD_SPACE_SCREENSHOT
        assert "截图" in why

    def test_non_coordinate_fields_are_untouched(self):
        out, _ = map_action_to_screen(
            {"action": "type", "text": "hello", "reason": "r"}, shot_size=(100, 100), screen_size=(200, 200)
        )
        assert out["text"] == "hello"
        assert out["reason"] == "r"

    def test_a_broken_coordinate_downgrades_the_whole_action(self):
        """一半换算一半没换是最糟的:看着像换过了。"""
        out, why = map_action_to_screen(
            {"action": "click", "x": "left", "y": 6}, shot_size=(100, 100), screen_size=(200, 200)
        )
        assert out[COORD_SPACE_FIELD] == COORD_SPACE_SCREENSHOT
        assert why

    def test_the_space_is_always_recorded(self):
        """有没有换算,必须从动作本身看得出来。"""
        for screen in [(200, 200), None]:
            out, _ = map_action_to_screen({"action": "click", "x": 1, "y": 2}, shot_size=(100, 100), screen_size=screen)
            assert COORD_SPACE_FIELD in out


class TestMeasuring:
    def test_a_real_png_is_measured(self):
        assert measure_screenshot(_png_b64(1366, 768)) == ((1366, 768), "")

    def test_nothing_is_not_measured(self):
        size, why = measure_screenshot("")
        assert size is None and why

    def test_garbage_is_not_measured(self):
        size, why = measure_screenshot(base64.b64encode(b"nope").decode())
        assert size is None and "量不出" in why


# --------------------------------------------------------------------------
# 闭环里真的走了这一步 —— 构造得出来 ≠ 用上了
# --------------------------------------------------------------------------


class TestTheLoopActuallyMapsCoordinates:
    """模型按截图给坐标,手点在屏幕上。这一段盯的是闭环**真的**做了换算。

    只测方言层等于没测:换算函数写得再对,没接在派发之前就等于不存在。
    """

    @staticmethod
    def _run(screen_size, model_reply=None):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from core.computer_use_loop import ComputerUseLoop

        shot = _png_b64(1280, 720)
        executed = []

        async def perceive():
            return shot

        async def act(action, params, node_id):
            executed.append((action, dict(params)))
            return {"success": True, "error": ""}

        class Reply:
            content = model_reply or json.dumps(
                {
                    "output": [
                        {
                            "type": "computer_call",
                            "call_id": "c1",
                            "actions": [{"type": "click", "button": "left", "x": 640, "y": 360}],
                        }
                    ]
                }
            )
            tool_calls = None

        class Router:
            async def chat(self, **kw):
                return Reply()

        class NoMemory:
            def __getattr__(self, _n):
                async def _noop(*a, **k):
                    return None

                return _noop

            async def recall(self, *a, **k):
                return "", []

        async def go():
            loop = ComputerUseLoop(router=Router(), perceive_fn=perceive, act_fn=act, memory=NoMemory())
            with patch(
                "core.computer_use_loop._screen_size_via_node",
                new=AsyncMock(return_value=screen_size),
            ):
                await asyncio.wait_for(loop.run("测试", max_steps=1), timeout=25)

        asyncio.run(go())
        return executed

    def test_same_size_reaches_the_node_unchanged(self):
        executed = self._run((1280, 720))
        _, params = executed[0]
        assert (params["x"], params["y"]) == (640, 360)

    def test_a_downscaled_screenshot_is_scaled_up_before_dispatch(self):
        """截图 1280x720、屏幕 2560x1440:图正中的 (640,360) 必须变成 (1280,720)。
        不换算的话每一次点击都落在屏幕左上四分之一里。"""
        executed = self._run((2560, 1440))
        _, params = executed[0]
        assert (params["x"], params["y"]) == (1280, 720)

    def test_unknown_screen_size_leaves_coordinates_alone_but_says_so(self):
        executed = self._run(None)
        _, params = executed[0]
        assert (params["x"], params["y"]) == (640, 360)
        assert params[COORD_SPACE_FIELD] == COORD_SPACE_SCREENSHOT

    def test_the_coordinate_space_is_recorded_on_every_step(self):
        """降级必须留痕:这一步有没有换算过,事后要看得出来。"""
        for size in [(2560, 1440), None]:
            _, params = self._run(size)[0]
            assert COORD_SPACE_FIELD in params

    def test_the_vendor_shape_survives_the_whole_loop(self):
        """OpenAI 的 computer_call 一路走到派发,不是只在方言层解得开。"""
        executed = self._run((1280, 720))
        assert executed[0][0] == "click"

    def test_a_toolset_reply_also_reaches_the_node(self):
        reply = json.dumps(
            {"type": "tool_use", "name": "left_click", "toolset_name": "computer", "input": {"coordinate": [640, 360]}}
        )
        executed = self._run((2560, 1440), model_reply=reply)
        action, params = executed[0]
        assert action == "click"
        assert (params["x"], params["y"]) == (1280, 720)
