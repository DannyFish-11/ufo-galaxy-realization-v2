"""Node 36 的权限白名单必须和它真正能做的事对得上 —— **两个方向都要**。

`core/node_action_permissions.py` 是 fail-closed 的:节点一旦声明了动作白名单,
不在白名单里的动作走 `invoke_node` 时直接拒绝。于是声明与实现一旦对不上,
两个方向各有一种坏法,而且**都不报错**:

  · 声明了却分发不到 → 权限闸放行,然后撞上 "Unknown tool"。读 manifest 的人
    会以为这个节点有这个能力;
  · 实现了却没声明 → 这个动作从 invoke_node 那条路**永远调不到**,而它明明在
    HTTP 面上活着。能力在、路没接。

两种都只有在真去调那一次才会发现。所以钉在这里。

排查到的实况(本次修掉):
  声明却分发不到:close / find_element / find_elements / focus / get_ui_tree /
                 maximize / minimize / restore
  实现却没声明:  hold_key / middle_click / mouse_down / mouse_up / triple_click / zoom
"""

from __future__ import annotations

import json
import pathlib
import re

#: /health、/status、/help 是节点自述,不是被派发的动作。
_META_ACTIONS = {"health", "status", "help"}


def _repo_root() -> pathlib.Path:
    for cand in (pathlib.Path("."), pathlib.Path("..")):
        if (cand / "config" / "node_catalog.json").is_file():
            return cand
    raise AssertionError("找不到 config/node_catalog.json —— 这里刻意不跳过")


def _declared() -> set[str]:
    d = json.loads((_repo_root() / "config" / "node_catalog.json").read_text(encoding="utf-8"))
    node = next(n for n in d["nodes"] if n.get("num") == 36)
    return set(node["permissions"]["actions"])


def _dispatchable() -> set[str]:
    """`UIATools.call_tool` 的分发表 —— 这才是**动作面**。

    刻意**不含 HTTP 路由**:路由名和动作名是两套(`/move` ↔ `move_mouse`、
    `/type` ↔ `type_text`、`/windows` ↔ `list_windows`)。权限闸
    (`node_action_permissions.evaluate_action_permission`)管的是动作名,
    `invoke_node` 转发的也是动作名。把路由混进来会让这条守卫拿两套命名去比,
    报出一堆假阳性 —— 第一版就是这么错的。

    顺带一个已知事实(本次不改,只记下来):**HTTP 路由完全不过权限闸**,
    白名单只保护 `invoke_node` 那条路。锁死节点自己的 HTTP 面是另一个决定。
    """
    src = (_repo_root() / "nodes" / "Node_36_UIAWindows" / "main.py").read_text(encoding="utf-8")
    names = set(re.findall(r'tool == "([a-z_]+)"', src))
    for group in re.findall(r"tool in \(([^)]+)\)", src):
        names |= {t.strip().strip('"') for t in group.split(",") if t.strip()}
    return names


def test_every_declared_action_is_dispatchable():
    missing = sorted(_declared() - _dispatchable() - _META_ACTIONS)
    assert not missing, (
        f"manifest 声明了这些动作,但分发表接不住:{missing}。"
        "走 invoke_node 会过了权限闸再撞 Unknown tool —— 而读 manifest 的人以为它有这个能力。"
    )


def test_every_dispatchable_action_is_declared():
    undeclared = sorted(_dispatchable() - _declared() - _META_ACTIONS)
    assert not undeclared, (
        f"这些动作实现了却没进 manifest:{undeclared}。"
        "node_action_permissions 是 fail-closed 的 —— 它们从 invoke_node 那条路永远调不到。"
    )


def test_the_structural_actions_delegate_and_are_not_reimplemented():
    """get_ui_tree / find_element / find_elements 转发给 desktop_uia,不在这里再写一份。

    两份实现必然会漂,而漂的时候现场看不出是哪一份抓的树。
    """
    src = (_repo_root() / "nodes" / "Node_36_UIAWindows" / "main.py").read_text(encoding="utf-8")
    assert "from .desktop_uia import" in src, "结构化动作没有委托给 desktop_uia"
    # 不许在 main.py 里出现第二份控件树构建
    assert "build_ui_graph" not in src, "main.py 里自己建了一棵控件树 —— 那是 ui_tree 的事"
    assert "pywinauto" not in src, "main.py 直接碰了 pywinauto —— 采集应当只经 desktop_uia"


def test_window_subactions_are_reachable_by_their_declared_names():
    """manifest 把 focus/minimize/... 声明成顶层动作,实现是 window_action 的子动作。

    不补这一层转发,`invoke_node(action="focus")` 会过了权限闸再撞 Unknown tool。
    """
    src = (_repo_root() / "nodes" / "Node_36_UIAWindows" / "main.py").read_text(encoding="utf-8")
    for name in ("focus", "minimize", "maximize", "restore", "close"):
        assert name in _dispatchable(), f"{name} 声明为顶层动作却分发不到"
    assert 'self.window_action(params.get("title", ""), tool)' in src, "顶层窗口动作没有转发给 window_action"


# ── 统一执行器真的能走到实现(端到端,不是读源码)────────────────────────────
def _run(action: str, **params):
    """经 fusion_entry 走一遍 `invoke_node` 实际用的那条路。"""
    import asyncio
    import sys

    node_dir = str((_repo_root() / "nodes" / "Node_36_UIAWindows").resolve())
    if node_dir not in sys.path:
        sys.path.insert(0, node_dir)
    from nodes.Node_36_UIAWindows.fusion_entry import get_node_instance

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(get_node_instance().execute(action, **params))
    finally:
        loop.close()


def test_invoke_node_path_actually_reaches_the_implementation():
    """这条路此前**什么都执行不了**。

    `invoke_node` 把动作名转发给节点的 `execute`;`FusionNode.execute` 在实例上按序
    找 process / execute / run / handle,一个都没有就返回一句泛化错误。本节点的动作面
    叫 `call_tool`,四个名字一个都不占 —— 实测:

        execute('click') → {'success': False, 'error': 'No executable method found'}

    而这条路正是 `core/routes/ui_act.py` 结构化命中之后的派发目标:读控件图、
    grounding 命中、算出坐标 —— 全做完了,最后一步掉在地上。
    """
    out = _run("click", x=1, y=2)
    assert out.get("success") is True, f"统一执行器入口没接上:{out}"
    assert "No executable method found" not in str(out)


def test_an_unknown_action_says_unknown_not_no_executable_method():
    """两种失败必须分得开。

    "这个动作不支持"是正常结果;"找不到可执行方法"是接线断了。报同一句话,
    前者会把后者盖住 —— 而后者是整条链路不通。
    """
    out = _run("this_action_does_not_exist")
    assert "Unknown tool" in str(out)
    assert "No executable method found" not in str(out)


def test_each_action_fails_with_its_own_honest_reason():
    """本环境不是 Windows。每个动作要报**自己的**原因,而不是一句笼统的失败。

    报得准才看得出是"这台机器不是 Windows"(没法修)还是"pywinauto 没装"(装一下
    就好)—— 这两种要采取的行动完全不同。
    """
    assert "Windows" in str(_run("click", x=1, y=2))
    assert "pywinauto" in str(_run("get_ui_tree"))
    assert "pygetwindow" in str(_run("focus", title="x"))
