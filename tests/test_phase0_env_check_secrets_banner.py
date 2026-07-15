"""tests/test_phase0_env_check_secrets_banner.py
==================================================
真机排查发现:启动横幅"API Key 已配置/未配置"(main.py::phase0_env_check())此前
纯读 .env 文本计数——但密钥经面板保存后会被收敛进 runtime/secrets.env(不再明文
留在 .env,见 core/config_store.py),于是这条横幅在密钥已正确保存的情况下依然
永远报"未配置",强化用户"存了但没用"的错觉,与真机反馈"这个面板上的 API 它就出
问题了为什么还是不能正常地保存和使用"完全吻合。

本测试锁定:phase0_env_check() 必须把 runtime/secrets.env 里的真实密钥也计入,
且不能把 .env 里未编辑的占位符(your_..._here)误计为已配置。
"""

from __future__ import annotations


def _run(monkeypatch, tmp_path, env_text: str, secrets: dict):
    import core.config_store as config_store_module
    import main as main_mod

    env_file = tmp_path / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    monkeypatch.setattr(main_mod, "ENV_FILE", env_file)

    store = config_store_module.ConfigStore(
        config_path=tmp_path / "config.json",
        secrets_path=tmp_path / "secrets.env",
    )
    for k, v in secrets.items():
        store.write_secret(k, v)
    monkeypatch.setattr(config_store_module, "_singleton", store)

    return main_mod.phase0_env_check()


def test_secret_saved_only_in_secrets_env_is_counted(monkeypatch, tmp_path, capsys):
    # .env 里该 key 是未编辑的占位符(面板保存后会把它从 .env 里剔除,但这里
    # 模拟"用户还没存过这个 key、.env 仍是自动生成的模板"这一常见起始状态)。
    status = _run(
        monkeypatch, tmp_path,
        env_text="OPENAI_API_KEY=your_openai_api_key_here\n",
        secrets={"DEEPSEEK_API_KEY": "sk-real-deepseek-key"},
    )
    out = capsys.readouterr().out
    assert status["api_keys_configured"] == 1, (
        f"只计了 .env 文本,漏了 runtime/secrets.env 里真实保存的密钥: {status}"
    )
    assert "API Key 已配置 (1个)" in out


def test_placeholder_only_reports_zero_configured(monkeypatch, tmp_path, capsys):
    status = _run(
        monkeypatch, tmp_path,
        env_text="OPENAI_API_KEY=your_openai_api_key_here\nGALAXY_API_TOKEN=your_galaxy_api_token_here\n",
        secrets={},
    )
    out = capsys.readouterr().out
    assert status["api_keys_configured"] == 0, "未编辑的占位符不该被计为已配置"
    assert "API Key 未配置" in out


def test_dedupes_key_present_in_both_env_and_secrets(monkeypatch, tmp_path, capsys):
    status = _run(
        monkeypatch, tmp_path,
        env_text="ANTHROPIC_API_KEY=sk-real-anthropic-key\n",
        secrets={"ANTHROPIC_API_KEY": "sk-real-anthropic-key"},
    )
    assert status["api_keys_configured"] == 1, "同一个 key 出现在两处不应被重复计数"
