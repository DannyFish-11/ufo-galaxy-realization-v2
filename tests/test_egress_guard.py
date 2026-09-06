"""出口闸:这次出站发去了哪儿,以及这道闸有没有实际拦截效力。

在这个模块之前,``core/`` 下 ``egress|outbound|network_policy|firewall`` 零命中 ——
一次执行往外连了哪些主机,系统里没有任何一处说得出来。

容器隔离挡住了"模型写的代码能干什么",挡不住出站;数据外泄走的正是这条路。
"""

from __future__ import annotations

import pytest

from core import egress_guard as eg


def _lists_host(entries, host: str) -> bool:
    """主机名是不是这个集合里的**一个完整成员**。

    为什么不直接写 ``host in entries``
    ----------------------------------
    CodeQL 的 "Incomplete URL substring sanitization" 会把 ``"a.com" in X`` 一律
    当成对 URL 做子串净化来报 —— 它分不清"元组成员判断"和"字符串包含"。而这里要的
    本来就是**精确相等**,写明白它既让告警消失,也让读的人不用猜。
    """
    return any(entry == host for entry in entries)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每条用例自己钉死前提,并且不让账本跨用例串味。"""
    for key in ("GALAXY_EGRESS_MODE", "GALAXY_EGRESS_ALLOW", "GALAXY_EGRESS_ALLOW_PRIVATE"):
        monkeypatch.delenv(key, raising=False)
    eg.clear_ledger()
    yield
    eg.clear_ledger()


# ══════════════════════════════════════════════════════════════════════════
# A. 档位语义 —— audit 不能被读成"已防护"
# ══════════════════════════════════════════════════════════════════════════


def test_a01_audit_is_the_default():
    assert eg.egress_mode() == "audit"


def test_a02_a_typo_does_not_silently_disable_the_gate(monkeypatch):
    """拼错按 audit 处理。按 off 处理会让一个笔误静默把记账也关掉。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enfroce")
    assert eg.egress_mode() == "audit"


def test_a03_audit_allows_but_is_not_enforcing():
    """这一条是整个模块最容易被读错的地方:audit 档下 allowed=True,
    但那**不代表审过了**。两件事必须分得开。"""
    decision = eg.evaluate("https://totally-unknown.example.com/x", purpose="t")
    assert decision.allowed is True
    assert decision.enforced is False
    assert decision.kind == "audit"
    assert "未拦截" in decision.reason


def test_a04_report_says_plainly_that_audit_does_not_protect():
    """报告绝不能让 mode=audit 看起来像"已防护"。"""
    report = eg.egress_report()
    assert report["enforcing"] is False
    assert "不提供保护" in report["protection"]


def test_a05_enforce_actually_blocks(monkeypatch):
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    decision = eg.evaluate("https://totally-unknown.example.com/x")
    assert decision.allowed is False
    assert decision.enforced is True
    with pytest.raises(eg.EgressBlocked):
        eg.check_egress("https://totally-unknown.example.com/x")


def test_a06_off_means_the_module_is_not_in_the_room(monkeypatch):
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "off")
    assert eg.evaluate("https://anything.example.com").allowed is True
    assert eg.recent() == []
    assert eg.egress_report()["enforcing"] is False


# ══════════════════════════════════════════════════════════════════════════
# B. 主机解析:"判不出来"不能被当成"没有出站"
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.openai.com/v1/chat", "api.openai.com"),
        ("http://10.0.0.5:8080/x", "10.0.0.5"),
        ("api.example.com/x", "api.example.com"),
        ("", ""),
        ("not a url at all", ""),
    ],
)
def test_b01_host_extraction(url, expected):
    assert eg.host_of(url) == expected


def test_b02_a_url_without_a_host_is_refused_under_enforce(monkeypatch):
    """取不出主机 = 判不出来。enforce 档下不能放过去。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    decision = eg.evaluate("::::")
    assert decision.allowed is False
    assert decision.kind == "unknown"


# ══════════════════════════════════════════════════════════════════════════
# C. 白名单:推导出来的,不是另攒一份
# ══════════════════════════════════════════════════════════════════════════


def test_c01_provider_hosts_are_derived_from_the_existing_registry():
    """自己另攒一份 provider 地址表的话,加一家云厂商就会漏一处。"""
    entries = eg.allowlist()
    assert _lists_host(entries, "api.openai.com")


def test_c02_weight_hosts_are_on_the_list_too():
    assert _lists_host(eg.allowlist(), "huggingface.co")


def test_c03_user_entries_are_appended(monkeypatch):
    monkeypatch.setenv("GALAXY_EGRESS_ALLOW", "my.internal.tool, other.example.com")
    entries = eg.allowlist()
    assert _lists_host(entries, "my.internal.tool")
    assert _lists_host(entries, "other.example.com")


def test_c04_provider_call_passes_under_enforce(monkeypatch):
    """enforce 档必须是**可用的** —— 程序自己的合法流量不能被自己打死。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    decision = eg.evaluate("https://api.openai.com/v1/chat/completions")
    assert decision.allowed is True
    assert decision.kind == "allowlist"


# ══════════════════════════════════════════════════════════════════════════
# D. 匹配规则:后缀包含匹配是形同虚设的白名单
# ══════════════════════════════════════════════════════════════════════════


def test_d01_lookalike_domain_does_not_match(monkeypatch):
    """``evil-openai.com`` 会命中朴素的后缀判断 —— 那种白名单等于没有。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    assert eg.evaluate("https://evil-openai.com/steal").allowed is False


def test_d02_explicit_wildcard_works(monkeypatch):
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    monkeypatch.setenv("GALAXY_EGRESS_ALLOW", "*.example.com")
    assert eg.evaluate("https://a.example.com/x").allowed is True
    assert eg.evaluate("https://deep.a.example.com/x").allowed is True


def test_d03_wildcard_does_not_match_the_bare_domain(monkeypatch):
    """``*.example.com`` 不该命中 ``example.com`` 本身 —— 写通配的人要的是子域。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    monkeypatch.setenv("GALAXY_EGRESS_ALLOW", "*.example.com")
    assert eg.evaluate("https://example.com/x").allowed is False


def test_d04_wildcard_does_not_match_a_suffix_lookalike(monkeypatch):
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    monkeypatch.setenv("GALAXY_EGRESS_ALLOW", "*.example.com")
    assert eg.evaluate("https://notexample.com/x").allowed is False


# ══════════════════════════════════════════════════════════════════════════
# E. 回环与内网
# ══════════════════════════════════════════════════════════════════════════


def test_e01_loopback_is_not_egress(monkeypatch):
    """本机推理不是出站。也不记账 —— 否则会瞬间刷满账本,把真出站淹掉。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    decision = eg.evaluate("http://localhost:11434/api/tags")
    assert decision.allowed is True
    assert decision.kind == "loopback"
    assert eg.recent() == []


def test_e02_private_is_allowed_by_default_but_recorded(monkeypatch):
    """内网默认放行(否则多设备编队直接死),但必须留痕 ——
    发给同一局域网的另一台机器同样是一条外泄路径。"""
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    decision = eg.evaluate("http://192.168.1.50:8080/x", purpose="mesh")
    assert decision.allowed is True
    assert decision.kind == "private"
    assert any(item["host"] == "192.168.1.50" for item in eg.recent())


def test_e03_private_can_be_closed(monkeypatch):
    monkeypatch.setenv("GALAXY_EGRESS_MODE", "enforce")
    monkeypatch.setenv("GALAXY_EGRESS_ALLOW_PRIVATE", "0")
    assert eg.evaluate("http://192.168.1.50:8080/x").allowed is False


# ══════════════════════════════════════════════════════════════════════════
# F. 账本有界
# ══════════════════════════════════════════════════════════════════════════


def test_f01_ledger_is_bounded():
    """无界的账本本身就是一次内存泄漏。"""
    for i in range(eg.LEDGER_MAX + 50):
        eg.evaluate(f"https://h{i}.example.com/x")
    assert len(eg.recent(eg.LEDGER_MAX * 2)) == eg.LEDGER_MAX


def test_f02_ledger_records_purpose():
    eg.evaluate("https://unknown.example.com/x", purpose="llm:openai")
    assert eg.recent()[-1]["purpose"] == "llm:openai"


# ══════════════════════════════════════════════════════════════════════════
# G. 真的接在出站路径上 —— 否则就是"看起来接上了,其实没有"
# ══════════════════════════════════════════════════════════════════════════


def test_g01_the_provider_chokepoint_asks_the_gate():
    """所有云端 POST 的收口点必须问判据。在每个适配器里各写一遍必然漏掉一家。"""
    import inspect

    from core.multi_llm_router import BaseProviderAdapter

    body = inspect.getsource(BaseProviderAdapter._post_with_retry)
    assert "check_egress" in body


@pytest.mark.parametrize("key", ["GALAXY_EGRESS_MODE", "GALAXY_EGRESS_ALLOW", "GALAXY_EGRESS_ALLOW_PRIVATE"])
def test_g02_switches_are_registered(key):
    from core.routes.config_schema_registry import CONFIG_SCHEMA

    assert key in CONFIG_SCHEMA


@pytest.mark.parametrize("key", ["GALAXY_EGRESS_MODE", "GALAXY_EGRESS_ALLOW", "GALAXY_EGRESS_ALLOW_PRIVATE"])
def test_g03_switches_reach_the_panel(key):
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / ("electron/renderer/panel/src/settings_inventory.ts")
    assert f"'{key}'" in src.read_text(encoding="utf-8")
