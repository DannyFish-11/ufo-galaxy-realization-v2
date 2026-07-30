"""tests/test_unified_config_manager_reload_secrets.py
=========================================================
面板 API-key 排查发现:`UnifiedConfigManager.reload()`(core/unified/config_manager.py)
只调用了 `_load_config()`(config.json)与 `_load_env()`(.env/os.environ),漏了
`_load_from_config_store()`——这一步才是 `runtime/secrets.env`(面板保存密钥的
真正落盘位置,见 core/config_store.py)被读回 `UnifiedConfig._config`(Dashboard 层)
的地方。少了它,一次 reload() 不会让刚保存的密钥反映到 Dashboard 层,此前全靠
`core/routes/config.py::update_config()` 里紧跟着的 `os.environ.update()` 巧合掩盖
——任何只走 Dashboard 层、不兜底 os.environ 的调用方都会读不到刚保存的密钥。
"""

from __future__ import annotations


def test_reload_calls_load_from_config_store():
    """回归锁定:reload() 必须调用 _load_from_config_store(),不能只有 _load_config/_load_env。"""
    from core.unified.config_manager import UnifiedConfigManager

    calls: list[str] = []

    class _FakeBackend:
        def _load_config(self):
            calls.append("_load_config")

        def _load_from_config_store(self):
            calls.append("_load_from_config_store")

        def _load_env(self):
            calls.append("_load_env")

    mgr = object.__new__(UnifiedConfigManager)
    mgr._backend = _FakeBackend()

    mgr.reload()

    assert "_load_from_config_store" in calls, (
        "reload() 漏了 _load_from_config_store() —— runtime/secrets.env 里刚保存的" "密钥不会被读回 Dashboard 层"
    )
    # 顺序必须和 UnifiedConfig.__init__ 一致:config.json(最低)→ runtime store
    # (secrets.env,居中)→ .env/环境变量(最高),否则优先级会被打乱。
    assert calls == ["_load_config", "_load_from_config_store", "_load_env"]


def test_reload_actually_refreshes_secret_from_config_store(tmp_path, monkeypatch):
    """端到端:直接用真实 UnifiedConfig + ConfigStore,验证 reload() 后能读到新写入的密钥。"""
    import core.config_store as config_store_module
    from core.unified.config_manager import UnifiedConfigManager
    from core.unified_config import UnifiedConfig

    monkeypatch.setattr(
        config_store_module,
        "_singleton",
        config_store_module.ConfigStore(
            config_path=tmp_path / "config.json",
            secrets_path=tmp_path / "secrets.env",
        ),
    )
    # 真隔离缺口(全量测试套件里复现过):_load_env()(core/unified_config.py:190-193)
    # 会无条件把 os.environ 里任何 OPENAI/ANTHROPIC/.../DEEPSEEK/... 前缀的变量合并
    # 进 self._config——这是真实生产行为(core/routes/config.py::update_config() 存
    # 密钥后会 os.environ.update(),让新值立即在当前进程生效),不是要修的 bug。但
    # 同一 pytest 进程里跑在本测试之前的任何测试(比如真的打过一次 POST /api/config
    # 保存 DEEPSEEK_API_KEY 的测试)会把这个环境变量真的留在 os.environ 里(不是走
    # monkeypatch.setenv,不会被自动清理),本测试如果不显式清掉,会被那个残留值
    # 覆盖掉刚从隔离 ConfigStore 里读到的 "sk-real-saved-key"。
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    backend = object.__new__(UnifiedConfig)
    backend._config = {}
    backend.project_root = tmp_path
    backend.config_file = tmp_path / "config.json.static"
    backend.env_file = tmp_path / ".env.nonexistent"
    backend._callbacks = {}
    backend._initialized = True

    mgr = object.__new__(UnifiedConfigManager)
    mgr._backend = backend

    assert mgr.get("deepseek_api_key", "") == ""

    config_store_module.get_config_store().write_secret("DEEPSEEK_API_KEY", "sk-real-saved-key")
    mgr.reload()

    assert (
        mgr.get("deepseek_api_key", "") == "sk-real-saved-key"
    ), "reload() 之后 Dashboard 层应能读到刚保存进 runtime/secrets.env 的密钥"
