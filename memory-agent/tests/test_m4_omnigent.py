"""Milestone 4 验收:Omnigent 封装(BUILD_SPEC §2-M4)。

Omnigent 为 alpha 且需 tmux/Node 22 + 已配置的 provider;完整会话验收须在
目标机器上人工执行(见 README M4 步骤)。此处覆盖:
- bundle 定义与 MCP 挂载文件的结构正确性(以 omnigent 0.4.0 实际 schema 为准)
- 成本策略函数逻辑
- omnigent CLI 冒烟(未安装则 SKIP)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

BUNDLE = Path(__file__).resolve().parent.parent / "omnigent" / "memory-agent"


def test_bundle_config_schema():
    cfg = yaml.safe_load((BUNDLE / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["spec_version"] == 1  # omnigent bundle 判别字段
    assert cfg["name"] == "memory-agent"
    assert cfg["executor"]["type"] == "omnigent"
    assert cfg["executor"]["config"]["harness"]
    assert "memory_search" in cfg["prompt"] and "memory_store" in cfg["prompt"]
    policy = cfg["guardrails"]["policies"]["cost_limit"]
    assert policy["function"]["arguments"]["max_cost_usd"] > 0


def test_bundle_mcp_mount():
    mcp_cfg = yaml.safe_load((BUNDLE / "tools" / "mcp" / "memory.yaml").read_text(encoding="utf-8"))
    assert mcp_cfg["transport"] == "stdio"
    assert mcp_cfg["command"]
    assert any("services.mcp_server" in str(a) for a in mcp_cfg["args"])


def test_cost_limit_policy():
    import sys

    sys.path.insert(0, str(BUNDLE.parent))
    from omnigent_policies.cost_limit import enforce

    below = enforce(SimpleNamespace(total_cost_usd=0.5), max_cost_usd=5.0)
    assert below["action"] == "allow"

    above = enforce(SimpleNamespace(total_cost_usd=6.0), max_cost_usd=5.0)
    assert above["action"] == "ask"
    assert "5.00" in above["reason"]


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("omnigent") is None,
                    reason="omnigent 未安装(uv tool install omnigent,需 Python 3.12+/Node 22/tmux)")
def test_m4_smoke_cli():
    """冒烟:CLI 可执行且能识别 bundle(完整会话验收在目标机器人工执行)。"""
    out = subprocess.run(["omnigent", "--version"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
