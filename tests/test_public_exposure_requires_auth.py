#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_public_exposure_requires_auth.py

钉住两件互为前提的事：

1. **鉴权默认开着**，而且零配置的安装不会因此起不来（首次自签本机令牌）；
2. **网关暴露到公网之前，鉴权必须是开的** —— 不是警告，是拒绝执行。

为什么这两件必须一起
====================
``GALAXY_AUTH_ENABLED`` 原来默认 ``false``。那个默认建立在一个隐含前提上：
"网关只在局域网里，家里网段本身就是信任边界"。而 Tailscale Funnel 会把网关推到
**公网**（手表没有 Wear OS 的 Tailscale 客户端，带流量单独出门时只能走这条），
前提当场消失 —— 此时默认放行等于任何人都能连 ``/ws/device/<任意 id>`` 驱动你的机器。

**可达性是会变的，默认值不能建立在"当前恰好不可达"上。** 所以默认翻成开。

但直接翻会让每一个没配令牌的现有安装 ``RuntimeError`` 起不来
（``validate_auth_config``）。所以必须同时有首次自签：零配置的体验从"不鉴权"
变成"鉴权开着 + 有一个本机令牌"，而不是"起不来"。

闸门为什么要判"能不能开"而不是"当前开没开"
==========================================
后者会让一次读取失败变成放行 —— 正是本仓反复修的那类形状
（"读不到"与"确实没有"取同一个值）。这里两种失败都必须落在**拒绝**那一侧。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import stat

import pytest


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """每条用例一个独立的 GALAXY_DATA_DIR，且清掉所有鉴权相关 env。"""
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    for k in (
        "GALAXY_AUTH_ENABLED",
        "GALAXY_API_TOKEN",
        "GALAXY_API_TOKENS",
        "GALAXY_MODE",
        "GALAXY_DEV_MODE",
        "GALAXY_REVOKED_TOKENS",
    ):
        monkeypatch.delenv(k, raising=False)
    import core.auth as auth

    importlib.reload(auth)
    return auth


# ---------------------------------------------------------------------------
# 一、默认开 + 零配置仍能起
# ---------------------------------------------------------------------------


def test_auth_is_enabled_by_default(clean_env):
    """**这就是被改掉的那条默认。** 原来是 false。"""
    assert clean_env.is_auth_enabled() is True


def test_explicit_opt_out_still_works(clean_env, monkeypatch):
    """区分度：改的是默认值，不是把开关焊死。仅限确无公网可达路径的场景。"""
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    assert clean_env.is_auth_enabled() is False


def test_unknown_value_now_fails_closed(clean_env, monkeypatch):
    """认不出来的值必须落在**开启**那一侧。原来落在关闭侧 —— 一个笔误就等于关掉鉴权。"""
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "ture")  # 故意拼错
    assert clean_env.is_auth_enabled() is True


def test_empty_value_reads_the_same_way_everywhere(clean_env, monkeypatch):
    """``GALAXY_AUTH_ENABLED=`` 是"没设"，两处读它的地方必须给同一个答案。

    翻默认之前空串两边都算"关"，一致；翻完 ``is_auth_enabled`` 把它当"开"，
    而生产校验那边还把它列在"显式关闭"里 —— 于是 env 文件里留一行空赋值，
    生产就以"不能在生产关闭鉴权"起不来，而鉴权其实开着。
    """
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "")
    monkeypatch.setenv("GALAXY_MODE", "production")
    monkeypatch.setenv("GALAXY_API_TOKEN", "x" * 40)
    assert clean_env.is_auth_enabled() is True
    clean_env.validate_auth_config()  # 不抛就算过

    # 区分度：真的显式关掉时，生产仍必须拒绝。
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    with pytest.raises(RuntimeError, match="Cannot disable authentication"):
        clean_env.validate_auth_config()


def test_zero_config_install_still_starts(clean_env):
    """默认翻成开之后，没配令牌的安装**不许**起不来。"""
    clean_env.validate_auth_config()  # 不抛就算过
    assert clean_env.read_local_token(), "既没抛错也没签出令牌 —— 那鉴权是空转的"


def test_local_token_is_actually_accepted(clean_env):
    """签出来还得真的能用，否则等于没签。"""
    tok = clean_env.ensure_local_token()
    assert tok and tok in clean_env.get_active_tokens()


def test_local_token_file_is_owner_only(clean_env, tmp_path):
    """令牌落盘必须 0600 —— 它等价于你机器的钥匙。"""
    clean_env.ensure_local_token()
    path = tmp_path / "api_token.json"
    assert path.exists()
    if hasattr(os, "fchmod"):  # Windows 上 chmod 只切只读位，不校验
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_token_is_not_regenerated_on_restart(clean_env):
    """重签会让所有已配对设备的令牌一起失效。"""
    first = clean_env.ensure_local_token()
    assert clean_env.ensure_local_token() == first


def test_explicit_token_is_never_overwritten(clean_env, monkeypatch, tmp_path):
    """用户显式配了就以他为准，不许自作主张再签一个。"""
    monkeypatch.setenv("GALAXY_API_TOKEN", "user-configured-token")
    assert clean_env.ensure_local_token() is None
    assert not (tmp_path / "api_token.json").exists()


def test_unreadable_token_file_is_not_silently_treated_as_absent(clean_env, tmp_path, caplog):
    """文件在但读不出 ≠ 还没签过。

    静默当成"没有"会让系统再签一个，旧令牌全部失效、已配对设备集体掉线。
    """
    (tmp_path / "api_token.json").write_text("{ this is not json", "utf-8")
    with caplog.at_level("WARNING"):
        assert clean_env.read_local_token() is None
    assert any("读不出" in r.message or "读不出" in str(r.msg) for r in caplog.records), "读取失败没有留痕"


# ---------------------------------------------------------------------------
# 二、公网暴露的硬闸门
# ---------------------------------------------------------------------------


@pytest.fixture
def mgr(clean_env, monkeypatch):
    """一个"tailscale 装了且已连上"的管理器 —— 只测闸门，不真跑 CLI。"""
    import core.tailscale_manager as tsm

    importlib.reload(tsm)
    monkeypatch.setattr(tsm.shutil, "which", lambda _n: "/usr/bin/tailscale")
    m = tsm.TailscaleManager()
    m._available = True
    return m


def test_gate_passes_on_a_default_install(mgr, clean_env):
    """默认装法（鉴权开 + 自签令牌）应当放行，否则闸门就成了"谁都开不了"。"""
    clean_env.validate_auth_config()
    assert mgr.funnel_preflight()["ok"] is True


def test_gate_refuses_when_auth_is_off(mgr, monkeypatch):
    """**印章本身。** 关了鉴权就不许暴露到公网。"""
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    gate = mgr.funnel_preflight()
    assert gate["ok"] is False
    assert gate["reason"] == "auth_disabled"
    assert gate["how_to_fix"], "拒绝了却不告诉人怎么办"


def test_gate_refuses_when_auth_on_but_no_token(mgr, monkeypatch):
    """鉴权开着但一个令牌都没有 —— 此时放行等于没有鉴权。"""
    monkeypatch.setattr("core.auth.get_active_tokens", lambda: [])
    gate = mgr.funnel_preflight()
    assert gate["ok"] is False
    assert gate["reason"] == "no_token"


def test_gate_blocks_before_any_command_runs(mgr, monkeypatch):
    """闸门不过时**一行 tailscale 命令都不许执行**。

    这条是"拒绝"与"警告后照做"的分水岭。第一版探针没跑到这里（容器里没装
    tailscale，在可用性检查就返回了），所以这里显式把 which 打桩，确保真的
    走到闸门那一步。
    """
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    calls = []
    monkeypatch.setattr(
        "core.tailscale_manager.subprocess.run",
        lambda *a, **k: calls.append(a) or pytest.fail("闸门没拦住，命令被执行了"),
    )
    out = asyncio.run(mgr.ensure_funnel_enabled())
    assert out["enabled"] is False
    assert out["reason"] == "auth_disabled"
    assert calls == []


def test_gate_result_is_carried_out_not_swallowed(mgr, monkeypatch):
    """拒绝的原因要能一路带到调用方（面板要拿它显示人话）。"""
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    out = asyncio.run(mgr.ensure_funnel_enabled())
    assert out["detail"] and out["how_to_fix"]


# ---------------------------------------------------------------------------
# 三、两个查实的地址 bug
# ---------------------------------------------------------------------------


def test_watch_url_is_not_a_hardcoded_ip(mgr, monkeypatch):
    """原来写死 ``wss://100.64.0.1:9000``。

    100.64.0.0/10 是按加入顺序分配的，本机几乎不可能正好是 .1 —— 写死等于
    给手表一个必然连不上的地址。
    """
    import inspect

    import core.tailscale_manager as tsm

    src = inspect.getsource(tsm.TailscaleManager.get_gateway_url_for_watch)
    assert 'return "wss://100.64.0.1' not in src, "又写死了"

    mgr.ts_ip = "100.99.88.77"
    monkeypatch.setattr(type(mgr), "get_funnel_url", lambda _s: None)
    assert "100.99.88.77" in (mgr.get_gateway_url_for_watch() or "")


def test_watch_prefers_funnel_over_tailnet_address(mgr, monkeypatch):
    """手表进不了 tailnet（Wear OS 没有客户端），tailnet 内地址对它没意义。"""
    mgr.ts_ip = "100.99.88.77"
    monkeypatch.setattr(type(mgr), "get_funnel_url", lambda _s: "https://box.tailnet.ts.net")
    assert mgr.get_gateway_url_for_watch() == "wss://box.tailnet.ts.net"


def test_connection_url_is_tls(mgr):
    """Funnel 强制 TLS；两条路统一成 wss，设备端就不用按来源切协议。"""
    mgr.ts_ip = "100.99.88.77"
    url = mgr.get_connection_url(9000)
    assert url and url.startswith("wss://"), f"还是明文：{url}"


def test_funnel_url_parses_real_cli_shape(mgr, monkeypatch):
    """按 ``tailscale serve status --json`` 的真实形状解析，别自己编一个。"""
    payload = {"AllowFunnel": {"box.tail1234.ts.net:443": True}}

    class _R:
        returncode = 0
        stdout = json.dumps(payload)

    monkeypatch.setattr("core.tailscale_manager.subprocess.run", lambda *a, **k: _R())
    assert mgr.get_funnel_url() == "https://box.tail1234.ts.net"


def test_funnel_url_false_flag_is_not_enabled(mgr, monkeypatch):
    """``AllowFunnel`` 里值为 false 的条目不算开着 —— 只看键会误判。"""

    class _R:
        returncode = 0
        stdout = json.dumps({"AllowFunnel": {"box.tail1234.ts.net:443": False}})

    monkeypatch.setattr("core.tailscale_manager.subprocess.run", lambda *a, **k: _R())
    assert mgr.get_funnel_url() is None
