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


def _api_key_line(out: str) -> str:
    """从横幅输出里取出 API Key 那一行。

    比整串文案匹配更耐改:版面几何(列宽/缩进)属于 core.ascii_art 的职责,
    在那边调整不该让这个**行为**测试变红;而这一项的结论变了必须变红。
    """
    for line in out.splitlines():
        if "API Key" in line:
            return line
    raise AssertionError(f"横幅里没有 API Key 这一项:\n{out}")


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
        monkeypatch,
        tmp_path,
        env_text="OPENAI_API_KEY=your_openai_api_key_here\n",
        secrets={"DEEPSEEK_API_KEY": "sk-real-deepseek-key"},
    )
    out = capsys.readouterr().out
    assert status["api_keys_configured"] == 1, f"只计了 .env 文本,漏了 runtime/secrets.env 里真实保存的密钥: {status}"
    # 横幅上要看得见这个数。断言取整行再看内容,不写死整串文案——
    # 计数从**标签**里挪到了**值列**("API Key 已配置 (1个)" → "API Key    1 个"),
    # 那正是统一版面要的:标签列放名字、值列放值,否则值的宽度会把对勾挤歪。
    line = _api_key_line(out)
    assert "1" in line, f"横幅没显示已配置的密钥数: {line!r}"
    assert "✓" in line, f"有真实密钥时这一项该是正常态: {line!r}"


def test_placeholder_only_reports_zero_configured(monkeypatch, tmp_path, capsys):
    status = _run(
        monkeypatch,
        tmp_path,
        env_text="OPENAI_API_KEY=your_openai_api_key_here\nGALAXY_API_TOKEN=your_galaxy_api_token_here\n",
        secrets={},
    )
    out = capsys.readouterr().out
    assert status["api_keys_configured"] == 0, "未编辑的占位符不该被计为已配置"
    line = _api_key_line(out)
    assert "未配置" in line, f"横幅该明说未配置: {line!r}"
    assert "⚠" in line, f"未配置属降级态,不该显示为正常: {line!r}"


def test_dedupes_key_present_in_both_env_and_secrets(monkeypatch, tmp_path, capsys):
    status = _run(
        monkeypatch,
        tmp_path,
        env_text="ANTHROPIC_API_KEY=sk-real-anthropic-key\n",
        secrets={"ANTHROPIC_API_KEY": "sk-real-anthropic-key"},
    )
    assert status["api_keys_configured"] == 1, "同一个 key 出现在两处不应被重复计数"
