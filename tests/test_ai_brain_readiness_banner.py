"""tests/test_ai_brain_readiness_banner.py
============================================
回归防护:启动横幅"AI 大脑"状态不得在模型实际不可用时显示 ✓。

真机复现:用户选了 gemma4:e2b，本地拉取失败(manifest 解析失败/版本过旧等)，
但 LocalBrainManager._healthy 只代表"Ollama 服务本身可达"——服务确实在跑，
于是启动横幅照样打绿色 ✓「AI 大脑 gemma4:e2b · CPU 模式」，用户以为一切正常，
实际每次对话都在后端报 404，且最终"就绪 · N 正常 · M 降级"总结卡完全不提
这个致命问题(降级项只列了 Docker)。

修复:unified_launcher.ai_brain_readiness() 额外核实选中模型是否真的在
Ollama 已安装列表里(按 tag 前缀宽松匹配)；未安装时如果配置了任一云端
API Key 则降级为 warn(仍可用云端兜底)，否则 fail(彻底不可用)，两者都会
计入启动横幅"降级"统计，而不是被静默吞掉显示成绿色 ✓。
"""

from __future__ import annotations

# 检查对象搬家了：服务编排原样搬到 launcher/services.py，unified_launcher.py 已删除。
from launcher.services import ai_brain_readiness


def test_model_installed_and_service_healthy_is_ok():
    status, installed, label = ai_brain_readiness(
        "gemma4:e2b",
        ["gemma4:e2b", "llama3"],
        True,
        env={},
    )
    assert status == "ok"
    assert installed is True
    assert "已安装" in label


def test_model_not_installed_no_cloud_key_is_fail():
    """真机复现场景:服务健康但选中模型没装好、且无云端 key 兜底 —— 必须是 fail,不能是 ok。"""
    status, installed, label = ai_brain_readiness(
        "gemma4:e2b",
        [],
        True,
        env={},
    )
    assert status == "fail", "模型未装且无云端兜底时必须标记为 fail,不能显示为已就绪"
    assert installed is False
    assert "当前无法对话" in label


def test_model_not_installed_but_cloud_key_set_is_warn():
    status, installed, label = ai_brain_readiness(
        "gemma4:e2b",
        [],
        True,
        env={"DEEPSEEK_API_KEY": "sk-real-key"},
    )
    assert status == "warn"
    assert installed is False
    assert "云端 API Key 可兜底" in label


def test_placeholder_cloud_key_not_counted():
    """占位符 key(如 'your-key-here')不应被当成"已配置"。"""
    status, installed, label = ai_brain_readiness(
        "gemma4:e2b",
        [],
        True,
        env={"OPENAI_API_KEY": "your-key-here"},
    )
    assert status == "fail"


def test_tag_variant_matches_by_root():
    """gemma4:e2b-q4 这类变体 tag 应能按根名匹配到 gemma4:e2b。"""
    status, installed, _ = ai_brain_readiness(
        "gemma4:e2b",
        ["gemma4:e2b-q4_0"],
        True,
        env={},
    )
    assert installed is True
    assert status == "ok"


def test_ollama_service_down_even_with_model_installed_is_not_ok():
    """服务本身不可达时,即便模型列表里有它,也不该是 ok(服务都连不上)。"""
    status, installed, _ = ai_brain_readiness(
        "gemma4:e2b",
        ["gemma4:e2b"],
        False,
        env={},
    )
    assert status != "ok"
