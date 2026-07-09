"""tests/test_node36_ui_tree.py
=================================

Windows System API(UIA)→ 结构化 UIGraph 的序列化与选择器搜索。
用最小假控件(鸭子类型)覆盖,无需 Windows / pywinauto。
"""
from __future__ import annotations

import importlib.util
import os

import pytest

# Node_36 目录名不是合法包名,用文件路径直接加载 ui_tree 模块。
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UT_PATH = os.path.join(_HERE, "nodes", "Node_36_UIAWindows", "ui_tree.py")
_spec = importlib.util.spec_from_file_location("node36_ui_tree", _UT_PATH)
ui_tree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui_tree)

from core.schemas.ui_element import UISource, UIActionKind


class _Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _EI:
    def __init__(self, control_type, automation_id=""):
        self.control_type = control_type
        self.automation_id = automation_id


class _Ctl:
    """最小假 pywinauto 控件(鸭子类型)。"""
    def __init__(self, control_type, text="", *, rect=None, enabled=True, visible=True,
                 automation_id="", class_name="", focused=False, toggle=None, children=None):
        self._ct = control_type
        self._text = text
        self.element_info = _EI(control_type, automation_id)
        self._rect = rect
        self._enabled = enabled
        self._visible = visible
        self._class = class_name or control_type
        self._focused = focused
        self._toggle = toggle
        self._children = children or []

    def window_text(self):
        return self._text

    def rectangle(self):
        return self._rect

    def is_enabled(self):
        return self._enabled

    def is_visible(self):
        return self._visible

    def class_name(self):
        return self._class

    def has_keyboard_focus(self):
        return self._focused

    def get_toggle_state(self):
        return self._toggle

    def children(self):
        return self._children


def _window():
    return _Ctl("Window", "记事本", rect=_Rect(0, 0, 1280, 800), children=[
        _Ctl("Edit", "文本区", rect=_Rect(0, 40, 1280, 760), automation_id="editor", focused=True),
        _Ctl("Button", "保存", rect=_Rect(1100, 0, 1200, 40), automation_id="saveBtn"),
        _Ctl("CheckBox", "自动换行", rect=_Rect(0, 0, 100, 40), toggle=True),
        _Ctl("Text", "状态栏", rect=_Rect(0, 760, 1280, 800)),
    ])


class TestControlToNode:
    def test_roles_and_states_mapped(self):
        node = ui_tree.control_to_node(_window())
        assert node.role == "window" and node.label == "记事本"
        edit = node.find(lambda n: n.role == "edit")
        assert edit.editable and edit.focused and edit.automation_id == "editor"
        assert UIActionKind.SET_TEXT in edit.actions
        btn = node.find(lambda n: n.role == "button")
        assert btn.clickable and UIActionKind.TAP in btn.actions
        assert btn.source is UISource.UIA

    def test_checkbox_tristate(self):
        node = ui_tree.control_to_node(_window())
        cb = node.find(lambda n: n.role == "checkbox")
        assert cb.checked is True

    def test_bounds_from_rect(self):
        node = ui_tree.control_to_node(_window())
        btn = node.find(lambda n: n.role == "button")
        assert btn.bounds.x == 1100 and btn.bounds.width == 100 and btn.bounds.height == 40

    def test_text_is_not_interactive(self):
        node = ui_tree.control_to_node(_window())
        txt = node.find(lambda n: n.role == "text")
        assert not txt.is_interactive()

    def test_max_depth_stops_recursion(self):
        node = ui_tree.control_to_node(_window(), max_depth=0)
        assert node.children == []

    def test_bad_control_does_not_crash(self):
        class Bad:
            def window_text(self):
                raise RuntimeError("window gone")
        node = ui_tree.control_to_node(Bad())
        assert node.label == ""  # 异常被吞,给空


class TestBuildGraphAndFind:
    def test_build_graph_prompt(self):
        g = ui_tree.build_ui_graph(_window(), device_id="windows")
        assert g.source is UISource.UIA and g.device_id == "windows"
        out = g.to_prompt()
        assert '"保存"' in out and "{editable,focused}" in out

    def test_find_by_automation_id(self):
        g = ui_tree.build_ui_graph(_window())
        hits = ui_tree.find_in_graph(g, {"automation_id": "saveBtn"})
        assert len(hits) == 1 and hits[0].label == "保存"

    def test_find_by_name_and_role(self):
        g = ui_tree.build_ui_graph(_window())
        hits = ui_tree.find_in_graph(g, {"name": "自动换行", "role": "checkbox"})
        assert len(hits) == 1 and hits[0].checked is True

    def test_empty_selector_matches_nothing(self):
        g = ui_tree.build_ui_graph(_window())
        assert ui_tree.find_in_graph(g, {}) == []

    def test_find_interactive_ranked_first(self):
        # 两个同名控件,一个可交互一个不可 → 可交互排前
        w = _Ctl("Window", "x", children=[
            _Ctl("Text", "确定"),
            _Ctl("Button", "确定", rect=_Rect(0, 0, 10, 10)),
        ])
        g = ui_tree.build_ui_graph(w)
        hits = ui_tree.find_in_graph(g, {"name": "确定"})
        assert hits[0].role == "button"
