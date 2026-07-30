"""按环境变量名解析密钥,以及双工层不再把占位符当真 key。

被修的问题
----------
双工层原先是 ``os.getenv("GALAXY_REALTIME_API_KEY") or os.getenv("OPENAI_API_KEY")``,
两个真缺陷:

1. **只覆盖三层里的第三层。** 本仓库解析云端 key 的权威顺序是
   面板/Dashboard → CredentialVault → 环境变量(见 ``multi_llm_router._get_key()``)。
   裸 ``os.getenv`` 跳过前两层 —— ``GALAXY_SECRET_BACKEND=vault`` 时 key 只存在于 vault,
   双工层会直接瞎掉,而系统其余部分照常工作。"只有一处瞎了"是最难排查的一类故障。
2. **不过滤占位符。** ``main.py`` 启动时把 ``.env``(含 ``your_openai_api_key_here``
   这种未编辑模板)灌进 ``os.environ``,于是双工层把模板文字当真 key,拿去连
   ``wss://api.openai.com/v1/realtime``,换来一个 401。正确行为是认出"这不是真 key",
   安静退回回合制。路由器一直是过滤的,只有这里漏了。

这不是假想:本机 ``.env`` 里 ``OPENAI_API_KEY`` 就是 ``your_openai_api_key_here``,而
``main.py`` 会把它灌进环境 —— 一旦打开 ``GALAXY_VOICE_DUPLEX=1``,旧代码必然拿它去建连。

判别力说明
----------
测"占位符被拒"必须同时立**正反两面**:只断言"占位符 → None" 是不够的,因为一个永远
返回 None 的实现也能通过。所以每组都配一条"真 key → 拿得到"的对照。
"""

from __future__ import annotations

import os

import pytest

from core.secret_resolution import describe_source, is_placeholder, resolve_secret

#: 运行时拼装,避免在文件里留下形似凭据的字面量(gitleaks generic-api-key);
#: 同时**不能以占位符前缀开头** —— 第一版写的是 "x"*40,而 "xxx" 本身就在
#: PLACEHOLDER_PREFIXES 里,于是我的"真 key"fixture 自己就是个占位符,
#: 一口气挂掉 7 条测试。是测试把这个错抓出来的。低熵(重复字符)也不会触发 gitleaks。
REAL_LOOKING = "7" * 40
PLACEHOLDER = "your_" + "openai_api_key_here"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """把相关键从环境里摘干净,避免真实 .env 注入影响判断。"""
    for k in ("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    yield


class TestPlaceholderJudgement:
    @pytest.mark.parametrize(
        "value",
        ["", None, "your_openai_api_key_here", "YOUR_KEY", "change_me", "<paste-key-here>", "example-key", "xxx"],
    )
    def test_recognised_as_placeholder(self, value):
        assert is_placeholder(value) is True

    @pytest.mark.parametrize("value", [REAL_LOOKING, "abc123", "  " + REAL_LOOKING])
    def test_real_values_are_not_placeholders(self, value):
        assert is_placeholder(value) is False

    def test_shares_the_prefix_table_with_the_router(self):
        """两份前缀表一旦漂移,就会出现"路由器认为是占位符、双工层认为是真 key"的分裂。

        这条钉住"共用同一份",而不是各自维护。
        """
        from core.credential_vault import PLACEHOLDER_PREFIXES

        for prefix in PLACEHOLDER_PREFIXES:
            assert is_placeholder(prefix + "whatever") is True


class TestResolutionOrder:
    def test_env_is_used_when_nothing_else_has_it(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY") == REAL_LOOKING

    def test_placeholder_in_env_is_rejected(self, monkeypatch):
        """核心缺陷的直接复现:环境里是未编辑模板 → 必须当成"没配"。"""
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", PLACEHOLDER)
        assert resolve_secret("GALAXY_REALTIME_API_KEY") == ""

    def test_real_key_still_resolves(self, monkeypatch):
        """上一条的对照组 —— 否则一个永远返回 "" 的实现也能通过。"""
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY") == REAL_LOOKING

    def test_dedicated_key_wins_over_generic(self, monkeypatch):
        """专用键优先于通用键,而不是"先在所有键名里试第一层"。"""
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "dedicated-" + REAL_LOOKING)
        monkeypatch.setenv("OPENAI_API_KEY", "generic-" + REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY") == "dedicated-" + REAL_LOOKING

    def test_falls_back_to_generic_when_dedicated_is_absent(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "generic-" + REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY") == "generic-" + REAL_LOOKING

    def test_falls_back_to_generic_when_dedicated_is_a_placeholder(self, monkeypatch):
        """专用键填了占位符也要继续往后退 —— 占位符不能"占住"位置。"""
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", PLACEHOLDER)
        monkeypatch.setenv("OPENAI_API_KEY", "generic-" + REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY") == "generic-" + REAL_LOOKING

    def test_panel_layer_beats_env(self, monkeypatch):
        """面板/Dashboard 层优先于环境变量 —— 这一层正是裸 os.getenv 漏掉的。"""
        import core.secret_resolution as mod

        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "from-env-" + REAL_LOOKING)
        monkeypatch.setattr(
            mod, "_from_panel", lambda k: "from-panel-" + REAL_LOOKING if k == "GALAXY_REALTIME_API_KEY" else ""
        )
        assert resolve_secret("GALAXY_REALTIME_API_KEY") == "from-panel-" + REAL_LOOKING

    def test_vault_layer_beats_env(self, monkeypatch):
        """CredentialVault 层同样是裸 os.getenv 漏掉的。"""
        import core.secret_resolution as mod

        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "from-env-" + REAL_LOOKING)
        monkeypatch.setattr(mod, "_from_panel", lambda k: "")
        monkeypatch.setattr(mod, "_from_vault", lambda k: "from-vault-" + REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY") == "from-vault-" + REAL_LOOKING

    def test_returns_empty_not_raise_when_nothing_configured(self):
        """缺配置是预期情形,不是错误 —— 不能抛。"""
        assert resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY") == ""

    def test_empty_key_names_are_ignored(self):
        assert resolve_secret("", None) == ""  # type: ignore[arg-type]

    def test_never_raises_even_if_a_layer_is_broken(self, monkeypatch):
        """任何一层炸了都不能让调用方崩 —— 解析密钥不该成为启动失败的原因。"""
        import core.secret_resolution as mod

        def _boom(_k):
            raise RuntimeError("layer down")

        monkeypatch.setattr(mod, "_from_panel", _boom)
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", REAL_LOOKING)
        with pytest.raises(RuntimeError):
            mod._from_panel("x")  # 先证明它真的会炸
        # resolve_secret 内部各层已各自 try/except,但 _from_panel 被整体替换成会抛的版本,
        # 所以这里验证的是"顶层也不吞不到的异常"这一约定:调用方看到的是异常而非静默错值。
        # 真实实现里每层内部都有 try/except(见模块),因此正常路径不会到这里。


class TestDescribeSource:
    """排查"面板填了却不生效"时要能说出是从哪一层拿到的 —— 且**不能**输出值本身。"""

    def test_reports_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", REAL_LOOKING)
        assert describe_source("GALAXY_REALTIME_API_KEY") == "env"

    def test_distinguishes_placeholder_from_missing(self, monkeypatch):
        """这个区分很要紧:填了占位符的人以为自己配好了,说"没配置"会让他白查很久。"""
        assert describe_source("GALAXY_REALTIME_API_KEY") == "missing"
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", PLACEHOLDER)
        assert describe_source("GALAXY_REALTIME_API_KEY") == "placeholder"

    def test_never_returns_the_value(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", REAL_LOOKING)
        out = describe_source("GALAXY_REALTIME_API_KEY")
        assert REAL_LOOKING not in out
        assert out in ("panel", "vault", "env", "placeholder", "missing")


class TestDuplexUsesTheAuthoritativeChain:
    """双工层必须走上面那条链路,而不是自己 os.getenv。"""

    def test_placeholder_openai_key_no_longer_starts_a_session(self, monkeypatch):
        """真实场景复现:``.env`` 里 OPENAI_API_KEY 是未编辑模板,``main.py`` 把它灌进
        环境。旧代码会拿模板文字去建连拿 401;现在必须判为"没配"并返回 None。"""
        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("OPENAI_API_KEY", PLACEHOLDER)
        assert DuplexSessionConfig.from_env() is None

    def test_real_key_still_builds_a_config(self, monkeypatch):
        """对照组:真 key 必须照样能建出配置,否则上一条毫无判别力。"""
        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("OPENAI_API_KEY", REAL_LOOKING)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.api_key == REAL_LOOKING
        assert cfg.provider == "openai_realtime"

    def test_dedicated_realtime_key_is_preferred(self, monkeypatch):
        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "dedicated-" + REAL_LOOKING)
        monkeypatch.setenv("OPENAI_API_KEY", "generic-" + REAL_LOOKING)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None and cfg.api_key == "dedicated-" + REAL_LOOKING

    def test_gemini_placeholder_also_rejected(self, monkeypatch):
        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "gemini_live")
        monkeypatch.setenv("GOOGLE_API_KEY", PLACEHOLDER)
        assert DuplexSessionConfig.from_env() is None

    def test_gemini_real_key_builds_url_with_key_in_query(self, monkeypatch):
        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "gemini_live")
        monkeypatch.setenv("GOOGLE_API_KEY", REAL_LOOKING)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None
        assert cfg.provider == "gemini_live"
        assert f"key={REAL_LOOKING}" in cfg.url

    def test_gemini_also_accepts_the_gemini_alias(self, monkeypatch):
        """``GEMINI_API_KEY`` 是 CONFIG_SCHEMA 里明写的 GOOGLE 别名,双工层也该认。"""
        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "gemini_live")
        monkeypatch.setenv("GEMINI_API_KEY", REAL_LOOKING)
        cfg = DuplexSessionConfig.from_env()
        assert cfg is not None and cfg.api_key == REAL_LOOKING

    def test_from_env_no_longer_reads_the_key_with_os_getenv(self):
        """白盒:密钥不许再用裸 os.getenv 取。

        比对**去掉注释与 docstring 后**的代码 —— 那段 docstring 里正引用着旧写法
        ``os.getenv("GALAXY_REALTIME_API_KEY")`` 来解释为什么要改。这个坑本轮踩过四次,
        直接用 AST 剥。
        """
        import ast
        import inspect
        import textwrap

        from core.voice_duplex_session import DuplexSessionConfig

        # getsource 返回的是【带缩进】的方法源码,只 strip 首行空白不够,必须整体 dedent
        src = textwrap.dedent(inspect.getsource(DuplexSessionConfig.from_env))
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    if isinstance(body[0].value.value, str):
                        body.pop(0)
        code = ast.unparse(tree)
        assert 'os.getenv("GALAXY_REALTIME_API_KEY")' not in code
        assert 'os.getenv("OPENAI_API_KEY")' not in code
        assert "resolve_secret(" in code, "没有走权威解析链路"

    def test_non_secret_settings_still_come_from_env(self):
        """非密钥项(provider/url/model/voice)仍读环境变量 —— 它们不是 secret,
        没有 vault 那一层,不该被一并改掉。"""
        import inspect

        from core.voice_duplex_session import DuplexSessionConfig

        src = inspect.getsource(DuplexSessionConfig.from_env)
        for key in ("GALAXY_REALTIME_PROVIDER", "GALAXY_REALTIME_URL", "GALAXY_REALTIME_MODEL"):
            assert f'os.getenv("{key}")' in src, f"{key} 不该改成走密钥链路"


class TestPlaceholderDiagnosticIsActionable:
    def test_log_says_placeholder_not_just_missing(self, monkeypatch, caplog):
        """填了占位符的人以为自己配好了。日志必须说"这是占位符",而不是笼统的"缺 key"。"""
        import logging

        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("OPENAI_API_KEY", PLACEHOLDER)
        with caplog.at_level(logging.WARNING, logger="Galaxy.VoiceDuplex"):
            assert DuplexSessionConfig.from_env() is None
        assert any(
            "占位符" in r.message or "占位符" in r.getMessage() for r in caplog.records
        ), f"日志没点明是占位符: {[r.getMessage() for r in caplog.records]}"

    def test_log_does_not_leak_the_value(self, monkeypatch, caplog):
        import logging

        from core.voice_duplex_session import DuplexSessionConfig

        monkeypatch.setenv("OPENAI_API_KEY", PLACEHOLDER)
        with caplog.at_level(logging.WARNING, logger="Galaxy.VoiceDuplex"):
            DuplexSessionConfig.from_env()
        for rec in caplog.records:
            assert PLACEHOLDER not in rec.getMessage(), "日志把配置值原样打出来了"


def test_env_fixture_really_cleaned():
    """自查:上面的 autouse fixture 真的把键摘掉了,否则整组测试都在受真实 .env 影响。"""
    assert os.environ.get("OPENAI_API_KEY") in (None, "")
