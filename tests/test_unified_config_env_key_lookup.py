"""tests/test_unified_config_env_key_lookup.py
=================================================
用户实测反馈:「模型」tab 存了 DeepSeek API Key，写进 .env 确认无误，但重启
新进程后，运行时判定它"未配置"——即所谓"保存失败"，其实保存本身是成功的，
真正坏的是【重启后读取】这一环。

根因链路：
  1. UnifiedConfig._load_env() 把 .env 里的 KEY=VALUE 按【扁平小写】存进
     self._config（如 "DEEPSEEK_API_KEY" → self._config["deepseek_api_key"]）。
  2. core.multi_llm_router.MultiLLMRouter._get_key() 实际查询的却是带命名空间
     前缀的路径："llm.providers.{key_name}.api_key" 和 "api_keys.{key_name}"。
  3. UnifiedConfig.get() 之前的"尝试多种键格式"变体
     (key/key.lower()/key.upper()/替换点为下划线/替换下划线为点) 全部保留了
     点号分隔的命名空间结构，永远匹配不上步骤 1 里的扁平存储 key——即便
     .env 里明明写着这个值，get() 也返回默认值(空字符串)，运行时误判为
     "未配置"。

修复：get() 在原有变体基础上，额外尝试"最后一段(及其大小写)"作为兜底，
让 "api_keys.DEEPSEEK_API_KEY" 也能命中扁平存储的 "deepseek_api_key"。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.unified_config import UnifiedConfig


@pytest.fixture(autouse=True)
def _isolate_os_environ():
    """UnifiedConfig._load_env() 会扫描真实 os.environ 里匹配
    OPENAI/ANTHROPIC/DEEPSEEK/... 前缀的 key 并入 _config——若同一 pytest
    进程内更早的测试(如通过 unified_launcher.py 防御性 load_dotenv())把
    仓库根目录真实的 .env(哪怕只是空值占位)加载进了 os.environ，会让这里
    的"未配置应为空"类断言变得依赖执行顺序、不稳定。这些测试用例通过
    _make_cfg() 显式构造自己的 .env 内容，完全不需要任何 ambient 环境变量——
    测试开始前清空 os.environ(不止测试后恢复，因为污染在测试【开始前】就
    已经发生)，结束后精确恢复原始快照。"""
    snapshot = dict(os.environ)
    os.environ.clear()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def _make_cfg(env_content: str, tmp_path: Path) -> UnifiedConfig:
    env_file = tmp_path / ".env"
    env_file.write_text(env_content, encoding="utf-8")
    cfg = UnifiedConfig.__new__(UnifiedConfig)
    cfg._config = {}
    cfg._callbacks = {}
    cfg.project_root = tmp_path
    cfg.env_file = env_file
    cfg._load_env()
    return cfg


def test_env_key_survives_flat_lowercase_storage(tmp_path):
    """_load_env() 本身的扁平小写存储行为——先确认这一步没坏。"""
    cfg = _make_cfg("DEEPSEEK_API_KEY=sk-real-deepseek-key\n", tmp_path)
    assert cfg._config.get("deepseek_api_key") == "sk-real-deepseek-key"


def test_namespaced_api_keys_lookup_finds_flat_env_value(tmp_path):
    """真机复现的确切查询路径:multi_llm_router._get_key 走的第二段
    "api_keys.{KEY}"。这必须能取到 .env 里的值,不能返回空。"""
    cfg = _make_cfg("DEEPSEEK_API_KEY=sk-real-deepseek-key\n", tmp_path)
    assert cfg.get("api_keys.DEEPSEEK_API_KEY", "") == "sk-real-deepseek-key"


def test_full_get_key_style_fallback_chain_resolves(tmp_path):
    """完整复现 MultiLLMRouter._get_key() 的两段查询顺序。"""
    cfg = _make_cfg("DEEPSEEK_API_KEY=sk-real-deepseek-key\n", tmp_path)

    key_name = "DEEPSEEK_API_KEY"
    val = cfg.get(f"llm.providers.{key_name}.api_key", "")
    if not val:
        val = cfg.get(f"api_keys.{key_name}", "")
    assert val == "sk-real-deepseek-key", (
        "重启后 unified_config 必须能从 .env 取回已保存的 Key，" "否则用户会误以为「保存失败」"
    )


def test_unrelated_placeholder_key_not_found(tmp_path):
    """占位符/未配置的 key 依然应该拿不到值（不能误报已配置）。"""
    cfg = _make_cfg("DEEPSEEK_API_KEY=sk-real-deepseek-key\n", tmp_path)
    assert cfg.get("api_keys.ANTHROPIC_API_KEY", "") == ""


def test_multiple_provider_keys_all_resolve_after_flat_load(tmp_path):
    """不止 DeepSeek——OpenAI/Anthropic/Gemini 等所有走同一模式的 Key 都要修好。"""
    cfg = _make_cfg(
        "OPENAI_API_KEY=sk-openai-x\n" "ANTHROPIC_API_KEY=sk-ant-x\n" "GEMINI_API_KEY=sk-gemini-x\n",
        tmp_path,
    )
    for key_name, expected in [
        ("OPENAI_API_KEY", "sk-openai-x"),
        ("ANTHROPIC_API_KEY", "sk-ant-x"),
        ("GEMINI_API_KEY", "sk-gemini-x"),
    ]:
        assert cfg.get(f"api_keys.{key_name}", "") == expected


def test_existing_dotted_and_underscore_variants_still_work(tmp_path):
    """确保新加的兜底不破坏原有的变体匹配逻辑(非命名空间前缀场景)。"""
    cfg = _make_cfg("SOME_FLAG=true\n", tmp_path)
    assert cfg.get("SOME_FLAG", "") == "true"
    assert cfg.get("some_flag", "") == "true"
    assert cfg.get("some.flag", "") == "true"
