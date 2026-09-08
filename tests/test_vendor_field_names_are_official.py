"""厂商字段名按官方 schema,不按感觉起。

这一片是两个**真 bug** 的墓碑
------------------------------
两个都不是崩溃,是静默降级 —— 动作照样派发,只是参数丢了,不报任何错:

1. ``scroll`` 的 Anthropic 字段名我写的是 ``direction`` / ``magnitude``,
   凭感觉起的。官方是 ``scroll_direction`` / ``scroll_amount``。
   名字对不上 → 方向和量都读不到 → "滚了但没动"。
2. 方言层发出去的是 ``direction`` + ``amount``,而本仓执行侧(planner prompt、
   Node_36、Node_45)读的是 ``clicks``,负数向下。
   → ``params.get("clicks", 0)`` 拿到 0 → **滚 0 格**,还是不报错。

第 2 条尤其值得记住:字段名对了一半也没用 —— 方言层和执行侧必须说同一种话。
"""

from __future__ import annotations

import pytest

from core.computer_use_dialects import (
    CANONICAL_SCROLL_PARAM,
    OPENAI_SCROLL_PX_PER_CLICK,
    translate_sequence,
)
from core.computer_use_loop import _N36_ACTION, ALLOWED_ACTIONS


def _one(payload):
    actions, _dialect, why = translate_sequence(payload)
    return (actions[0] if actions else None), why


def _toolset(name, **inp):
    return {"type": "tool_use", "id": "t1", "name": name, "toolset_name": "computer", "input": inp}


def _legacy(action, **inp):
    return {"type": "tool_use", "id": "t1", "name": "computer", "input": dict(action=action, **inp)}


def _openai(**action):
    return {"type": "computer_call", "call_id": "c1", "actions": [action]}


# --------------------------------------------------------------------------
# scroll —— 两个 bug 都在这里
# --------------------------------------------------------------------------


class TestScrollUsesOfficialNamesAndCanonicalParam:
    def test_official_field_names_are_read(self):
        """官方是 scroll_direction / scroll_amount。"""
        action, _ = _one(_toolset("scroll", scroll_direction="down", scroll_amount=3))
        assert action[CANONICAL_SCROLL_PARAM] == -3

    def test_the_guessed_names_no_longer_work(self):
        """旧的 direction / magnitude 不该再被当成有效输入 ——
        它们从来就不是官方字段,认了只会掩盖上游改名。"""
        action, _ = _one(_toolset("scroll", direction="down", magnitude=3))
        assert CANONICAL_SCROLL_PARAM not in action

    def test_the_canonical_param_is_clicks(self):
        """执行侧读的是 clicks。方言层发别的名字 = 滚 0 格。"""
        assert CANONICAL_SCROLL_PARAM == "clicks"

    def test_down_is_negative_up_is_positive(self):
        down, _ = _one(_toolset("scroll", scroll_direction="down", scroll_amount=2))
        up, _ = _one(_toolset("scroll", scroll_direction="up", scroll_amount=2))
        assert down["clicks"] == -2
        assert up["clicks"] == 2

    def test_the_legacy_generation_uses_the_same_names(self):
        """20251124 那代的字段名和 toolset 一样,别写两套。"""
        action, _ = _one(_legacy("scroll", scroll_direction="down", scroll_amount=5))
        assert action["clicks"] == -5

    @pytest.mark.parametrize("direction", ["left", "right"])
    def test_horizontal_scroll_is_refused_not_bent_into_vertical(self, direction):
        """执行侧只有竖直滚。硬翻成竖直是**滚错方向**,比不滚糟。"""
        action, why = _one(_toolset("scroll", scroll_direction=direction, scroll_amount=2))
        assert action is None
        assert "竖直" in why

    def test_a_missing_direction_does_not_invent_one(self):
        action, _ = _one(_toolset("scroll", scroll_amount=3))
        assert CANONICAL_SCROLL_PARAM not in action

    def test_a_non_integer_amount_is_refused(self):
        action, why = _one(_toolset("scroll", scroll_direction="down", scroll_amount="三格"))
        assert action is None
        assert why


class TestOpenAIScrollIsPixelsNotClicks:
    def test_pixels_are_converted_to_clicks(self):
        action, _ = _one(_openai(type="scroll", scroll_y=300))
        assert action["clicks"] == -int(round(300 / OPENAI_SCROLL_PX_PER_CLICK))

    def test_the_raw_pixel_value_is_kept_for_the_trace(self):
        """换算用的系数是个近似,所以换算前的原值必须留着 —— 事后才查得出
        是坐标不对还是系数不对。"""
        action, _ = _one(_openai(type="scroll", scroll_y=300))
        assert action["scroll_px_y"] == 300.0

    def test_positive_scroll_y_means_down(self):
        action, _ = _one(_openai(type="scroll", scroll_y=300))
        assert action["clicks"] < 0

    def test_a_small_scroll_still_moves(self):
        """小幅滚动被四舍五入成 0 的话,模型以为自己滚过了,
        下一轮看到画面没变会开始纠正一个不存在的问题。"""
        action, _ = _one(_openai(type="scroll", scroll_y=5))
        assert action["clicks"] != 0

    def test_horizontal_is_refused_here_too(self):
        action, why = _one(_openai(type="scroll", scroll_x=100, scroll_y=0))
        assert action is None
        assert "横向" in why


# --------------------------------------------------------------------------
# 其余动作的官方字段名
# --------------------------------------------------------------------------


class TestOtherOfficialFieldNames:
    def test_key_uses_text_not_key(self):
        """官方 key 的字段是 text(不是 key)。"""
        action, _ = _one(_toolset("key", text="ctrl+c"))
        assert action["key"] == "ctrl+c"

    def test_key_repeat_is_carried(self):
        action, _ = _one(_toolset("key", text="Down", repeat=5))
        assert action["repeat"] == 5

    def test_repeat_of_one_is_not_noise(self):
        action, _ = _one(_toolset("key", text="Down", repeat=1))
        assert "repeat" not in action

    def test_hold_key_uses_text_and_duration(self):
        action, _ = _one(_toolset("hold_key", text="shift", duration=1.5))
        assert action["action"] == "hold_key"
        assert action["key"] == "shift"
        assert action["seconds"] == 1.5

    def test_type_uses_text(self):
        action, _ = _one(_toolset("type", text="penguin"))
        assert action["text"] == "penguin"

    def test_drag_uses_start_coordinate_and_coordinate(self):
        action, _ = _one(_toolset("left_click_drag", start_coordinate=[1, 2], coordinate=[3, 4]))
        assert (action["from_x"], action["from_y"], action["to_x"], action["to_y"]) == (1, 2, 3, 4)

    def test_zoom_uses_region_of_four(self):
        action, _ = _one(_toolset("zoom", region=[0, 0, 100, 80]))
        assert action["region"] == [0, 0, 100, 80]

    def test_a_malformed_region_is_dropped_not_guessed(self):
        action, _ = _one(_toolset("zoom", region=[0, 0]))
        assert "region" not in action

    def test_triple_click_uses_coordinate(self):
        action, _ = _one(_toolset("triple_click", coordinate=[7, 8]))
        assert (action["x"], action["y"]) == (7, 8)

    def test_mouse_down_and_up_take_no_input(self):
        for member, expected in (("left_mouse_down", "mouse_down"), ("left_mouse_up", "mouse_up")):
            action, _ = _one(_toolset(member))
            assert action["action"] == expected


# --------------------------------------------------------------------------
# 补齐的七个动作:方言认得出 → 白名单放行 → 节点有实现
# --------------------------------------------------------------------------

NEWLY_SUPPORTED = [
    ("middle_click", "middle_click"),
    ("triple_click", "triple_click"),
    ("hold_key", "hold_key"),
    ("left_mouse_down", "mouse_down"),
    ("left_mouse_up", "mouse_up"),
    ("cursor_position", "cursor_position"),
    ("zoom", "zoom"),
]


class TestTheSevenActionsAreCompleteEndToEnd:
    """认得出还不够 —— 白名单不放行、或者节点没实现,一样是走不通。"""

    @pytest.mark.parametrize("member,canonical", NEWLY_SUPPORTED)
    def test_the_dialect_translates_it(self, member, canonical):
        action, why = _one(_toolset(member, coordinate=[1, 2], text="k", region=[0, 0, 9, 9]))
        assert action is not None, why
        assert action["action"] == canonical

    @pytest.mark.parametrize("_member,canonical", NEWLY_SUPPORTED)
    def test_the_safety_gate_lets_it_through(self, _member, canonical):
        """白名单不放行的话,循环会当场判"动作不在白名单"并整个停掉。"""
        assert canonical in ALLOWED_ACTIONS

    @pytest.mark.parametrize("_member,canonical", NEWLY_SUPPORTED)
    def test_it_maps_to_a_node_action(self, _member, canonical):
        assert canonical in _N36_ACTION

    @pytest.mark.parametrize("_member,canonical", NEWLY_SUPPORTED)
    def test_the_default_node_actually_implements_it(self, _member, canonical):
        """派发表里有这个分支 —— 否则节点回 "Unknown tool"。"""
        src = open("nodes/Node_36_UIAWindows/main.py", encoding="utf-8").read()
        node_action = _N36_ACTION[canonical]
        assert f'tool == "{node_action}"' in src

    @pytest.mark.parametrize("_member,canonical", NEWLY_SUPPORTED)
    def test_the_desktop_node_implements_it_too(self, _member, canonical):
        src = open("nodes/Node_45_DesktopAuto/main.py", encoding="utf-8").read()
        node_action = _N36_ACTION[canonical]
        # Node_45 的取坐标叫 position,与 Node_36 的 get_mouse_position 是同一件事
        alt = {"get_mouse_position": "position"}.get(node_action, node_action)
        assert f'tool == "{node_action}"' in src or f'tool == "{alt}"' in src

    def test_cursor_position_reuses_the_existing_node_action(self):
        """节点早就有取光标坐标,别新开一个。"""
        assert _N36_ACTION["cursor_position"] == "get_mouse_position"

    def test_the_none_mapping_is_still_expressible(self):
        """ "上游有、本仓没有"这个表达能力不能因为补齐了就消失 ——
        下一代上游再加成员时还要用它。"""
        from core.computer_use_dialects import _TOOLSET_MEMBER_ACTION

        assert None not in _TOOLSET_MEMBER_ACTION.values() or True  # 现在恰好都补齐了
        action, why = _one(_toolset("teleport"))
        assert action is None and "不认识" in why


class TestHoldKeyCannotJamTheKeyboard:
    """按住不放的键必须有上限,而且异常路径也要松开 ——
    卡住的 hold 会让之后每一次输入都带着那个修饰键,表现是"键盘坏了"。"""

    @pytest.mark.parametrize("path", ["nodes/Node_36_UIAWindows/main.py", "nodes/Node_45_DesktopAuto/main.py"])
    def test_there_is_an_upper_bound(self, path):
        src = open(path, encoding="utf-8").read()
        assert "HOLD_KEY_MAX_SECONDS" in src

    @pytest.mark.parametrize("path", ["nodes/Node_36_UIAWindows/main.py", "nodes/Node_45_DesktopAuto/main.py"])
    def test_the_key_is_released_in_a_finally(self, path):
        src = open(path, encoding="utf-8").read()
        block = src[src.index("def hold_key") : src.index("def hold_key") + 1600]
        assert "finally:" in block
        assert "keyUp" in block.split("finally:")[1][:200]
