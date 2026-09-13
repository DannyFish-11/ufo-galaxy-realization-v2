"""nodes/Node_36_UIAWindows/desktop_uia.py — 桌面 UIA 采集(只读,可接线)
=========================================================================

为什么要有这个文件
------------------
桌面唯一一条真正读取 Windows UIA 控件树的代码,此前长在
:class:`nodes.Node_36_UIAWindows.ufo_deep_integration.UFODeepIntegration` 上。
那个类被 ``scripts/check_wiring.py`` **整体豁免为"故意不接线"**,理由写在
``_EXEMPT_NAMES['close_app']`` 里:它的 ``launch_app`` / ``close_app`` 能执行任意
二进制(``subprocess.Popen([app_path])``),上一轮暴露成 HTTP 接口时 CodeQL 当场判
critical,已撤回。

那条豁免是对的。但它的副作用是:**采集也一起被关在门外**。于是整个系统里"结构优先"
的桌面那条腿——``core/routes/ui_act.py`` 明确写着三个图源之一是桌面 UIA——实际上
没有任何活的生产者。``build_ui_graph`` 的非测试调用点只有那一处,而那一处够不着。

拆开之后边界就清楚了:

  · 本模块:**只读**。读控件树、按选择器查找。全文件没有 ``subprocess``、没有
    ``os.system``、不启动也不结束任何进程——这是可以接线的部分。
  · ``UFODeepIntegration``:继续被豁免,继续盖住 ``launch_app`` / ``close_app``。
    要接那两个得先定产品策略(允许启动哪些程序、谁有权调),那是产品决定。

换句话说,这次拆分没有放宽任何一条安全边界:危险的还在门外,只读的进来了。

为什么不做成类
--------------
做成模块级函数而不是类,是为了让"本模块不能启动进程"这件事**结构上成立**而不是
靠自觉:没有类,就没有人能通过继承或者往实例上挂方法把危险能力带进来。

可测性
------
沿用 :mod:`nodes.Node_36_UIAWindows.ui_tree` 的立场:真正连接桌面的那一步
(``pywinauto.Desktop``)通过 ``desktop_factory`` 注入,默认延迟 import 真的
pywinauto。于是:

  · 生产环境吃真实 pywinauto(Windows);
  · 单测塞一个假 Desktop 就能覆盖**全部判定逻辑**,无需 Windows、无需 pywinauto。

不可测的部分被压到最薄:只剩 ``_real_desktop_factory`` 里那一行 import 和
``Desktop(backend="uia")`` 本身。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Node36.DesktopUIA")

__all__ = [
    "DesktopUIAAvailability",
    "availability",
    "capture_desktop_graph",
    "get_ui_tree",
    "find_element",
    "find_elements",
    "BACKEND_PYWINAUTO_UIA",
    "BACKEND_UNAVAILABLE",
]

BACKEND_PYWINAUTO_UIA = "pywinauto_uia"
BACKEND_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DesktopUIAAvailability:
    """桌面 UIA 此刻可不可用,以及**为什么**。

    冻结,且 ``reason`` 永远非空。一个光秃秃的 ``False`` 不能告诉调用方这是
    "这台机器不是 Windows"(没法修)还是"pywinauto 没装"(装一下就好)——
    这两种要采取的行动完全不同。

    形状对齐 :class:`core.execution_isolation.IsolationDecision`:能力探测的结果
    必须自己说清楚它落在哪一档,而不是让调用方去猜。
    """

    available: bool
    backend: str
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "backend": self.backend,
            "reason": self.reason,
            **({"detail": self.detail} if self.detail else {}),
        }


def _real_desktop_factory() -> Any:
    """默认工厂:真的 pywinauto UIA 后端。仅 Windows 可用,故延迟 import。"""
    from pywinauto import Desktop  # noqa: PLC0415 — 延迟 import 是刻意的

    return Desktop(backend="uia")


def availability(*, desktop_factory: Optional[Callable[[], Any]] = None) -> DesktopUIAAvailability:
    """探测桌面 UIA 能不能用。**不读任何窗口**,只回答"这条路通不通"。

    单独拎出来,是因为 :mod:`core.routes.ui_act` 的自述接口需要在**不真的去抓一棵树**
    的前提下回答"桌面这条腿在不在"。拿采集失败去反推可用性是错的:一次采集失败可能
    只是当时没有前台窗口。
    """
    factory = desktop_factory or _real_desktop_factory
    try:
        desk = factory()
    except ImportError as exc:
        return DesktopUIAAvailability(
            available=False,
            backend=BACKEND_UNAVAILABLE,
            reason=f"pywinauto 不可用(非 Windows 或未安装): {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — 探测失败 ≠ 系统故障
        return DesktopUIAAvailability(
            available=False,
            backend=BACKEND_UNAVAILABLE,
            reason=f"UIA 后端初始化失败: {exc}",
        )
    if desk is None:
        return DesktopUIAAvailability(
            available=False,
            backend=BACKEND_UNAVAILABLE,
            reason="desktop_factory 返回 None",
        )
    return DesktopUIAAvailability(
        available=True,
        backend=BACKEND_PYWINAUTO_UIA,
        reason="pywinauto UIA 后端就绪",
    )


def capture_desktop_graph(
    window_title: Optional[str] = None,
    max_depth: int = 40,
    *,
    desktop_factory: Optional[Callable[[], Any]] = None,
) -> Optional[Dict[str, Any]]:
    """读一棵真实的 Windows UIA 控件树 → 结构化 UIGraph(dict)。

    这是桌面 system-API 的"结构优先"输入:对着语义控件图(名为『发送』的按钮)推理,
    而不是对着像素猜坐标。拿不到时返回 ``None``,由上层决定回退视觉——本函数不替
    上层决定回退策略。

    ``window_title`` 缺省取前台窗口。
    """
    factory = desktop_factory or _real_desktop_factory
    try:
        desk = factory()
    except Exception as exc:  # noqa: BLE001
        logger.info("桌面 UIA 不可用(非 Windows / 缺 pywinauto): %s", exc)
        return None
    if desk is None:
        return None

    from .ui_tree import build_ui_graph

    try:
        win = desk.window(title=window_title) if window_title else desk.window(active_only=True)
        ctl = win.wrapper_object()
        app = ""
        try:
            app = ctl.window_text()
        except Exception:  # noqa: BLE001 — 取不到标题不该让整次采集失败
            pass
        graph = build_ui_graph(ctl, app=app, device_id="windows", max_depth=max_depth)
        return graph.model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.warning("桌面 UIA 采集失败: %s", exc)
        return None


def get_ui_tree(
    window_title: Optional[str] = None,
    max_depth: int = 40,
    *,
    desktop_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """结构化界面树端点。返回 ``{success, graph?, prompt?, error?, reason?}``。

    失败时带上 :func:`availability` 给出的 ``reason`` —— 只回一个
    ``ui_tree_unavailable`` 等于让调用方去猜是没装 pywinauto 还是当时没有前台窗口。
    """
    graph = capture_desktop_graph(window_title, max_depth, desktop_factory=desktop_factory)
    if graph is None:
        avail = availability(desktop_factory=desktop_factory)
        return {
            "success": False,
            "error": "ui_tree_unavailable",
            "reason": avail.reason if not avail.available else "UIA 可用,但这次没抓到窗口",
            "availability": avail.to_dict(),
        }
    prompt = ""
    try:
        from core.schemas.ui_element import UIGraph

        prompt = UIGraph.model_validate(graph).to_prompt()
    except Exception as exc:  # noqa: BLE001 — 提示词生成失败不该丢掉已经抓到的树
        logger.debug("to_prompt 生成失败(树本身有效): %s", exc)
    return {"success": True, "graph": graph, "prompt": prompt}


def find_elements(
    selector: Dict[str, Any],
    *,
    window_title: Optional[str] = None,
    desktop_factory: Optional[Callable[[], Any]] = None,
) -> List[Dict[str, Any]]:
    """按选择器查找全部匹配控件。

    selector 支持 ``name`` / ``label`` · ``automation_id`` · ``class_name`` ·
    ``control_type`` / ``role``。匹配规则是 :func:`ui_tree.find_in_graph` 那一份,
    **不在这里重写一遍** —— 两份选择器语义必然会漂,而漂的时候现场看不出是谁匹配的。
    """
    graph = capture_desktop_graph(window_title, desktop_factory=desktop_factory)
    if graph is None:
        return []
    from core.schemas.ui_element import UIGraph

    from .ui_tree import find_in_graph

    try:
        return [n.model_dump() for n in find_in_graph(UIGraph.model_validate(graph), selector)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("选择器匹配失败: %s", exc)
        return []


def find_element(
    selector: Dict[str, Any],
    *,
    window_title: Optional[str] = None,
    desktop_factory: Optional[Callable[[], Any]] = None,
) -> Optional[Dict[str, Any]]:
    """按选择器查找单个控件;命中多个时可交互控件优先(排序在 find_in_graph 里)。"""
    hits = find_elements(selector, window_title=window_title, desktop_factory=desktop_factory)
    return hits[0] if hits else None
