"""面板：能叫停，只有一个相位来源，而且那份上下文是齐的。

判据落在**去掉注释的源码**上（产物里的端点另有 test_panel_surfaces_are_really_wired
那道门）：要钉的是「还有没有代码这样做」，不是「文件里有没有提到这个词」。
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "electron" / "renderer" / "panel" / "src"


def _code(rel: str) -> str:
    src = (_SRC / rel).read_text(encoding="utf-8")
    return re.sub(r"^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S), flags=re.M)


class TestPhaseHasOneWriter:
    """「此刻」只有一个权威 —— WS 的 payload.render。

    面板自己发起的那几轮里,SSE 的 phase 帧也往同一个状态位上写过:两路各有各的时序,
    线和岛会在两个相位之间来回跳一下。
    """

    def test_the_sse_phase_frame_is_not_read(self) -> None:
        assert "onPhase" not in _code("main.ts"), "面板又接了 SSE 的 phase 帧 —— 同一个状态位两个写者"
        assert "onPhase" not in _code("transport.ts")

    def test_phase_is_written_only_from_the_posture(self) -> None:
        main = _code("main.ts")
        writers = re.findall(r"phase:\s*toPhase\(", main)
        assert len(writers) == 1, f"phase 的写者不止一处:{len(writers)}"
        assert "toPhase(posture.lifecycle)" in main


class TestItCanBeStopped:
    def test_the_send_button_doubles_as_stop(self) -> None:
        dock = _code("ui/dock.ts")
        assert "onStop()" in dock and "cb.onStop()" in dock
        assert "'stop'" in dock, "停止键没有自己的样子 —— 余光里分不出按下去是「说」还是「停」"

    def test_stop_shows_while_it_works_or_acts(self) -> None:
        main = _code("main.ts")
        assert re.search(
            r"s\.chatBusy\s*\|\|\s*Boolean\(s\.posture\?\.acting\)", main
        ), "停止键只在面板自己那一轮里出现 —— 它因为一句语音在动鼠标键盘时,面板上没法停"

    def test_stop_asks_the_backend_first(self) -> None:
        main = _code("main.ts")
        body = main[main.index("async function stop()") :][:400]
        assert body.index("stopActivity(") < body.index("abort()"), "先断开 SSE 只停得了面板自己那一轮 —— 要先让后端停"

    def test_a_stopped_turn_says_so(self) -> None:
        main = _code("main.ts")
        assert "onDone: (response, stopped)" in main
        assert "你叫停的" in main, "被叫停的那一轮说成了「后端什么都没给」"


class TestTheContextIsWhole:
    def test_the_panel_opens_on_the_mainline(self) -> None:
        main = _code("main.ts")
        body = main[main.index("async function restoreSession()") :][:600]
        assert "fetchPrimarySession(BASE)" in body
        assert body.index("fetchPrimarySession(") < body.index(
            "recallSession()"
        ), "面板只认本地记着的那一条 —— 面板关着时语音里说过的话,重开就看不到"

    def test_its_own_echo_is_not_drawn_twice(self) -> None:
        transport = _code("transport.ts")
        assert re.search(r"payload\['client_id'\]\s*===\s*this\.#clientId", transport)
        main = _code("main.ts")
        assert re.search(r"client_id:\s*clientId", main), "发起那一轮没带 client_id,回声认不出来"
        assert re.search(r"\},\s*clientId\);", main), "WS 那条连接不知道自己是谁,认不出回声"

    def test_a_voice_reply_only_extends_its_own_bubble(self) -> None:
        """语音那边的一句话不能拼进打字那一轮还在流的气泡里。"""
        main = _code("main.ts")
        assert "wsLive" in main
        body = main[main.index("function appendTurn(") :][:900]
        assert "last.streaming" not in body, "又回到了「最后一个在流的同角色气泡就续」"
