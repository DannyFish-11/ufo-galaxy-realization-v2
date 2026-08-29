"""core/phase_transition_ledger.py —— 三态转移的耐久账

为什么要有它
------------
2026-08-29 为「每 3 天折一张记忆卡片」查原料时发现:**这个主体最本体的那一维,
没有历史。**

耐久的东西有:``canonical_tasks.jsonl``(任务,带全套时间戳)、``context_archive``
的对话原文分段、``agent_identity_memory``。而三态本身:

* ``RenderPosture`` 每拍现算,不落盘;
* ``DecisionTimeline`` 是进程内的 list,满了 FIFO 淘汰,进程一死就没;
* ``_execution_lifecycle_history`` 同样是模块级 dict。

于是「这三天它是静着、阈限着、还是在表达」这件事,**问不出来**。在这种情况下
去生成一张讲它这三天的卡片,卡上关于三态的每一句都是编的。

为什么记的是转移,不是每拍
--------------------------
三天的 tick 量很大而且几乎全是重复。真正带信息的是**跳变**:
``silent → liminal → manifest → receding``。跳变离散、稀疏,而且
:func:`core.phase_contract.transition_kind_of` 已经把「这是哪一种跳变」算好了 ——
这里直接用那一份,不另立第二套判据。

停留时长不需要单独记:两条相邻记录之间,相位就是前一条的 ``to_phase``,时长是
两个时间戳之差。记跳变等于记了全部,而且省三个数量级。

「连续」怎么变成可机械判定的
----------------------------
需求原话是「**既确保连续**的情况下每 3 天化作一张卡」。要让「连续」不是一句
指望,账本必须能指出**哪一段是不知道的**。

所以每条记录带 ``epoch`` —— 本进程的标识。相邻两条记录 epoch 不同,中间就是一段
**进程不在**的时间:那段里发生过什么,这里答不上来。

这条区分是这个模块存在的一半理由:

* **安静** = 同一 epoch 内两条记录隔了很久。相位是**已知**的(前一条的 to_phase),
  「它安静地待了 40 小时」是一句实话。
* **不可知** = epoch 边界。进程不在,可能关机了,也可能在别的机器上跑。
  这段**不能**被当成安静。

把两者混成一个,卡片就会把「关机三天」写成「安静了三天」—— 那正是本仓一直在
防的那类失效:看起来有答案,其实没有。

已知的边界
----------
**一个进程如果启动了却一次都没转移过,这里不留痕。** 那段时间会被算成「不可知」
而不是「安静」。这是刻意选的偏向:宁可说不知道,不可把没记录说成没发生。
(代价是不去多加一个「开机就写一笔」的接线点 —— 那个点很容易变成没人调的死代码,
本仓这半年在这上面栽过五次。)

写失败不静默
------------
落账绝不能把相位推进本身搞挂,所以异常一律吞掉。但吞掉要留痕:
:func:`ledger_status` 会报出本进程失败了多少笔,读账的人据此知道这段可能不全。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from core.phase_contract import transition_kind_of

logger = logging.getLogger("Galaxy.PhaseTransitionLedger")

#: 落盘位置。遵守本仓既有的 ``GALAXY_DATA_DIR`` 约定 —— 不认它的话,运维把数据目录
#: 指到别处时这份账会留在源码树里,而容器化部署的源码树往往是只读或临时的。
LEDGER_PATH: str = os.path.join(
    os.environ.get("GALAXY_DATA_DIR")
    or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
    "phase_transitions.jsonl",
)

#: 本进程的标识。相邻两条记录 epoch 不同 = 中间有一段进程不在的时间。
EPOCH_ID: str = uuid.uuid4().hex[:12]

#: 保留多久。默认 90 天 —— 够 30 张三天卡,再往前的卡本身已经是摘要了。
RETENTION_DAYS: int = max(1, int(os.environ.get("GALAXY_PHASE_LEDGER_DAYS", "90") or 90))

#: 超过这个行数才去做一次裁剪。每写一笔都重写整个文件的话,转移频繁时会把磁盘打满。
_PRUNE_EVERY_LINES = 2000

_KIND_TRANSITION = "transition"
_KIND_EPOCH_OPEN = "epoch_open"

_lock = threading.Lock()
_epoch_written = False
_write_failures = 0
_writes = 0


def _now() -> float:
    return time.time()


def _append(record: Dict[str, Any]) -> None:
    """追加一行。调用方已持锁。"""
    d = os.path.dirname(LEDGER_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _maybe_prune() -> None:
    """按保留期裁剪。调用方已持锁;失败不抛(裁剪失败不该影响记账)。"""
    try:
        if not os.path.exists(LEDGER_PATH):
            return
        with open(LEDGER_PATH, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) < _PRUNE_EVERY_LINES:
            return
        cutoff = _now() - RETENTION_DAYS * 86400.0
        kept: List[str] = []
        for line in lines:
            try:
                if float(json.loads(line).get("at", 0.0)) >= cutoff:
                    kept.append(line)
            except Exception:  # noqa: BLE001 — 坏行直接丢,不让它卡住裁剪
                continue
        if len(kept) == len(lines):
            return
        tmp = LEDGER_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
        os.replace(tmp, LEDGER_PATH)
    except Exception as exc:  # noqa: BLE001
        logger.debug("相位账裁剪跳过(非致命): %s", exc)


def record_transition(
    from_phase: str,
    to_phase: str,
    *,
    source: str = "",
    runtime_session_id: str = "",
    trace_id: str = "",
) -> bool:
    """记一笔三态转移。返回是否真的写进去了。

    **绝不抛异常** —— 相位推进是主体的主干,不能因为一次磁盘写失败而中断。
    失败会计入 :func:`ledger_status` 的 ``write_failures``,读账的人据此知道
    这段可能不全。
    """
    global _epoch_written, _write_failures, _writes
    with _lock:
        try:
            if not _epoch_written:
                # 本进程第一笔之前先开一个 epoch —— 有了它,读账时才能把
                # 「进程不在的那段」与「安静的那段」分开。
                _append(
                    {
                        "kind": _KIND_EPOCH_OPEN,
                        "at": _now(),
                        "epoch": EPOCH_ID,
                        "pid": os.getpid(),
                    }
                )
                _epoch_written = True

            _append(
                {
                    "kind": _KIND_TRANSITION,
                    "at": _now(),
                    "epoch": EPOCH_ID,
                    "from": str(from_phase or ""),
                    "to": str(to_phase or ""),
                    # 转移性质用契约里那一份算,不在这里另写一张表 ——
                    # 两张表迟早对不上,而对不上的那天没人会发现。
                    "transition_kind": transition_kind_of(from_phase or None, str(to_phase or "")),
                    "source": str(source or ""),
                    "session": str(runtime_session_id or ""),
                    "trace": str(trace_id or ""),
                }
            )
            _writes += 1
            if _writes % _PRUNE_EVERY_LINES == 0:
                _maybe_prune()
            return True
        except Exception as exc:  # noqa: BLE001 — 见 docstring
            _write_failures += 1
            logger.warning("相位转移落账失败(第 %d 笔): %s", _write_failures, exc)
            return False


def read_window(start_at: float, end_at: float, *, limit: int = 5000) -> List[Dict[str, Any]]:
    """读 ``[start_at, end_at)`` 里的记录,按时间升序。

    读不到文件返回空表 —— 但**空表不等于「这段什么都没发生」**:账本不在、
    或者这段落在进程不在的时间里,同样是空。要区分这两件事得看 epoch,
    见模块头。这个函数只负责搬运。
    """
    out: List[Dict[str, Any]] = []
    try:
        if not os.path.exists(LEDGER_PATH):
            return out
        with open(LEDGER_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                at = float(rec.get("at", 0.0) or 0.0)
                if start_at <= at < end_at:
                    out.append(rec)
                    if len(out) >= limit:
                        break
    except Exception as exc:  # noqa: BLE001
        logger.warning("相位账读取失败: %s", exc)
        return []
    out.sort(key=lambda r: float(r.get("at", 0.0) or 0.0))
    return out


def ledger_status() -> Dict[str, Any]:
    """账本自己的状态。给诊断面。"""
    exists = os.path.exists(LEDGER_PATH)
    size = 0
    if exists:
        try:
            size = os.path.getsize(LEDGER_PATH)
        except Exception:  # noqa: BLE001
            size = -1
    return {
        "path": LEDGER_PATH,
        "exists": exists,
        "size_bytes": size,
        "epoch": EPOCH_ID,
        "epoch_written": _epoch_written,
        "writes_this_process": _writes,
        # 降级留痕:写失败过就得说出来,否则读账的人会把不全的账当成全的。
        "write_failures": _write_failures,
        "retention_days": RETENTION_DAYS,
        "empty_means": (
            "读到空**不等于**这段什么都没发生 —— 账本不在、或这段落在进程不在的"
            "时间里,同样是空。要分开这两件事看记录上的 epoch。"
        ),
        "known_blind_spot": (
            "启动了却一次都没转移过的进程不留痕,那段会被算成不可知而不是安静。" "这是刻意选的偏向:宁可说不知道。"
        ),
    }


def reset_for_tests(path: Optional[str] = None) -> None:
    """仅供测试:换一个落盘位置并清空进程内计数。"""
    global LEDGER_PATH, _epoch_written, _write_failures, _writes
    with _lock:
        if path is not None:
            LEDGER_PATH = path
        _epoch_written = False
        _write_failures = 0
        _writes = 0
