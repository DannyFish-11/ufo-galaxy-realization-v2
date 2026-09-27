"""启动屏上每一行都得是真的 —— 逐条对着真机(Windows,首次克隆)日志里说错的那几行。

每个测试的 docstring 里贴着真机上那一行原话。
"""

from __future__ import annotations

import io
import os

import pytest


def _report(**kw):
    from launcher.env_check import EnvReport

    base = dict(python_version="3.12.6", python_ok=True, python_executable="python", pip_ok=True)
    base.update(kw)
    return EnvReport(**base)


# ── Ollama:超时 ≠ 没装;安装命令按系统给 ────────────────────────────────────


class TestOllama:
    def test_windows_is_not_given_a_bash_pipe(self):
        """真机 Windows:``⚠ Ollama 未安装  curl -fsSL https://ollama.com/install.sh | sh``。"""
        from launcher.env_check import ollama_install_hint

        win = ollama_install_hint("Windows")
        assert "| sh" not in win and "curl" not in win
        assert "winget install Ollama.Ollama" in win
        assert "brew install ollama" in ollama_install_hint("Darwin")
        assert "install.sh | sh" in ollama_install_hint("Linux")

    def test_timeout_is_carried_to_the_deps_phase(self):
        rep = _report(probes_timed_out=["ollama"])
        assert rep.to_status_dict()["ollama_probe_timed_out"] is True
        assert _report().to_status_dict()["ollama_probe_timed_out"] is False

    def _printed(self, monkeypatch):
        import main

        lines = []
        monkeypatch.setattr(main, "print_item", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))
        return main, lines

    def test_timed_out_then_found_is_not_called_uninstalled(self, monkeypatch):
        """真机:``⏱ Ollama 12s 没有回应`` → 后面 ``⚠ Ollama 未安装``,而它明明在跑。"""
        main, lines = self._printed(monkeypatch)
        st = {"ollama_installed": False, "ollama_probe_timed_out": True}
        ok = main._settle_ollama_presence(st, reprobe=lambda: (True, True, ["gemma4:e2b"], True))
        assert ok is True
        assert st["ollama_installed"] is True and st["ollama_probe_timed_out"] is False
        assert not any("未安装" in ln for ln in lines), lines

    def test_still_timing_out_says_so_instead_of_guessing(self, monkeypatch):
        main, lines = self._printed(monkeypatch)
        st = {"ollama_installed": False, "ollama_probe_timed_out": True}
        ok = main._settle_ollama_presence(
            st, reprobe=lambda: (False, False, [], False), install_hint=lambda: "winget install Ollama.Ollama"
        )
        assert ok is False
        assert any("还是没查完" in ln and "不等于没装" in ln for ln in lines), lines
        assert not any(ln.startswith("Ollama 未安装") for ln in lines)

    def test_really_missing_gets_this_machines_install_command(self, monkeypatch):
        main, lines = self._printed(monkeypatch)
        called = []
        st = {"ollama_installed": False, "ollama_probe_timed_out": False}
        ok = main._settle_ollama_presence(
            st, reprobe=lambda: called.append(1), install_hint=lambda: "winget install Ollama.Ollama"
        )
        assert ok is False and not called, "查完了的'没装'不需要再查一次"
        assert lines == ["Ollama 未安装 warn winget install Ollama.Ollama"]


# ── Phase 0 的进度行不替结论表态 ───────────────────────────────────────────


def test_probe_progress_row_is_neutral_not_a_green_tick():
    """真机:同一屏先 ``✓ Electron 依赖``,几行后 ``⚠ Electron 依赖  还没装``。"""
    from launcher.live_list import STATE_DONE, LiveList

    buf = io.StringIO()
    ll = LiveList([("electron", "Electron 依赖")], stream=buf)
    ll.update("electron", STATE_DONE, "查完")
    line = ll._line("electron", final=True)
    assert "✓" not in line and "+" not in line.split("Electron")[0]
    assert "查完" in line

    import inspect

    import main

    src = inspect.getsource(main.phase0_env_check)
    assert "STATE_DONE" in src and "STATE_OK" not in src


# ── "API Key N 个" 只数大模型密钥 ──────────────────────────────────────────


class TestApiKeyCount:
    @pytest.fixture
    def no_store(self, monkeypatch):
        import sys

        mod = type(sys)("core.config_store")
        mod.get_config_store = lambda: type("S", (), {"read_secrets": lambda s: {}})()
        monkeypatch.setitem(sys.modules, "core.config_store", mod)

    def test_the_template_env_has_zero_model_keys(self, no_store, tmp_path):
        """真机第二次启动(.env 刚从模板复制):``✓ API Key  2 个`` —— 数的是
        ``MINIO_ACCESS_KEY=minioadmin`` 和 ``GALAXY_STOP_KEY=true``。"""
        from launcher import env_check

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = tmp_path / ".env"
        env.write_text(open(os.path.join(root, ".env.example"), encoding="utf-8").read(), encoding="utf-8")
        assert env_check._probe_api_keys(env) == 0

    def test_non_model_keys_do_not_count(self, no_store, tmp_path):
        from launcher import env_check

        env = tmp_path / ".env"
        env.write_text(
            "MINIO_ACCESS_KEY=minioadmin\nGALAXY_STOP_KEY=true\nBRAVE_API_KEY=real\n"
            "DEEPSEEK_API_KEY=sk-real\nGEMINI_API_KEY=real-gemini\n",
            encoding="utf-8",
        )
        assert env_check._probe_api_keys(env) == 2

    def test_no_cloud_key_but_local_model_is_not_degraded(self):
        rep = _report(api_keys_configured=0, ollama_models=["gemma4:e2b"])
        row = [s for s in rep.to_steps() if s.name == "API Key"][0]
        assert row.status.value == "ok"
        assert "本机模型" in row.value


# ── 配置检查块:数得对、说得对 ──────────────────────────────────────────────


_PREFLIGHT_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GALAXY_API_TOKEN",
    "GALAXY_API_TOKENS",
    "GALAXY_AUTH_ENABLED",
    "GALAXY_REQUIRE_API_TOKEN",
    "GALAXY_MODE",
    "GALAXY_SYSTEM_MODE",
    "GALAXY_GATEWAY_MODE",
    "GALAXY_TLS_CERT",
    "GALAXY_ANDROID_WS_ENABLED",
    "GALAXY_SIGNALING_TIMEOUT_S",
    "GALAXY_TURN_URLS",
    "GALAXY_SECRET_BACKEND",
    "LLM_API_KEY",
)


@pytest.fixture
def clean_preflight_env(monkeypatch):
    from core import config_preflight as cp

    for v in _PREFLIGHT_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(cp, "_load_runtime_secrets_into_env", lambda: [])
    monkeypatch.setattr(cp, "_other_llm_key_configured", cp._other_llm_key_configured)
    return cp


class TestPreflight:
    def test_the_counts_add_up(self, clean_preflight_env):
        """真机首启:``通过 0  提醒 3  阻断 0   共 4 项判据``。"""
        cp = clean_preflight_env
        rep = cp.run_preflight(dry_run=True, fail_fast=False, verbose=False)
        n = len(rep.passed) + len(rep.warnings) + len(rep.criticals) + len(rep.defaulted)
        assert n == len(rep.findings)
        text = rep.format()
        if rep.defaulted:
            assert f"用默认 {len(rep.defaulted)}" in text

    def test_missing_token_with_auth_on_by_default_is_not_a_warning(self, clean_preflight_env):
        """真机首启:缺口令被列成提醒,还说"再加 GALAXY_AUTH_ENABLED=true 才真正生效" ——
        而鉴权默认就开着,缺口令时会自签本机令牌。"""
        cp = clean_preflight_env
        rep = cp.run_preflight(dry_run=True, fail_fast=False, verbose=False)
        tok = [f for f in rep.findings if f.check.var == "GALAXY_API_TOKEN"][0]
        assert tok.check.severity == cp.Severity.INFO
        assert "本机令牌" in tok.check.description
        assert tok not in rep.warnings
        assert "GALAXY_AUTH_ENABLED=true 才真正生效" not in rep.format()

    def test_auth_turned_off_is_called_out_not_passed(self, clean_preflight_env, monkeypatch):
        """``.env`` 里 ``GALAXY_AUTH_ENABLED=false``:以前这一行算"通过"。"""
        cp = clean_preflight_env
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
        rep = cp.run_preflight(dry_run=True, fail_fast=False, verbose=False)
        auth = [f for f in rep.findings if f.check.var == "GALAXY_AUTH_ENABLED"][0]
        assert auth in rep.warnings
        tok = [f for f in rep.findings if f.check.var == "GALAXY_API_TOKEN"][0]
        assert tok in rep.warnings and "任何人" in tok.check.description

    def test_no_llm_key_is_not_said_to_stop_the_agent(self, clean_preflight_env):
        """真机:本机 gemma4 大脑好好的,配置检查说"至少要有一家大模型的密钥,智能体才跑得起来"。"""
        cp = clean_preflight_env
        text = cp.run_preflight(dry_run=True, fail_fast=False, verbose=True).format()
        assert "智能体才跑得起来" not in text.replace("都能让智能体跑起来", "")
        assert "Ollama" in text

    def test_another_providers_key_quiets_openai_and_anthropic(self, clean_preflight_env, monkeypatch):
        cp = clean_preflight_env
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-genuine")
        rep = cp.run_preflight(dry_run=True, fail_fast=False, verbose=False)
        warned = {f.check.var for f in rep.warnings}
        assert "OPENAI_API_KEY" not in warned and "ANTHROPIC_API_KEY" not in warned


# ── 系统模式那一行说的总线,和真正拉总线的那一处同一判据 ─────────────────────


class TestBusLine:
    def _said(self, monkeypatch, value):
        from core.system_orchestrator import SystemOrchestrator

        if value is None:
            monkeypatch.delenv("GALAXY_NATS_ENABLED", raising=False)
        else:
            monkeypatch.setenv("GALAXY_NATS_ENABLED", value)
        monkeypatch.delenv("GALAXY_NATS_URL", raising=False)
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        orch = SystemOrchestrator.__new__(SystemOrchestrator)
        return orch._run_phase_2_resolve_mode().said

    def test_unset_means_the_bus_will_be_started(self, monkeypatch):
        """真机首启:``只用本机,不用消息总线`` → 后面 ``✓ 消息总线 nats://localhost:4222``。"""
        said = self._said(monkeypatch, None)
        assert "不用消息总线" not in said and "拉起" in said

    def test_explicit_false_means_no_bus(self, monkeypatch):
        assert "不用消息总线" in self._said(monkeypatch, "false")


# ── .env 在加载配置之前就生成 ────────────────────────────────────────────────


def test_env_file_exists_before_config_is_loaded(tmp_path, monkeypatch):
    import main

    (tmp_path / ".env.example").write_text("GALAXY__PROBE_FROM_TEMPLATE=yes\n", encoding="utf-8")
    monkeypatch.delenv("GALAXY__PROBE_FROM_TEMPLATE", raising=False)

    assert main.bootstrap_env_file(str(tmp_path)) is True
    assert (tmp_path / ".env").exists()
    assert main.bootstrap_env_file(str(tmp_path)) is False, "已有 .env 不许覆盖"

    main.load_env_files_into_environ(str(tmp_path))
    assert os.environ.get("GALAXY__PROBE_FROM_TEMPLATE") == "yes"
    monkeypatch.delenv("GALAXY__PROBE_FROM_TEMPLATE", raising=False)

    import inspect

    src = inspect.getsource(main)
    guard = src[src.index('if __name__ == "__main__":') :]
    assert guard.index("bootstrap_env_file()") < guard.index("load_env_files_into_environ()")


def test_phase_1_does_not_claim_everything_is_ready():
    """真机:``[Phase 1]`` 里 ``✓ 就绪汇总  一切就绪 —— 6/6 个阶段正常``,后面服务才开始起。"""
    import inspect

    from core import system_orchestrator as so

    src = inspect.getsource(so)
    assert 'OrchestratorReadiness.READY: "一切就绪"' not in src
    assert 'OrchestratorReadiness.READY: "预检全部通过' in src
