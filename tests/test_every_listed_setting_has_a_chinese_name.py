"""设置页上每一行都有中文名，每个档位牌都有中文名；整档按钮的主键不再摆第二份。

背景：「全部设置」原先每行第一行是环境变量名（``GALAXY_AEC_RES_FLOOR_DB``），档位牌是原始取值
（``best-effort`` / ``shadow``），读不懂；同时 ``GALAXY_CROSS_DEVICE_ENABLED`` / ``GALAXY_AMBIENT_LOOP`` /
``GALAXY_AUTONOMY`` 这三个键在底部「整档按钮」里已经有开关，设置页里又摆了一行 —— 同一件事两处能拨。

这里钉住的是**数据面**：``GET /api/config/all`` 返回的每个键都带 ``label``，下拉键带 ``option_labels``，
整档主键带 ``bundle`` 标记；前端据此画（只读源码核对，面板构建产物另有一致性检查）。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from core.routes import config_labels
from core.routes.config import CONFIG_BUNDLES, CONFIG_SCHEMA, PANEL_HIDDEN_KEYS, get_config

ROOT = Path(__file__).resolve().parents[1]
PANEL_SRC = ROOT / "electron" / "renderer" / "panel" / "src"
_CJK = re.compile(r"[一-鿿]")


def _listed() -> dict:
    return asyncio.run(get_config())


def test_every_listed_key_has_a_short_chinese_name():
    listed = _listed()
    missing = sorted(k for k, v in listed.items() if not v.get("label"))
    assert not missing, f"设置页列出了这些键却没有中文名，补进 core/routes/config_labels.py::LABELS: {missing}"
    bad = {k: v["label"] for k, v in listed.items() if not _CJK.search(v["label"]) or not 2 <= len(v["label"]) <= 20}
    assert not bad, f"中文名要含汉字且 2–20 字: {bad}"


def test_chinese_names_are_unique():
    """两行同名，人就分不清改的是哪一个。"""
    by_label: dict = {}
    for key, meta in _listed().items():
        by_label.setdefault(meta["label"], []).append(key)
    dup = {label: keys for label, keys in by_label.items() if len(keys) > 1}
    assert not dup, dup


def test_the_name_table_has_no_stale_keys():
    """键删了、改名了、藏起来了，这里的名字就是一条没人读的死记录。"""
    from core.tuning import knob_keys

    # 调参键不在面板上，但智能体报出来给人看时也说中文名，所以这里留着它们的名字
    stale = sorted(set(config_labels.LABELS) - set(_listed()) - knob_keys())
    assert not stale, f"LABELS 里有设置页不再列出、也不是调参键的: {stale}"
    assert not set(config_labels.LABELS) & PANEL_HIDDEN_KEYS
    missing = sorted(k for k in knob_keys() if k not in config_labels.LABELS)
    assert not missing, f"调参键没有中文名，智能体只能报英文键名给人看: {missing}"


def test_every_dropdown_value_has_a_chinese_name():
    listed = _listed()
    for key, meta in listed.items():
        if meta["type"] != "select" or key == "OLLAMA_MODEL":  # OLLAMA_MODEL 的候选是现算的型号串
            continue
        names = meta.get("option_labels") or {}
        assert set(names) == set(meta["options"]), f"{key}: 档位 {meta['options']} 与中文名 {sorted(names)} 对不上"
        assert all(names.values()), key
    from core.tuning import knob_keys

    stale = sorted(
        set(config_labels.OPTION_LABELS) - {k for k, v in listed.items() if v["type"] == "select"} - knob_keys()
    )
    assert not stale, f"OPTION_LABELS 里有不是下拉键的: {stale}"


def test_bundle_primaries_are_marked_so_the_settings_page_skips_them():
    listed = _listed()
    marked = {k: v["bundle"] for k, v in listed.items() if v.get("bundle")}
    # 主键要么已经整个藏起来了（GALAXY_SPEAK），要么列出来并带着档名；不许有「列着却没标」的
    expected = {b["primary"]: b["key"] for b in CONFIG_BUNDLES if b["primary"] in listed}
    assert marked == expected
    assert {b["primary"] for b in CONFIG_BUNDLES if b["primary"] not in listed} <= PANEL_HIDDEN_KEYS
    assert {"GALAXY_AMBIENT_LOOP", "GALAXY_AUTONOMY", "GALAXY_CROSS_DEVICE_ENABLED"} <= set(marked)
    # 值仍然照给 —— 按钮、别的消费者要读；只是设置页不再摆第二个开关
    assert all("value" in listed[k] for k in marked)


def test_the_panel_draws_the_label_and_skips_bundled_rows():
    settings = (PANEL_SRC / "ui" / "settings.ts").read_text(encoding="utf-8")
    transport = (PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
    assert "item.label || item.key" in settings, "行首该画中文名（没有才退回键名）"
    assert "name.title = item.key" in settings, "环境变量名退到悬停提示，别丢了"
    assert "item.optionLabels?.[opt]" in settings, "档位牌该画中文名"
    assert "!i.bundle" in settings, "整档主键不该在设置页再摆一行"
    for token in ("option_labels", "o['bundle']", "label: str('label')"):
        assert token in transport, f"transport.ts 没读 {token}"


def test_dropdown_values_match_what_the_code_really_accepts():
    """面板上能选的，必须是代码认的 —— 否则选了等于没选，甚至让命令行报错。"""
    # GALAXY_PREFLIGHT_MODE 的唯一读者是预检命令行的 --mode
    cli = (ROOT / "core" / "config_preflight.py").read_text(encoding="utf-8")
    choices = re.search(r"choices=\[([^\]]+)\]", cli).group(1)
    accepted = set(re.findall(r'"([a-z]+)"', choices))
    assert set(CONFIG_SCHEMA["GALAXY_PREFLIGHT_MODE"]["options"]) == accepted
    assert CONFIG_SCHEMA["GALAXY_PREFLIGHT_MODE"]["default"] in accepted
    # GALAXY_MODE 里代码只认 production（强制鉴权）；distributed / federated / standalone 从来没有读者
    assert "production" in CONFIG_SCHEMA["GALAXY_MODE"]["options"]
    assert not {"distributed", "federated", "standalone"} & set(CONFIG_SCHEMA["GALAXY_MODE"]["options"])


def test_the_line_under_each_name_does_not_repeat_the_name():
    """名字多半取自描述的开头；下面那一句再写一遍同样的话，就是同一句出现两次。"""
    for key, meta in _listed().items():
        hint, label = meta["hint"], meta["label"]
        assert isinstance(hint, str), key
        # 名字后面紧跟分隔符才算「重复」；名字只是描述里一个更长词语的开头（草稿 / 草稿位）不算
        repeated = hint.startswith(label) and (len(hint) == len(label) or hint[len(label)] in "（(：:，,。;；·—= ")
        assert not repeated, f"{key}: 说明以名字开头 —— {hint!r}"


def test_dropdown_lines_speak_the_chinese_names_not_the_raw_values():
    """档位牌是中文，说明里再写 ``env=…`` / ``strict=…`` 就又得读两套词。"""
    for key, meta in _listed().items():
        if meta["type"] != "select" or not meta.get("option_labels") or key == "GALAXY_AUTONOMY":
            continue
        shown = "".join(meta["option_labels"].values())
        # 档位牌上本来就印着这个取值（A 轻量本地）的，说明里可以用它指代
        leaked = [
            v for v in meta["options"] if v and v not in shown and re.search(rf"\b{re.escape(v)}\s*[=＝]", meta["hint"])
        ]
        assert not leaked, f"{key}: 说明里还有原始取值 {leaked}: {meta['hint']}"


def test_hint_strips_only_a_real_leading_name():
    from core.routes.config_labels import hint_for

    # 名字后面是括号：括号拆开，括号后的话并上；嵌套括号不截断
    assert hint_for("GALAXY_CB_WINDOW_SIZE", "熔断统计窗口（最近 N 次(含重试)的结果 · 默认 20）。越大越稳") == (
        "最近 N 次(含重试)的结果 · 默认 20；越大越稳"
    )
    # 描述只是名字本身：不再画第二行
    assert hint_for("FEDERATION_LOCAL_HOST", "联邦里本机对外的主机名") == ""
    # 名字只是描述开头的一个词、而不是一个完整短语：不能把半个词削掉
    assert hint_for("GALAXY_VOICE", "启用语音输入输出") == "启用语音输入输出"
    # 描述不以名字开头：原样
    assert hint_for("GALAXY_API_HOST", "回连用的主机名") == "回连用的主机名"


def test_finite_string_keys_are_drawn_as_dropdowns_and_keep_their_default_choosable():
    """auto / 1 / 0 这类取值有限的字符串键：面板按档位牌画；登记的默认值必须是其中一档。"""
    from core.tuning import knob_keys

    listed = _listed()
    # 调参键（如全双工的 auto/1/0）已不在面板上；留在面板上的取值有限的字符串键仍按档位牌画
    finite = [k for k in config_labels.OPTION_LABELS if CONFIG_SCHEMA[k]["type"] == "string" and k not in knob_keys()]
    assert {"GALAXY_MCP_PIN_MODE", "GALAXY_EGRESS_MODE", "GALAXY_EXECUTION_ISOLATION"} <= set(finite)
    for key in finite:
        assert listed[key]["type"] == "select", key
        assert listed[key]["options"] == list(config_labels.OPTION_LABELS[key]), key
        assert CONFIG_SCHEMA[key]["default"] in listed[key]["options"], f"{key} 的默认值不在档位里"
    # 档位里不含空值时，面板也不会凭空多出一个「自动」牌
    assert all("" not in listed[k]["options"] for k in finite)
