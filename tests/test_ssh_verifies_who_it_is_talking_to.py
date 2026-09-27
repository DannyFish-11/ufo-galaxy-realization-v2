"""SSH 连接必须确认"对面真是那台机器"。

原来 Node_39 / Node_40 都传 ``known_hosts=None`` —— 关掉主机校验。局域网里冒充那台
电脑(同名主机抢先应答、ARP/DNS 欺骗),我们会照样把用户名密码送过去。

这组测试起**真的 asyncssh 服务端**(真主机密钥、真握手),不打桩传输:

1. 第一次连 → 记下指纹,连得上;
2. 同一台再连 → 指纹一致,连得上;
3. **换掉服务端主机密钥**(等于换了一台机器冒充它)→ 连接被拒,密码不会送过去;
4. 忘掉旧指纹 → 又能连(真重装系统时的正当出路);
5. 严格模式下,没见过的机器直接拒。
"""

from __future__ import annotations

import asyncio

import pytest

asyncssh = pytest.importorskip("asyncssh")

from core.ssh_host_keys import (  # noqa: E402
    HostKeyMismatch,
    HostKeyStore,
    HostKeyUnknown,
    connect_kwargs,
    fingerprint,
)

_USER = "tester"
_PASSWORD = "s3cret-not-to-be-leaked"


class _Server(asyncssh.SSHServer):
    """只认一个用户名 + 密码;记下它**是否真的被问过密码**。"""

    asked_for_password = False

    def begin_auth(self, username: str) -> bool:
        return True  # 需要认证

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        _Server.asked_for_password = True
        return username == _USER and password == _PASSWORD


async def _start(host_key) -> asyncssh.SSHAcceptor:
    return await asyncssh.listen(
        "127.0.0.1",
        0,
        server_factory=_Server,
        server_host_keys=[host_key],
        # 起一个 shell 就够,测试只连不跑命令
        process_factory=lambda process: process.exit(0),
    )


@pytest.fixture
def store(tmp_path):
    return HostKeyStore(path=str(tmp_path / "known_hosts.json"))


def _connect(port: int, store: HostKeyStore, seen=None):
    async def go():
        async with asyncssh.connect(
            "127.0.0.1",
            port=port,
            username=_USER,
            password=_PASSWORD,
            **connect_kwargs(store, on_new=seen),
        ) as conn:
            return conn.get_extra_info("server_version") is not None

    return asyncio.run(go())


def test_first_connection_records_the_fingerprint_and_says_it_is_new(store):
    key = asyncssh.generate_private_key("ssh-ed25519")
    told = []

    async def run():
        server = await _start(key)
        port = server.get_port()
        try:
            async with asyncssh.connect(
                "127.0.0.1",
                port=port,
                username=_USER,
                password=_PASSWORD,
                **connect_kwargs(store, on_new=lambda h, p, fp: told.append((h, p, fp))),
            ):
                pass
        finally:
            server.close()
            await server.wait_closed()
        return port

    port = asyncio.run(run())
    expected = fingerprint(key.convert_to_public())
    # 第一次见:记下来了,并且把指纹告诉了调用方(由它去告诉人)
    assert told and told[0][2] == expected
    assert store.known()[f"127.0.0.1:{port}"]["fingerprint"] == expected
    assert expected.startswith("SHA256:")


def test_a_swapped_host_key_is_refused_and_the_password_never_goes_out(store):
    real = asyncssh.generate_private_key("ssh-ed25519")
    impostor = asyncssh.generate_private_key("ssh-ed25519")

    async def run():
        # 1) 真机器:第一次连,记下指纹
        server = await _start(real)
        port = server.get_port()
        try:
            async with asyncssh.connect(
                "127.0.0.1", port=port, username=_USER, password=_PASSWORD, **connect_kwargs(store)
            ):
                pass
        finally:
            server.close()
            await server.wait_closed()

        # 2) 同一个地址换成另一把主机密钥 —— 冒充者
        _Server.asked_for_password = False
        impostor_server = await asyncssh.listen(
            "127.0.0.1",
            port,
            server_factory=_Server,
            server_host_keys=[impostor],
            process_factory=lambda process: process.exit(0),
        )
        try:
            # 必须是"主机校验没通过"这一种失败 —— 不能是连不上之类的别的原因
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                async with asyncssh.connect(
                    "127.0.0.1", port=port, username=_USER, password=_PASSWORD, **connect_kwargs(store)
                ):
                    pass
        finally:
            impostor_server.close()
            await impostor_server.wait_closed()
        return port

    port = asyncio.run(run())
    # 关键:冒充者根本没机会问密码 —— 主机校验在认证之前就把连接掐了
    assert _Server.asked_for_password is False
    # 记录仍是真机器那把,没有被冒充者改写
    assert store.known()[f"127.0.0.1:{port}"]["fingerprint"] == fingerprint(real.convert_to_public())


def test_check_raises_mismatch_with_both_fingerprints(store):
    a = asyncssh.generate_private_key("ssh-ed25519").convert_to_public()
    b = asyncssh.generate_private_key("ssh-ed25519").convert_to_public()
    assert store.check("nas.local", 22, a) == ("new", fingerprint(a))
    assert store.check("nas.local", 22, a) == ("known", fingerprint(a))
    with pytest.raises(HostKeyMismatch) as ei:
        store.check("nas.local", 22, b)
    assert ei.value.known == fingerprint(a) and ei.value.seen == fingerprint(b)
    assert "指纹变了" in str(ei.value) and ei.value.how_to_fix


def test_forgetting_lets_a_genuinely_reinstalled_machine_back_in(store):
    a = asyncssh.generate_private_key("ssh-ed25519").convert_to_public()
    b = asyncssh.generate_private_key("ssh-ed25519").convert_to_public()
    store.check("nas.local", 22, a)
    assert store.forget("nas.local", 22) is True
    assert store.check("nas.local", 22, b) == ("new", fingerprint(b))
    assert store.forget("nas.local", 22) is True
    assert store.forget("nas.local", 22) is False  # 已经没有了


def test_strict_mode_refuses_machines_it_has_never_seen(store, monkeypatch):
    monkeypatch.setenv("GALAXY_SSH_STRICT_HOST_KEYS", "true")
    k = asyncssh.generate_private_key("ssh-ed25519").convert_to_public()
    with pytest.raises(HostKeyUnknown) as ei:
        store.check("stranger.local", 22, k)
    assert ei.value.seen == fingerprint(k) and "ssh-keygen" in ei.value.how_to_fix
    # 事先录进来的就放行
    store.remember("stranger.local", 22, fingerprint(k), "ssh-ed25519")
    assert store.check("stranger.local", 22, k) == ("known", fingerprint(k))


def test_a_broken_store_file_is_not_silently_overwritten(tmp_path, caplog):
    p = tmp_path / "known_hosts.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = HostKeyStore(path=str(p))
    k = asyncssh.generate_private_key("ssh-ed25519").convert_to_public()
    s.check("h", 22, k)  # 当没有记录处理
    assert p.read_text(encoding="utf-8") == "{ this is not json"  # 原文件没被覆盖


def test_both_ssh_nodes_go_through_the_verifying_path():
    """守住这条线:两个节点都不许再出现 known_hosts=None 这种关掉校验的写法。"""
    for path in ("nodes/Node_39_SSH/main.py", "nodes/Node_40_SFTP/main.py"):
        code = "\n".join(
            line for line in open(path, encoding="utf-8").read().splitlines() if not line.lstrip().startswith("#")
        )
        assert "connect_kwargs()" in code, f"{path} 没有走主机校验"
        assert "known_hosts" not in code, f"{path} 又自己传了 known_hosts —— 校验要由 connect_kwargs 统一给"
