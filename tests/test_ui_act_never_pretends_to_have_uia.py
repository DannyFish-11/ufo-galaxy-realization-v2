"""服务端不是那台 Windows 时,不许装作用上了 UIA。

``WindowsExecutionArbiter`` 长在 ``core/`` 里,在 Linux 上一样 import 得进来 ——
只是它的 Level 1/2 适配器都需要 Windows(``_make_default_uia_executor`` import 失败
时静默返回 None),于是 ``_try_uia`` 一律 SKIPPED、直接降到坐标级。

从外面看,"跑了仲裁器"和"跑了仲裁器并且用上了 UIA"长得一模一样。这正是跨设备
部署下的常态:服务端在 Linux,目标 Windows 是另一台机器。不把这一层区分出来,
``ui_act`` 会在跨设备下静默降级,而响应里看不出任何异样。
"""

from __future__ import annotations

from core.windows_execution_arbiter import WindowsExecutionArbiter


def _bare_arbiter() -> WindowsExecutionArbiter:
    """一个四级全空的仲裁器 —— 等价于"这台机器不是 Windows"。"""
    return WindowsExecutionArbiter(
        system_api_executor=None,
        uia_executor=None,
        gui_executor=None,
        vlm_executor=None,
        use_defaults=False,
    )


def test_arbiter_says_whether_it_actually_has_uia():
    a = _bare_arbiter()
    assert a.uia_available is False


def test_arbiter_reports_uia_once_an_executor_is_set():
    a = _bare_arbiter()

    async def _fake_uia(action, params, device_id):
        return {"success": True}

    a.set_executors(uia=_fake_uia)
    assert a.uia_available is True


def test_the_flag_is_not_just_sys_platform():
    """判据必须是"这一级接上了没有",不是"这是不是 Windows"。

    两者不等价:Windows 上也可能因为 comtypes 没装好而拿不到 UIA 执行器,那时
    按平台判会得出"有 UIA"的错误结论,然后一路盲点坐标还以为自己在按身份操作。
    """
    import inspect

    src = inspect.getsource(WindowsExecutionArbiter.uia_available.fget)
    assert "sys.platform" not in src and "platform" not in src.replace("平台", "")
    assert "self._uia" in src
