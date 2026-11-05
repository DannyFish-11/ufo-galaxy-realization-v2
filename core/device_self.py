"""core/device_self.py — 设备自述(``device_self/1``):设备怎么描述自己,中心怎么读。

设计见 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 第 3 节;schema 在 ``contracts/device_self_v1.json``,
手机、手表用 shared-protocol 的 ``DeviceSelfDescription.kt`` 拼同一个形状。

中心只在这里把新旧两种上报读成同一个对象(存进 UDM 元数据的 ``self_description``):

* 新版设备在 ``capability_report`` 里带 ``self_description``;
* 旧版设备只有散字段:``supported_actions`` + ``capability_schemas[].description`` / ``action_descriptions``、
  ``bridge_agent``、``answers_decisions``、``shows_request_progress``。

读入是**宽松**的:不合 schema 的地方记一条日志、能用的照用,不因为设备拼错一个字段就把它整个拒掉。
严格的是契约测试(三边各自核对拼出来的帧)。

带了自述的上报,``absorb`` 把它展开回旧字段再交给后面的处理(能力权威面、声明、派桥接 Agent),
那几处不用知道有两种上报。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("Galaxy.DeviceSelf")

SCHEMA = "device_self/1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "device_self_v1.json"

#: 动作做了会怎样:只看 / 打扰人 / 改设备状态 / 对外发出 / 不可逆。旧版设备不报,记成空串(没声明)。
EFFECTS = ("read", "notify", "act", "send", "danger")
TAILNET_MODES = ("embedded", "system", "none")


@lru_cache(maxsize=1)
def schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def problems(desc: Any) -> List[str]:
    """``desc`` 哪里不合 schema(合就是空表)。只用来记日志和给契约测试,读入不因此拒收。"""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover — requirements 里有;没装就不查
        return []
    validator = jsonschema.Draft202012Validator(schema())
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(desc)
    ]


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _flag(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _action(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
        return {}
    effect = str(raw.get("effect") or "").strip()
    out: Dict[str, Any] = {
        "name": _text(raw["name"], 48),
        "description": _text(raw.get("description"), 300),
        "effect": effect if effect in EFFECTS else "",
        "params": dict(raw["params"]) if isinstance(raw.get("params"), dict) else {},
        "needs_human": _flag(raw.get("needs_human")),
    }
    if isinstance(raw.get("returns"), dict):
        out["returns"] = dict(raw["returns"])
    return out


def _from_self(sd: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    issues = problems(sd)
    if issues:
        logger.info("设备 %s 的自述有不合 schema 的地方(照常读入能用的部分): %s", report.get("device_id"), issues[:5])
    actions = [a for a in (_action(x) for x in sd.get("actions") or []) if a]
    unavailable = [
        {"name": _text(u.get("name"), 48), "reason": _text(u.get("reason"), 200)}
        for u in sd.get("unavailable") or []
        if isinstance(u, dict) and str(u.get("name") or "").strip()
    ]
    declares = sd.get("declares") if isinstance(sd.get("declares"), dict) else {}
    tailnet = str(declares.get("tailnet") or "")
    return {
        "schema": SCHEMA,
        "source": "self_description",
        "name": _text(sd.get("name"), 80),
        "kind": _text(sd.get("kind"), 40),
        "about": _text(sd.get("about"), 300),
        "actions": actions,
        "unavailable": unavailable,
        "declares": {
            "answers_decisions": _flag(declares.get("answers_decisions")),
            "shows_request_progress": _flag(declares.get("shows_request_progress")),
            "hosts_agent": _text(declares.get("hosts_agent"), 40),
            "tailnet": tailnet if tailnet in TAILNET_MODES else "",
        },
    }


def _from_legacy(report: Dict[str, Any]) -> Dict[str, Any]:
    payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}

    def pick(key: str) -> Any:
        return report.get(key, payload.get(key))

    schemas = {
        str(s["action"]): s for s in (pick("capability_schemas") or []) if isinstance(s, dict) and s.get("action")
    }
    said = pick("action_descriptions") if isinstance(pick("action_descriptions"), dict) else {}
    actions = []
    for name in pick("supported_actions") or []:
        s = schemas.get(str(name), {})
        actions.append(_action({**s, "name": name, "description": s.get("description") or said.get(str(name)) or ""}))
    return {
        "schema": SCHEMA,
        "source": "legacy",
        "name": _text(pick("device_name"), 80),
        "kind": _text(pick("device_type") or pick("platform"), 40),
        "about": "",
        "actions": [a for a in actions if a],
        "unavailable": [],
        "declares": {
            "answers_decisions": _flag(pick("answers_decisions")),
            "shows_request_progress": _flag(pick("shows_request_progress")),
            "hosts_agent": _text(pick("bridge_agent"), 40),
            "tailnet": "",
        },
    }


def self_description_in(report: Dict[str, Any]) -> Any:
    sd = report.get("self_description")
    if sd is None and isinstance(report.get("payload"), dict):
        sd = report["payload"].get("self_description")
    return sd


def read(report: Dict[str, Any]) -> Dict[str, Any]:
    """一份能力上报 → 统一的自述对象。带了 ``self_description`` 就读它,否则从旧字段拼。"""
    sd = self_description_in(report)
    return _from_self(sd, report) if isinstance(sd, dict) else _from_legacy(report)


def legacy_fields(desc: Dict[str, Any]) -> Dict[str, Any]:
    """自述展开成旧字段,给还在读旧字段的处理用。"""
    out: Dict[str, Any] = {
        "supported_actions": [a["name"] for a in desc["actions"]],
        "capability_schemas": [
            {k: v for k, v in {**a, "action": a["name"]}.items() if k != "name"} for a in desc["actions"]
        ],
        "answers_decisions": desc["declares"]["answers_decisions"],
        "shows_request_progress": desc["declares"]["shows_request_progress"],
    }
    if desc["declares"]["hosts_agent"]:
        out["bridge_agent"] = desc["declares"]["hosts_agent"]
    return out


def absorb(report: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """读入一份能力上报:返回(给后面处理用的上报,统一的自述对象)。

    带了自述的,自述说了算:展开成旧字段盖在上报上(过渡期新旧一起发时以新的为准)。没带的原样返回。
    """
    desc = read(report)
    if desc["source"] != "self_description":
        return report, desc
    merged = dict(report)
    merged.update(legacy_fields(desc))
    merged.pop("action_descriptions", None)
    return merged, desc


def described(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """UDM 元数据里记下的自述(没有就是空字典)。"""
    sd = (metadata or {}).get("self_description")
    return sd if isinstance(sd, dict) else {}
