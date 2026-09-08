"""按名字打开应用:一处实现,而且那条路真的通。

``device_control_service.open_app`` 的 Windows 兜底原来有**两条死路**,在同一段
代码里:

1. 一张写死的"应用名 → 绝对路径"表,只有微信和浏览器两条,路径只对"装在 C 盘
   默认位置的英文版 Windows"成立;
2. 它 POST 到 ``/open_app`` —— **Node_45 根本没有这个端点**。命中表也只会 404,
   这条兜底从来没成功过。

第 2 条尤其典型:旁边就有一句"修复:未配置的 app 之前返回 success=True 的假象"的
注释 —— 修的是同一处的另一半,而端点不存在这一半一直没人发现。
"""

import inspect
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _open_app_src() -> str:
    from core.device_control_service import DeviceControlService

    return inspect.getsource(DeviceControlService.open_app)


class TestNoHardcodedPathTable:
    def test_the_windows_path_table_is_gone(self):
        src = _open_app_src()
        assert "Program Files" not in src, "写死的绝对路径表又回来了"
        assert "WeChat.exe" not in src
        assert "chrome.exe" not in src.lower()

    def test_it_does_not_keep_an_app_name_to_path_mapping(self):
        src = _open_app_src()
        assert "app_paths" not in src, "路径表换个名字还是路径表"


class TestItCallsAnEndpointThatActuallyExists:
    def test_it_targets_launch_app_not_the_nonexistent_open_app(self):
        src = _open_app_src()
        # 只看**代码行** —— 注释里正解释着"以前调的是 /open_app,那是条死路",
        # 那段说明不该被当成真调用(和别处那条"提到显卡 ≠ 甩锅显卡"同一个道理)。
        code = "\n".join(ln for ln in src.split("\n") if not ln.lstrip().startswith("#"))
        assert "/launch_app" in code, "该走 Node_45 真有的那个端点"
        assert "/open_app" not in code, "/open_app 在 Node_45 上不存在,调它必然 404"

    def test_node_45_really_serves_that_endpoint(self):
        """判据要盯着**两边**:调用方改对了,被调方也真的有这个端点。

        只断言调用方写了 /launch_app 是不够的 —— 上一版死在这里的原因,
        正是没有人核对被调方到底有没有那个路由。
        """
        import importlib

        m = importlib.import_module("nodes.Node_45_DesktopAuto.main")
        paths = {r.path for r in m.app.routes if hasattr(r, "path")}
        assert "/launch_app" in paths
        assert "/open_app" not in paths, "如果哪天加了 /open_app,这两处该重新对齐"


class TestFailuresAreNeverReportedAsSuccess:
    def test_an_unreachable_node_is_reported_honestly(self):
        src = _open_app_src()
        # 连不上必须走进一个 success=False 的分支,而不是静默继续。
        assert "调不通" in src or 'success": False' in src or "'success': False" in src

    def test_launch_app_itself_refuses_an_empty_target(self):
        import importlib

        from fastapi.testclient import TestClient

        m = importlib.import_module("nodes.Node_45_DesktopAuto.main")
        body = TestClient(m.app).post("/launch_app", json={"target": ""}).json()
        assert body["success"] is False
