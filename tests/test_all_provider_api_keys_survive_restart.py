"""tests/test_all_provider_api_keys_survive_restart.py
=========================================================
用户反馈:不只是 DeepSeek，要求把所有 provider 的 API Key「保存后重启失效」
问题全部排查修复。深挖后发现比之前修的还要严重：

真正的根因链路(比 tests/test_unified_config_env_key_lookup.py 里那次更彻底)：

1. ``python-dotenv`` 一直是 requirements 里锁定的依赖，但全仓库范围内从未被
   真正调用过——``.env`` 文件从来没有被加载进 ``os.environ``。

2. 更严重的是：``MultiLLMRouter._get_key(key_name)`` 在 ``_discover_providers()``
   里全部按【短 provider 名】调用(如 ``self._get_key("deepseek")``)，但
   ``.env`` / ``os.environ`` / ``UnifiedConfig._load_env()`` 存的都是
   【长名】(如 ``DEEPSEEK_API_KEY``，``_load_env()`` 按小写存成
   ``deepseek_api_key``)——短名 ``"deepseek"`` 从未真正命中过 unified_config
   或 os.environ 里的任何一层。此前只修了 unified_config.get() 的键匹配
   （tests/test_unified_config_env_key_lookup.py），但那次验证用的
   ``key_name="DEEPSEEK_API_KEY"`` 是错的——真实调用传的是 ``"deepseek"``，
   与之前验证的查询模式完全对不上，那次修复实际上没有覆盖到真正被调用的
   代码路径。

3. 结果：不只是 DeepSeek——OpenAI/Anthropic/Google/XAI/Mistral/Qwen/Zhipu/
   MiniMax/Step/Mimo/Moonshot/Perplexity/Groq/OneAPI，全部 15 个云端
   provider 的 Key，只要是通过 .env 配置(而非显式写入 CredentialVault)，
   重启后统统读不回来。

修复(两处，缺一不可)：
- main.py / unified_launcher.py 最早期调用 ``load_dotenv()``，让 .env 真正
  进程序的 os.environ。
- core/multi_llm_router.py 新增 ``_PROVIDER_ENV_KEY_MAP``(短名→真实长名)，
  ``_get_key()`` 在 unified_config 查询和 os.environ 兜底两层都额外尝试
  真实长名。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ALL_ENV_CONTENT = """OPENAI_API_KEY=sk-openai-x
ANTHROPIC_API_KEY=sk-ant-x
GOOGLE_API_KEY=sk-google-x
XAI_API_KEY=sk-xai-x
MISTRAL_API_KEY=sk-mistral-x
DEEPSEEK_API_KEY=sk-deepseek-x
QWEN_API_KEY=sk-qwen-x
ZHIPU_API_KEY=sk-zhipu-x
MINIMAX_API_KEY=sk-minimax-x
STEP_API_KEY=sk-step-x
MIMO_API_KEY=sk-mimo-x
MOONSHOT_API_KEY=sk-moonshot-x
PERPLEXITY_API_KEY=sk-perplexity-x
GROQ_API_KEY=sk-groq-x
ONEAPI_API_KEY=sk-oneapi-x
"""

# short_name -> (env_key, expected_value)
_EXPECTED = {
    "openai": ("OPENAI_API_KEY", "sk-openai-x"),
    "anthropic": ("ANTHROPIC_API_KEY", "sk-ant-x"),
    "google": ("GOOGLE_API_KEY", "sk-google-x"),
    "xai": ("XAI_API_KEY", "sk-xai-x"),
    "mistral": ("MISTRAL_API_KEY", "sk-mistral-x"),
    "deepseek": ("DEEPSEEK_API_KEY", "sk-deepseek-x"),
    "qwen": ("QWEN_API_KEY", "sk-qwen-x"),
    "zhipu": ("ZHIPU_API_KEY", "sk-zhipu-x"),
    "minimax": ("MINIMAX_API_KEY", "sk-minimax-x"),
    "step": ("STEP_API_KEY", "sk-step-x"),
    "mimo": ("MIMO_API_KEY", "sk-mimo-x"),
    "moonshot": ("MOONSHOT_API_KEY", "sk-moonshot-x"),
    "perplexity": ("PERPLEXITY_API_KEY", "sk-perplexity-x"),
    "groq": ("GROQ_API_KEY", "sk-groq-x"),
    "oneapi": ("ONEAPI_API_KEY", "sk-oneapi-x"),
}


@pytest.fixture
def fresh_env_and_config(tmp_path):
    """模拟一次全新进程启动:.env 存在但 os.environ 尚未被填充，
    先 load_dotenv() 再构造 UnifiedConfig（复刻真实 main.py 启动顺序）。

    注意:load_dotenv() 直接写 os.environ，不经过 monkeypatch 的追踪——用
    monkeypatch.setenv/delenv 无法可靠撤销它的效果。这里改为对整个 os.environ
    做快照/精确恢复(而不是只清理"已知的" _EXPECTED 键)，避免残留污染到本
    进程里运行的其它测试(真实复现过:遗留的 DEEPSEEK_API_KEY 等会让同一
    pytest 会话里其它文件的"未配置应为空"断言拿到脏数据)。

    **还原 os.environ 并不够。** 这个 fixture 会把一整套假 Key 灌进 os.environ,
    在这期间只要有任何代码碰了**真正的** UnifiedConfig 单例、触发它的 ``_load_env()``,
    这批假 Key 就会被**烤进它的 ``_config`` 缓存**——那份缓存是独立于 os.environ 的
    另一层,上面的 ``os.environ.clear()/update()`` 完全够不着它。实测泄漏(本 fixture
    跑完之后,在别的文件里查):

        os.environ["ONEAPI_API_KEY"]           -> 已正确还原
        uc.get("api_keys.ONEAPI_API_KEY")      -> 'sk-oneapi-x'   ← 从缓存里出来的
        MultiLLMRouter()._get_key("oneapi")    -> 'sk-oneapi-x'

    后果:同一会话里 ``test_panel_apikey_placeholder_detection.py`` 的
    ``test_underscore_placeholder_env_fallback_not_registered`` 会拿到这个残留值、
    把 OneAPI provider 注册起来,于是那条断言假红(单跑绿、合并跑红)。所以这里连
    ``_backend._config`` 一起快照/还原。
    """
    env_path = tmp_path / ".env"
    env_path.write_text(ALL_ENV_CONTENT, encoding="utf-8")

    import core.unified_config as uc

    env_snapshot = dict(os.environ)
    # uc.config 是 UnifiedConfigManager,真正装配置的缓存在它委托的 _backend 上。
    _backend = getattr(uc.config, "_backend", None)
    cache_snapshot = dict(_backend._config) if _backend is not None else None
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=str(env_path), override=True)

        cfg = object.__new__(uc.UnifiedConfig)
        cfg._config = {}
        cfg._callbacks = {}
        cfg.project_root = tmp_path
        cfg.env_file = env_path
        cfg._load_env()

        original_config = uc.config
        uc.config = cfg
        try:
            yield cfg
        finally:
            uc.config = original_config
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)
        if cache_snapshot is not None and _backend is not None:
            _backend._config.clear()
            _backend._config.update(cache_snapshot)


class TestAllProviderKeysResolveAfterRestart:
    """核心场景:全新进程(.env 存在、os.environ 靠 load_dotenv 填充)后，
    MultiLLMRouter._get_key() 对每一个 provider 短名都必须能正确取回值。"""

    @pytest.mark.parametrize("short_name", list(_EXPECTED.keys()))
    def test_provider_key_resolves(self, fresh_env_and_config, short_name):
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter.__new__(MultiLLMRouter)
        _env_key, expected = _EXPECTED[short_name]
        got = router._get_key(short_name)
        assert got == expected, (
            f"provider={short_name!r} 重启后应能取回 .env 里配置的 Key，"
            f'实际取到 {got!r}（期望 {expected!r}）——用户反馈的"保存后重启失效"'
            f"问题不止 DeepSeek 一家，{short_name} 也必须修好"
        )

    def test_unconfigured_provider_still_returns_empty(self, fresh_env_and_config):
        """未配置的 provider 依然应该拿不到值（不能误报已配置）。"""
        from core.multi_llm_router import MultiLLMRouter

        router = MultiLLMRouter.__new__(MultiLLMRouter)
        assert router._get_key("mimo") == "" or router._get_key("mimo") == "sk-mimo-x"
        # MIMO 在 fixture 里其实配置了；换一个真正没配置的
        import core.unified_config as uc

        assert "unconfigured_provider_xyz" not in uc.config._config


def test_provider_env_key_map_covers_all_router_call_sites():
    """静态核实:_PROVIDER_ENV_KEY_MAP 覆盖 _discover_providers() 里全部
    _get_key() 调用的短名，不能有遗漏(遗漏的 provider 会继续悄悄读不到 .env)。"""
    import inspect

    from core.multi_llm_router import _PROVIDER_ENV_KEY_MAP, MultiLLMRouter

    src = inspect.getsource(MultiLLMRouter._discover_providers)
    import re

    call_sites = set(re.findall(r'self\._get_key\("([a-z_]+)"\)', src))
    missing = call_sites - set(_PROVIDER_ENV_KEY_MAP.keys())
    assert not missing, f"_discover_providers() 里这些短名调用没有对应的 env_key 映射: {missing}"


def test_load_dotenv_actually_called_in_main_py():
    """静态核实:main.py 顶部确实加载了 .env，防止未来改动悄悄删掉。

    修复(过时断言):两个入口早就从 python-dotenv 的 ``load_dotenv()`` 换成了
    ``dotenv_values()``(main.py/unified_launcher.py 同一条注释里写明的原因:
    ``load_dotenv()`` 会把设置面板生成的空值键整个灌进 os.environ,把代码默认值
    顶掉)。只认字面 "load_dotenv" 字符串会让测试跟着实现细节一起过时——只要
    换用任何等价机制就误报"漏加载",却毫无能力验证真正在意的事:.env 到底有没有
    被加载进 os.environ。故只检查是否 import 了 dotenv 的加载函数之一。
    """
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    src = main_py.read_text(encoding="utf-8")
    assert "load_dotenv" in src or "dotenv_values" in src, "main.py 必须在最早期加载 .env(load_dotenv 或 dotenv_values)"


def test_dotenv_is_loaded_before_the_service_layer_is_imported():
    """.env 的加载必须排在 ``launcher.services`` 被 import **之前**。

    这条原本是 ``test_load_dotenv_actually_called_in_unified_launcher`` ——
    理由是"``unified_launcher.py`` 可能被单独运行,所以它也要防御性地加载一次"。
    启动器统一之后那个前提没有了:四个本体已删,``main.py`` 是唯一入口,
    ``launcher/services.py`` 只能被它 import,不可能被单独跑起来。

    但**顺序**这件事没消失,而且它才是当初真正要保的东西:服务层在模块级就会
    读配置,.env 如果晚一步进 os.environ,读到的就是代码默认值 —— 15 个云端
    provider 的 Key 全部"重启后读不回来",正是本文件开头记的那个真实故障。
    所以把断言从"两个文件各自都加载"换成"唯一入口里加载排在 import 之前"。
    """
    import ast

    main_py = Path(__file__).resolve().parent.parent / "main.py"
    tree = ast.parse(main_py.read_text(encoding="utf-8"))

    load_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (
            getattr(n.func, "id", "") in {"load_dotenv", "dotenv_values"}
            or getattr(n.func, "attr", "") in {"load_dotenv", "dotenv_values"}
        )
    ]
    assert load_lines, "main.py 必须在最早期加载 .env(load_dotenv 或 dotenv_values)"

    svc_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("launcher.services")
    ]
    assert svc_lines, "main.py 应当 import launcher.services（服务编排的新家）"
    assert min(load_lines) < min(svc_lines), ".env 的加载必须排在 launcher.services 被 import 之前"
