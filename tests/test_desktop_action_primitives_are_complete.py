"""桌面动作原语要**够用**,而且用不了时要如实说。

对照 GUI-VLA 类模型(如 Mano-P)的动作空间:
``click / type / hotkey / scroll / drag / mouse move / screenshot / wait /
app launch / URL navigation``。

Node_45 原来缺 ``drag`` / ``wait`` / ``launch_app`` / ``open_url`` 四个。缺了会怎样:
模型规划出一串动作,执行层接不住其中几步 —— 而这不是"模型不行",是这边没有那个动词。
"""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import importlib

    m = importlib.import_module("nodes.Node_45_DesktopAuto.main")
    return TestClient(m.app)


@pytest.fixture(scope="module")
def paths(client):
    import importlib

    m = importlib.import_module("nodes.Node_45_DesktopAuto.main")
    return {r.path for r in m.app.routes if hasattr(r, "path")}


class TestTheActionSpaceIsCovered:
    @pytest.mark.parametrize(
        "path",
        [
            "/click",
            "/double_click",
            "/type",
            "/hotkey",
            "/press",
            "/move",
            "/scroll",
            "/screenshot",
            "/drag",
            "/wait",
            "/launch_app",
            "/open_url",
        ],
    )
    def test_the_verb_exists(self, paths, path):
        assert path in paths, f"执行层没有 {path} —— 模型规划出这一步就落不了地"


class TestWaitWorksEvenWithoutADesktop:
    """``wait`` 跟有没有桌面**无关**。

    其余动作在无头机器上都降级了,它照样该能用:模型的一串动作里夹着 wait,
    不该因为这一步"不可用"就把整条动作链打断。
    """

    def test_it_succeeds_regardless_of_pyautogui(self, client):
        r = client.post("/wait", json={"seconds": 0.05})
        assert r.json()["success"] is True

    def test_it_actually_waits(self, client):
        t0 = time.time()
        client.post("/wait", json={"seconds": 0.3})
        assert time.time() - t0 >= 0.25

    def test_an_absurd_duration_is_capped_and_the_cap_is_visible(self, client):
        """模型给个离谱的秒数,不该把这条请求挂死;但也要看得出被削过。"""
        body = client.post("/wait", json={"seconds": 99999}).json()
        assert body["waited_seconds"] == 60.0
        assert body["requested_seconds"] == 99999.0, "削了就要说削了,不能假装等满了"

    def test_negative_is_clamped_to_zero(self, client):
        assert client.post("/wait", json={"seconds": -5}).json()["waited_seconds"] == 0.0


class TestOpenUrlDoesNotPretend:
    def test_non_http_schemes_are_refused(self, client):
        """webbrowser.open 会把 file:// 也照开 —— 那是本地文件读取面。"""
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x/y"):
            body = client.post("/open_url", json={"url": bad}).json()
            assert body["success"] is False, f"{bad} 不该被放行"

    def test_it_reports_failure_when_there_is_no_browser(self, client):
        """没有可用浏览器时必须回 False。

        一律报成功就是"看起来打开了,其实没有" —— 上层据此往下走,错得无声无息。
        """
        body = client.post("/open_url", json={"url": "https://example.com"}).json()
        assert isinstance(body["success"], bool)
        if not body["success"]:
            assert body["error"], "失败了就要说为什么"


class TestLaunchAppHasNoHardcodedPathTable:
    def test_empty_target_is_rejected(self, client):
        assert client.post("/launch_app", json={"target": "   "}).json()["success"] is False

    def test_a_missing_binary_says_so_instead_of_claiming_success(self, client):
        body = client.post("/launch_app", json={"target": "definitely-not-a-real-binary-xyz"}).json()
        assert body["success"] is False
        assert body["error"]

    def test_the_source_does_not_hardcode_app_paths(self):
        """不许在这里放"应用名 → 绝对路径"的字典。

        那种表一写死就只对写它的那台机器成立(装在 D 盘、换了语言、绿色版全都
        不认),而且会跟别处的同类表散成两处。
        """
        import os

        src = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "nodes",
                "Node_45_DesktopAuto",
                "main.py",
            ),
            encoding="utf-8",
        ).read()
        launch = src[src.index("async def launch_app") :]
        launch = launch[: launch.index('@app.post("/open_url")')]
        assert "C:\\\\Program Files" not in launch
        assert ".exe" not in launch, "写死可执行文件名就是把某一台机器的布局钉进代码"


class TestDegradedActionsStillSayWhy:
    @pytest.mark.parametrize(
        "path,body",
        [
            ("/drag", {"from_x": 1, "from_y": 2, "to_x": 3, "to_y": 4}),
            ("/click", {"x": 1, "y": 2}),
        ],
    )
    def test_when_the_desktop_is_missing_the_reason_is_given(self, client, path, body):
        import importlib

        m = importlib.import_module("nodes.Node_45_DesktopAuto.main")
        r = client.post(path, json=body).json()
        if m.pyautogui is None:
            assert r["success"] is False
            assert r["error"], "用不了就得说为什么"
            assert "没装" not in r["error"] or "pyautogui 没装" in r["error"]
