"""桌面这条腿通不通、下一次点击走哪条路 —— 必须问得出来。

这条链上每一环都可能"看起来在工作,其实没有":

  · 采集拿不到(不是 Windows / 没装 pywinauto)→ 结构图这条腿是空的,但 ui_act
    照样能用视觉投影跑,从响应上看不出差别;
  · 仲裁器 import 得进来但 Level 1/2 是空的 → "跑了仲裁器"和"用上了 UIA"
    长得一模一样,而后者才是按控件身份操作;
  · 于是最后一米可能是 InvokePattern,也可能是盲点坐标。

不把这三件事合成一句可问的结论,调用方只能从日志里猜 —— 而这三种情况下
它拿到的响应是一样的。
"""

from __future__ import annotations

import core.routes.ui_act as ui_act
from core.routes.ui_act import desktop_perception_state


def test_it_answers_all_four_questions():
    st = desktop_perception_state()
    for key in ("grounding_owner", "uia_capture", "arbiter_uia_available", "next_click_route"):
        assert key in st, f"自述里缺 {key}"


def test_the_route_conclusion_is_one_of_two_known_values():
    # "下一次会走哪条路"必须是确定的两者之一,不能是"看情况"。
    assert desktop_perception_state()["next_click_route"] in ("uia_invoke", "coordinates")


def test_on_a_host_without_uia_it_says_coordinates_not_silence():
    """本环境没有 pywinauto。它必须**说出来**,而不是留空让人以为一切正常。"""
    st = desktop_perception_state()
    assert st["arbiter_uia_available"] is False
    assert st["next_click_route"] == "coordinates"
    assert st["uia_capture"]["available"] is False
    # 原因要说清是"没装"还是别的 —— 这两种要采取的行动不同
    assert st["uia_capture"]["reason"], "拿不到 UIA 却没给原因"


def test_the_coordinate_route_explains_what_it_costs():
    # 只说"走坐标"不够:调用方得知道这一下可能落空,而且落在哪儿不可知。
    note = desktop_perception_state()["next_click_note"]
    assert "落空" in note
    assert "agent_deploy" in note, "没有指出跨设备该走哪条路"


def test_capability_probing_never_touches_a_window():
    """这是**能力探测**,不是"试一次看看"。

    不抓窗口、不派动作、不改状态。拿一次失败去反推能力是错的 ——
    一次采集失败可能只是当时没有前台窗口。
    """
    import inspect

    src = inspect.getsource(desktop_perception_state)
    for forbidden in ("capture_desktop_graph", "get_ui_tree", "execute(", "dispatch"):
        assert forbidden not in src, f"自述里调用了 {forbidden} —— 那是动作不是探测"


def test_it_hangs_off_the_existing_perception_endpoint():
    """扩展既有的 /perception,不另起一个自述端点。

    两个自述端点必然会漂,而漂的时候你看到的两份"当前状态"互相矛盾。
    """
    src = __import__("inspect").getsource(ui_act.ui_perception_state)
    assert 'out["desktop"] = desktop_perception_state()' in src


def test_a_broken_probe_degrades_instead_of_raising(monkeypatch):
    # 自述接口自己不能成为故障源:探测失败要如实报,不能把整个 /perception 打挂。
    import nodes.Node_36_UIAWindows.desktop_uia as duia

    def _boom():
        raise RuntimeError("探测炸了")

    monkeypatch.setattr(duia, "availability", _boom)
    st = desktop_perception_state()
    assert st["uia_capture"]["available"] is False
    assert "探测失败" in st["uia_capture"]["reason"]
