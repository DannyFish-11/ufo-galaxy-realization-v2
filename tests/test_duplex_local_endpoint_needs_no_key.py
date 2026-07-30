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

from core.voice_duplex_session import DuplexSessionConfig, is_local_endpoint

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
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mod, "_from_panel", lambda _k: "")
    monkeypatch.setattr(mod, "_from_vault", lambda _k: "")
    yield


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

    def test_native_active_adds_the_clarifying_line(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
        with caplog.at_level(logging.INFO, logger="Galaxy.VoiceDuplex"):
            assert DuplexSessionConfig.from_env() is None
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "本地原生听/说已就绪" in joined, f"没有说明原生其实是通的: {joined}"
        assert "GALAXY_REALTIME_URL" in joined, "没有告诉用户怎么把双工也指到本地"

    def test_no_such_line_when_native_is_off(self, monkeypatch, caplog):
        """对照组:原生没开就不该冒出这句,否则是另一种误导。"""
        import logging

        with caplog.at_level(logging.INFO, logger="Galaxy.VoiceDuplex"):
            assert DuplexSessionConfig.from_env() is None
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "本地原生听/说已就绪" not in joined


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
