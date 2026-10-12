"""前后端那条线:**断了会自己回来,死了看得出来,回来之后把错过的补上。**

所有者:「优化前后端的连接代码,确保前后端连接稳定持续」。逐条对过之后,真实的断点是这几处:

* **半开连接认不出来** —— 合盖再打开、后端被硬杀、网卡切换之后,WebSocket 在浏览器这边仍是「开着的」,
  不会有 close 事件也就不会重连;静息相位里后端本来就很少说话,于是界面看着正常、实际早就聋了。
  面板那份没有保活;覆盖层那份是固定 3 秒重试、也没有保活。
* **覆盖层只靠 IPC 推送** —— 后端 POST 到 Electron 主进程、主进程转给覆盖层。那条路没有快照(覆盖层比
  后端先起来时,静息相位里可能很久都等不到第一帧),主进程端口被占(EADDRINUSE)时整条是死的。
* **HTTP 请求没有期限** —— 后端事件循环被一件同步的事占住、或连接没断干净时,请求一直挂着,
  那一块永远停在「正在拉」。
* **开机那一拨只拉一次** —— 面板比后端先起来时拉到的全是「没拉到」,之后没有任何东西会再去拉。
* **把「没问到」当成「会话过期」** —— 拉历史失败(后端还没起来)时把本地记的会话 id 删了,对话就这样被忘了。
* **重连上来的面板设备名册是旧的** —— 名册只在设备事件时才推。

连接本身的行为(保活、半开、超时、退避、抖动、网回来立刻重连)在 node 那边用假 WebSocket + 假时钟测
(``electron/renderer/live_socket.test.js``,CI 里跑);这里钉的是**两边都真的用它**、以及后端那一侧。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RENDERER = _ROOT / "electron" / "renderer"
_PANEL = _RENDERER / "panel" / "src"


def _code(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _fn(src: str, header: str) -> str:
    """从函数头到它的下一个同级 ``export``/``function``(粗切,够判据用)。"""
    start = src.index(header)
    nxt = [i for i in (src.find("\nexport ", start + 1), src.find("\n  async function ", start + 1)) if i > 0]
    return src[start : min(nxt) if nxt else len(src)]


# ── 一份连接,两边都用 ─────────────────────────────────────────────────────────


def test_the_panel_socket_is_the_shared_live_socket():
    ts = _code(_PANEL / "transport.ts")
    assert "import '../../live_socket.js';" in ts
    cls = ts[ts.index("export class PresenceSocket") : ts.index("export interface ChatHandlers")]
    assert "new globalThis.LiveSocket(" in cls, "面板的长连接不走共用的那一份"
    assert "setTimeout" not in cls and "new WebSocket(" not in cls, "面板又自己写了一份重连"


def test_the_overlay_has_its_own_socket_with_ipc_only_as_the_fallback():
    js = _code(_RENDERER / "app.js")
    body = js[js.index("_connectBackend() {") : js.index("_onStateEvent(payload) {")]
    assert "new LiveSocket(" in body, "覆盖层没有自己的长连接 —— 只剩 IPC 那条没有快照、端口被占就整条死的路"
    assert "window.galaxyShell" in body, "覆盖层不认外壳给的网关地址"
    assert re.search(
        r"if \(this\._ws && this\._ws\.connected\) return;", body
    ), "WS 连着时还在吃 IPC 那份 —— 同一拍两条路先后不定,后到的旧帧会把画面拽回去"
    assert (
        "localhost:${gwPort}" not in body
    ), "兜底地址又写回 localhost —— Windows 上先解析到 ::1,连不上只监听 IPv4 的网关"
    html = (_RENDERER / "index.html").read_text(encoding="utf-8")
    assert html.index('<script src="live_socket.js">') < html.index('<script src="app.js">')


def test_the_overlay_window_is_told_where_the_gateway_is():
    main = (_ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    overlay = main[main.index("mainWindow = new BrowserWindow({") : main.index("mainWindow.loadFile(")]
    assert "additionalArguments: [`--galaxy-base=${GATEWAY_BASE}`]" in overlay
    panel = main[main.index("function createPanelWindow()") :]
    assert "additionalArguments: [`--galaxy-base=${GATEWAY_BASE}`]" in panel, "两扇窗的网关地址要同一个出处"


def test_the_shared_socket_tests_run_in_ci():
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "electron/renderer/live_socket.test.js" in ci


def test_the_backend_answers_the_keepalive():
    """保活靠后端回 pong;回不了的话,前端每 40 秒就会把一条好好的连接当成死的拆掉。"""
    src = (_ROOT / "core" / "api_routes.py").read_text(encoding="utf-8")
    ws = src[src.index('@app.websocket("/ws/desktop-presence")') :][:2500]
    assert 'if raw == "ping":' in ws and '{"type": "pong"}' in ws
    live = (_RENDERER / "live_socket.js").read_text(encoding="utf-8")
    assert "this._send('ping')" in live and "msg.type === 'pong'" in live


# ── HTTP:每一条都有期限 ───────────────────────────────────────────────────────


def test_every_panel_request_has_a_deadline():
    ts = _code(_PANEL / "transport.ts")
    helper = ts[ts.index("async function fetchT(") : ts.index("async function fetchT(") + 900]
    rest = ts.replace(helper, "")
    raw = re.findall(r"(?<![\w.])fetch\(", rest)
    assert not raw, f"还有 {len(raw)} 处 fetch 没走 fetchT —— 后端卡住时它会一直挂着"
    assert "ctrl.abort()" in helper and "AbortController" in helper
    # 写不重试:不知道上一次到没到,重发可能就是做两遍
    assert "!== 'GET') throw err" in helper.replace('"', "'")


@pytest.mark.parametrize(
    "fn",
    ["streamChat", "setTier", "ingestFiles", "installGitHubAddon", "retryIsolatedResult"],
)
def test_the_slow_ones_are_not_cut_off(fn):
    """换档要驱逐 / 拉模型、装 GitHub 项目、喂文件、重跑步骤、对话流:本来就慢,给期限就会把成功的半路掐断。"""
    ts = _code(_PANEL / "transport.ts")
    body = _fn(ts, f"export async function {fn}(")
    assert "NO_LIMIT" in body, f"{fn} 被设了期限 —— 它本来就要很久"


@pytest.mark.parametrize("fn", ["saveConfig", "setBundle", "setPrivacy", "saveUserProvider", "deleteUserProvider"])
def test_writes_get_the_write_deadline(fn):
    ts = _code(_PANEL / "transport.ts")
    assert "WRITE_MS" in _fn(ts, f"export async function {fn}(")


# ── 回来之后把错过的补上 ─────────────────────────────────────────────────────


def test_not_reaching_the_backend_is_not_the_same_as_an_expired_session():
    ts = _code(_PANEL / "transport.ts")
    hist = _fn(ts, "export async function fetchHistory(")
    assert "Promise<readonly Turn[] | null | undefined>" in hist
    assert "resp.status === 404 ? null : undefined" in hist, "5xx / 网关还在起 被当成了「后端不认识这条会话」"
    assert re.search(r"catch \(err\) \{[^}]*return undefined;", hist), "连不上被当成了「后端不认识这条会话」"
    main = _code(_PANEL / "main.ts")
    restore = main[main.index("async function restoreSession()") : main.index("async function openCard(")]
    unreachable = restore[restore.index("if (turns === undefined) {") : restore.index("if (turns === null) {")]
    assert "removeItem" not in unreachable, "没问到也把本地记的会话删了 —— 面板比后端先起来一次,对话就被忘了"
    assert "store.patch({ sessionId: sid })" in unreachable


def test_reconnecting_pulls_again_what_was_missed():
    main = _code(_PANEL / "main.ts")
    on_open = main[main.index("onOpen: () => {") :][:200]
    assert "resyncAfterOpen()" in on_open
    resync = main[main.index("function resyncAfterOpen(): void {") :][:1200]
    for loader in (
        "loadSelf",
        "loadTiers",
        "loadEndpoints",
        "loadBundles",
        "loadVendors",
        "loadAddons",
        "restoreSession",
    ):
        assert f"void {loader}()" in resync, f"连上之后没有补拉 {loader}"
    # 正在出字、正在看某张卡的时候不动历史 —— 那会把人眼前的东西换掉
    assert "!s.chatBusy && s.drawn < 0" in resync


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


def test_a_newly_connected_client_gets_the_device_roster_right_away(monkeypatch):
    """名册只在设备事件时才推 —— 重连上来的面板若只等下一次事件,断开期间上线下线的设备就一直是旧的。"""
    import core.lumiv_websocket_bridge as B
    import core.routes.panel as panel_routes

    async def fake_feed():
        return {"devices": [{"device_id": "phone-1", "status": "online"}]}

    monkeypatch.setattr(panel_routes, "build_panel_feed", fake_feed)
    B.GalaxyPresenceBridge._instance = None
    try:
        b = B.GalaxyPresenceBridge.get_instance()
        ws = _FakeWS()

        async def run():
            await b.register_client(ws)
            await asyncio.sleep(0.05)
            await b.unregister_client(ws)

        asyncio.run(run())
        kinds = [m.get("type") for m in ws.sent]
        assert kinds[0] == "state_event", "新连上的先要一份当前状态"
        assert "panel_feed" in kinds, "新连上的没补到设备名册"
        feed = next(m for m in ws.sent if m.get("type") == "panel_feed")["feed"]
        assert feed["devices"][0]["device_id"] == "phone-1"
    finally:
        B.GalaxyPresenceBridge._instance = None


def test_while_disconnected_the_pets_say_they_do_not_know():
    """断开时感知那一份是**上一个进程的样子**。照着它画,桌宠会一直睁着眼,而后端根本不在了 ——
    当成「还没收到」画(眼睛虚着),与左下清单全写「无」同一条规矩。"""
    main = _code(_PANEL / "main.ts")
    assert "const perception = s.connected ? s.posture?.perception ?? null : null;" in main
    assert "island.render(perception," in main
    js = _code(_RENDERER / "app.js")
    on_close = js[js.index("onClose: () => {") :][:400]
    assert "perception: null" in on_close, "覆盖层断开后桌宠还照着上一个进程的样子画"
