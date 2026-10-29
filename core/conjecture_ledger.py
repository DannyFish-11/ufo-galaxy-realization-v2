"""core/conjecture_ledger.py —— 猜想账本：说出口的「猜」记成类型化的一条，核完记结论，事后能算准不准。

设计见 ``docs/GROUNDED_AGENT_DESIGN.md`` §4。开放问题才猜，猜要说出来（「我猜……」「可能……」）；
说出来的那一句在这里记一条（``said``），后台联网 + 换一个模型核完再记一条（``settled``：证实 / 驳倒 / 查不到）。

**校准**（:func:`calibration`）= 后来核得出结论的猜想里，被证实的占多少。它告诉人「它说『可能』的时候有几成是对的」。

这本账**只给人看**（``GET /api/v1/agent/live-check``）：不进任何决策路径 —— 选策略、选设备、判权限、决定做不做
都不读它（``tests/test_guesses_are_said_checked_and_counted.py`` 扫描决策模块守着）。要动手就转执行路，从事实层重来。

落盘：``$GALAXY_DATA_DIR/conjecture_ledger.jsonl``，只追加；读的时候按 ``id`` 折叠。写由调用方放进工作线程。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ConjectureLedger")

#: 账本超过这么多行就只留最近的（每条猜想两行）
MAX_LINES = 4000

_lock = threading.Lock()


def ledger_path() -> str:
    from core.data_paths import data_path

    return data_path("conjecture_ledger.jsonl")


def _append(row: Dict[str, Any]) -> None:
    path = ledger_path()
    with _lock:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _trim(path)


def _trim(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    if len(lines) > MAX_LINES:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines[-MAX_LINES:])


def record(text: str, *, session_id: str = "") -> str:
    """记一条说出口的猜想，返回它的编号。同步写盘（调用方在工作线程里调）。"""
    gid = f"cj_{uuid.uuid4().hex[:12]}"
    _append({"event": "said", "id": gid, "at": time.time(), "session_id": session_id, "text": text.strip()[:400]})
    return gid


def settle(gid: str, verdict: str, *, note: str = "", source: str = "", judge: str = "") -> None:
    """记它核出来的结论（``supported`` / ``refuted`` / ``unverified``）。"""
    _append(
        {
            "event": "settled",
            "id": gid,
            "at": time.time(),
            "verdict": verdict,
            "note": note[:200],
            "source": source[:300],
            "judge": judge,
        }
    )


def entries(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """按编号折叠后的猜想，新的在前。"""
    try:
        with _lock, open(ledger_path(), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return []
    folded: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        gid = str(row.get("id") or "")
        if not gid:
            continue
        if row.get("event") == "said":
            folded[gid] = {**row, "verdict": None}
        elif gid in folded:
            folded[gid].update(
                {k: row.get(k) for k in ("verdict", "note", "source", "judge")}, settled_at=row.get("at")
            )
    out = sorted(folded.values(), key=lambda r: r.get("at") or 0, reverse=True)
    return out[:limit] if limit else out


def calibration() -> Dict[str, Any]:
    """猜过多少、核出结论的多少、其中证实几成。``hit_rate`` 在一条结论都没有时为 ``None``（不编一个数）。"""
    rows = entries()
    counts = {"supported": 0, "refuted": 0, "unverified": 0}
    for row in rows:
        if row.get("verdict") in counts:
            counts[row["verdict"]] += 1
    decided = counts["supported"] + counts["refuted"]
    return {
        "said": len(rows),
        "open": sum(1 for r in rows if r.get("verdict") is None),
        **counts,
        "hit_rate": round(counts["supported"] / decided, 3) if decided else None,
    }


__all__ = ["MAX_LINES", "calibration", "entries", "ledger_path", "record", "settle"]
