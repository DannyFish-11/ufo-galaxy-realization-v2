"""测试里手表、手机的设备自述:取自安卓仓 Kotlin 构造器真拼出来的两份(``tests/fixtures/device_self/``)。

真手表、真手机的能力上报都带 ``self_description``(设计文档第 1 步),中心按里面每个动作的 ``effect`` 判
要不要先问人(``core/device_boundaries.py``)。测试替身照真设备拼,只挑这一次报的那几个动作。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "device_self"


def _load(name: str) -> Dict[str, Any]:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _pick(full: Dict[str, Any], actions: Iterable[str], unavailable: Optional[Dict[str, str]]) -> Dict[str, Any]:
    desc = copy.deepcopy(full)
    by_name = {a["name"]: a for a in desc["actions"]}
    missing = [a for a in actions if a not in by_name]
    assert not missing, f"真设备没有这些动作:{missing}"
    desc["actions"] = [by_name[a] for a in actions]
    if unavailable:
        desc["unavailable"] = [{"name": k, "reason": v} for k, v in unavailable.items()]
    else:
        desc.pop("unavailable", None)
    return desc


def watch_self(actions: Iterable[str], *, answers_decisions: bool = True, unavailable=None) -> Dict[str, Any]:
    desc = _pick(_load("watch_self_all_actions"), actions, unavailable)
    desc["declares"]["answers_decisions"] = answers_decisions
    return desc


def phone_self(actions: Iterable[str], *, unavailable=None) -> Dict[str, Any]:
    return _pick(_load("phone_self_all_actions"), actions, unavailable)
