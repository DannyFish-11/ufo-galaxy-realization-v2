"""发现一台开着远程登录的电脑 → 人给一次凭据 → 智能体登进去装好客户端并配对。

省掉的是"人去敲命令",**不是"那台电脑同意"**:它得自己开着远程登录,人还得把凭据给
一次。所以这条路的 ``human_step`` 是 ``credential``,永远不会被自动接入。

这组测试里"远端"是**真的 asyncssh 服务端**:真握手、真主机密钥、真 exec、真 SFTP。
断言的是真实痕迹 —— 文件真的落到了服务端的目录里、命令真的被执行了、参数对。

同时钉住三件不能松的事:
* 主机指纹对不上时,**凭据不会发出去**;
* Windows 如实说"远程装不了"并给命令,不假装装好了;
* 装完配对完也**不等于成员** —— 成员身份由它自己连上主脑时产生。
"""

from __future__ import annotations

import asyncio
import os

import pytest

asyncssh = pytest.importorskip("asyncssh")

from core.device_onboarding import remote_install as ri  # noqa: E402
from core.device_onboarding.models import AUTOMATABLE, Candidate, HumanStep  # noqa: E402
from core.ssh_host_keys import HostKeyStore  # noqa: E402

_USER = "operator"
_PASSWORD = "only-the-human-has-this"


# ── 解析与命令拼装(纯函数,先钉住) ────────────────────────────────────────────────


def test_probe_output_is_parsed_into_facts_without_guessing():
    out = "Darwin studio.local 23.5.0 arm64\n---\nstudio.local\n---\nPython 3.11.9\n---\nDISPLAY=\n"
    facts = ri.parse_probe(out)
    assert (facts.platform, facts.python, facts.python_version) == ("macos", "python3", "Python 3.11.9")
    assert facts.hostname == "studio.local" and facts.has_display is False

    linux = ri.parse_probe("Linux nas 6.1.0 x86_64\n---\nnas\n---\nPython 3.10.12\n---\nDISPLAY=:0\n")
    assert (linux.platform, linux.has_display) == ("linux", True)

    # 什么都没拿到:如实留空并记一条,不编
    blank = ri.parse_probe("")
    assert blank.platform == "unknown" and blank.python == "" and "没找到 python3" in blank.notes[0]


def test_platform_is_read_from_uname_not_assumed():
    assert ri.platform_from_uname("Darwin foo 23.5.0") == "macos"
    assert ri.platform_from_uname("Linux nas 6.1") == "linux"
    assert ri.platform_from_uname("MINGW64_NT-10.0 host") == "windows"
    assert ri.platform_from_uname("") == "unknown"


def test_the_pair_command_quotes_everything_it_interpolates():
    """恶意配对码必须整条变成**一个参数**,而不是拼出第二条命令。

    用 shlex.split 真解析一遍 —— 这才叫证明,光看字符串里有没有分号证明不了什么。
    """
    import shlex

    nasty = "7KQ2MX'; rm -rf /"
    cmd = ri.pair_command("python3", nasty, "http://10.0.0.2:9000", "dir with space")
    head, sep, tail = cmd.partition(" && ")
    assert sep and shlex.split(head) == ["cd", "dir with space"]  # 带空格的目录是一个参数
    argv = shlex.split(tail)
    assert argv[:4] == ["python3", "-m", "device_client", "--pair"]
    assert argv[4] == nasty  # 原样一个参数,分号没有变成命令分隔
    assert "rm" not in argv[5:] and "--install-autostart" in argv and "--no-run" in argv


def test_credentials_are_never_echoed_back():
    red = ri._redact({"username": "me", "password": "hunter2", "private_key": "-----BEGIN", "port": 22})
    assert red["username"] == "me" and red["port"] == 22
    assert "hunter2" not in str(red) and "BEGIN" not in str(red)


def test_this_path_can_never_be_auto_joined():
    """凭据类永远要人给 —— 不在可自动化的档位里。"""
    assert HumanStep.CREDENTIAL not in AUTOMATABLE
    from core.device_onboarding.service import _auto_allows

    assert _auto_allows(HumanStep.CREDENTIAL.value) is False


# ── 真 SSH 服务端 ────────────────────────────────────────────────────────────────


class _Remote(asyncssh.SSHServer):
    """一台假装的"远端电脑":记下被执行的每条命令,uname 由测试指定。"""

    uname = "Linux testbox 6.1.0 x86_64"
    python_line = "Python 3.11.2"
    pair_exit = 0
    commands: list = []

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == _USER and password == _PASSWORD


async def _handle(process) -> None:
    cmd = process.command or ""
    _Remote.commands.append(cmd)
    if cmd.startswith("uname"):
        process.stdout.write(f"{_Remote.uname}\n---\ntestbox\n---\n{_Remote.python_line}\n---\nDISPLAY=:0\n")
        process.exit(0)
    elif "--pair" in cmd:
        process.stdout.write("✓ 已配对\n" if _Remote.pair_exit == 0 else "✗ 配对失败\n")
        process.exit(_Remote.pair_exit)
    elif "nohup" in cmd:
        process.stdout.write("started\n")
        process.exit(0)
    else:
        process.exit(0)


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """起一台真远端,cwd 指到临时目录 —— SFTP 传过去的文件落在那里,可以直接看。"""
    _Remote.commands = []
    _Remote.uname = "Linux testbox 6.1.0 x86_64"
    _Remote.python_line = "Python 3.11.2"
    _Remote.pair_exit = 0
    landing = tmp_path / "remote_home"
    landing.mkdir()
    key = asyncssh.generate_private_key("ssh-ed25519")
    store = HostKeyStore(path=str(tmp_path / "hostkeys.json"))

    async def boot():
        return await asyncssh.listen(
            "127.0.0.1",
            0,
            server_factory=_Remote,
            server_host_keys=[key],
            process_factory=_handle,
            sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(landing)),
        )

    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(boot())
    yield {"port": server.get_port(), "landing": landing, "store": store, "key": key, "loop": loop}
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


def _install(remote, **overrides):
    """走真实的 install_and_pair,只把"连哪个端口/用哪个指纹库"换掉。"""
    from core.ssh_host_keys import connect_kwargs

    async def connector(*, host, port, username, password, private_key):
        conn = await asyncssh.connect(
            host=host,
            port=remote["port"],
            username=username,
            password=password,
            **connect_kwargs(remote["store"]),
        )
        return ri._AsyncsshSession(conn)

    inputs = {"username": _USER, "password": _PASSWORD, **overrides.pop("inputs", {})}
    return remote["loop"].run_until_complete(
        ri.install_and_pair(
            "127.0.0.1",
            inputs,
            overrides.pop("code", "7KQ2MX"),
            overrides.pop("gateway", "http://10.0.0.2:9000"),
            connector=connector,
            **overrides,
        )
    )


def test_the_client_really_lands_on_the_remote_and_gets_paired(remote):
    out = _install(remote)

    assert out["installed"] is True and out["platform"] == "linux"
    assert out["facts"]["python"] == "python3"

    # 文件真的落到了远端目录里
    landed = remote["landing"] / ri.REMOTE_DIR
    assert (landed / "device_client" / "__main__.py").is_file()
    assert (landed / "device_client" / "executors" / "linux_x11.py").is_file()
    assert (landed / "nodes" / "Node_124_LinuxDesktopAuto" / "x11_actions.py").is_file()
    # 传过去的内容和本仓库一致,不是空壳
    local = open(os.path.join(ri.repo_root(), "device_client", "__main__.py"), encoding="utf-8").read()
    assert (landed / "device_client" / "__main__.py").read_text(encoding="utf-8") == local

    # 命令真的执行了,参数对(解析一遍,别靠字符串里"看起来像")
    import shlex

    joined = " | ".join(_Remote.commands)
    assert "uname" in joined
    [pair_cmd] = [c for c in _Remote.commands if "--pair" in c]
    argv = shlex.split(pair_cmd.partition(" && ")[2])
    assert argv[argv.index("--pair") + 1] == "7KQ2MX"
    assert argv[argv.index("--gateway") + 1] == "http://10.0.0.2:9000"
    assert "--install-autostart" in argv
    assert any("nohup" in c for c in _Remote.commands) and out["started"] is True


def test_a_failed_pairing_on_the_remote_is_reported_not_swallowed(remote):
    _Remote.pair_exit = 1
    with pytest.raises(ri.RemoteInstallError) as ei:
        _install(remote)
    assert "配对没成功" in str(ei.value) and ei.value.how_to_fix


def test_a_remote_without_python_is_told_so_before_anything_is_copied(remote):
    _Remote.python_line = "bash: python3: command not found"
    with pytest.raises(ri.RemoteInstallError) as ei:
        _install(remote)
    assert "没有 python3" in str(ei.value) and "brew install python" in ei.value.how_to_fix
    assert not (remote["landing"] / ri.REMOTE_DIR).exists()  # 没白传文件


def test_windows_says_it_cannot_be_installed_remotely_and_hands_over_a_command(remote):
    _Remote.uname = "MINGW64_NT-10.0-22631 WORKPC 3.4.10"
    out = _install(remote)
    assert out["installed"] is False and out["platform"] == "windows"
    assert out["commands"] and "--pair 7KQ2MX" in out["commands"][0]
    assert "WindowsExecutionArbiter" in out["why"]
    assert not (remote["landing"] / ri.REMOTE_DIR).exists()


def test_an_unknown_os_is_refused_rather_than_guessed(remote):
    _Remote.uname = "Plan9 glenda"
    with pytest.raises(ri.RemoteInstallError) as ei:
        _install(remote)
    assert "认不出" in str(ei.value)


def test_missing_credentials_are_asked_for_before_connecting(remote):
    for bad in ({"username": ""}, {"password": ""}):
        with pytest.raises(ri.RemoteInstallError) as ei:
            _install(remote, inputs=bad)
        assert ei.value.how_to_fix
    assert _Remote.commands == []  # 一次都没连


def test_a_changed_host_key_stops_us_before_the_password_goes_out(remote, tmp_path):
    """先录一个别的指纹,等于"对面换了机器" —— 凭据不能发出去。"""
    from core.ssh_host_keys import fingerprint

    other = asyncssh.generate_private_key("ssh-ed25519")
    remote["store"].remember("127.0.0.1", remote["port"], fingerprint(other.convert_to_public()), "ssh-ed25519")

    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        _install(remote)
    assert _Remote.commands == []  # 握手就被掐了,没有任何命令、也没送密码


# ── 接入路径:把这条路接到平面上 ──────────────────────────────────────────────────


def _candidate(**props) -> Candidate:
    base = {
        "is_computer": True,
        "remote_login": True,
        "computer_hint": "macbook",
        "mdns_services": ["_ssh._tcp.local."],
    }
    return Candidate(
        candidate_id="cand_mdns_x",
        source="mdns",
        key="studio.local",
        name="Danny 的 MacBook",
        addresses=["192.168.1.42"],
        properties={**base, **props},
    )


def test_the_path_only_offers_itself_when_remote_login_is_advertised():
    from core.device_onboarding.join_paths import RemoteInstallPath

    path = RemoteInstallPath()
    assert path.can_handle(_candidate()) is True
    assert path.can_handle(_candidate(remote_login=False)) is False  # 登不进去就别提议
    assert path.can_handle(_candidate(is_computer=False)) is False
    assert path.human_step is HumanStep.CREDENTIAL


def test_without_credentials_the_path_asks_for_them_and_says_they_are_not_stored():
    from core.device_onboarding.join_paths import RemoteInstallPath

    out = asyncio.run(RemoteInstallPath().join(_candidate(), {}))
    assert out.kind == "needs_human" and out.human_step == HumanStep.CREDENTIAL.value
    assert "不会存下来" in out.needs["what"] and "192.168.1.42" in out.needs["what"]
    names = {i["name"] for i in out.needs["inputs"]}
    assert names == {"username", "password", "private_key", "port"}
    assert all(i.get("secret") for i in out.needs["inputs"] if i["name"] in ("password", "private_key"))


def test_a_candidate_with_no_address_fails_loudly():
    from core.device_onboarding.join_paths import RemoteInstallPath

    cand = _candidate()
    cand.addresses = []
    cand.properties.pop("mdns_server", None)
    out = asyncio.run(RemoteInstallPath().join(cand, {"username": "u", "password": "p"}))
    assert out.kind == "failed" and "地址" in out.error
