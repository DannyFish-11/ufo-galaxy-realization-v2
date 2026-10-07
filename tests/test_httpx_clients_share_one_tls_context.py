"""httpx 每建一个客户端就把整份 CA 证书重新载入一遍；在事件循环线程上现建现用时，那是循环上的卡顿。

``core.shared_tls`` 让最普通的那种调用（verify=True、无客户端证书）进程内只建一次，其余原样走 httpx 自己的路径。
"""

from __future__ import annotations

import ssl

import httpx
import pytest

import core.shared_tls as shared


def _wait_for_the_warm_up(counting, seconds=5.0):
    """安装时旁边的线程会先建第一份；等它建完，再数。"""
    import time

    deadline = time.time() + seconds
    while not counting and time.time() < deadline:
        time.sleep(0.01)


@pytest.fixture()
def installed(monkeypatch):
    import httpx._transports.default as transport

    monkeypatch.setattr(transport, "create_ssl_context", transport.create_ssl_context)  # 还原点
    monkeypatch.setattr(shared, "_installed", False)
    assert shared.install_shared_tls_context() is True
    return transport


@pytest.fixture()
def counting(monkeypatch):
    """数 ssl.create_default_context 被调了几次（httpx 载入 CA 证书走的就是它）。"""
    calls = []
    real = ssl.create_default_context

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(ssl, "create_default_context", counted)
    return calls


def test_many_clients_load_the_ca_bundle_once(counting, installed):
    _wait_for_the_warm_up(counting)
    for _ in range(6):
        httpx.AsyncClient()
        httpx.Client()
    assert len(counting) == 1


def test_the_same_context_object_is_shared(installed):
    import httpx._transports.default as transport

    assert transport.create_ssl_context(verify=True, cert=None, trust_env=True) is transport.create_ssl_context(
        verify=True, cert=None, trust_env=True
    )


def test_verify_false_and_custom_ca_take_httpxs_own_path(counting, installed):
    httpx.AsyncClient(verify=False)
    httpx.AsyncClient(verify=False)
    ctx = ssl.create_default_context()
    n = len(counting)
    c1, c2 = httpx.AsyncClient(verify=ctx), httpx.AsyncClient(verify=ctx)
    assert len(counting) == n  # 传进来的上下文照用，不重建
    assert c1 is not c2


def test_a_changed_ca_file_environment_gets_its_own_context(installed, monkeypatch):
    import httpx._transports.default as transport

    a = transport.create_ssl_context(verify=True, cert=None, trust_env=True)
    import certifi

    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    b = transport.create_ssl_context(verify=True, cert=None, trust_env=True)
    assert a is not b


def test_installing_twice_is_harmless(installed):
    assert shared.install_shared_tls_context() is True


def test_it_declines_quietly_when_httpx_changes_shape(monkeypatch):
    import sys

    monkeypatch.setattr(shared, "_installed", False)
    monkeypatch.setitem(sys.modules, "httpx._transports.default", None)  # import 失败
    assert shared.install_shared_tls_context() is False


def test_the_first_context_is_built_in_the_background_not_in_the_first_request(monkeypatch, counting):
    import httpx._transports.default as transport

    monkeypatch.setattr(transport, "create_ssl_context", transport.create_ssl_context)
    monkeypatch.setattr(shared, "_installed", False)
    shared.install_shared_tls_context()
    _wait_for_the_warm_up(counting)
    assert len(counting) == 1  # 没有任何客户端被建出来，已经有一份了
    httpx.AsyncClient()
    assert len(counting) == 1
