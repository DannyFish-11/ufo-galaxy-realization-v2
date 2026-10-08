"""「调数据方式」的参数不上面板，由智能体按人的话调 —— 边界与行为（core/tuning.py）。

背景：「全部设置」里原先有一百来行数字与档位（回声消除步长、熔断失败次数、并发目标延迟、各种超时……），
几乎都是某个自适应算法自己的常数；人真正会说的是效果（「回声太大」「它老抢我话」「别老主动开口」）。
这些键撤出面板，改由智能体两个工具 ``tuning__list`` / ``tuning__set`` 按人的话调。这里钉的是：

* 白名单有多窄（密钥 / 地址 / 路径 / 端口 / 安全类 / 会删数据的键一个都不在）、每个键有硬范围、出厂值落在范围内；
* 登记的出厂值与代码里真正用的默认值**一致**（保存设置曾把不一致的登记值钉进 .env，悄悄改了行为）；
* 「改了要重启」的清单（读取点在导入时）与源码一致；
* 只在人发起的回合里调、越界不写、放大自主度的方向要人点头、一个回合最多改几个、写进 .env 的是覆盖不是出厂值、
  一句话可撤销、每次留痕。
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import re
from pathlib import Path

import pytest

from core import tuning
from core.routes import config as cfg
from core.routes.config_schema_registry import CONFIG_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
_SOURCE_DIRS = ("core", "launcher", "galaxy_gateway", "enhancements")


# ── 白名单的形状 ─────────────────────────────────────────────────────────────────


def test_every_knob_is_registered_named_and_explained():
    from core.routes.config_labels import LABELS

    for key in tuning.KNOBS:
        assert key in CONFIG_SCHEMA, f"{key} 没登记 —— POST /api/config 会把它当 unknown_keys 拒掉"
        assert key in LABELS, f"{key} 没有中文名 —— 智能体只能报英文键名给人看"


def test_the_whitelist_never_reaches_secrets_addresses_paths_or_security():
    """调参不是配置、更不是权限：这些一个都不许进白名单。"""
    bad_words = {"KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "URL", "HOST", "PORT", "DIR", "PATH", "CERT"}
    bad_words |= {"ALLOW", "ALLOWLIST", "BLOCKLIST", "TRUST"}
    llm_tokens = {"GALAXY_ROUTE_TOKEN_WEIGHT"}  # 这里的 token 是模型用量（选模型时「省 token」的权重），不是凭据
    for key in tuning.KNOBS:
        sch = CONFIG_SCHEMA[key]
        assert sch["category"] != "security", f"{key} 是安全类，不许让模型调"
        assert sch["type"] in ("number", "string", "select"), f"{key} 是 {sch['type']} 类"
        if key in llm_tokens:
            continue
        assert not bad_words & set(key.split("_")), f"{key} 的名字像密钥/地址/路径/权限，不该在调参白名单里"


def test_keys_that_delete_data_stay_with_the_human():
    """调小就是自动删东西（上下文归档、相位账、媒体库、运维记录）—— 只归人，留在面板上。"""
    deleters = {
        "GALAXY_CONTEXT_ARCHIVE_MAX_MB",
        "GALAXY_CONTEXT_ARCHIVE_MIN_DAYS",
        "GALAXY_PHASE_LEDGER_DAYS",
        "GALAXY_MEMORY_MEDIA_MB",
        "GALAXY_OPS_FAILURE_REASONS_MAX",
        "GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX",
        "GALAXY_OPS_REJECTION_REASONS_MAX",
        "GALAXY_OPS_FALLBACK_KINDS_MAX",
        "GALAXY_DEVICE_TOKEN_RETENTION_DAYS",
        "GALAXY_DEVICE_TOKEN_MAX_RECORDS",
        "GALAXY_HITL_CONFIRM_TIMEOUT_S",
        "GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S",
        "GALAXY_MAX_MESSAGE_SIZE",
        "GALAXY_MAX_CONTEXT_TOKENS",
    }
    assert not deleters & set(tuning.KNOBS), sorted(deleters & set(tuning.KNOBS))


def test_every_numeric_knob_has_a_range_and_the_factory_value_is_inside_it():
    for key, kb in tuning.KNOBS.items():
        if kb.kind == "c":
            continue
        assert kb.lo is not None and kb.hi is not None and kb.lo < kb.hi, key
        default = CONFIG_SCHEMA[key]["default"]
        if default != "":  # 空 = 系统自己按本机情况定
            assert kb.lo <= float(default) <= kb.hi, f"{key} 出厂值 {default} 在范围 {kb.lo}~{kb.hi} 之外"


def test_every_choice_knob_offers_its_factory_value():
    for key, kb in tuning.KNOBS.items():
        if kb.kind == "c":
            assert CONFIG_SCHEMA[key]["default"] in tuning.choices_of(key), key


def test_knobs_are_not_listed_on_the_panel_but_can_still_be_saved():
    listed = asyncio.run(cfg.get_config())
    assert not set(listed) & set(tuning.KNOBS), sorted(set(listed) & set(tuning.KNOBS))
    assert set(tuning.KNOBS) <= set(CONFIG_SCHEMA)  # 登记着：POST /api/config、.env、环境变量照旧能用


# ── 登记的出厂值 = 代码里真正用的默认值 ─────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _sources():
    """(相对路径, 文本) —— 只读一遍，下面逐键扫描共用。"""
    skip = ("config_schema_registry.py", "config_labels.py", "core/tuning.py")
    files = [ROOT / "main.py"] + [p for d in _SOURCE_DIRS for p in (ROOT / d).rglob("*.py")]
    out = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and not any(rel.endswith(s) for s in skip):
            out.append((rel, p.read_text(encoding="utf-8", errors="ignore")))
    return tuple(out)


def _read_sites(key: str):
    pat = re.compile(r"""["']""" + re.escape(key) + r"""["']""")
    out = []
    for rel, text in _sources():
        if key not in text:
            continue
        for i, line in enumerate(text.split("\n"), 1):
            st = line.lstrip()
            if pat.search(line) and not st.startswith(("#", '"""')):
                out.append((rel, i, len(line) - len(st), line))
    return out


def test_registered_factory_values_equal_the_defaults_the_code_really_uses():
    """保存设置会把登记的出厂值写进 .env —— 与代码里的默认值不一致，保存一次就悄悄改了行为。

    曾经就是这样：并发的目标延迟登记 2000、代码里 500；熔断窗口登记 60、代码里 10 ……（共 13 个，已对齐）。
    """
    bad = {}
    for key, kb in tuning.KNOBS.items():
        default = CONFIG_SCHEMA[key]["default"]
        if kb.kind == "c" or default == "":
            continue
        pat = re.compile(r"""["']""" + re.escape(key) + r"""["']\s*,\s*([^,)\n]+)""")
        in_code = set()
        for rel, _i, _ind, line in _read_sites(key):
            m = pat.search(line)
            if not m:
                continue
            try:
                in_code.add(float(m.group(1).strip().strip("\"'")))
            except ValueError:
                continue
        if in_code and any(abs(v - float(default)) > 1e-9 for v in in_code):
            bad[key] = (default, sorted(in_code))
    assert not bad, f"登记的出厂值与代码里的默认值不一致: {bad}"


def test_the_restart_list_matches_where_the_code_reads_each_key():
    """读取点在导入时（模块级）的键，改了要重启 —— 清单与源码一致；漏标会让人以为改了就生效。"""
    for key in tuning._AT_IMPORT:
        sites = [s for s in _read_sites(key) if re.search(r"environ|getenv", s[3])]
        assert sites, f"{key} 在源码里找不到读取点"
        assert all(ind == 0 for _rel, _i, ind, _l in sites), f"{key} 的读取点不全在模块级：{sites}"
    for key, kb in tuning.KNOBS.items():
        if kb.kind == "c":
            continue
        sites = [s for s in _read_sites(key) if re.search(r"environ|getenv", s[3])]
        if sites and all(ind == 0 for _rel, _i, ind, _l in sites):
            assert key in tuning._AT_IMPORT, f"{key} 在导入时读（{sites[0][0]}:{sites[0][1]}），该登记进 _AT_IMPORT"


# ── 调参的行为 ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离：.env 与状态文件在临时目录；调参键从环境里清掉；人发起的回合。"""
    import core.config_store as store

    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env.test")
    monkeypatch.setattr(
        store,
        "_singleton",
        store.ConfigStore(config_path=tmp_path / "config.json.test", secrets_path=tmp_path / "secrets.env.test"),
    )
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    for key in tuning.KNOBS:
        monkeypatch.delenv(key, raising=False)
    turn = {"id": "turn-1", "source": "chat"}
    monkeypatch.setattr(
        "core.device_onboarding.conversation._current_turn", lambda: (turn["id"], turn["source"], "太吵了")
    )
    tuning._changes_this_turn.clear()
    return {"tmp": tmp_path, "turn": turn, "monkeypatch": monkeypatch}


def _set(key, value, **kw):
    return asyncio.run(tuning.apply(key, value, reason="用户说的", **kw))


def test_a_human_turn_can_adjust_a_knob_and_gets_the_words_to_tell_the_user(env):
    out = _set("GALAXY_AEC_RES_OVER", "2.5")
    assert out["success"] and out["new"] == "2.5" and out["old"] == "1.5"
    assert os.environ["GALAXY_AEC_RES_OVER"] == "2.5"
    assert "回声残余抑制强度" in out["tell_user"] and "撤销" in out["tell_user"]
    assert "GALAXY_AEC_RES_OVER=2.5" in (env["tmp"] / ".env.test").read_text(encoding="utf-8")


def test_background_turns_cannot_adjust_anything(env):
    for source in ("ambient", "heartbeat", "active_perception", ""):
        env["turn"]["source"] = source
        out = _set("GALAXY_AEC_RES_OVER", "2.5")
        assert not out["success"] and "用户自己发起" in out["error"], source
    env["turn"]["id"] = ""  # 不在任何一次请求里：同样不行（fail closed）
    env["turn"]["source"] = "chat"
    assert not _set("GALAXY_AEC_RES_OVER", "2.5")["success"]
    assert "GALAXY_AEC_RES_OVER" not in os.environ


def test_out_of_range_and_garbage_values_are_refused_and_nothing_is_written(env):
    for bad in ("99", "-3", "abc", "nan", "inf"):
        out = _set("GALAXY_AEC_RES_OVER", bad)
        assert not out["success"], bad
    assert "GALAXY_AEC_RES_OVER" not in os.environ
    assert not (env["tmp"] / ".env.test").exists()


def test_integers_are_rounded_and_choices_must_be_one_of_the_offered(env):
    assert _set("GALAXY_MOA_PROPOSERS", "3.6")["new"] == "4"
    assert _set("GALAXY_VOICE_EAGERNESS", "high")["success"]
    assert os.environ["GALAXY_VOICE_EAGERNESS"] == "high"
    out = _set("GALAXY_VOICE_EAGERNESS", "very-high")
    assert not out["success"] and "可选的档位" in out["error"]


@pytest.mark.parametrize(
    "key",
    [
        "GALAXY_API_TOKEN",
        "OPENAI_API_KEY",
        "GATEWAY_PORT",
        "GALAXY_NATS_URL",
        "GALAXY_EGRESS_MODE",
        "GALAXY_CONTEXT_ARCHIVE_MAX_MB",
        "GALAXY_HITL_CONFIRM_TIMEOUT_S",
        "NOT_A_REAL_KEY",
    ],
)
def test_keys_outside_the_whitelist_are_refused(env, key):
    before = os.environ.get(key)
    out = _set(key, "1")
    assert not out["success"] and "不在可调的参数里" in out["error"]
    assert os.environ.get(key) == before, "被拒的键一个字都不许动（环境里本来就有的也不行）"


def test_keys_that_must_keep_an_order_cannot_cross(env):
    assert not _set("GALAXY_AS_MIN_LIMIT", "60")["success"], "下限 60 > 上限 50"
    assert not _set("GALAXY_CASCADE_FLOOR_MID", "0.9")["success"], "中档门槛 0.9 > 高档门槛 0.70"
    assert _set("GALAXY_CASCADE_FLOOR_HI", "0.95")["success"]
    assert _set("GALAXY_CASCADE_FLOOR_MID", "0.9")["success"], "高档门槛抬到 0.95 之后就可以了"


def test_making_the_agent_more_active_needs_the_user_to_say_yes(env):
    """额度往大、节拍往密、桌面操作步数往多 —— 放大的是它自己的自主度，要人点头；往收敛的方向不用问。"""
    asked = []

    async def _ask(what, session_id):
        asked.append(what)
        return {"state": "asked", "ask_user": f"要不要{what}？"}

    env["monkeypatch"].setattr("core.device_onboarding.agent_tools._ask", _ask)
    out = _set("GALAXY_AMBIENT_DELEGATE_PER_HOUR", "30")
    assert not out["success"] and "要不要" in out["error"], "第一次只是问"
    assert "GALAXY_AMBIENT_DELEGATE_PER_HOUR" not in os.environ and len(asked) == 1

    quieter = _set("GALAXY_AMBIENT_DELEGATE_PER_HOUR", "2")
    assert quieter["success"] and len(asked) == 1, "往少调不用问"
    assert _set("GALAXY_AMBIENT_SPEAK_PER_HOUR", "0")["success"], "让它别主动开口，不用问"

    async def _approved(what, session_id):
        asked.append(what)
        return None

    env["monkeypatch"].setattr("core.device_onboarding.agent_tools._ask", _approved)
    assert _set("GALAXY_AMBIENT_INTERVAL_S", "0.5")["success"], "人点了头就调（节拍更密 = 放大）"
    assert len(asked) == 2


def test_at_most_a_handful_of_changes_per_turn(env):
    keys = ["GALAXY_AEC_RES_OVER", "GALAXY_AEC_MU", "GALAXY_AEC_TAIL_MS", "GALAXY_VOICE_HOLD_S", "GALAXY_LOCKSTEP_CPS"]
    for i, key in enumerate(keys):
        assert _set(key, str(tuning.KNOBS[key].lo + (tuning.KNOBS[key].hi - tuning.KNOBS[key].lo) / 3))["success"], i
    out = _set("GALAXY_LOCKSTEP_GRACE_S", "3")
    assert not out["success"] and "最多改" in out["error"]
    env["turn"]["id"] = "turn-2"  # 下一回合重新算
    assert _set("GALAXY_LOCKSTEP_GRACE_S", "3")["success"]


def test_reset_removes_the_override_instead_of_pinning_the_factory_value(env):
    _set("GALAXY_AEC_RES_OVER", "2.5")
    assert "GALAXY_AEC_RES_OVER=2.5" in (env["tmp"] / ".env.test").read_text(encoding="utf-8")
    out = asyncio.run(tuning.apply("GALAXY_AEC_RES_OVER", None, reason="用户说撤销"))
    assert out["success"] and "GALAXY_AEC_RES_OVER" not in os.environ
    assert "GALAXY_AEC_RES_OVER" not in (env["tmp"] / ".env.test").read_text(encoding="utf-8")
    again = asyncio.run(tuning.apply("GALAXY_AEC_RES_OVER", None))
    assert again["success"] and again.get("unchanged"), "没有覆盖可撤"


def test_saving_one_knob_does_not_pin_the_factory_value_of_all_the_others(env):
    """保存设置会把登记的出厂值整体写进 .env —— 调参键不能这样：钉了，以后代码里自适应常数再调也不会生效。"""
    _set("GALAXY_AEC_RES_OVER", "2.5")
    text = (env["tmp"] / ".env.test").read_text(encoding="utf-8")
    pinned = [k for k in tuning.KNOBS if k != "GALAXY_AEC_RES_OVER" and re.search(rf"^{k}=", text, re.M)]
    assert not pinned, f"这些没人动过的调参键被钉进了 .env: {pinned}"


def test_every_change_leaves_a_trace(env):
    _set("GALAXY_AEC_RES_OVER", "2.5")
    asyncio.run(tuning.apply("GALAXY_AEC_RES_OVER", None, reason="撤销"))
    rows = [json.loads(x) for x in (env["tmp"] / "tuning_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["key"], r["new"], r["reset"]) for r in rows] == [
        ("GALAXY_AEC_RES_OVER", "2.5", False),
        ("GALAXY_AEC_RES_OVER", "1.5", True),
    ]
    assert rows[0]["reason"] == "用户说的" and rows[0]["source"] == "chat" and rows[0]["turn"] == "turn-1"


def test_it_says_honestly_whether_a_restart_is_needed(env):
    assert "重启一次才生效" in _set("GALAXY_AS_MAX_LIMIT", "80")["tell_user"]  # 导入时读
    live = _set("GALAXY_AEC_RES_OVER", "2.5")["tell_user"]
    assert "下一次用到" in live and "没看到变化" in live, "没核实过的不说「已生效」"


# ── 工具：列、查、接线 ───────────────────────────────────────────────────────────


def test_list_without_a_query_gives_topics_and_with_a_query_gives_knobs():
    out = asyncio.run(tuning.dispatch_tuning_tool("list", {}))
    assert out["success"] and set(out["topics"]) == set(tuning.TOPICS)
    hit = asyncio.run(tuning.dispatch_tuning_tool("list", {"query": "回声"}))
    names = {k["key"] for k in hit["knobs"]}
    assert "GALAXY_AEC_RES_OVER" in names
    row = next(k for k in hit["knobs"] if k["key"] == "GALAXY_AEC_RES_OVER")
    assert {"name", "meaning", "value", "default", "range"} <= set(row) and row["default"] == "1.5"


def test_the_set_tool_needs_a_value_or_reset(env):
    out = asyncio.run(tuning.dispatch_tuning_tool("set", {"key": "GALAXY_AEC_RES_OVER"}))
    assert not out["success"] and "value" in out["error"]
    assert not asyncio.run(tuning.dispatch_tuning_tool("nope", {}))["success"]


def test_the_tools_are_wired_into_the_agent_loop_and_survive_trimming():
    src = (ROOT / "core" / "openclawd.py").read_text(encoding="utf-8")
    assert "tuning_tools_for_agent()" in src, "工具没收进智能体的工具表"
    assert '"tuning__"' in src and "dispatch_tuning_tool" in src, "分发没接上"
    from core import context_trim

    assert "tuning__" in context_trim._CORE_TOOL_MARKERS, "工具表一长，调参工具按词法相关性会被裁掉（中文请求得 0 分）"
    assert {t["function"]["name"] for t in tuning.tuning_tools_for_agent()} == {tuning.LIST_TOOL, tuning.SET_TOOL}
