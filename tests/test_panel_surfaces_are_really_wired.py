"""面板上这几处必须**真的接在后端上**,不是画出来好看。

这个文件守的是本仓最常见的那种失效:**操作有反馈,结果没有。** 每一条都对应
一次真实存在过的断线:

* 「喂文件」四个入口点得动、浮层会收起,而 ``platform().pickFiles()`` 的返回值
  **被丢掉了** —— 用户选完文件,界面毫无变化,他以为喂进去了。
* 「隐私暂停」在面板上**根本没有入口**,只能改 .env 再重启;而这个动作要的恰恰
  是此刻立刻生效。
* 面板每次打开都是一屏空白,而后端明明记着上一轮 —— 那不是「新对话」,是看起来
  失忆。
* 左栏那叠卡片没有数据源。

判据一律落在**构建产物**上而不是源码:``dist/`` 是提交进仓库的、Electron 直接
加载它。源码接上了而 dist 没重建,界面照常打开,只是那一块什么都不做 —— 这是
这条路上最难看出来的一种断线。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_SRC = REPO_ROOT / "electron" / "renderer" / "panel" / "src"
DIST = REPO_ROOT / "electron" / "renderer" / "panel" / "dist" / "assets"


@pytest.fixture(scope="module")
def bundle() -> str:
    js = sorted(DIST.glob("*.js"))
    if not js:
        pytest.fail(
            "dist/assets 下一个 js 都没有。dist/ 必须提交进仓库 —— "
            "修法: cd electron/renderer/panel && npm ci && npm run build"
        )
    return "\n".join(p.read_text(encoding="utf-8") for p in js)


def _code_only(path: Path) -> str:
    """去掉注释的源码。

    **必须比对去掉注释后的代码。** 这些文件里的说明注释大量提到端点路径和函数名,
    直接在整份文件里搜,测的是「文件里有没有提到这个名字」,而要测的是「还有没有
    代码在用它」。这个仓库为同样的写法栽过两次。
    """
    src = path.read_text(encoding="utf-8")
    return re.sub(r"^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S), flags=re.M)


class TestEveryNewlyWiredEndpointIsInTheBuiltBundle:
    """产物里必须真的有这些路径 —— 没有就说明 dist/ 没跟着源码重建。"""

    @pytest.mark.parametrize(
        ("endpoint", "what"),
        [
            ("/api/v1/sessions/ingest_turns", "喂文件"),
            ("/api/perception/desktop/privacy", "隐私暂停"),
            ("/api/v1/memory/cards", "记忆卡片"),
            ("/api/v1/chat/stream", "对话"),
        ],
    )
    def test_the_endpoint_is_reachable_from_the_built_page(self, bundle: str, endpoint: str, what: str):
        assert endpoint in bundle, (
            f"构建产物里没有 {endpoint} —— 「{what}」在界面上照常画得出来、" "点得动,但什么都不会发生"
        )

    def test_history_is_read_back_on_open(self, bundle: str):
        """开面板时要把上次那条对话读回来,否则每次打开都像失忆。"""
        assert "/history" in bundle, "构建产物里没有会话历史那条路 —— 面板每次打开都是一屏空白"


class TestThePickedFilesAreActuallyUsed:
    """``pickFiles()`` 的返回值不许被丢掉。

    这条钉的是一个具体的回归:从前那行是 ``void platform().pickFiles(accept)``
    —— 拿到 ``File[]`` 之后什么都不做。它比「按钮没反应」难查得多,因为**是有
    反馈的**(浮层收起来了),只是结果不存在。
    """

    def test_the_result_is_handed_to_a_callback(self):
        code = _code_only(PANEL_SRC / "ui" / "dock.ts")
        assert "pickFiles" in code, "dock.ts 里没有 pickFiles 了?那这条判据要跟着改"
        assert re.search(r"pickFiles\([^)]*\)\s*\.then", code), (
            "pickFiles() 的返回值没有被接住 —— 选完文件之后什么都不会发生," "而浮层照样收起,用户以为喂进去了"
        )
        assert "onFeed" in code, "接住了却没往上交给谁"


class TestDegradationIsVisibleNotSilent:
    """降级必须留痕 —— 这几处都出过「静默」的版本。"""

    def test_an_empty_answer_says_so(self):
        """一个 delta 都没来的那一轮不许画成空气泡。

        实测撞到过:锁步 ``engaged`` 而这台机器没有可用发声器时,后端一个 delta
        都不发,整段答复只在 done 帧的 response 里。只认 delta 的话答复就丢了,
        而空气泡跟「它想了想没什么好说的」长得一模一样。
        """
        code = _code_only(PANEL_SRC / "main.ts")
        assert re.search(r"onDone:\s*\(response\)", code), (
            "onDone 不再接 done 帧里的 response —— 锁步吞掉 delta 的那种情况下," "整轮答复会丢掉,面板画出一个空气泡"
        )
        assert "response ||" in code or "|| response" in code, "接了 response 却没拿它兜底"

    def test_a_failed_turn_is_not_only_a_console_warning(self):
        """出错的那一轮要在**界面上**说,不能只写 console。"""
        code = _code_only(PANEL_SRC / "main.ts")
        m = re.search(r"onError:\s*\(msg\)\s*=>\s*\{(.*?)\n        \}", code, re.S)
        assert m, "main.ts 里找不到 onError 了?"
        body = m.group(1)
        assert "patchAgent" in body, "onError 只写了日志 —— 出错的那一轮在界面上还是个空气泡"

    def test_privacy_has_three_states_not_two(self):
        """``null``(还没问到后端)不许被当成「正在采」。

        说错任何一边都比说「不知道」糟:说成已暂停会让人放心地在摄像头前做别的事;
        说成正在采会让人以为按钮坏了。
        """
        code = _code_only(PANEL_SRC / "ui" / "island.ts")
        assert "privacyPaused === null" in code, "隐私状态被压成了两态 —— 「不知道」没有自己的样子"

    def test_cards_and_history_keep_null_distinct_from_empty(self):
        """「没拉到」与「确实是空的」在状态里必须分得开。"""
        store = _code_only(PANEL_SRC / "store.ts")
        assert (
            "readonly cards: readonly MemoryCard[] | null" in store
        ), "cards 不再可为 null —— 「还没拉到」会被画成「这条线上什么都没有」,而那是句谎话"
        assert "readonly privacyPaused: boolean | null" in store


class TestTheSessionIdComesFromTheBackend:
    """会话 id 必须是后端认下的那个,面板不许自己编。

    编一个的话,历史、记忆卡片、补录三条路问出来的永远是空的 —— 而且每一条都
    「成功」返回,没有任何一处报错。
    """

    def test_the_meta_frame_is_no_longer_ignored(self):
        code = _code_only(PANEL_SRC / "transport.ts")
        assert "onSession" in code, "meta 帧里的 session_id 又被丢掉了"
        assert re.search(r"case 'meta'", code), "SSE 分发里没有 meta 分支"

    def test_the_panel_does_not_invent_one(self):
        """不许出现自造 id 的痕迹(``session_`` 前缀 + 随机数)。"""
        code = _code_only(PANEL_SRC / "main.ts")
        assert not re.search(r"['\"]session[_-]['\"]\s*\+", code), "面板在自己拼会话 id"
