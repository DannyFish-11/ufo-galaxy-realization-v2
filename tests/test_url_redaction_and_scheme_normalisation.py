"""带凭据的 URL 不许进日志;缺 scheme 的地址不许把主机名弄丢。

两个被修的问题
--------------

**一、``GALAXY_NATS_URL`` / ``SECRETVAULT_URL`` 被原样写进日志。**

这不是洁癖:``core/nats_bus.py`` 调 ``nats.connect(target, ...)`` 时**没有传任何
user / password / token 参数**,也就是说在这个仓库里 NATS 鉴权**只能**靠
``nats://user:pass@host:4222`` 这种 URL 内嵌形式。所以那几行 ``logger.info(..., nats_url)``
就是把唯一的凭据通道明文记进日志。``SECRETVAULT_URL`` 同理,而它恰恰是**密钥库自己**的
地址 —— 最不该漏的地方。

当前配置下还没有实际泄露(仓库没配 NATS 鉴权),属于**潜在**缺口;但它不需要任何代码改动
就会变成现行泄露 —— 用户给 NATS 加个密码即可。

**二、``urlsplit`` 对缺 scheme 的地址行为反直觉,而且不一致。**

    urlsplit("http://localhost:32550") → scheme='http'      netloc='localhost:32550'
    urlsplit("localhost:32550")        → scheme='localhost' netloc=''  path='32550'  ← 主机没了
    urlsplit("192.168.1.7:9000")       → scheme=''          netloc=''  path='192...'

``localhost:32550`` 会被当成"scheme 是 localhost、路径是 32550",主机名整个丢掉;而
``192.168.1.7:9000`` 因为点分数字不是合法 scheme,反倒落进 path 里侥幸可用。**同一类输入
两种结果**,坏掉的恰好是最常见的写法。

我在 ``native_realtime_url()`` 里正是这么踩的:写了 ``parts.netloc or parts.path`` 并注释
"允许 localhost:32550 这种没有 scheme 的写法",实际推出来是 ``ws://32550/v1/realtime``
—— 端口当成了主机。这个地址是用户在面板里手填的,不带 scheme 完全正常。

为什么脱敏函数要单独成模块
--------------------------
它原先长在 ``core/voice_duplex_session.py``(第一次需要它的地方)。但 ``nats_bus`` /
``credential_vault`` 去 import 语音模块显然不对,各自再抄一份又会重演"复制粘贴的助手修一处
修不到其它处" —— 本仓库刚因 5 份逐字相同的 ``_flag()`` 吃过一次亏(见
``core/config_flags.py``)。所以提到 ``core/url_redaction.py``,语音模块保留同名再导出。

一句必须说清的边界
------------------
**脱敏不能替代"断数据流"。** CodeQL 的 ``py/clear-text-logging-sensitive-data`` 不会因为你
套了个清洗函数就放行:把 secret 喂进一个返回值会被打印的函数,那条边只会更明显(我为此在
alert 1026 上栽过一次)。脱敏管的是另一半:值本身来自用户配的地址、而那个地址可能夹带凭据。
两件事都要做,别互相替代。
"""

from __future__ import annotations

import ast
import inspect
import re

import pytest

from core.url_redaction import INVALID, normalise_base_url, safe_endpoint


class TestSafeEndpointStripsCredentials:
    @pytest.mark.parametrize(
        "url,expected",
        [
            # userinfo 形式 —— NATS 的标准鉴权写法
            ("nats://admin:s3cr3t@nats.internal:4222", "nats://nats.internal:4222"),
            ("nats://mytoken@10.0.0.5:4222", "nats://10.0.0.5:4222"),
            # 密码里含 @ —— hostname 应取最后一个 @ 之后的部分
            ("nats://admin:p@ssw0rd@nats.internal:4222", "nats://nats.internal:4222"),
            # query 形式 —— Gemini realtime 与不少本地网关这么带 token
            ("https://vault.internal:8200/v1?token=abcdef", "https://vault.internal:8200"),
            ("wss://x.example.com/ws?key=SECRETVALUE", "wss://x.example.com"),
            # 无凭据的正常地址应原样保留 host:port(诊断需要)
            ("nats://localhost:4222", "nats://localhost:4222"),
            ("http://localhost:32550", "http://localhost:32550"),
            ("https://api.example.com", "https://api.example.com"),
        ],
    )
    def test_only_scheme_host_port_survives(self, url, expected):
        assert safe_endpoint(url) == expected

    @pytest.mark.parametrize("bad", ["", "   ", "not a url", "://///", "http://h:notaport/"])
    def test_malformed_returns_placeholder_not_the_raw_string(self, bad):
        """畸形输入里照样可能有凭据,所以不回显原串。"""
        assert safe_endpoint(bad) == INVALID

    def test_never_raises(self):
        for weird in [None, 12345, object()]:
            try:
                safe_endpoint(weird)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"打日志的助手抛异常了: {exc!r}")

    def test_a_secret_never_appears_in_the_output(self):
        """总括性质:任意位置的凭据都不许出现在返回值里。"""
        secret = "7" * 32
        for url in (
            f"nats://user:{secret}@h:4222",
            f"nats://{secret}@h:4222",
            f"https://h:8200/p?token={secret}",
            f"https://h:8200/{secret}",
            f"https://h:8200/p#{secret}",
        ):
            assert secret not in safe_endpoint(url), url


class TestNormaliseBaseUrl:
    """缺 scheme 的地址必须先补齐,否则 urlsplit 会把主机名弄丢。"""

    def test_the_urlsplit_quirk_is_real(self):
        """先证明这个坑真的存在 —— 否则下面的修复没有前提。"""
        from urllib.parse import urlsplit

        assert urlsplit("localhost:32550").netloc == "", "urlsplit 行为变了,本测试前提需重核"
        assert urlsplit("localhost:32550").scheme == "localhost"
        assert urlsplit("localhost:32550").path == "32550"
        # 而点分数字不是合法 scheme,于是落进 path —— 同类输入两种结果
        assert urlsplit("192.168.1.7:9000").scheme == ""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("localhost:32550", "http://localhost:32550"),
            ("192.168.1.7:9000", "http://192.168.1.7:9000"),
            ("box.local", "http://box.local"),
            # 已有 scheme 的原样返回
            ("http://localhost:32550", "http://localhost:32550"),
            ("https://box:8443", "https://box:8443"),
            ("nats://h:4222", "nats://h:4222"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert normalise_base_url(raw) == expected

    def test_custom_default_scheme(self):
        assert normalise_base_url("h:4222", default_scheme="nats") == "nats://h:4222"

    def test_empty_stays_empty(self):
        assert normalise_base_url("") == ""
        assert normalise_base_url("   ") == ""

    def test_normalised_urls_parse_correctly(self):
        """真正要的性质:补完之后 urlsplit 能拿到主机名。"""
        from urllib.parse import urlsplit

        for raw in ("localhost:32550", "192.168.1.7:9000", "box.local"):
            parts = urlsplit(normalise_base_url(raw))
            assert parts.hostname, f"{raw} 补完后仍拿不到 hostname"


class TestNativeRealtimeUrlNoLongerLosesTheHost:
    """我踩的那个坑:``localhost:32550`` 推出 ``ws://32550/...``。"""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("GALAXY_NATIVE_REALTIME_PATH", raising=False)
        yield

    @pytest.mark.parametrize(
        "server,expected",
        [
            ("http://localhost:32550", "ws://localhost:32550/v1/realtime"),
            ("localhost:32550", "ws://localhost:32550/v1/realtime"),  # ← 修复前是 ws://32550/...
            ("192.168.1.7:9000", "ws://192.168.1.7:9000/v1/realtime"),
            ("https://box.local:8443", "wss://box.local:8443/v1/realtime"),
        ],
    )
    def test_host_survives(self, monkeypatch, server, expected):
        from core.voice_duplex_session import native_realtime_url

        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", server)
        assert native_realtime_url() == expected

    def test_the_old_implementation_really_lost_the_host(self):
        """把旧写法原样跑一遍,证明这个 bug 存在过 —— 不是我臆想的。"""
        from urllib.parse import urlsplit

        parts = urlsplit("localhost:32550")
        old_netloc = parts.netloc or parts.path  # 旧代码就是这么写的
        assert old_netloc == "32550", "旧写法居然没丢主机?那本次改动的前提就错了"

    def test_the_derived_url_is_still_judged_local(self, monkeypatch):
        """连带性质:修好之后推出的地址仍要被判成本地(否则又会去要 key)。"""
        from core.voice_duplex_session import is_local_endpoint, native_realtime_url

        monkeypatch.setenv("GALAXY_MINICPM_SERVER_URL", "localhost:32550")
        assert is_local_endpoint(native_realtime_url()) is True


class TestCredentialBearingUrlsAreRedactedAtTheirLogSites:
    """光有助手不够 —— 得真的用上。按 AST 检查那几个已知的调用点。"""

    #: (模块路径, 该模块里必须被脱敏的变量名)
    SITES = (
        ("core/nats_bus.py", ("ts_url", "target")),
        ("galaxy_gateway/bootstrap/lifecycle.py", ("nats_url",)),
    )

    @pytest.mark.parametrize("rel,names", SITES)
    def test_no_raw_credential_url_reaches_a_logger(self, rel, names):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in ("logger", "logging", "log")
                and f.attr in ("debug", "info", "warning", "error", "exception")
            ):
                continue
            for arg in node.args[1:]:
                if isinstance(arg, ast.Name) and arg.id in names:
                    offenders.append(f"{rel}:{node.lineno} logger.{f.attr}(..., {arg.id})")
        assert not offenders, "带凭据的 URL 被原样打进日志,应先过 safe_endpoint(): " + "; ".join(offenders)

    def test_nats_connect_really_has_no_separate_auth_args(self):
        """核实本文件的前提:NATS 鉴权确实只能走 URL。

        若哪天改成显式传 user/password,那 URL 就不再是凭据载体,上面几条的理由要重写。
        """
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        src = (root / "core/nats_bus.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "connect"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "nats"
        ]
        assert calls, "找不到 nats.connect 调用 —— 本测试的前提需重核"
        for c in calls:
            kw = {k.arg for k in c.keywords if k.arg}
            assert not (kw & {"user", "password", "token", "user_credentials"}), (
                "nats.connect 现在有独立鉴权参数了 —— URL 不再是唯一凭据通道," "本文件的理由需要重写"
            )

    def test_vault_log_is_redacted(self, monkeypatch, caplog):
        """密钥库自己的地址 —— 最不该漏的那个,端到端验一次。"""
        import importlib
        import logging

        secret = "7" * 24
        monkeypatch.setenv("SECRETVAULT_URL", f"https://vault.internal:8200/v1?token={secret}")
        import core.credential_vault as cv

        importlib.reload(cv)
        cls = next(
            c
            for _n, c in vars(cv).items()
            if inspect.isclass(c) and "SecretVault" in (c.__doc__ or "") and hasattr(c, "get")
        )
        with caplog.at_level(logging.INFO):
            cls()
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert secret not in joined, f"密钥库地址里的 token 被打进日志了: {joined}"
        assert "vault.internal:8200" in joined, "脱敏过头了,连主机都看不到就没法诊断"


class TestHelperLivesInOnePlace:
    """收敛必须是真的收敛 —— 不能留副本继续各自演化。"""

    def test_voice_module_reexports_rather_than_redefines(self):
        import core.voice_duplex_session as mod

        src = inspect.getsource(mod)
        assert "from core.url_redaction import safe_endpoint" in src
        assert not re.search(r"^def safe_endpoint\(", src, re.M), "语音模块又自己定义了一份"

    def test_still_importable_from_the_old_place(self):
        """既有调用点与测试不该因为搬家而挂。"""
        from core.voice_duplex_session import safe_endpoint as from_voice

        assert from_voice is safe_endpoint

    def test_no_other_module_defines_its_own(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        dupes = []
        for p in list((root / "core").rglob("*.py")) + list((root / "galaxy_gateway").rglob("*.py")):
            if p.name == "url_redaction.py":
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            if re.search(r"^def safe_endpoint\(", text, re.M):
                dupes.append(str(p.relative_to(root)))
        assert not dupes, f"又出现了副本: {dupes}"


class TestDuckGainUsesTheSharedNumHelper:
    """那次「合并 7 份重复助手」漏掉的第 8 份(它不叫 _num,躲过了搜索)。"""

    def test_defaults_unchanged(self, monkeypatch):
        from core.voice_duplex_session import duck_gain

        monkeypatch.delenv("GALAXY_VOICE_DUCK_GAIN", raising=False)
        assert duck_gain() == 0.25

    def test_empty_is_treated_as_unset(self, monkeypatch):
        from core.voice_duplex_session import duck_gain

        monkeypatch.setenv("GALAXY_VOICE_DUCK_GAIN", "")
        assert duck_gain() == 0.25

    @pytest.mark.parametrize("raw,expected", [("5", 1.0), ("-5", 0.0), ("0.5", 0.5)])
    def test_clamped(self, monkeypatch, raw, expected):
        from core.voice_duplex_session import duck_gain

        monkeypatch.setenv("GALAXY_VOICE_DUCK_GAIN", raw)
        assert duck_gain() == expected

    def test_invalid_warns_and_falls_back(self, monkeypatch, caplog):
        import logging

        from core.voice_duplex_session import duck_gain

        monkeypatch.setenv("GALAXY_VOICE_DUCK_GAIN", "abc")
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConfigFlags"):
            assert duck_gain() == 0.25
        assert caplog.records, "非法数值必须告警"

    def test_no_hand_rolled_parsing_remains(self):
        import core.voice_duplex_session as mod

        body = inspect.getsource(mod.duck_gain)
        assert "os.getenv" not in body, "又自己手写了一遍解析"
        assert "_num(" in body
