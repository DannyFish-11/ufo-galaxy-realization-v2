"""本地 realtime 端点不需要云端 API key。

被修的 bug
----------
``DuplexSessionConfig.from_env()`` 无条件要求 key,拿不到就返回 ``None`` 并告警"缺少
API key"。但本地服务根本没有 key 这个概念。

B 档切过去之后 ``core.native_modal.activate()`` 会把 MiniCPM-o 官方 server 拉起来
(默认 ``localhost:32550``)并置 ``GALAXY_NATIVE_AUDIO=1``。这时::

    GALAXY_REALTIME_URL=ws://localhost:32550/v1/realtime
    GALAXY_NATIVE_AUDIO=1
    (没有云端 key)

旧逻辑一律判"缺 key → 退回回合制"。也就是说**本地服务配好了、端点也指对了,双工照样
起不来**,而且日志还把人引去配云端 key —— 那是完全无关的一件事。

这是纯逻辑错误,与任何 provider 的帧协议无关:WebSocket 传输层与会话循环(connect /
send / close、AEC、ducking、barge-in)本来就是 provider 无关的一份实现,能不能连上本地
服务跟"要不要 key"是两回事。

判据为什么取"回环/私网/.local"
------------------------------
另一个看似更简单的写法是"只要用户显式设了 GALAXY_REALTIME_URL 就免 key"。不采用:那样
会把指向**云端**的自定义 URL(代理、网关)也放过去,拿空 key 去建连换一个 401,反而更难
查。取"本机或本局域网"这个判据,含义明确,也正好覆盖本地全模态 server 这个真实场景。
"""

from __future__ import annotations

import pytest

from core.voice_duplex_session import DuplexSessionConfig, is_local_endpoint, safe_endpoint

REAL_LOOKING = "7" * 40


@pytest.fixture(autouse=True)
def _isolate_all_three_layers(monkeypatch):
    """三层都摘干净 —— 只摘 env 会被面板层的单例缓存击穿(详见
    tests/test_secret_resolution_and_duplex_key.py 里那条 fixture 的说明)。"""
    import core.secret_resolution as mod

    for k in (
        "GALAXY_REALTIME_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GALAXY_REALTIME_URL",
        "GALAXY_REALTIME_PROVIDER",
        "GALAXY_NATIVE_AUDIO",
        "GALAXY_NATIVE_REALTIME_PATH",
        "GALAXY_MINICPM_SERVER_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mod, "_from_panel", lambda _k: "")
    monkeypatch.setattr(mod, "_from_vault", lambda _k: "")
    yield


class TestAutoPointsAtTheLocalNativeServer:
    """B 档原生就绪时,自动去试本地全模态 server 的 realtime 端点。

    为什么是"推导 + 去试"而不是等人确认协议
    --------------------------------------
    MiniCPM-o server 到底有没有 OpenAI 兼容的 realtime 端点,只有那台机器上才知道。在代码
    里猜没有意义,**编造帧协议更是错的**。

    但"不确定"不等于什么都不能做:这条链路上的失败是**安全且已被处理**的 ——
    ``open_duplex_session()`` 连不上返回 None,``voice_loop`` 收到 None 就回落回合制,而
    回合制现在听/说都走原生。所以最坏情况是"没拿到流式,但仍然全原生",不是坏掉。

    于是:自动试一次。通了就是真流式双工,不通就安静退回原生回合制。两种服务器都覆盖,
    一行协议也没编。
    """

    def test_derives_ws_url_from_the_server_address(self, monkeypatch):
        from core.voice_duplex_session import native_realtime_url

        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", "http://localhost:32550")
        assert native_realtime_url() == "ws://localhost:32550/v1/realtime"

    def test_https_maps_to_wss(self, monkeypatch):
        from core.voice_duplex_session import native_realtime_url

        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", "https://box.local:8443")
        assert native_realtime_url() == "wss://box.local:8443/v1/realtime"

    def test_path_is_overridable(self, monkeypatch):
        """server 不按 OpenAI 惯例时,改路径就行,不必动代码。"""
        from core.voice_duplex_session import native_realtime_url

        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", "http://localhost:32550")
        monkeypatch.setenv("GALAXY_NATIVE_REALTIME_PATH", "audio/stream")  # 没有前导斜杠也要认
        assert native_realtime_url() == "ws://localhost:32550/audio/stream"

    def test_reuses_the_same_address_source_as_native_modal(self):
        """地址只能有一个来源,否则两处会漂。"""
        import inspect

        import core.voice_duplex_session as mod

        assert "from core.native_modal import _server_url" in inspect.getsource(mod.native_realtime_url)

    def test_auto_used_when_native_on_and_no_explicit_url(self, monkeypatch):
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", "http://localhost:32550")
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None, "B 档原生就绪却没去试本地流式"
        assert cfg.url == "ws://localhost:32550/v1/realtime"
        assert cfg.api_key == "", "本地端点不该要 key"

    def test_explicit_url_always_wins(self, monkeypatch):
        """用户显式配了就完全不走推导 —— 自动化不能覆盖明示的意图。"""
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://192.168.5.5:1234/rt")
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None and cfg.url == "ws://192.168.5.5:1234/rt"

    def test_not_used_when_native_is_off(self, monkeypatch):
        """A 档行为必须一字不变:没 key 没 URL → 仍然退回回合制。"""
        monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
        assert DuplexSessionConfig.from_env() is None

    def test_cloud_key_path_is_untouched_by_the_derivation(self, monkeypatch):
        """原生开着、但用户配了云端 key 且没配 URL —— 不能把云端那条路抢走。

        这条是防回归的:推导只在"没有显式 URL"时介入,而云端默认 URL 是在 provider 分支里
        才拼的。若推导抢先,配了 OPENAI_API_KEY 的人会莫名其妙连到本地。
        """
        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", "http://localhost:32550")
        monkeypatch.setenv("GALAXY_REALTIME_URL", "wss://api.openai.com/v1/realtime")
        monkeypatch.setenv("OPENAI_API_KEY", REAL_LOOKING)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.url == "wss://api.openai.com/v1/realtime"
        assert cfg.api_key == REAL_LOOKING

    def test_failure_to_derive_is_not_fatal(self, monkeypatch):
        import core.voice_duplex_session as mod

        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        monkeypatch.setattr(mod, "native_realtime_url", lambda: "")
        assert DuplexSessionConfig.from_env() is None  # 安静退回,不抛

    def test_the_fallback_chain_is_intact(self):
        """核实本方案赖以成立的前提:连不上 → 返回 None → 调用方回落回合制。

        没有这条,"试不通也安全"就只是我的说法,不是被验证过的事实。
        """
        import ast
        import inspect

        import core.voice_duplex_session as duplex
        import core.voice_loop as loop

        d = ast.unparse(ast.parse(inspect.getsource(duplex.open_duplex_session)))
        assert "if not await sess.connect():" in d and "return None" in d, "连接失败不再返回 None"

        loop_src = inspect.getsource(loop)
        assert "if session is None:" in loop_src and "return False" in loop_src, "调用方不再回落回合制"


class TestLocalEndpointJudgement:
    @pytest.mark.parametrize(
        "url",
        [
            "ws://localhost:32550/v1/realtime",
            "ws://127.0.0.1:32550/v1/realtime",
            "ws://[::1]:32550/v1/realtime",
            "ws://192.168.1.50:32550/v1/realtime",
            "ws://10.0.0.5:32550/v1/realtime",
            "ws://172.16.3.9:32550/v1/realtime",
            "ws://minicpm.local:32550/v1/realtime",
        ],
    )
    def test_local_urls(self, url):
        assert is_local_endpoint(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",
            "wss://generativelanguage.googleapis.com/ws/x",
            "wss://my-proxy.example.com/v1/realtime",
            "ws://8.8.8.8/v1/realtime",
        ],
    )
    def test_remote_urls(self, url):
        assert is_local_endpoint(url) is False

    @pytest.mark.parametrize("url", ["", "not a url", "://///", None])
    def test_malformed_never_raises(self, url):
        """URL 畸形不该让调用方崩,也不该被误判成本地(免 key 是放宽,不能靠猜)。"""
        assert is_local_endpoint(url if url is not None else "") is False


class TestUrlIsNeverLoggedInFull:
    """realtime URL 是**带凭据的**,任何日志都只许打 ``scheme://host:port``。

    本模块 Gemini 那一支的 URL 形如::

        wss://generativelanguage.googleapis.com/ws/...BidiGenerateContent?key={key}

    —— API key 直接拼在 query 里。我自己在加"本地端点免 key"那段时把整个 url 打进了
    INFO 日志(CodeQL alert 1025 指的就是那一行),这是实打实的明文泄露,不是误报:本地
    网关用 query 带 token 很常见,用户一旦把 GALAXY_REALTIME_URL 设成那种形式就会中招。
    """

    def test_query_string_is_dropped(self):
        got = safe_endpoint("wss://example.com/ws/x?key=" + REAL_LOOKING)
        assert REAL_LOOKING not in got
        assert "?" not in got and "key=" not in got
        assert got == "wss://example.com"

    def test_userinfo_is_dropped(self):
        """``wss://user:pass@host/`` 这种把凭据放在 userinfo 里的形式同样要丢掉。"""
        got = safe_endpoint("wss://user:" + REAL_LOOKING + "@example.com:8443/ws")
        assert REAL_LOOKING not in got
        assert "@" not in got
        assert got == "wss://example.com:8443"

    def test_path_is_dropped(self):
        assert safe_endpoint("ws://localhost:32550/v1/realtime") == "ws://localhost:32550"

    def test_port_is_kept(self):
        """端口要留 —— 诊断"连的是哪台机器"时它是有用信息,且不含凭据。"""
        assert safe_endpoint("ws://127.0.0.1:32550/x") == "ws://127.0.0.1:32550"

    @pytest.mark.parametrize("bad", ["", "not a url", "://///", "ws://host:notaport/"])
    def test_malformed_never_raises(self, bad):
        assert safe_endpoint(bad) == "(无效地址)"

    def test_the_real_gemini_url_shape_is_scrubbed(self):
        """用本模块真实构造的那种形状验一遍,而不是我编的例子。"""
        gemini = (
            "wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1alpha.GenerativeService."
            f"BidiGenerateContent?key={REAL_LOOKING}"
        )
        got = safe_endpoint(gemini)
        assert REAL_LOOKING not in got
        assert got == "wss://generativelanguage.googleapis.com"

    def test_local_branch_log_does_not_contain_the_full_url(self, monkeypatch, caplog):
        """端到端:走本地免 key 那条分支时,日志里不许出现 query。"""
        import logging

        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://localhost:32550/v1/realtime?token=" + REAL_LOOKING)
        with caplog.at_level(logging.INFO, logger="Galaxy.VoiceDuplex"):
            cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert REAL_LOOKING not in joined, f"日志把 URL 里的凭据打出来了: {joined}"
        assert "token=" not in joined

    def test_no_log_call_in_the_module_takes_a_raw_url(self):
        """结构性守卫:本模块任何日志调用都不许直接把 url 类变量当参数。

        只修我踩的那一行是不够的 —— 下一个人加日志时会照样写 ``logger.info("...", url)``。
        这条按 AST 检查所有 logger 调用的实参,凡是名字像 url/endpoint/uri 的一律不许直接传,
        必须先过 ``safe_endpoint()``。
        """
        import ast
        import inspect
        import re

        import core.voice_duplex_session as mod

        urlish = re.compile(r"(url|endpoint|uri)$", re.I)
        tree = ast.parse(inspect.getsource(mod))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "logger"
                and f.attr in ("debug", "info", "warning", "error", "exception")
            ):
                continue
            for arg in node.args[1:]:
                name = arg.id if isinstance(arg, ast.Name) else (arg.attr if isinstance(arg, ast.Attribute) else None)
                if name and urlish.search(name):
                    offenders.append(f"line {node.lineno}: logger.{f.attr}(..., {name})")
        assert not offenders, "日志里直接传了 URL(可能带凭据),应先过 safe_endpoint(): " + "; ".join(offenders)

    def test_logged_value_is_not_derived_from_the_key(self):
        """结构性:本地分支打的必须是 configured_url,而不是可能被 key 拼过的 url。

        我上一版写的是 ``safe_endpoint(url)``,以为脱敏函数就够了 —— CodeQL 照报
        (alert 1026),而且它是对的:``key → url → safe_endpoint(url) → 返回值 → logger``
        这条数据流摆在那里,静态分析没有理由相信某个函数把密钥清干净了。同一个道理我在
        scripts/verify_provider_apis.py 的注释里已经写过一遍,这次又犯了同一个错。

        所以这条不测"脱没脱敏",而是直接钉住**被打印的值不来自 key** 这个更强的性质。
        """
        import ast
        import inspect
        import re

        import core.voice_duplex_session as mod

        tree = ast.parse(inspect.getsource(mod))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "from_env")
        # configured_url 可以被赋值多次(环境变量 / 本地推导),但**每一次的右值都不许沾 key**。
        # 我第一版断言的是"只许赋值一次" —— 那是把手段当成了目的:加了本地地址推导之后它
        # 合法地变成两次,断言就假报了。真正要守的性质是"不来自 key",直接断言这个。
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "configured_url" for t in n.targets):
                continue
            rhs = ast.unparse(n.value)
            assert not re.search(r"\bkey\b", rhs), f"configured_url 被 key 污染了: {rhs}"

        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "logger":
                rendered = ast.unparse(node)
                assert "safe_endpoint(url)" not in rendered, "日志里又用回了被 key 污染的 url"

    def test_configured_url_and_url_agree_on_the_local_branch(self, monkeypatch):
        """核实上面那条注释里的推理:走到本地分支时两者本来就相等,所以换用不丢信息。"""
        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://localhost:32550/v1/realtime")
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.url == "ws://localhost:32550/v1/realtime"

    def test_the_guard_would_catch_a_regression(self):
        """反向证明上面那条真的会抓人 —— 否则它可能只是恒真。"""
        import ast
        import re

        urlish = re.compile(r"(url|endpoint|uri)$", re.I)
        bad = ast.parse('logger.info("endpoint is %s", url)\n')
        found = [
            a.id
            for n in ast.walk(bad)
            if isinstance(n, ast.Call)
            for a in n.args[1:]
            if isinstance(a, ast.Name) and urlish.search(a.id)
        ]
        assert found == ["url"], "守卫的检测逻辑本身失效了"

    def test_the_config_itself_still_keeps_the_full_url(self, monkeypatch):
        """对照:脱敏只针对**日志**,配置对象里必须是完整 URL —— 否则连都连不上。

        没有这条,一个"把 url 整个截断"的实现也能让上面那些断言变绿。
        """
        full = "ws://localhost:32550/v1/realtime?token=" + REAL_LOOKING
        monkeypatch.setenv("GALAXY_REALTIME_URL", full)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None and cfg.url == full


class TestLocalEndpointBuildsConfigWithoutKey:
    """核心复现:指向本地 + 无 key → 必须建得出配置。"""

    def test_local_url_without_key_still_builds(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://localhost:32550/v1/realtime")
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None, "本地服务不需要 key,却仍被判成「缺 key,退回回合制」"
        assert cfg.api_key == ""
        assert cfg.url == "ws://localhost:32550/v1/realtime"

    def test_the_old_behaviour_really_was_broken(self, monkeypatch):
        """证明这个 bug 真的存在过:去掉本地判据后,同样的配置会返回 None。

        没有这条,上面那条只能说明"现在是对的",无法说明"以前是错的"。
        """
        import core.voice_duplex_session as mod

        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://localhost:32550/v1/realtime")
        monkeypatch.setattr(mod, "is_local_endpoint", lambda _u: False)
        assert DuplexSessionConfig.from_env() is None

    def test_remote_url_without_key_still_returns_none(self, monkeypatch):
        """对照组:远端端点没 key 仍必须退回 —— 否则就是拿空 key 去换 401。"""
        monkeypatch.setenv("GALAXY_REALTIME_URL", "wss://api.openai.com/v1/realtime")
        assert DuplexSessionConfig.from_env() is None

    def test_default_cloud_url_without_key_still_returns_none(self, monkeypatch):
        """没设 URL 时用的是内置云端默认值,同样必须要 key。"""
        assert DuplexSessionConfig.from_env() is None

    def test_a_real_key_is_still_honoured_on_a_local_url(self, monkeypatch):
        """本地端点免 key,但**给了** key 也不能丢掉(有人给本地服务加了鉴权)。"""
        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://localhost:32550/v1/realtime")
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", REAL_LOOKING)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None and cfg.api_key == REAL_LOOKING

    def test_local_url_reuses_the_openai_adapter(self, monkeypatch):
        """不需要新写 adapter:本地服务若是 OpenAI 兼容的,复用既有那个即可。

        这条把"WebSocket 是共用传输、adapter 只是帧格式"这个事实钉住 —— 免得后人以为
        换个端点就得再写一份传输。
        """
        from core.voice_duplex_session import _ADAPTERS

        monkeypatch.setenv("GALAXY_REALTIME_URL", "ws://localhost:32550/v1/realtime")
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.provider == "openai_realtime"
        assert cfg.provider in _ADAPTERS, "默认 provider 不在登记表里"


class TestDiagnosticNoLongerMisleads:
    """原生已就绪时,日志不能只说"缺 key" —— 那会让人以为语音整个是瞎的。"""

    def test_native_active_now_auto_points_local_instead_of_just_warning(self, monkeypatch, caplog):
        """原先这里断言的是一句「补充:本地原生听/说已就绪…」的提示。

        加上自动推导之后那句变成了死代码 —— 原生就绪且没 key 时,地址已经被指向本地并
        返回了配置,根本走不到那条告警。所以这条测试改成断言**新的真实行为**:不再是
        「告诉你怎么手动配」,而是直接替你接上。
        """
        import logging

        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        with caplog.at_level(logging.INFO, logger="Galaxy.VoiceDuplex"):
            cfg = DuplexSessionConfig.from_env()
        assert cfg is not None, "原生就绪时应自动指向本地,而不是退回并只给一句提示"
        assert is_local_endpoint(cfg.url)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "自动尝试本地全模态 server" in joined
        assert "原生回合制" in joined, "没说清试不通时会退回到哪里"

    def test_no_auto_local_when_native_is_off(self, monkeypatch, caplog):
        """对照组:原生没开就不该自动指本地(那台 server 根本没在跑)。"""
        import logging

        with caplog.at_level(logging.INFO, logger="Galaxy.VoiceDuplex"):
            assert DuplexSessionConfig.from_env() is None
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "自动尝试本地全模态 server" not in joined

    def test_the_dead_hint_is_really_gone(self):
        """那句死掉的提示必须真的删掉 —— 留着一句永远不会打印、却声称在帮人排查的日志,
        比没有更坏。

        注意必须比对**剥掉注释后**的代码:我在原处留了一条注释解释「这里原先有一句…」,
        直接扫源码会命中那条注释,断言就永远失败。这个坑本轮已经踩到第五次了。
        """
        import ast
        import inspect
        import textwrap
        import tokenize
        from io import StringIO

        import core.voice_duplex_session as mod

        src = textwrap.dedent(inspect.getsource(mod.DuplexSessionConfig.from_env))
        # 先按 token 去掉注释(ast.unparse 会丢注释,但它保不住 # 之外的东西,双保险)
        out = []
        for tok in tokenize.generate_tokens(StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok)
        stripped = tokenize.untokenize(out)
        tree = ast.parse(stripped)
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    if isinstance(first.value.value, str):
                        body.pop(0)
        code = ast.unparse(tree)
        assert "补充:本地原生听/说已就绪" not in code, "那句死掉的提示还在代码里"

    def test_the_stripper_used_above_actually_strips(self):
        """自证上一条的剥离真的有效 —— 否则它可能只是恒真。"""
        import ast

        tree = ast.parse('def f():\n    """doc 补充"""\n    x = 1  # 补充\n')
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    if isinstance(first.value.value, str):
                        body.pop(0)
        code = ast.unparse(tree)
        assert "补充" not in code and "x = 1" in code


class TestTransportIsSharedNotPerProvider:
    """把"WebSocket 只有一份、每家不同的只是帧格式"这个结构事实钉住。

    这次讨论的起点就是"我不是已经有 websocket 了,还要单独写 adapter 吗"。答案是:传输
    共用,adapter 只管帧。写成测试,免得日后有人为了新 provider 又复制一份连接逻辑。
    """

    def test_adapters_do_not_touch_the_transport(self):
        import ast
        import inspect

        import core.voice_duplex_session as mod

        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Adapter"):
                body = ast.unparse(node)
                assert "websockets.connect" not in body, f"{node.name} 自己建连了 —— 传输应当共用"
                assert "await " not in body, f"{node.name} 有异步 I/O —— adapter 应当是纯函数"

    def test_every_adapter_implements_the_same_surface(self):
        from core.voice_duplex_session import _ADAPTERS, ProtocolAdapter

        surface = {m for m in vars(ProtocolAdapter) if not m.startswith("_")}
        for name, cls in _ADAPTERS.items():
            missing = sorted(surface - set(dir(cls)))
            assert not missing, f"{name} 少实现了 {missing}"

    def test_connection_logic_exists_exactly_once(self):
        import inspect

        import core.voice_duplex_session as mod

        src = inspect.getsource(mod)
        assert src.count("websockets.connect(") == 1, "建连逻辑出现了不止一处 —— 传输被复制了"
