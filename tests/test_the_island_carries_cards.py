"""灵动岛上的卡片(core.island_cards):这台电脑上刚发生、人该余光知道的事。

借 WinIslands 的上岛推送,只取适合这里的:一张卡一个 id 原地更新、分先后、会过期、带进度、只放类型化短字段。
推卡的三处:桌面操作(走到第几步 → 核对的结论)、「没收口的结果」、等你同意的设备。到岛上走 ``/ws/desktop-presence``
一帧 ``type="island"``;覆盖层刚连上补发一份。覆盖层那一侧的行为见 electron/renderer/browser-tests/island.test.js。
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.island_cards as ic

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh_island():
    ic.get_island_cards().reset()
    yield ic.get_island_cards()
    ic.get_island_cards().reset()


class _Bridge:
    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def _ws_broadcast(self, msg: Dict[str, Any]) -> None:
        self.sent.append(msg)


@pytest.fixture()
def bridge(monkeypatch):
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    fake = _Bridge()
    monkeypatch.setattr(GalaxyPresenceBridge, "get_instance", classmethod(lambda cls: fake))
    return fake


# ── 队列 ──────────────────────────────────────────────────────────────────────


def test_same_id_updates_in_place_and_keeps_its_place(fresh_island):
    fresh_island.post("a", kind="computer_use", title="正在操作电脑", subtitle="第 1/5 步", progress=0.0, ttl_s=None)
    fresh_island.post("b", kind="result", title="有结果没收口")
    fresh_island.post("a", kind="computer_use", title="正在操作电脑", subtitle="第 2/5 步", progress=0.2, ttl_s=None)
    cards = fresh_island.active()
    assert [c["id"] for c in cards] == ["b", "a"], "同级新的在前;a 原地更新,不因为更新就插到最前"
    assert cards[1]["subtitle"] == "第 2/5 步" and cards[1]["progress"] == 0.2
    assert len(cards) == 2


def test_priority_then_newest(fresh_island):
    fresh_island.post("low", kind="x", title="低", priority="low")
    fresh_island.post("n1", kind="x", title="普通一")
    fresh_island.post("high", kind="x", title="高", priority="high")
    fresh_island.post("n2", kind="x", title="普通二")
    assert [c["id"] for c in fresh_island.active()] == ["high", "n2", "n1", "low"]


def test_cards_expire_on_their_own(fresh_island):
    fresh_island.post("short", kind="x", title="一下就走", ttl_s=0.5)
    fresh_island.post("stay", kind="x", title="一直在", ttl_s=None)
    assert {c["id"] for c in fresh_island.active()} == {"short", "stay"}
    assert [c["expires_in_s"] for c in fresh_island.active() if c["id"] == "stay"] == [None]
    time.sleep(0.6)
    assert [c["id"] for c in fresh_island.active()] == ["stay"]


def test_the_queue_is_bounded_and_drops_the_least_important(fresh_island):
    fresh_island.post("keep", kind="x", title="要紧", priority="high")
    for i in range(ic.MAX_CARDS + 3):
        fresh_island.post(f"n{i}", kind="x", title=f"第 {i} 张", priority="low")
    ids = [c["id"] for c in fresh_island.active()]
    assert len(ids) == ic.MAX_CARDS and ids[0] == "keep"


def test_only_short_typed_fields_go_out(fresh_island):
    assert fresh_island.post("", kind="x", title="没 id") is None
    assert fresh_island.post("x", kind="x", title="   ") is None
    card = fresh_island.post(
        "x",
        kind="x",
        title="标题" * 40,
        subtitle="副" * 200,
        body="正文" * 200,
        progress=7,
        tone="rainbow",
        priority="urgent",
        action="rm -rf",
    )
    assert len(card["title"]) <= 24 and len(card["subtitle"]) <= 48 and len(card["body"]) <= 160
    assert card["progress"] == 1.0 and card["tone"] == "info" and card["priority"] == "normal" and card["action"] == ""
    assert set(card) == {
        "id",
        "kind",
        "title",
        "subtitle",
        "body",
        "progress",
        "tone",
        "priority",
        "action",
        "expires_in_s",
    }


# ── 推到岛上 ──────────────────────────────────────────────────────────────────


def test_every_change_broadcasts_the_whole_queue_on_the_presence_socket(fresh_island, bridge):
    async def run():
        fresh_island.post("a", kind="x", title="一")
        fresh_island.post("b", kind="x", title="二")
        fresh_island.remove("a")
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert [m["type"] for m in bridge.sent] == ["island"] * 3
    assert [[c["id"] for c in m["payload"]["cards"]] for m in bridge.sent] == [["a"], ["b", "a"], ["b"]]
    assert bridge.sent[-1]["payload"]["seq"] > bridge.sent[0]["payload"]["seq"]


def test_a_card_posted_from_another_thread_reaches_the_loop(fresh_island, bridge):
    """补跑计时器在别的线程里隔离一条结果 —— 卡照样要上岛(交回记下的那个事件循环)。"""

    async def run():
        fresh_island.post("seed", kind="x", title="先在循环里推一张")
        worker = threading.Thread(target=lambda: fresh_island.post("t", kind="x", title="线程里推的"))
        worker.start()
        await asyncio.to_thread(worker.join)
        await asyncio.sleep(0.1)

    asyncio.run(run())
    assert any(c["id"] == "t" for m in bridge.sent for c in m["payload"]["cards"])


def test_no_loop_no_crash(fresh_island):
    assert ic.post_card("x", kind="x", title="脚本里推") is not None
    ic.remove_card("x")
    ic.remove_card("never-there")


def test_a_fresh_overlay_gets_the_cards_already_up(fresh_island, monkeypatch):
    from core import presence_fanout

    sent: List[Dict[str, Any]] = []

    class _WS:
        async def send_json(self, msg):
            sent.append(msg)

    async def no_feed(ws, timeout):
        return None

    monkeypatch.setattr(presence_fanout, "_send_feed", no_feed)

    async def run():
        fresh_island.post("cu", kind="computer_use", title="正在操作电脑", ttl_s=None)
        presence_fanout.welcome(_WS(), 1.0)
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert [m["type"] for m in sent] == ["island"]
    assert sent[0]["payload"]["cards"][0]["id"] == "cu"


# ── 谁推卡 ────────────────────────────────────────────────────────────────────


def test_computer_use_steps_then_verdict_on_one_card(fresh_island, monkeypatch):
    import core.computer_use_verdict as verdict
    from core.computer_use_loop import _island_finished, _island_step

    _island_step("cu:1", 1, 5, "")
    _island_step("cu:1", 3, 5, "click")
    [c] = fresh_island.active()
    assert (c["title"], c["subtitle"], c["progress"], c["action"], c["expires_in_s"]) == (
        "正在操作电脑",
        "第 3/5 步 · 刚点击",
        0.4,
        "stop",
        None,
    )
    _island_finished("cu:1", {"stop_reason": "done"})
    assert fresh_island.active()[0]["subtitle"] == "对着屏幕核对中…"

    async def screen():
        return "c2NyZWVu"

    async def yes(instruction, shot):
        return {"done": True, "reason": "记事本在前台"}

    asyncio.run(verdict.settle("开记事本", {"stop_reason": "done", "run_id": "cu:1"}, perceive=screen, ask=yes))
    [c] = fresh_island.active()
    assert (c["id"], c["title"], c["tone"]) == ("cu:1", "做完了", "success"), "结论原地换上,不是第二张卡"


def test_a_run_the_model_gave_up_on_says_so(fresh_island):
    from core.computer_use_loop import _island_finished

    _island_finished("cu:2", {"stop_reason": "max_steps", "message": "15 步用完了"})
    [c] = fresh_island.active()
    assert (c["title"], c["tone"], c["subtitle"]) == ("没做成", "error", "15 步用完了")


def test_the_loop_puts_its_progress_on_the_island(fresh_island, monkeypatch):
    import core.computer_use_loop as cul

    seen: List[str] = []
    real = cul._island_step

    def spy(card_id, step, limit, last):
        seen.append(f"{step}/{limit}")
        real(card_id, step, limit, last)

    monkeypatch.setattr(cul, "_island_step", spy)
    monkeypatch.setattr(cul, "computer_use_enabled", lambda: True)

    async def no_screen():
        return None

    loop = cul.ComputerUseLoop(perceive_fn=no_screen, memory=_NoMemory())
    out = asyncio.run(loop.run("开记事本", max_steps=3))
    assert seen == ["1/3"] and out["stop_reason"] == "no_perception"
    assert out["run_id"].startswith("cu:")
    [c] = fresh_island.active()
    assert c["id"] == out["run_id"] and c["title"] == "没做成"


def test_a_dry_run_stays_off_the_island(fresh_island, monkeypatch):
    import core.computer_use_loop as cul

    monkeypatch.setattr(cul, "computer_use_enabled", lambda: True)

    async def no_screen():
        return None

    out = asyncio.run(cul.ComputerUseLoop(perceive_fn=no_screen, memory=_NoMemory()).run("看看", dry_run=True))
    assert "run_id" not in out and fresh_island.active() == []


class _NoMemory:
    async def recall_experience_parts(self, instruction):
        return []

    async def remember_outcome(self, *a, **kw):
        return None


def test_an_isolated_result_puts_one_summary_card_up(fresh_island, tmp_path):
    from core.truth_chain_recovery import TruthChainRecovery

    rec = TruthChainRecovery(store_path=tmp_path / "isolated.json")
    rec.isolate("k1", "computer_use", {"task_id": "k1"}, {"instruction": "x"}, "没打开")
    rec.isolate("k2", "computer_use", {"task_id": "k2"}, {"instruction": "y"}, "没打开")
    [c] = fresh_island.active()
    assert (c["id"], c["subtitle"], c["action"], c["tone"]) == (
        "truth_chain:isolated",
        "2 条等你看 · 面板「全部设置」最上面",
        "panel",
        "warning",
    )
    assert "没打开" not in c["body"], "岛上只有条数,不带结果内容"


def test_a_stranger_at_the_door_is_on_the_island(fresh_island, tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.delenv("GALAXY_ONBOARDING_AUTO", raising=False)
    monkeypatch.delenv("GALAXY_ONBOARDING_ENABLED", raising=False)
    from core.device_onboarding import service

    service.reset_onboarding_service()
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    try:
        with TestClient(app) as client:
            r = client.post("/api/v1/devices/register", json={"device_id": "stranger-isl", "device_name": "客厅平板"})
            assert r.status_code == 202
    finally:
        service.reset_onboarding_service()
    [c] = [c for c in fresh_island.active() if c["kind"] == "device"]
    assert (c["title"], c["subtitle"], c["priority"], c["action"]) == ("有设备在等你同意", "客厅平板", "high", "panel")


def test_once_the_owner_decides_the_card_leaves(fresh_island, monkeypatch):
    from core.device_onboarding import service as onboarding

    class _Cands:
        def __init__(self):
            self.rows = {"cand-1": type("C", (), {"status": "needs_human", "to_dict": lambda self: {}})()}

        def get(self, cid):
            return self.rows.get(cid)

        def put(self, cid, cand):
            self.rows[cid] = cand

    svc = onboarding.OnboardingService.__new__(onboarding.OnboardingService)
    svc.candidates = _Cands()
    fresh_island.post("device:pending:cand-1", kind="device", title="有设备在等你同意", ttl_s=None)
    assert svc.ignore("cand-1")["success"] is True
    assert fresh_island.active() == [], "人已经在面板上定了,岛上那张卡还挂着就是一句过时的话"


# ── 接口 ──────────────────────────────────────────────────────────────────────


def test_the_island_endpoints(fresh_island, auth_headers):
    from core.routes import observability

    fresh_island.post("device:pending:abc", kind="device", title="有设备在等你同意")
    app = FastAPI()
    app.include_router(observability.create_router())
    with TestClient(app) as client:
        assert client.get("/api/v1/presence/island").status_code in (401, 403), "卡片里有设备名,要令牌"
        body = client.get("/api/v1/presence/island", headers=auth_headers).json()
        assert [c["id"] for c in body["cards"]] == ["device:pending:abc"]
        assert client.delete("/api/v1/presence/island/device:pending:abc", headers=auth_headers).status_code == 200
        assert client.delete("/api/v1/presence/island/device:pending:abc", headers=auth_headers).status_code == 404
    assert fresh_island.active() == []


# ── 桌宠还是那一只 ────────────────────────────────────────────────────────────


def test_the_pet_still_sits_on_the_island_unchanged():
    """卡片来去,岛上那只桌宠的外形与眼睛一点没动(三只同一只的核对在 test_every_pet_is_the_same_pet)。"""
    html = (REPO / "electron" / "renderer" / "index.html").read_text(encoding="utf-8")
    island = html[html.index('<div id="island">') : html.index('<div class="isl-full"')]
    assert '<svg id="pet"' in island
    assert 'class="pet-skin" d="M20 4.6c8 0 13.6 4.2 15 11' in island
    app_js = (REPO / "electron" / "renderer" / "app.js").read_text(encoding="utf-8")
    assert "PetState.derive(" in app_js, "桌宠的推导还是三只共用的那一份"


# ── winsland 借来的那几样：静态接线 ───────────────────────────────────────────
#
# 行为（声波、感知点、已复制、换页）在 electron/renderer/browser-tests/island.test.js 里问真浏览器，
# 弹簧与状态在 electron/renderer/island.test.js，剪贴板提示在 electron/clipboard_watch.test.js。
# 这里只钉那几条读源码就能看出来、而浏览器测试替身看不出来的接线。

_RENDERER = REPO / "electron" / "renderer"


def test_island_js_loads_before_app_js():
    """app.js 构造时就 new IslandView —— 晚一步加载，覆盖层整个起不来（而浏览器测试会一起红，CI 能抓到；这里给一句人话）。"""
    html = (_RENDERER / "index.html").read_text(encoding="utf-8")
    assert '<script src="island.js"></script>' in html
    assert html.index('<script src="island.js">') < html.index('<script src="app.js">')


def test_the_clipboard_only_ever_crosses_as_a_kind():
    """剪贴板的原文不出主进程：主进程发给覆盖层的只有 watchClipboard 给的 {type}，预加载只转发这一条。"""
    main = (REPO / "electron" / "main.js").read_text(encoding="utf-8")
    watch = (REPO / "electron" / "clipboard_watch.js").read_text(encoding="utf-8")
    preload = (REPO / "electron" / "preload.js").read_text(encoding="utf-8")
    assert "watchClipboard(clipboard," in main
    assert "webContents.send('galaxy:clipboard', msg)" in main
    # 主进程里除了交给 watchClipboard，别处不读剪贴板
    assert "clipboard.read" not in main, "main.js 自己读剪贴板了 —— 内容会不会顺手发出去，就没人能一眼看清"
    sends = re.findall(r"send\(\{([^}]*)\}\)", watch)
    assert sends == [" type: kindOf(now.formats) "], f"发出去的不只是类别：{sends}"
    assert "onClipboard" in preload and "'galaxy:clipboard'" in preload


def test_the_pet_is_not_owned_by_the_island_view():
    """桌宠还是那一只：island.js 只管岛上的字和交互，不碰桌宠的样子与推导（量一下它多宽来排版可以）。"""
    isle = (_RENDERER / "island.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*(?:.|\n)*?\*/|//[^\n]*", " ", isle)
    assert "PetState" not in code, "岛视图自己推导桌宠了"
    for touch in ("pet.dataset", "pet.setAttribute", "pet.style", "pet.classList"):
        assert touch not in code, f"岛视图在改桌宠（{touch}）—— 它的样子归 app.js 的 _paintPet"


def test_one_island_and_its_dots_speak_with_light_like_the_panel():
    """所有者：不要右边那个小岛、不要拿黄点表示在线、点要与面板同一套色彩。

    面板说状态靠光和深度（hud.css 的 .wired-dot：白芯带柔光 / 只亮半边 / 沉进去），不靠颜色。
    岛上的点照这一套：行上带 data-light（on / part / off），样式里没有给状态上色的色点。
    """
    html = (_RENDERER / "index.html").read_text(encoding="utf-8")
    isle = (_RENDERER / "island.js").read_text(encoding="utf-8")
    assert "islandSenses" not in html and "islandSenses" not in isle, "岛旁边又多出一座放点的小岛"
    assert "islandDot" not in html and "islandDot" not in isle, "第一行又挂回了表示「在」的色点"
    css = html[html.index("<style>") : html.index("</style>")]
    for light in ("on", "part"):
        assert f"#islandList .row[data-light='{light}'] i" in css
    assert "row.dataset.light" in isle
    # 原先给状态上色的那几个色值（绿 / 橙 / 黄）一个都不许回来
    for colour in ("#93b39a", "#d1a585", "#cdb38f", "#9fb5a0"):
        assert colour not in css, f"岛的样式里又出现了状态色 {colour}"
