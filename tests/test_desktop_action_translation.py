"""结构化命中之后,派给仲裁器的必须是能用上 UIA 的那个动作词。

``ui_act`` 此前把命中结果派到 Node_36 的 ``/click {x,y}`` —— 那是仲裁器四级链里
**最弱的一级**(Level 3 坐标),而 Level 2(按控件身份的 find_and_click)就在隔壁、
一路到底都是通的。这组测试钉的是那句翻译,以及"退坐标必须说出来"。
"""

from __future__ import annotations

from core import desktop_action_translation as dat


def _node(**kw):
    base = {"node_id": "0.3.1", "automation_id": "", "label": "", "role": "button"}
    base.update(kw)
    return base


# ── 身份择取 ──────────────────────────────────────────────────────────────────
def test_automation_id_wins_and_name_is_not_sent_alongside():
    # _action_find_and_click 的分支是 `if name: ... elif automation_id:` —— 两个都给
    # 时 name 赢,而 name 是可见文本(会随语言/状态变、可能重名)。所以有 id 就只给 id,
    # 否则那条更稳的路永远走不到。
    ident = dat.identity_of(_node(automation_id="send_btn", label="发送"))
    assert ident == {"automation_id": "send_btn"}
    assert "name" not in ident


def test_label_is_used_when_there_is_no_automation_id():
    assert dat.identity_of(_node(label="发送")) == {"name": "发送"}


def test_node_id_is_never_treated_as_identity():
    # node_id 是树路径("0.3.1"),窗口多一个子控件它就变。拿它当身份是把位置当标识。
    assert dat.identity_of(_node()) == {}


def test_blank_identity_is_not_identity():
    assert dat.identity_of(_node(automation_id="   ", label="\t")) == {}


def test_missing_node_is_not_identity():
    assert dat.identity_of(None) == {}


# ── 翻译 ──────────────────────────────────────────────────────────────────────
def test_identity_click_goes_to_level_2():
    d = dat.translate(kind="tap", node=_node(automation_id="ok"), coordinates=(5, 6))
    assert d.action == dat.ARBITER_FIND_AND_CLICK
    assert d.params == {"automation_id": "ok"}
    assert d.identity_used is True and d.degraded is False
    # 有身份时坐标不该跟着发下去 —— 仲裁器 Level 2 不需要它,带上只会让人以为它被用了
    assert "x" not in d.params


def test_identity_typing_goes_to_find_and_type_with_text():
    d = dat.translate(kind="set_text", node=_node(label="搜索框"), text="你好")
    assert d.action == dat.ARBITER_FIND_AND_TYPE
    assert d.params == {"name": "搜索框", "text": "你好"}
    assert d.degraded is False


def test_no_identity_falls_back_to_coordinates_but_is_degraded():
    d = dat.translate(kind="tap", node=_node(), coordinates=(10, 20))
    assert d.action == dat.ARBITER_CLICK
    assert d.params == {"x": 10, "y": 20}
    assert d.identity_used is False
    assert d.degraded is True  # 能点成 ≠ 点对了
    assert d.dispatchable is True
    assert "落空" in d.reason  # 为什么弱,必须留在结果里


def test_no_identity_typing_still_carries_the_text():
    d = dat.translate(kind="type", node=None, coordinates=(1, 2), text="abc")
    assert d.action == dat.ARBITER_TYPE
    assert d.params == {"x": 1, "y": 2, "text": "abc"}
    assert d.degraded is True


def test_neither_identity_nor_coordinates_is_an_explicit_failure():
    d = dat.translate(kind="tap", node=None, coordinates=None)
    assert d.dispatchable is False
    assert d.action == ""
    assert "不猜一个中心点" in d.reason


def test_degraded_and_dispatchable_are_different_things():
    # 退坐标是「弱」不是「失败」;没有任何依据才是失败。两者混在一起就没法区分
    # 「点了但可能点错」和「根本没点」。
    weak = dat.translate(kind="tap", node=_node(), coordinates=(1, 1))
    dead = dat.translate(kind="tap", node=None, coordinates=None)
    assert weak.degraded and weak.dispatchable
    assert dead.degraded and not dead.dispatchable


def test_dict_form_carries_the_accounting():
    d = dat.translate(kind="tap", node=_node(automation_id="x"), coordinates=(1, 1)).to_dict()
    assert d["action"] == "find_and_click"
    assert d["identity_used"] is True
    assert d["degraded"] is False
    assert d["reason"]
