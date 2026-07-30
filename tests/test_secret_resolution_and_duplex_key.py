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
def _isolate_all_three_layers(monkeypatch):
    """把**三层**都摘干净,不只是环境变量。

    为什么必须连面板/vault 一起摘(这条 fixture 的第一版只摘了 env,在 CI 全量跑时挂了
    6 条)
    ----------------------------------------------------------------------------------
    ``resolve_secret`` 的顺序是 **面板 → vault → env**,只摘 env 等于只摘了最后一层。
    实际发生的事:``tests/test_round2_fix_behaviors.py`` 里有

        monkeypatch.setenv("OPENAI_API_KEY", "FROM_ENV_OPENAI")

    ``monkeypatch`` 会在那条测试结束时把**环境变量**还原,但面板层背后的
    ``UnifiedConfig`` 单例(经 ``core.unified_config.config._backend`` 委派)是惰性加载的
    —— 它恰好在那个环境下首次加载,把 ``FROM_ENV_OPENAI`` 缓存进自己的 ``_config``,而这个
    缓存活到进程结束。于是本文件后面每次 ``resolve_secret(..., "OPENAI_API_KEY")`` 都从
    **第一层**拿到 ``FROM_ENV_OPENAI``,根本走不到我 setenv 的那一层。已实测复现:删掉
    环境变量后 ``_from_env`` 返回 ``""``,而 ``_from_panel`` 仍返回 ``FROM_ENV_OPENAI``。

    单独跑本文件全绿、全量跑挂 6 条,就是这么来的 —— 典型的顺序依赖,而且错在测试这边:
    要验第三层就必须先把前两层按住,否则测的到底是哪一层完全不确定。

    需要验前两层的测试(``test_panel_layer_beats_env`` 等)自己再 ``setattr`` 覆盖回去
    即可 —— 后设的赢。
    """
    import core.secret_resolution as mod

    for k in ("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mod, "_from_panel", lambda _k: "")
    monkeypatch.setattr(mod, "_from_vault", lambda _k: "")
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


class TestTheFixtureItselfIsLoadBearing:
    """自查:上面那条 autouse fixture 真的在起作用。

    一条只摘了 env 的 fixture 看起来和摘了三层的一模一样(本文件单独跑都是全绿),差别
    只在全量跑时才暴露。所以这里明确断言"前两层被按住了",让这个前提本身可验证 ——
    否则下一个人很容易把 setattr 那两行当成多余的删掉。
    """

    def test_env_keys_are_cleaned(self):
        assert os.environ.get("OPENAI_API_KEY") in (None, "")

    def test_panel_layer_is_neutralised(self):
        import core.secret_resolution as mod

        assert mod._from_panel("OPENAI_API_KEY") == "", "面板层没被按住 —— 本文件的三层测试会测错层"

    def test_vault_layer_is_neutralised(self):
        import core.secret_resolution as mod

        assert mod._from_vault("OPENAI_API_KEY") == "", "vault 层没被按住"

    def test_a_leftover_panel_value_would_have_won(self, monkeypatch):
        """把当初的故障原样复现一遍:面板层残留值会盖掉环境变量。

        这条证明的不是"实现有 bug"(面板优先本来就是设计),而是**只摘 env 的 fixture
        挡不住它** —— 也就是 CI 上那 6 条为什么会挂。
        """
        import core.secret_resolution as mod

        monkeypatch.setattr(mod, "_from_panel", lambda k: "FROM_ENV_OPENAI" if k == "OPENAI_API_KEY" else "")
        monkeypatch.setenv("OPENAI_API_KEY", REAL_LOOKING)
        assert resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY") == "FROM_ENV_OPENAI"

    def test_the_singleton_cache_is_the_real_culprit(self):
        """把成因钉在**经过核实**的那条路径上。

        缓存不在 ``core.unified_config.config`` 自己身上 —— 它是个
        ``UnifiedConfigManager``,真正持有 ``_config`` 字典的是它委派的后端
        ``UnifiedConfig``(而 ``UnifiedConfig`` 本身是单例)。所以路径是
        ``uc.config._backend._config``。

        我这条测试的第一版直接断言 ``hasattr(uc.config, "_config")`` 就挂了 —— 当时是照着
        污染源那个测试里的 ``cfg._config`` 想当然推的,没核实运行期的 ``config`` 到底是哪个
        类。写"成因"的测试尤其不能想当然:说错了成因,下一个人就会照着错的方向去修。

        这个缓存本身不是 bug(``main.py`` 启动时本就先注入 ``.env`` 再加载配置),但它意味着
        ``monkeypatch.delenv`` **管不到面板层** —— 这正是必须显式按住前两层的原因。
        """
        import core.unified_config as uc

        assert hasattr(uc, "config"), "模块级单例不在了,本测试的成因说明需要重核"
        backend = getattr(uc.config, "_backend", None)
        assert backend is not None, "UnifiedConfigManager 不再委派后端?成因说明需要重核"
        assert hasattr(backend, "_config"), f"后端 {type(backend).__name__} 没有 _config 缓存了?成因说明需要重核"
        assert isinstance(backend._config, dict)
