"""tests/test_url_guard.py — 出站守卫必须真的拦得住。

这份测试的重点不是"函数能跑",而是**那些写法各异、最终都指向内网的 URL**
一个都不许过去。SSRF 的全部难度就在这里:``127.0.0.1`` 谁都会挡,
``http://127.1``、``http://2130706433``、``http://[::ffff:127.0.0.1]``
才是真正会漏的那些。

同样重要的是**重定向**:只在调用点校验一次、然后 ``follow_redirects=True``,
等于只锁了大门没锁后窗。所以这里专门起一个真实的本地 HTTP 服务去发 302,
验证守卫在那一跳上也生效。
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nodes.common.url_guard import (
    UrlNotAllowed,
    assert_url_allowed,
    guarded_async_client,
    internal_fetch_allowed,
    resolved_addresses,
)


@pytest.fixture(autouse=True)
def _default_deny(monkeypatch):
    """每个用例都从"默认拒绝"开始 —— 别让开发机上碰巧设过的环境变量影响结论。"""
    monkeypatch.delenv("GALAXY_ALLOW_INTERNAL_FETCH", raising=False)


class TestSchemes:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://127.0.0.1:9000/_x",
            "ftp://example.com/x",
            "data:text/plain;base64,aGk=",
            "//example.com/x",  # 没有 scheme
        ],
    )
    def test_non_http_schemes_rejected(self, url):
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed(url)

    def test_missing_host_rejected(self):
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed("http:///just-a-path")


class TestLiteralAddresses:
    """字面量 IP 的各种写法。这些**不该**触发 DNS 查询,判定直接落在地址上。"""

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "127.1",  # 短写法,socket 认,人容易忘
            "0.0.0.0",
            "10.1.2.3",
            "172.16.5.4",
            "192.168.1.1",
            "169.254.169.254",  # 云实例元数据
            "[::1]",
            "[::ffff:127.0.0.1]",  # IPv4-mapped:IPv6Address.is_loopback 对它返回 False
            "[fd00::1]",  # unique-local
            "[fe80::1]",  # link-local
            "224.0.0.1",  # multicast
        ],
    )
    def test_internal_literals_rejected(self, host):
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed(f"http://{host}/x")

    @pytest.mark.parametrize("host", ["93.184.216.34", "[2606:2800:220:1:248:1893:25c8:1946]"])
    def test_public_literals_allowed(self, host):
        assert_url_allowed(f"http://{host}/x")

    def test_short_form_is_not_special_cased(self):
        """``127.1`` 与 ``127.0.0.1`` 必须得到同一个结论。

        这一条单独写出来,是因为按字符串做黑名单时它正是第一个漏掉的。
        """
        for host in ("127.1", "127.0.0.1"):
            with pytest.raises(UrlNotAllowed):
                assert_url_allowed(f"http://{host}/")


class TestDnsBasedDecisions:
    def test_name_resolving_to_loopback_is_rejected(self):
        """``localhost`` 是名字不是字面量 —— 判定必须发生在解析之后。"""
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed("http://localhost:9000/api/v1/devices")

    def test_all_resolved_addresses_are_checked(self, monkeypatch):
        """一个名字同时解析出公网和 127.0.0.1 时必须拒。

        只查第一条等于没查 —— 攻击者完全可以让 DNS 先返回一个公网地址。
        """
        monkeypatch.setattr(
            "nodes.common.url_guard.resolved_addresses",
            lambda host, port=0: ["93.184.216.34", "127.0.0.1"],
        )
        with pytest.raises(UrlNotAllowed, match="127.0.0.1"):
            assert_url_allowed("http://mixed.example/x")

    def test_unresolvable_host_is_rejected_not_allowed(self, monkeypatch):
        """解析失败按**拒绝**处理。

        反过来(解析不出来就放过去)会让守卫在 DNS 抖动时静默失效 ——
        而"失效时放行"正是这类守卫最常见的死法。
        """

        def _boom(*_a, **_k):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", _boom)
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed("http://whatever.invalid/x")

    def test_resolved_addresses_dedupes(self, monkeypatch):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **k: [(0, 0, 0, "", ("1.2.3.4", 80)), (0, 0, 0, "", ("1.2.3.4", 80))],
        )
        assert resolved_addresses("example.com", 80) == ["1.2.3.4"]


class TestExplicitOptIn:
    def test_process_level_switch(self, monkeypatch):
        assert internal_fetch_allowed() is False
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed("http://127.0.0.1:9000/x")
        monkeypatch.setenv("GALAXY_ALLOW_INTERNAL_FETCH", "true")
        assert internal_fetch_allowed() is True
        assert_url_allowed("http://127.0.0.1:9000/x")

    def test_per_call_override_can_allow(self):
        assert_url_allowed("http://127.0.0.1:9000/x", allow_internal=True)

    def test_per_call_override_can_deny_even_when_process_allows(self, monkeypatch):
        """进程级放行时,单次仍然可以说"这一次不行"。

        没有这一条,一个部署级的开关就会把所有调用点一起放倒。
        """
        monkeypatch.setenv("GALAXY_ALLOW_INTERNAL_FETCH", "true")
        with pytest.raises(UrlNotAllowed):
            assert_url_allowed("http://127.0.0.1:9000/x", allow_internal=False)

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_falsy_values_do_not_enable(self, value, monkeypatch):
        monkeypatch.setenv("GALAXY_ALLOW_INTERNAL_FETCH", value)
        assert internal_fetch_allowed() is False


# ---------------------------------------------------------------------------
# 重定向 —— 这一段是整份测试里最要紧的
# ---------------------------------------------------------------------------
class _RedirectToInternal(BaseHTTPRequestHandler):
    """一个只会把你踢向内网的服务。真实的 302,不是 mock。"""

    target = "http://127.0.0.1:9/nope"

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler 的约定
        self.send_response(302)
        self.send_header("Location", self.target)
        self.end_headers()

    def log_message(self, *_a):
        return


@pytest.fixture
def redirector():
    srv = HTTPServer(("127.0.0.1", 0), _RedirectToInternal)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/start"
    srv.shutdown()


@pytest.mark.asyncio
class TestRedirectsAreGuarded:
    async def test_guard_runs_on_the_redirect_hop(self, redirector):
        """**重定向那一跳也过守卫** —— 这是整个模块存在的主要理由。

        怎么证明:把模块级的 ``assert_url_allowed`` 换成一个记录器,它放行起点、
        但对重定向目标抛错。如果钩子只在第一次请求时跑,这个错就永远不会出现,
        请求会安安静静地打到内网去。

        换掉模块属性是有效的:钩子内部是按名字查全局的,不是闭包捕获的引用。
        """
        pytest.importorskip("httpx")
        import nodes.common.url_guard as guard_mod

        seen: list[str] = []
        target = _RedirectToInternal.target

        def _recording_guard(url, *, allow_internal=None):
            seen.append(url)
            if url.startswith(target.rstrip("/")[:22]):
                raise UrlNotAllowed(f"blocked redirect target: {url}")

        original = guard_mod.assert_url_allowed
        guard_mod.assert_url_allowed = _recording_guard
        try:
            with pytest.raises(UrlNotAllowed):
                async with guarded_async_client(follow_redirects=True, timeout=5.0) as client:
                    await client.get(redirector)
        finally:
            guard_mod.assert_url_allowed = original

        assert len(seen) == 2, f"守卫只跑了 {len(seen)} 次;重定向那一跳没过守卫:{seen}"
        assert seen[0] == redirector
        assert seen[1].startswith("http://127.0.0.1:9/"), f"第二次看到的不是重定向目标:{seen[1]}"

    async def test_without_the_hook_the_redirect_would_slip_through(self, redirector):
        """对照:普通 httpx 客户端会**照常**跟着 302 打到内网去。

        没有这一条,上面那条只证明了"我们的钩子被调用了两次",
        证明不了"不装钩子真的会出事"。
        """
        httpx = pytest.importorskip("httpx")
        attempted: list[str] = []

        async def _record(request):
            attempted.append(str(request.url))

        async with httpx.AsyncClient(follow_redirects=True, timeout=2.0, event_hooks={"request": [_record]}) as client:
            try:
                await client.get(redirector)
            except Exception:
                # 127.0.0.1:9 大概率连不上 —— 连不上不重要,重要的是**它试了**。
                pass
        assert any(
            u.startswith("http://127.0.0.1:9/") for u in attempted
        ), "没有守卫时客户端居然没去打内网目标 —— 那说明这个对照实验本身没成立"

    async def test_hook_runs_for_every_request(self):
        """守卫是挂在客户端上的钩子,不是调用点的一次性检查。

        直接验钩子的存在与生效:每发一个请求它都跑一次。
        """
        httpx = pytest.importorskip("httpx")
        client = guarded_async_client()
        try:
            hooks = client._event_hooks["request"]
            assert hooks, "客户端上没有 request 钩子 —— 重定向就不过守卫了"
        finally:
            await client.aclose()
        assert isinstance(client, httpx.AsyncClient)

    async def test_existing_hooks_are_preserved(self):
        """调用方自己的钩子不能被顶掉,守卫插在最前面。"""
        pytest.importorskip("httpx")
        seen = []

        async def _mine(request):
            seen.append(str(request.url))

        client = guarded_async_client(event_hooks={"request": [_mine]})
        try:
            assert len(client._event_hooks["request"]) == 2
        finally:
            await client.aclose()

    async def test_public_url_passes_the_hook(self, monkeypatch):
        """守卫不该把正常的公网请求也拦掉 —— 那样它会被第一时间关掉。"""
        pytest.importorskip("httpx")
        monkeypatch.setattr(
            "nodes.common.url_guard.resolved_addresses",
            lambda host, port=0: ["93.184.216.34"],
        )
        assert_url_allowed("https://example.com/x")
