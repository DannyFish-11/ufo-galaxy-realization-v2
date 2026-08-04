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


# ── reload() 必须是 reload,不是 merge ────────────────────────────────────────
#
# 上面两条守的是"少 load 了一步"。这一组守的是相反的一半:**多留了一步没清**。
#
# `UnifiedConfigManager.reload()` 原先手工调那三个 loader,而 loader 都是"往 dict
# 里写",从不清空 —— 于是它实际是 merge:值**改了**能反映出来(后写覆盖前值),值
# **没了**却永远不消失。面板上删掉一个配置项、或把它从 .env 里去掉,进程内那份仍旧
# 照着旧值工作,直到重启。只影响删除、不影响修改,所以它安静且能活很久。
#
# `UnifiedConfig.reload()` 自己是对的(先 `_config.clear()` 再按同样顺序 load)。
# 管理器那三步是把它抄了一遍却漏了第一步 —— 第二份实现漂移的典型形状。修法是
# **委托给后端自己的 reload()**,不再维护第二份顺序。


def test_reload_drops_keys_that_no_longer_exist():
    """删掉的键必须真的消失 —— 这条直接钉住"reload 不是 merge"。"""
    from core.unified.config_manager import UnifiedConfigManager

    class _Backend:
        def __init__(self):
            self._config = {}
            self.disk = {"kept": "v"}

        def reload(self):
            self._config.clear()
            self._config.update(self.disk)

    backend = _Backend()
    mgr = object.__new__(UnifiedConfigManager)
    mgr._backend = backend

    mgr.reload()
    assert backend._config == {"kept": "v"}

    # 模拟"面板上删掉了一项 / .env 里去掉了一行":磁盘上没有了,内存里还留着。
    backend._config["removed_from_disk"] = "stale"
    mgr.reload()
    assert "removed_from_disk" not in backend._config, (
        "reload() 之后被删掉的键还在 —— 它是 merge 不是 reload," "面板删掉的配置项会继续以旧值生效直到进程重启"
    )


def test_reload_delegates_to_the_backend_instead_of_reimplementing_the_order():
    """判别用例:后端有 reload() 时**必须用它**,不能再自己走那三步。

    只断言"删掉的键消失了"是不够的 —— 在管理器里补一行 `_config.clear()` 也能让
    上面那条通过,而那仍然是第二份要手工同步的加载顺序(这次漂移的正是它)。
    这条钉住的是"顺序只有一份"。
    """
    from core.unified.config_manager import UnifiedConfigManager

    calls: list[str] = []

    class _Backend:
        def reload(self):
            calls.append("reload")

        def _load_config(self):
            calls.append("_load_config")

        def _load_from_config_store(self):
            calls.append("_load_from_config_store")

        def _load_env(self):
            calls.append("_load_env")

    mgr = object.__new__(UnifiedConfigManager)
    mgr._backend = _Backend()
    mgr.reload()

    assert calls == ["reload"], f"没有委托给后端的 reload(),而是又抄了一遍加载顺序: {calls}"


def test_the_real_process_singleton_actually_drops_stale_keys():
    """端到端:拿**进程里真正那个单例**验一遍,不是拿 fake backend。

    上面两条都用替身后端。替身证明了管理器的逻辑对,但证明不了生产上那个
    `core.unified_config.config`(它是 UnifiedConfigManager 包着 UnifiedConfig)
    真的具备这个行为 —— 而污染就是在那个真实单例上发生的。
    """
    from core.unified_config import config as real_singleton

    backend = real_singleton._backend
    assert hasattr(backend, "_config"), "真实后端没有 _config 快照?本条的前提已不成立"

    backend._config["GALAXY_PROBE_STALE_KEY"] = "leftover"
    real_singleton.reload()
    assert backend._config.get("GALAXY_PROBE_STALE_KEY") is None, "真实单例上 reload() 仍然是 merge"
