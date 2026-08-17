"""覆盖层深度运动的接线门 —— 纯结构检查，不需要 node。

为什么要这一层
--------------
`electron/renderer/presence_motion.js` 的**行为**由 `presence_motion.test.js`
用 node 跑（CI 的 panel-dist-consistency 作业里）。但那个作业装了 node，而
pytest 的分片作业没有；如果在 pytest 里写"有 node 才跑"的跳过守卫，它会变成
一条永远不执行的绿线 —— 这仓库栽过这种跟头。

所以这里只钉**接线**，不钉物理：脚本有没有被加载、加载顺序对不对、有没有人
把物理又内联回 app.js。这三件事恰好是最容易在重构里被无声弄坏的，而且不用
跑 JS 就能查。
"""

from __future__ import annotations

import pathlib

import pytest

_RENDERER = pathlib.Path(__file__).parent.parent / "electron" / "renderer"


@pytest.fixture(scope="module")
def index_html() -> str:
    return (_RENDERER / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_js() -> str:
    return (_RENDERER / "app.js").read_text(encoding="utf-8")


class TestMotionScriptIsLoaded:
    def test_presence_motion_file_exists(self) -> None:
        assert (_RENDERER / "presence_motion.js").is_file()

    def test_index_html_loads_it(self, index_html: str) -> None:
        assert "presence_motion.js" in index_html, "覆盖层没有加载 presence_motion.js —— 深度运动会整个停摆"

    def test_loaded_before_app_js(self, index_html: str) -> None:
        """顺序错了 app.js 的渲染循环就取不到它（会走那条'保持静止'的兜底）。"""
        assert index_html.index("presence_motion.js") < index_html.index(
            'src="app.js"'
        ), "presence_motion.js 必须早于 app.js 加载"


class TestPhysicsIsNotInlinedBack:
    """防回归：物理被内联回 app.js 的话，node 那 9 条测试就测不到真正在跑的代码。"""

    @pytest.mark.parametrize("marker", ["CHOREO_UP", "CHOREO_DOWN", "springV +="])
    def test_app_js_no_longer_holds_the_physics(self, app_js: str, marker: str) -> None:
        assert marker not in app_js, f"app.js 里又出现了 {marker!r} —— 物理被内联回去了，测试就跟丢了"

    def test_app_js_delegates_to_presence_motion(self, app_js: str) -> None:
        assert "PresenceMotion.advance" in app_js, "app.js 没有调用 PresenceMotion.advance"


class TestPostureReachesTheRenderer:
    def test_app_js_reads_posture_from_payload(self, app_js: str) -> None:
        """姿态没被读进来的话，倾向就还是只影响目的地、不影响过程。"""
        assert "payload.posture" in app_js, "app.js 没有从 payload 里读 posture"

    def test_app_js_reads_the_faithful_contract_too(self, app_js: str) -> None:
        """双轴忠实契约必须也被读进来。

        在场桥每一帧同时广播 ``payload.posture``（一维遗留投影）与
        ``payload.render``（RenderPosture 双轴契约），其源码注释写着
        「新代码应当消费这一份」。覆盖层此前只读前者，于是副轴四相、
        ``is_returning``、``transition_kind``、两条执行链在渲染端根本不存在 ——
        退场只能把进场动画倒放。
        """
        assert "payload.render" in app_js, "app.js 没有从 payload 里读 render —— 退场语汇无从谈起"

    def test_motion_prefers_the_faithful_contract(self, app_js: str) -> None:
        """运动学优先读 render，读不到才退回 posture。

        两份姿态的 collapse_tendency / retreat_tendency / stability 由同一份
        ContinuumState 导出、逐位相同，所以这是纯换源：观感不变，但覆盖层从此
        不再依赖那份一维遗留投影。保留 ``|| this.posture`` 是降级路径 ——
        老后端不发 render 时行为与改造前一致。
        """
        assert "posture: this.render || this.posture" in app_js, (
            "运动函数拿到的不是「优先忠实契约、缺席时退回遗留投影」的那一份 —— " "要么姿态没传进去，要么优先级反了"
        )


class TestNodeSuiteIsActuallyRunSomewhere:
    """自证：上面那些结构检查只有在 node 那套真的会跑时才够用。

    钉住 CI 里确实有一条命令在跑 presence_motion.test.js —— 否则本文件会
    退化成"文件在、字符串在"的假绿，而真正的物理无人验证。
    """

    def test_ci_runs_the_node_suite(self) -> None:
        ci = (pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "presence_motion.test.js" in ci, "CI 里没有任何一步在跑覆盖层运动测试"

    def test_node_suite_file_exists(self) -> None:
        assert (_RENDERER / "presence_motion.test.js").is_file()
