"""网关"开没开 TLS"只判一次 —— 起服务的和发地址的读同一处。

为什么要这道门
==============
两边原先各判各的,判出了相反的结论:网关默认明文起(没配证书),而发给设备的
tailnet 地址写死 ``wss://``。客户端拨 TLS、服务端说明文 —— 一条语法正确、
**必然握手失败**的路,还被一条测试钉成了"正确行为"。

所以这里钉三件事:
  1. 判据本身:两个都配才算开,只配一半算没开(与服务端起法一致);
  2. 起服务的 ``app.py`` 走这个判据,不再自己读 env;
  3. 发地址的几处不许再写死 ``ws://`` / ``wss://`` —— 写死就是在猜。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from core.gateway_tls import tls_paths, ws_scheme

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def no_tls(monkeypatch):
    monkeypatch.delenv("GALAXY_TLS_CERT", raising=False)
    monkeypatch.delenv("GALAXY_TLS_KEY", raising=False)


def test_plain_by_default(no_tls):
    assert tls_paths() is None
    assert ws_scheme() == "ws"


def test_both_set_means_tls(no_tls, monkeypatch):
    monkeypatch.setenv("GALAXY_TLS_CERT", "/c.pem")
    monkeypatch.setenv("GALAXY_TLS_KEY", "/k.pem")
    assert tls_paths() == ("/c.pem", "/k.pem")
    assert ws_scheme() == "wss"


@pytest.mark.parametrize("which", ["GALAXY_TLS_CERT", "GALAXY_TLS_KEY"])
def test_half_configured_is_not_tls(no_tls, monkeypatch, which):
    """只配一半时服务端按明文起 —— 这里也必须报"没开",否则两边又判反了。"""
    monkeypatch.setenv(which, "/x.pem")
    assert tls_paths() is None
    assert ws_scheme() == "ws"


def test_whitespace_only_is_not_configured(no_tls, monkeypatch):
    monkeypatch.setenv("GALAXY_TLS_CERT", "   ")
    monkeypatch.setenv("GALAXY_TLS_KEY", "/k.pem")
    assert tls_paths() is None


def _code(rel: str) -> str:
    """去掉注释与文档串再看 —— 判据查的是代码,不是解释这件事的散文。"""
    src = (ROOT / rel).read_text(encoding="utf-8")
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    return re.sub(r"#[^\n]*", "", src)


def test_the_server_uses_the_same_rule():
    """起服务的地方不许再自己读 env —— 那就是第二份判据。"""
    code = _code("galaxy_gateway/app.py")
    assert "tls_paths()" in code, "app.py 没有走 core.gateway_tls 的判据"
    assert 'os.getenv("GALAXY_TLS_CERT"' not in code, "app.py 又自己读了一份 TLS 配置"


@pytest.mark.parametrize(
    "rel, pattern",
    [
        ("core/tailscale_manager.py", r'f"wss?://\{self\.ts_ip\}'),
        ("core/agent_card.py", r'f"wss?://\{lan_ip\}'),
        ("core/agent_card.py", r'f"wss?://\{_ip\}'),
    ],
)
def test_no_address_builder_guesses_the_scheme(rel, pattern):
    """发给设备的地址,协议必须来自 ws_scheme(),不能写死。"""
    assert not re.search(pattern, _code(rel)), f"{rel} 又把协议写死了(匹配 {pattern})"
