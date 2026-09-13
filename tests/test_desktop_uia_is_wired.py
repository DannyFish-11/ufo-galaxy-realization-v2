"""桌面 UIA 采集:拆出来之后**真的接得上**,而且拆分没放宽任何安全边界。

这组测试守两件事,它们同等重要:

1. 只读采集能在没有 Windows 的机器上被完整驱动(注入假 Desktop),于是"桌面那条腿"
   的判定逻辑是可测的——此前它整个长在一个被豁免不接线的类上,连测都测不到。
2. 拆出来的模块**没有把危险能力一起带出来**。``launch_app`` / ``close_app`` 能执行
   任意二进制,CodeQL 判过 critical;它们必须留在门外。一次"顺手把整个类搬过来"的
   重构会悄悄把它们放进活路径,而且不会有任何测试变红——除非有人专门钉这一条。
"""

from __future__ import annotations

import pathlib

import pytest

from nodes.Node_36_UIAWindows import desktop_uia


# ── 假控件 / 假 Desktop(鸭子类型,和 ui_tree 同一套立场)──────────────────────
class _FakeCtl:
    def __init__(self, name, ctype="Button", aid="", children=None, rect=(0, 0, 10, 10)):
        self._name = name
        self._ctype = ctype
        self._aid = aid
        self._children = children or []
        self._r = rect

    def window_text(self):
        return self._name

    def element_info(self):
        return self

    @property
    def control_type(self):
        return self._ctype

    @property
    def automation_id(self):
        return self._aid

    def friendly_class_name(self):
        return self._ctype

    def rectangle(self):
        class _R:
            left, top, right, bottom = self._r

        r = _R()
        r.left, r.top, r.right, r.bottom = self._r
        return r

    def children(self):
        return self._children


class _FakeWindow:
    def __init__(self, ctl):
        self._ctl = ctl

    def wrapper_object(self):
        return self._ctl


class _FakeDesktop:
    def __init__(self, ctl):
        self._ctl = ctl
        self.asked_active_only = None
        self.asked_title = None

    def window(self, title=None, active_only=None):
        self.asked_title = title
        self.asked_active_only = active_only
        return _FakeWindow(self._ctl)


def _tree():
    return _FakeCtl(
        "记事本",
        ctype="Window",
        children=[
            _FakeCtl("发送", ctype="Button", aid="send_btn"),
            _FakeCtl("取消", ctype="Button", aid="cancel_btn"),
        ],
    )


# ── 可用性探测 ────────────────────────────────────────────────────────────────
def test_availability_says_why_when_pywinauto_is_missing():
    def _boom():
        raise ImportError("No module named 'pywinauto'")

    a = desktop_uia.availability(desktop_factory=_boom)
    assert not a.available
    assert a.backend == desktop_uia.BACKEND_UNAVAILABLE
    # reason 必须说清是"没装"而不是别的 —— 光一个 False 不告诉调用方该做什么
    assert "pywinauto" in a.reason


def test_availability_distinguishes_missing_from_broken():
    def _broken():
        raise RuntimeError("COM 初始化失败")

    a = desktop_uia.availability(desktop_factory=_broken)
    assert not a.available
    assert "COM" in a.reason or "初始化" in a.reason
    # 这两种要采取的行动不同:一个是装依赖,一个是查环境。reason 必须能分开。
    missing = desktop_uia.availability(desktop_factory=lambda: (_ for _ in ()).throw(ImportError("x")))
    assert a.reason != missing.reason


def test_availability_ok_with_a_live_backend():
    a = desktop_uia.availability(desktop_factory=lambda: _FakeDesktop(_tree()))
    assert a.available
    assert a.backend == desktop_uia.BACKEND_PYWINAUTO_UIA


def test_availability_never_probes_a_window():
    # 探测不该去抓树:一次采集失败可能只是当时没有前台窗口,拿它反推"UIA 不可用"是错的。
    desk = _FakeDesktop(_tree())
    desktop_uia.availability(desktop_factory=lambda: desk)
    assert desk.asked_active_only is None and desk.asked_title is None


# ── 采集 ──────────────────────────────────────────────────────────────────────
def test_capture_builds_a_uia_graph():
    g = desktop_uia.capture_desktop_graph(desktop_factory=lambda: _FakeDesktop(_tree()))
    assert g is not None
    assert g["source"] == "uia"
    assert g["device_id"] == "windows"


def test_capture_defaults_to_the_foreground_window():
    desk = _FakeDesktop(_tree())
    desktop_uia.capture_desktop_graph(desktop_factory=lambda: desk)
    assert desk.asked_active_only is True and desk.asked_title is None


def test_capture_honours_an_explicit_title():
    desk = _FakeDesktop(_tree())
    desktop_uia.capture_desktop_graph("记事本", desktop_factory=lambda: desk)
    assert desk.asked_title == "记事本"


def test_capture_returns_none_instead_of_raising():
    # 拿不到就是 None,由上层决定要不要回退视觉。本函数不替上层定回退策略。
    def _boom():
        raise ImportError("no pywinauto")

    assert desktop_uia.capture_desktop_graph(desktop_factory=_boom) is None


# ── 端点语义 ──────────────────────────────────────────────────────────────────
def test_get_ui_tree_failure_says_which_kind_of_failure():
    out = desktop_uia.get_ui_tree(desktop_factory=lambda: (_ for _ in ()).throw(ImportError("no pywinauto")))
    assert out["success"] is False
    # 只回 ui_tree_unavailable 等于让调用方猜是没装还是没窗口
    assert out["reason"] and "pywinauto" in out["reason"]
    assert out["availability"]["available"] is False


def test_get_ui_tree_success_carries_graph_and_prompt():
    out = desktop_uia.get_ui_tree(desktop_factory=lambda: _FakeDesktop(_tree()))
    assert out["success"] is True
    assert out["graph"]["source"] == "uia"
    assert isinstance(out["prompt"], str)


# ── 选择器 ────────────────────────────────────────────────────────────────────
def test_find_element_by_automation_id():
    hit = desktop_uia.find_element({"automation_id": "send_btn"}, desktop_factory=lambda: _FakeDesktop(_tree()))
    assert hit is not None and hit["automation_id"] == "send_btn"


def test_find_elements_empty_when_no_tree():
    assert desktop_uia.find_elements({"name": "发送"}, desktop_factory=lambda: None) == []


def test_selector_semantics_are_not_reimplemented_here():
    # 两份选择器语义必然会漂,而漂的时候现场看不出是谁匹配的。
    src = pathlib.Path("nodes/Node_36_UIAWindows/desktop_uia.py").read_text(encoding="utf-8")
    assert "find_in_graph" in src, "没有复用 ui_tree 的匹配实现"
    assert "_selector_pred" not in src, "在这里重写了一份选择器语义"


# ── 拆分没有放宽安全边界(这一条和上面所有条同等重要)────────────────────────
def test_the_split_did_not_carry_process_spawning_along():
    """只读模块的**代码**里不许出现任何启动/结束进程的能力。

    launch_app / close_app 能执行任意二进制(subprocess.Popen 那一类),上一轮暴露成
    HTTP 接口时 CodeQL 当场判 critical。它们留在 UFODeepIntegration 里、继续被
    check_wiring 豁免盖住。这一条钉的是:**它们没有跟着搬过来**。

    查的是 AST 不是原文。第一版用字符串扫,结果抓住了本模块 docstring 里解释
    这条边界本身的那几个词 —— 而那段解释正是要留下的。改成 AST 之后这道闸更严
    (``foo.Popen`` 这种拼不出来的写法也挡得住),同时不再惩罚文档。
    """
    import ast

    src = pathlib.Path("nodes/Node_36_UIAWindows/desktop_uia.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    banned_modules = {"subprocess", "multiprocessing", "pty", "shlex"}
    banned_attrs = {"Popen", "system", "popen", "spawn", "spawnv", "spawnl", "execv", "execl", "fork", "run"}
    banned_defs = {"launch_app", "close_app"}

    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in banned_modules:
                    problems.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in banned_modules:
                problems.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Attribute):
            if node.attr in banned_attrs:
                base = getattr(node.value, "id", "") or getattr(node.value, "attr", "")
                # os.system / subprocess.run 这类;放过无关的 .run(例如未来某个 runner)
                if base in {"os", "subprocess", "sp"}:
                    problems.append(f"{base}.{node.attr}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in banned_defs:
                problems.append(f"def {node.name}")

    assert not problems, f"只读模块里出现了危险能力: {problems} —— 它们被带进了活路径"


def test_read_only_module_exposes_no_class_to_hang_powers_on():
    """模块级函数,不是类。

    没有类就没人能通过继承或往实例上挂方法把危险能力带进来 —— 让"本模块只读"
    结构上成立,而不是靠自觉。
    """
    import inspect

    classes = [n for n, o in vars(desktop_uia).items() if inspect.isclass(o) and o.__module__ == desktop_uia.__name__]
    # 只允许那个冻结的结果载体
    assert classes == ["DesktopUIAAvailability"], f"意外的类: {classes}"
