"""面板 API key 与智能路由的一致性契约。

所有者的疑问是:「面板上填的云端 API,跟智能路由系统到底接上没有?」

排查实测出**一处真 bug**:``SONAR_API_KEY`` 在 CONFIG_SCHEMA 里明写是
"Perplexity Sonar API Key (alias)",面板的"已配置"角标也认它——

    "perplexity": _is_configured("SONAR_API_KEY") or _is_configured("PERPLEXITY_API_KEY")

——但 ``PROVIDER_REGISTRY`` 里 perplexity 只有 ``env_key=PERPLEXITY_API_KEY``、
没有 ``alt_env``。于是用户只填 SONAR_API_KEY 时:**面板亮绿标说"已配置",
路由器却根本不读它**,provider 永远不注册,那把密钥静默失效。
"UI 说通了、实际没通"是最坏的一种不一致 —— 用户会以为自己配好了。

本文件把这类漂移钉死,分三层:
1. 面板每个 API key 字段都必须有真实消费者(不一定是 LLM provider:
   OCR/OneAPI 各有自己的消费路径);
2. **面板绿标的判据 key 必须都能被对应 provider 真正读到**(SONAR 那条);
3. 保存路由必须做完整联动(落盘 → os.environ → 路由热刷新),不必重启。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from core.multi_llm_router import PROVIDER_REGISTRY
from core.routes.config import CONFIG_SCHEMA

REPO = Path(__file__).resolve().parent.parent

#: registry 里所有 provider 真正会去读的环境变量名(env_key + alt_env)。
_ROUTER_READS: set[str] = set()
for _spec in PROVIDER_REGISTRY:
    _ROUTER_READS.add(_spec["env_key"])
    _ROUTER_READS.update(_spec.get("alt_env", []) or [])

#: 面板暴露的全部 API key 输入框。
_PANEL_API_KEYS = sorted(k for k in CONFIG_SCHEMA if k.endswith("_API_KEY"))


def _has_code_consumer(key: str) -> bool:
    """全仓(排除 schema 定义自身)是否有生产代码读这个 key。"""
    out = subprocess.run(
        ["grep", "-rl", key, "--include=*.py", "core/", "nodes/", "galaxy_gateway/", "enhancements/"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.split()
    return any("routes/config.py" not in p for p in out)


# ── 1. 面板上不该有"填了没人读"的框 ────────────────────────────────────


@pytest.mark.parametrize("key", _PANEL_API_KEYS)
def test_every_panel_api_key_has_a_real_consumer(key):
    """判据刻意**不是**"必须是 LLM provider"。

    排查时我一度用错判据,把 ``DEEPSEEK_OCR2_API_KEY``(OCR 服务密钥,由
    core/vision_pipeline.py 消费)和 ``ONEAPI_API_KEY``(OneAPI 有独立发现段,
    不在 PROVIDER_REGISTRY 里)误判成孤儿、差点删掉。正确判据是"有没有任何
    生产代码读它"。
    """
    assert key in _ROUTER_READS or _has_code_consumer(key), (
        f"{key} 出现在面板配置里,但全仓没有任何 provider 或模块会读取它 —— "
        "面板不该有填了不起作用的输入框。要么接上消费者,要么从 CONFIG_SCHEMA 移除。"
    )


# ── 2. 绿标判据必须与路由器真读的 key 一致(SONAR 那类 bug)────────────


def _badge_keys_by_provider() -> dict[str, list[str]]:
    """从 core/routes/config.py 里解析出"每个绿标看哪些 key"。

    直接读源码而不是调接口:这条契约要在**静态**层面成立,任何人改了判据
    却忘了同步 registry,测试就该红。
    """
    src = (REPO / "core" / "routes" / "config.py").read_text(encoding="utf-8")
    block = src.split('"status": {')[1].split("},")[0]
    out: dict[str, list[str]] = {}
    for line in block.splitlines():
        m = re.match(r'\s*"([a-z_0-9]+)":\s*(.+?),?\s*$', line)
        if not m:
            continue
        provider, expr = m.group(1), m.group(2)
        keys = re.findall(r'_is_configured\("([A-Z_0-9]+)"\)', expr)
        if keys:
            out[provider] = keys
    return out


def test_badge_criteria_match_what_router_actually_reads():
    """面板说"已配置"的每个 key,对应 provider 必须真的会去读。

    否则就是"绿标亮了但密钥失效" —— 用户完全无从察觉。
    只校验 registry 里有的 provider;OCR/OneAPI 等自有消费路径的不在此列
    (它们由第 1 组用例保证有消费者)。
    """
    registry_by_name = {s["name"]: s for s in PROVIDER_REGISTRY}
    badges = _badge_keys_by_provider()
    assert badges, "未能从 config.py 解析出绿标判据,测试自身失效"

    problems: list[str] = []
    for provider, keys in badges.items():
        spec = registry_by_name.get(provider)
        if spec is None:
            continue  # 非 registry provider(ocr/oneapi/ollama),另有消费路径
        reads = {spec["env_key"], *(spec.get("alt_env", []) or [])}
        for k in keys:
            if k not in reads:
                problems.append(
                    f"面板用 {k} 点亮 '{provider}' 绿标,但该 provider 只读 {sorted(reads)} —— "
                    f"用户填了 {k} 会看到'已配置'却完全不生效"
                )
    assert not problems, "\n".join(problems)


def test_sonar_alias_is_wired_to_perplexity():
    """SONAR_API_KEY 是排查时实证的那个真 bug,单独钉死。"""
    spec = next(s for s in PROVIDER_REGISTRY if s["name"] == "perplexity")
    assert "SONAR_API_KEY" in (spec.get("alt_env") or []), "SONAR_API_KEY 必须作为 perplexity 的别名被读取"


# ── 3. 保存即生效:落盘 → os.environ → 路由热刷新 ────────────────────


def test_save_route_does_full_propagation():
    """保存后必须【不需要重启】就生效。

    完整联动缺任何一环,面板存了都等于没存:
      - os.environ.update  → 同进程内立刻可读(_get_key 第三层兜底靠它);
      - UnifiedConfig.reload → 否则"最高优先级"那层一直上报启动时的旧值;
      - schedule_llm_router_refresh → 否则 provider 列表还是启动时那份,
        新填的 key 不会让 provider 注册进来。
    """
    src = (REPO / "core" / "routes" / "config.py").read_text(encoding="utf-8")
    body = src.split("async def update_config(")[1].split("\n@router.")[0]

    assert "os.environ.update(final)" in body, "保存后未把值应用进 os.environ,同进程内读不到"
    assert "_unified_cfg.reload()" in body, "保存后未 reload UnifiedConfig,最高优先级层会一直是旧值"
    assert "schedule_llm_router_refresh()" in body, "保存后未热刷新 LLM 路由,新 key 不会让 provider 注册"


def test_secrets_go_to_secret_store_not_plain_env():
    """密钥必须收敛到 runtime/secrets.env,不能明文落 .env。

    否则重启时 .env 的旧值会盖住 secrets.env —— 这是历史上"重启丢 key"的根因。
    """
    src = (REPO / "core" / "routes" / "config.py").read_text(encoding="utf-8")
    body = src.split("async def update_config(")[1].split("\n@router.")[0]
    assert "set_secret" in body and "classify_key" in body, "密钥未走密钥库收敛"
    assert "exclude=_secrets_persisted" in body, "已入密钥库的项必须从 .env 落盘中排除"
