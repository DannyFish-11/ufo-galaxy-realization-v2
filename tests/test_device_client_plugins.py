"""一台电脑接主脑:连接层三个系统共用,在本机怎么动手由执行插件决定。

覆盖:插件怎么选(系统 / 环境变量 / 第三方 entry point);插件接口的约定(不支持的动作
如实说、异常不外抛);Windows / Linux / macOS 三个插件各自怎么动手(命令一律按参数列表、
文字不进命令行);连接层照实上报「本机能做什么、为什么不能」;开机自启三种写法;
局域网里自己找主脑。

Linux 插件另有一组在**真的 X 服务器(Xvfb)**上跑:打字、剪贴板、鼠标、截图都是真做的。
机器上没有 Xvfb / xdotool 时那组跳过。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import types

import pytest


class FakeRun:
    """命令执行的替身:记下每条 argv / stdin,按规则返回。"""

    def __init__(self, rules=None):
        self.calls = []
        self.rules = rules or {}

    def __call__(self, argv, input=None, timeout=10.0, capture=True):
        self.calls.append((list(argv), input))
        for prefix, (code, out) in self.rules.items():
            if " ".join(argv).startswith(prefix):
                return subprocess.CompletedProcess(argv, code, out, "" if code == 0 else out)
        return subprocess.CompletedProcess(argv, 0, "", "")


# ── 选插件 ───────────────────────────────────────────────────────────────────────


def test_the_executor_is_chosen_by_platform(monkeypatch):
    from device_client.executors import select_executor

    monkeypatch.delenv("GALAXY_DESKTOP_EXECUTOR", raising=False)
    assert select_executor("windows").name == "windows-arbiter"
    assert select_executor("linux").name == "linux-x11"
    assert select_executor("macos").name == "macos"


def test_an_env_var_or_a_third_party_plugin_can_take_over(monkeypatch):
    import device_client.executors as ex

    class Custom(ex.DesktopExecutor):
        name = "custom"
        platform = "linux"

    monkeypatch.setattr(ex, "_entry_point_plugins", lambda: {"linux": Custom, "wayland": Custom})
    monkeypatch.delenv("GALAXY_DESKTOP_EXECUTOR", raising=False)
    assert ex.select_executor("linux").name == "custom"  # 第三方插件覆盖内置
    monkeypatch.setenv("GALAXY_DESKTOP_EXECUTOR", "wayland")
    assert ex.select_executor("windows").name == "custom"
    monkeypatch.setenv("GALAXY_DESKTOP_EXECUTOR", "nope")
    with pytest.raises(ValueError):
        ex.select_executor()


def test_the_plugin_contract_never_raises_and_never_fakes_support():
    from device_client.executors import DesktopExecutor

    class Boom(DesktopExecutor):
        name = "boom"

        def supported_actions(self):
            return ["click"]

        def _do(self, action, params):
            raise RuntimeError("driver crashed")

    out = Boom().execute("click", {"x": 1})
    assert out == {"success": False, "error": "driver crashed"}
    out = Boom().execute("type", {})
    assert out["success"] is False and "不支持" in out["error"]


# ── Windows ──────────────────────────────────────────────────────────────────────


def test_windows_plugin_hands_actions_to_the_arbiter_entry(monkeypatch):
    import windows_client.windows_aip_client as wac
    from device_client.executors.windows import WindowsExecutor

    seen = []
    monkeypatch.setattr(wac, "_execute_command", lambda a, p: (seen.append((a, p)), {"success": True})[1])
    assert WindowsExecutor().execute("click", {"x": 3, "y": 4}) == {"success": True}
    assert seen == [("click", {"x": 3, "y": 4})]


def test_the_old_windows_entry_is_the_shared_client_with_the_windows_plugin():
    from device_client.client import DeviceClient
    from windows_client.windows_aip_client import WindowsAIPClient

    c = WindowsAIPClient(state={})
    assert isinstance(c, DeviceClient) and c.executor.name == "windows-arbiter"


# ── Linux(替身) ────────────────────────────────────────────────────────────────


@pytest.fixture
def x11(monkeypatch):
    from nodes.Node_124_LinuxDesktopAuto import x11_actions

    run = FakeRun()
    x11_actions._set_runner(run, which=lambda t: f"/usr/bin/{t}")
    yield types.SimpleNamespace(mod=x11_actions, run=run)
    x11_actions._set_runner(None, None)


def test_linux_typing_goes_through_stdin_not_the_command_line(x11):
    text = 'it\'s "ok" -rf $(whoami)\n'
    assert x11.mod.type_text(text)["success"]
    [(argv, stdin)] = x11.run.calls
    assert argv == ["xdotool", "type", "--delay", "12", "--file", "-"] and stdin == text


def test_linux_keys_cannot_smuggle_options(x11):
    assert not x11.mod.press_key("--window 1")["success"]
    assert x11.mod.press_key("ctrl+c")["success"]
    assert x11.run.calls == [(["xdotool", "key", "--", "ctrl+c"], None)]


def test_linux_window_ids_must_be_numeric(x11):
    assert not x11.mod.window("close", window_id="1; rm -rf /")["success"]
    assert x11.run.calls == []


def test_linux_failures_are_reported_not_swallowed(x11):
    x11.run.rules["xdotool mousemove"] = (1, "Can't open display")
    out = x11.mod.click(1, 2)
    assert out["success"] is False and "display" in out["error"]


def test_linux_plugin_says_why_it_cannot_run(monkeypatch):
    from device_client.executors.linux_x11 import LinuxX11Executor

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    ok, why = LinuxX11Executor().available()
    assert not ok and "Wayland" in why


# ── macOS(替身) ────────────────────────────────────────────────────────────────


def _mac(**rules):
    from device_client.executors.macos import MacOSExecutor

    run = FakeRun(rules)
    return MacOSExecutor(run=run, which=lambda t: f"/usr/bin/{t}"), run


def test_mac_typing_passes_the_text_as_an_argument_not_as_script():
    ex, run = _mac()
    text = 'say "hi" & do shell script "rm"'
    assert ex.execute("type", {"text": text})["success"]
    [(argv, _)] = run.calls
    assert argv[-1] == text and argv[-2] == "--"
    assert all(text not in part for part in argv[:-1])  # 文字不进 AppleScript 源码


@pytest.mark.parametrize(
    "keys,expect",
    [
        ("cmd+c", ("keystroke (item 1 of argv) using {command down}", ["c"])),
        ("Return", ("key code 36", [])),
        ("cmd+shift+s", ("using {command down, shift down}", ["s"])),
    ],
)
def test_mac_key_combos(keys, expect):
    from device_client.executors.macos import key_script

    lines, argv = key_script(keys)
    assert expect[0] in " ".join(lines) and argv == expect[1]


def test_mac_unknown_keys_and_flag_like_app_names_are_refused():
    ex, run = _mac()
    assert not ex.execute("press_key", {"keys": "hyper+x"})["success"]
    assert not ex.execute("open_app", {"name": "-a"})["success"]
    assert run.calls == []


def test_mac_permission_errors_say_where_to_grant_it():
    ex, _ = _mac(osascript=(1, "System Events got an error: osascript is not allowed assistive access. (-1719)"))
    out = ex.execute("type", {"text": "x"})
    assert out["success"] is False and "辅助功能" in out["how_to_fix"]


def test_mac_only_advertises_mouse_actions_when_it_can_move_the_mouse(monkeypatch):
    from device_client.executors.macos import MacOSExecutor

    monkeypatch.setattr(MacOSExecutor, "_has_pyautogui", staticmethod(lambda: False))
    no_mouse = MacOSExecutor(run=FakeRun(), which=lambda t: None if t == "cliclick" else f"/usr/bin/{t}")
    assert "click" not in no_mouse.supported_actions()
    with_cliclick = MacOSExecutor(run=FakeRun(), which=lambda t: f"/usr/bin/{t}")
    assert "click" in with_cliclick.supported_actions() and "scroll" not in with_cliclick.supported_actions()


# ── 连接层如实上报 ───────────────────────────────────────────────────────────────


def test_an_unusable_plugin_still_connects_but_offers_no_actions(monkeypatch):
    from device_client.client import DeviceClient
    from device_client.executors.linux_x11 import LinuxX11Executor

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    msg = DeviceClient(LinuxX11Executor(), state={})._device_register_msg()
    assert msg["supported_actions"] == []
    assert msg["executor_status"]["available"] is False and "DISPLAY" in msg["executor_status"]["reason"]
    assert msg["platform"] == "linux" and msg["device_type"].startswith("linux_")


# ── 开机自启 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("plat", ["windows", "linux", "macos"])
def test_autostart_writes_one_entry_and_removes_it(tmp_path, plat):
    from device_client import autostart

    info = autostart.install(
        plat, home=str(tmp_path), appdata=str(tmp_path / "AppData"), python="/py dir/python", repo="/src/galaxy repo"
    )
    body = open(info["path"], encoding="utf-8").read()
    assert "device_client" in body and "galaxy repo" in body
    if plat == "linux":
        assert info["path"].endswith(".config/autostart/galaxy-device-client.desktop") and "Exec=sh -c" in body
    if plat == "macos":
        assert "<key>RunAtLoad</key><true/>" in body and "<key>KeepAlive</key><true/>" in body
    if plat == "windows":
        assert "Startup" in info["path"] and body.startswith("@echo off")
    assert autostart.uninstall(plat, home=str(tmp_path), appdata=str(tmp_path / "AppData"))["removed"] == "True"
    assert not os.path.exists(info["path"])


# ── 找主脑 ───────────────────────────────────────────────────────────────────────


def test_finding_the_gateway_on_the_lan_only_trusts_device_ingress_announcements():
    from device_client.pairing import discover_gateways

    rows = [
        {"addresses": ["192.168.1.10"], "port": 9000, "properties": {"path": "/ws/device/{device_id}", "tls": "false"}},
        {"addresses": ["192.168.1.20"], "port": 7000, "properties": {"role": "node"}},  # 别的 Galaxy 节点
        {"addresses": ["192.168.1.30"], "port": 8443, "properties": {"path": "/ws/device/{device_id}", "tls": "true"}},
    ]
    assert discover_gateways(browse=lambda t: rows) == ["http://192.168.1.10:9000", "https://192.168.1.30:8443"]


def test_a_code_is_tried_on_each_gateway_found_until_one_accepts_it():
    from device_client import pairing as dp

    tried = []

    def post(url, body):
        tried.append(url)
        if url.startswith("http://b"):
            return {"success": True, "capability_token": "tok", "candidates": []}
        return {"success": False, "error": "配对码无效"}

    state = {}
    dp.pair_anywhere("ABC123", state, ["http://a:9000", "http://b:9000"], post=post, device_type="linux_laptop")
    assert [u.split("/api")[0] for u in tried] == ["http://a:9000", "http://b:9000"]
    assert state["gateway"] == "http://b:9000" and state["token"] == "tok"
    with pytest.raises(dp.PairingError) as e:
        dp.pair_anywhere("ABC123", {}, [])
    assert "--gateway" in e.value.how_to_fix


def test_cli_status_and_unpaired_start(monkeypatch, tmp_path, capsys):
    from device_client.__main__ import main

    monkeypatch.setenv("GALAXY_DEVICE_STATE", str(tmp_path / "s.json"))
    monkeypatch.delenv("GALAXY_DESKTOP_EXECUTOR", raising=False)
    assert main(["--status"], default_executor="linux") == 0
    assert json.loads(capsys.readouterr().out)["executor"] == "linux-x11"
    assert main([], default_executor="linux") == 2
    assert "--pair" in capsys.readouterr().out


# ── Linux:真的 X 服务器 ─────────────────────────────────────────────────────────

_REAL_X = all(shutil.which(t) for t in ("Xvfb", "xdotool", "scrot", "xclip"))


@pytest.fixture
def xvfb(monkeypatch):
    if not _REAL_X:
        pytest.skip("本机没有 Xvfb / xdotool / scrot / xclip")
    xlib = pytest.importorskip("Xlib.display")
    disp = ":%d" % (90 + os.getpid() % 9)
    proc = subprocess.Popen(
        ["Xvfb", disp, "-screen", "0", "800x600x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1.0)
    monkeypatch.setenv("DISPLAY", disp)
    try:
        yield xlib.Display(disp)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_real_x_typing_arrives_exactly_even_with_quotes(xvfb):
    from Xlib import X

    from device_client.executors.linux_x11 import LinuxX11Executor

    d = xvfb
    scr = d.screen()
    w = scr.root.create_window(0, 0, 300, 100, 0, scr.root_depth, event_mask=X.KeyPressMask)
    w.map()
    d.sync()
    time.sleep(0.3)
    w.set_input_focus(X.RevertToParent, X.CurrentTime)
    d.sync()
    text = 'it\'s "ok" -rf $(x)'
    assert LinuxX11Executor().execute("type", {"text": text, "delay_ms": 5})["success"]
    got, end = [], time.time() + 5
    while time.time() < end and len(got) < len(text):
        while d.pending_events():
            e = d.next_event()
            if e.type == X.KeyPress:
                ks = d.keycode_to_keysym(e.detail, 1 if e.state & X.ShiftMask else 0)
                if 32 <= ks < 127:
                    got.append(chr(ks))
        time.sleep(0.01)
    assert "".join(got) == text


def test_real_x_mouse_clipboard_and_screenshot(xvfb):
    from device_client.executors.linux_x11 import LinuxX11Executor

    ex = LinuxX11Executor()
    assert ex.available() == (True, "")
    assert ex.execute("move", {"x": 123, "y": 45})["success"]
    pos = ex.execute("mouse_position", {})
    assert (pos["x"], pos["y"]) == (123, 45)
    assert ex.execute("clipboard", {"action": "set", "content": "剪贴板'测试"})["success"]
    assert ex.execute("clipboard", {"action": "get"})["content"] == "剪贴板'测试"
    shot = ex.execute("screenshot", {})
    assert base64.b64decode(shot["image_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert ex.execute("screen_size", {}) == {"success": True, "width": 800, "height": 600}
