"""core/tuning.py —— 「调数据方式」的那些参数：不上面板，智能体按人的话调。

为什么这些不该在面板上
----------------------
面板「全部设置」里原先有一百来行是数字与档位：回声消除的步长、双讲检测余量、熔断的失败次数、并发的目标延迟、
各种超时与窗口……它们**几乎都是某个自适应算法自己的常数**：回声消除是自适应滤波（时延自己估、滤波器自己收敛），
并发限额是 AIMD（按实测延迟与错误率自己涨跌），熔断自己试探恢复，选模型的打分吃的是实测表现。
默认值就是这些算法的出厂调校；没人该为「不知道调哪个」去一行行试。人真正会说的是**效果**：
「回声太大了」「它老抢我话」「别老主动开口」「这个超时太短了」。

所以这些键从面板撤下（仍登记在 ``CONFIG_SCHEMA``：``POST /api/config``、``.env``、环境变量照旧能用），
改由智能体在对话里按人的话调：两个工具 ``tuning__list`` / ``tuning__set``。

调参的边界（这是安全的一部分，不是实现细节）
------------------------------------------
* **只调白名单里的键**（本模块的 ``_NUMERIC`` / ``_CHOICES``），**每个键有硬范围**，越界不写。密钥、地址、路径、端口、
  安全类、模式类一个都不在里面 —— 它们不是「调参」，是配置与权限。
* **只在人发起的回合里调**（文字 / 语音 / 手表），后台自发的回合（环境注意力、心跳）连调都不行；
  一个回合最多改 ``MAX_CHANGES_PER_TURN`` 个，防止一段注入的文字让它连改一串。
* **会放大智能体自己自主度的方向要人点头**：自发开口 / 委托的额度调大、节拍调密、桌面操作步数调多
  （``expands``）—— 走设备接入已有的人在环（``agent_tools._ask``），与「模型只能请求、不能决定」同一条规矩；
  往收敛的方向调（少说话、少动手）不用问。
* **不碰会删数据的键**：上下文归档上限与保留天数、相位账保留天数、媒体库容量、运维记录条数 —— 调小就是自动删东西，
  只归人，留在面板上。
* **每次改动留痕**（``$GALAXY_DATA_DIR/tuning_log.jsonl`` + 日志 ``[AUDIT]``），**可一句话撤销**（``reset``：
  删掉覆盖，回到出厂默认 —— 也就是系统自己的自适应调校）。
* 写入走面板「保存设置」同一个函数（``core.routes.config.update_config``），不另写一条落盘路径。
  「改了要不要重启」如实说：读取点在导入时的键（``_AT_IMPORT``，由 ``tests/test_tuning_knobs.py`` 逐个核对）要重启；
  其余多数下一次用到就按新值，没把握的不说「已生效」。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Tuning")

MAX_CHANGES_PER_TURN = 5

LIST_TOOL = "tuning__list"
SET_TOOL = "tuning__set"


@dataclass(frozen=True)
class Knob:
    key: str
    topic: str
    lo: Optional[float] = None
    hi: Optional[float] = None
    kind: str = "f"  # "i" 整数 / "f" 小数 / "c" 档位（取值见 config_labels.OPTION_LABELS）
    #: 往哪个方向调会放大智能体自己的自主度（"up" / "down" / ""）—— 那个方向要人点头。
    expands: str = ""


# (键, 话题, 下限, 上限, 类型, 放大自主度的方向)。范围按「语义上还有意义」划，宽于出厂值几倍；
# 出厂值本身必须落在范围内（tests/test_tuning_knobs.py 核对）。
_NUMERIC: List[Tuple[str, str, float, float, str, str]] = [
    # 回声与打断 —— 回声消除（自适应滤波）与「别把自己的声音当成人说的」
    ("GALAXY_AEC_RES_OVER", "回声与打断", 0.5, 4.0, "f", ""),
    ("GALAXY_AEC_RES_FLOOR_DB", "回声与打断", -40, 0, "f", ""),
    ("GALAXY_AEC_RES_DT_FLOOR_DB", "回声与打断", -20, 0, "f", ""),
    ("GALAXY_AEC_DTD_HANGOVER", "回声与打断", 0, 50, "i", ""),
    ("GALAXY_AEC_TAIL_MS", "回声与打断", 32, 512, "f", ""),
    ("GALAXY_AEC_MU", "回声与打断", 0.05, 1.0, "f", ""),
    ("GALAXY_AEC_MAX_DELAY_MS", "回声与打断", 50, 1000, "f", ""),
    ("GALAXY_AEC_DTD_MARGIN_DB", "回声与打断", 0, 20, "f", ""),
    ("GALAXY_VOICE_DUCK_GAIN", "回声与打断", 0, 1, "f", ""),
    ("GALAXY_VOICE_ECHO_SIM", "回声与打断", 0.3, 0.95, "f", ""),
    ("GALAXY_VOICE_ECHO_TAIL_S", "回声与打断", 0, 30, "f", ""),
    ("GALAXY_VOICE_ECHO_MIN_CHARS", "回声与打断", 1, 20, "i", ""),
    ("GALAXY_VOICE_ECHO_MIN_BLOCK", "回声与打断", 1, 20, "i", ""),
    # 说话与节奏
    ("GALAXY_VOICE_HOLD_S", "说话与节奏", 5, 600, "f", ""),
    ("GALAXY_LOCKSTEP_CPS", "说话与节奏", 4, 40, "f", ""),
    ("GALAXY_LOCKSTEP_GRACE_S", "说话与节奏", 0.5, 10, "f", ""),
    ("GALAXY_LOCKSTEP_STALL_S", "说话与节奏", 2, 30, "f", ""),
    ("GALAXY_LOCKSTEP_DRAIN_S", "说话与节奏", 0, 5, "f", ""),
    ("GALAXY_MELO_SPEED", "说话与节奏", 0.5, 2, "f", ""),
    ("GALAXY_INDEXTTS_EMO_ALPHA", "说话与节奏", 0, 1, "f", ""),
    ("GALAXY_SPEAK_MAX_CHARS", "说话与节奏", 50, 5000, "i", ""),
    ("GALAXY_VOICE_DIAG_S", "说话与节奏", 5, 120, "f", ""),
    ("GALAXY_EDGE_TTS_TIMEOUT_S", "说话与节奏", 2, 60, "f", ""),
    # 自发在场 —— 它多久主动开口 / 委托一次。额度往大、节拍往密调，是放大它自己的自主度
    ("GALAXY_AMBIENT_INTERVAL_S", "自发在场", 0.5, 60, "f", "down"),
    ("GALAXY_AMBIENT_COOLDOWN_S", "自发在场", 0, 600, "f", "down"),
    ("GALAXY_AMBIENT_SPEAK_PER_HOUR", "自发在场", 0, 120, "i", "up"),
    ("GALAXY_AMBIENT_DELEGATE_PER_HOUR", "自发在场", 0, 60, "i", "up"),
    ("GALAXY_DESKTOP_PERCEPTION_TTL", "自发在场", 2, 120, "f", ""),
    ("GALAXY_PERCEPTION_KEYFRAMES", "自发在场", 1, 16, "i", ""),
    ("GALAXY_VIDEO_FPS_NATIVE", "自发在场", 0.5, 15, "f", ""),
    ("GALAXY_VIDEO_FPS_BRIDGE", "自发在场", 0.2, 10, "f", ""),
    ("GALAXY_DUPLEX_VIDEO_FPS", "自发在场", 0.2, 10, "f", ""),
    ("GALAXY_DUPLEX_VIDEO_JPEG_QUALITY", "自发在场", 30, 95, "i", ""),
    # 模型与规划 —— 选哪个模型、什么时候多模型协作、想几轮
    ("GALAXY_ROUTE_OBSERVED_WEIGHT", "模型与规划", 0, 3, "f", ""),
    ("GALAXY_ROUTE_LATENCY_WEIGHT", "模型与规划", 0, 3, "f", ""),
    ("GALAXY_ROUTE_TOKEN_WEIGHT", "模型与规划", 0, 3, "f", ""),
    ("GALAXY_CASCADE_FLOOR_MID", "模型与规划", 0, 1, "f", ""),
    ("GALAXY_CASCADE_FLOOR_HI", "模型与规划", 0, 1, "f", ""),
    ("GALAXY_MOA_COMPLEXITY", "模型与规划", 0, 1, "f", ""),
    ("GALAXY_MOA_PROPOSERS", "模型与规划", 2, 8, "i", ""),
    ("GALAXY_MOA_LAYERS", "模型与规划", 1, 4, "i", ""),
    ("GALAXY_CRITIC_MAX_ROUNDS", "模型与规划", 0, 6, "i", ""),
    ("GALAXY_PLANNER_MAX_REPLANS", "模型与规划", 0, 5, "i", ""),
    ("GALAXY_REHEARSAL_CANDIDATES", "模型与规划", 1, 5, "i", ""),
    ("GALAXY_REHEARSAL_COMPLEXITY_FLOOR", "模型与规划", 0, 1, "f", ""),
    ("GALAXY_OLLAMA_NUM_CTX", "模型与规划", 512, 262144, "i", ""),
    ("GALAXY_LLAMA_CTX", "模型与规划", 512, 262144, "i", ""),
    ("GALAXY_CU_MAX_STEPS", "模型与规划", 3, 60, "i", "up"),
    ("GALAXY_CU_SETTLE_S", "模型与规划", 0.2, 5, "f", ""),
    # 等待与超时
    ("GALAXY_CHAT_TIMEOUT_S", "等待与超时", 20, 600, "f", ""),
    ("GALAXY_LOCAL_GUI_VLM_TIMEOUT_S", "等待与超时", 10, 600, "f", ""),
    ("GALAXY_MODELS_PROBE_BUDGET", "等待与超时", 1, 30, "f", ""),
    ("GALAXY_MODELS_STATUS_TTL", "等待与超时", 0.5, 60, "f", ""),
    ("GALAXY_NATS_EXECUTOR_TIMEOUT", "等待与超时", 5, 300, "f", ""),
    ("GALAXY_MESH_DISCOVERY_TIMEOUT", "等待与超时", 0.5, 30, "f", ""),
    ("GALAXY_SIGNALING_TIMEOUT_S", "等待与超时", 5, 120, "f", ""),
    ("GALAXY_AUTO_DOCKER_DAEMON_WAIT", "等待与超时", 10, 600, "f", ""),
    ("GALAXY_AUTO_DOCKER_WAIT", "等待与超时", 10, 900, "f", ""),
    ("GALAXY_RUNTIME_PROMPT_TIMEOUT", "等待与超时", 5, 300, "f", ""),
    ("GALAXY_AUTO_PODMAN_API_WAIT", "等待与超时", 5, 300, "f", ""),
    # 并发与容错 —— 并发限额是 AIMD 自适应，熔断自己试探恢复；这里只是它们的常数
    ("GALAXY_AS_TARGET_LATENCY_MS", "并发与容错", 50, 20000, "f", ""),
    ("GALAXY_AS_ERROR_THRESHOLD", "并发与容错", 0.01, 0.9, "f", ""),
    ("GALAXY_AS_INIT_LIMIT", "并发与容错", 1, 500, "i", ""),
    ("GALAXY_AS_MAX_LIMIT", "并发与容错", 1, 1000, "i", ""),
    ("GALAXY_AS_MIN_LIMIT", "并发与容错", 1, 100, "i", ""),
    ("GALAXY_AS_SAMPLE_WINDOW", "并发与容错", 10, 2000, "i", ""),
    ("GALAXY_AS_PROBE_INTERVAL_S", "并发与容错", 1, 120, "f", ""),
    ("GALAXY_CB_FAILURE_THRESHOLD", "并发与容错", 1, 100, "i", ""),
    ("GALAXY_CB_RECOVERY_TIMEOUT_S", "并发与容错", 1, 600, "f", ""),
    ("GALAXY_CB_HALF_OPEN_PROBES", "并发与容错", 1, 20, "i", ""),
    ("GALAXY_CB_WINDOW_SIZE", "并发与容错", 3, 500, "i", ""),
    ("CMD_MAX_CONCURRENT", "并发与容错", 1, 500, "i", ""),
    ("CONCURRENCY_GLOBAL_MAX", "并发与容错", 1, 1000, "i", ""),
    ("GALAXY_ROUTER_MAX_QUEUE_DEPTH", "并发与容错", 10, 10000, "i", ""),
    # 心跳与监控
    ("GALAXY_HEARTBEAT_INTERVAL", "心跳与监控", 2, 120, "f", ""),
    ("FEDERATION_HEARTBEAT_INTERVAL", "心跳与监控", 5, 300, "f", ""),
    ("ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS", "心跳与监控", 10, 900, "f", ""),
    ("GALAXY_NODE_HEALTH_RETRIES", "心跳与监控", 2, 30, "i", ""),
    ("GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S", "心跳与监控", 5, 600, "f", ""),
    ("GALAXY_ONBOARDING_SCAN_INTERVAL_S", "心跳与监控", 10, 3600, "f", ""),
    ("GALAXY_ONBOARDING_CAN_LISTEN_S", "心跳与监控", 0.2, 10, "f", ""),
    ("GALAXY_TAILSCALE_CHECK_INTERVAL", "心跳与监控", 5, 600, "f", ""),
    ("GALAXY_PANEL_PUSH_MIN_INTERVAL", "心跳与监控", 0.2, 30, "f", ""),
    ("GALAXY_SLO_LATENCY_WINDOW", "心跳与监控", 50, 10000, "i", ""),
    ("GALAXY_SLO_HEARTBEAT_WINDOW", "心跳与监控", 20, 5000, "i", ""),
    ("GALAXY_TRANSPORT_BULK_BYTES", "心跳与监控", 4096, 1048576, "i", ""),
]

# 档位类的调参：取值就是 config_labels.OPTION_LABELS 里登记的那几档（它们本来就是 auto / 1 / 0 这种三态）。
_CHOICES: List[Tuple[str, str]] = [
    ("GALAXY_VOICE_EAGERNESS", "回声与打断"),
    ("GALAXY_VOICE_DUPLEX", "回声与打断"),
    ("GALAXY_TEXT_VOICE_LOCKSTEP", "说话与节奏"),
    ("GALAXY_SPECULATIVE_DRAFT", "模型与规划"),
    ("GALAXY_LIMINAL_REHEARSAL", "模型与规划"),
    ("GALAXY_COMPUTER_USE_STRATEGY", "模型与规划"),
    ("GALAXY_TOOLS_SLIM", "模型与规划"),
    ("GALAXY_TOOLS_STICKY", "模型与规划"),
    ("GALAXY_TOOLS_JIT", "模型与规划"),
]

#: 读取点在**导入时**的键 —— 改了要重启才生效。tests/test_tuning_knobs.py 逐个核对「确实是模块级读取」。
_AT_IMPORT: FrozenSet[str] = frozenset(
    {
        "ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS",
        "GALAXY_ROUTER_MAX_QUEUE_DEPTH",
        "GALAXY_MODELS_PROBE_BUDGET",
        "GALAXY_MODELS_STATUS_TTL",
        "GALAXY_AS_TARGET_LATENCY_MS",
        "GALAXY_AS_ERROR_THRESHOLD",
        "GALAXY_AS_INIT_LIMIT",
        "GALAXY_AS_MAX_LIMIT",
        "GALAXY_AS_MIN_LIMIT",
        "GALAXY_AS_SAMPLE_WINDOW",
        "GALAXY_AS_PROBE_INTERVAL_S",
        "GALAXY_CB_FAILURE_THRESHOLD",
        "GALAXY_CB_RECOVERY_TIMEOUT_S",
        "GALAXY_CB_HALF_OPEN_PROBES",
        "GALAXY_CB_WINDOW_SIZE",
        "GALAXY_VIDEO_FPS_NATIVE",
        "GALAXY_VIDEO_FPS_BRIDGE",
        "GALAXY_HEARTBEAT_INTERVAL",
    }
)

#: 彼此有大小关系的键：左边的不许大过右边的（按调完之后的有效值判）。
_ORDER: List[Tuple[str, str]] = [
    ("GALAXY_AS_MIN_LIMIT", "GALAXY_AS_INIT_LIMIT"),
    ("GALAXY_AS_INIT_LIMIT", "GALAXY_AS_MAX_LIMIT"),
    ("GALAXY_CASCADE_FLOOR_MID", "GALAXY_CASCADE_FLOOR_HI"),
]

KNOBS: Dict[str, Knob] = {
    **{k: Knob(k, topic, lo, hi, kind, expands) for k, topic, lo, hi, kind, expands in _NUMERIC},
    **{k: Knob(k, topic, kind="c") for k, topic in _CHOICES},
}

TOPICS: Tuple[str, ...] = tuple(dict.fromkeys(kb.topic for kb in KNOBS.values()))


def knob_keys() -> FrozenSet[str]:
    return frozenset(KNOBS)


def is_import_time(key: str) -> bool:
    return key in _AT_IMPORT


# ── 读 ───────────────────────────────────────────────────────────────────────────


def _schema(key: str) -> Dict[str, Any]:
    from core.routes.config_schema_registry import CONFIG_SCHEMA

    return CONFIG_SCHEMA[key]


def _fmt(kb: Knob, v: float) -> str:
    return str(int(round(v))) if kb.kind == "i" else ("%g" % v)


def choices_of(key: str) -> List[str]:
    from core.routes.config_labels import OPTION_LABELS

    return list(OPTION_LABELS.get(key, {}))


def current_value(key: str) -> str:
    """此刻生效的值（环境里有就是环境里的，没有就是登记的出厂值）；出厂值为空表示系统自己按本机情况定。"""
    return os.environ.get(key, _schema(key)["default"])


def describe(key: str) -> Dict[str, Any]:
    from core.routes.config_labels import OPTION_LABELS, hint_for, label_for

    kb = KNOBS[key]
    sch = _schema(key)
    value, default = current_value(key), sch["default"]
    row: Dict[str, Any] = {
        "key": key,
        "name": label_for(key),
        "topic": kb.topic,
        "meaning": hint_for(key, sch["description"]),
        "value": value if value != "" else "自动",
        "default": default if default != "" else "自动",
        "changed": key in os.environ and os.environ.get(key) != default,
    }
    if kb.kind == "c":
        row["choices"] = {v: n for v, n in OPTION_LABELS.get(key, {}).items()}
    else:
        row["range"] = [_fmt(kb, kb.lo or 0), _fmt(kb, kb.hi or 0)]
    if kb.expands:
        row["needs_user_ok_when"] = "调大" if kb.expands == "up" else "调小"
    return row


def list_for_agent(query: str = "") -> Dict[str, Any]:
    """没给话题：列话题与每个话题里有哪些；给了：列匹配的参数（名字 / 话题 / 说明 / 键名里含这段字）。"""
    q = (query or "").strip().lower()
    if not q:
        by: Dict[str, List[str]] = {}
        from core.routes.config_labels import label_for

        for kb in KNOBS.values():
            by.setdefault(kb.topic, []).append(label_for(kb.key))
        return {
            "topics": {t: names for t, names in by.items()},
            "next": "带上 query（话题名或关键词）再调一次，拿到具体参数、当前值和范围",
        }
    rows = []
    for key, kb in KNOBS.items():
        d = describe(key)
        hay = " ".join([d["name"], d["topic"], d["meaning"], key]).lower()
        if q in hay or q in kb.topic.lower():
            rows.append(d)
    return {"knobs": rows[:25], "truncated": len(rows) > 25}


# ── 写 ───────────────────────────────────────────────────────────────────────────


def _parse(kb: Knob, raw: Any) -> Tuple[Optional[str], Optional[str]]:
    """校验并规整成要写进环境的字符串。返回 (值, 错误)。"""
    if kb.kind == "c":
        v = str(raw).strip()
        ok = choices_of(kb.key)
        return (v, None) if v in ok else (None, f"可选的档位是 {ok}，不是 {v!r}")
    try:
        x = float(str(raw).strip())
    except ValueError:
        return None, f"需要一个数字，收到 {raw!r}"
    if x != x or x in (float("inf"), float("-inf")):
        return None, "不是有限的数字"
    if not (kb.lo <= x <= kb.hi):  # type: ignore[operator]
        return None, f"超出允许的范围 {_fmt(kb, kb.lo or 0)} ~ {_fmt(kb, kb.hi or 0)}（收到 {raw}）"
    if kb.kind == "i":
        x = round(x)
    return _fmt(kb, x), None


def _effective_number(key: str, override: Dict[str, str]) -> Optional[float]:
    raw = override.get(key, os.environ.get(key, _schema(key)["default"]))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _order_violation(key: str, new: str) -> Optional[str]:
    from core.routes.config_labels import label_for

    for lo_key, hi_key in _ORDER:
        if key not in (lo_key, hi_key):
            continue
        a, b = _effective_number(lo_key, {key: new}), _effective_number(hi_key, {key: new})
        if a is not None and b is not None and a > b:
            return f"「{label_for(lo_key)}」不能大过「{label_for(hi_key)}」（调完是 {a:g} > {b:g}）"
    return None


def _moves_toward_more_autonomy(kb: Knob, old: Optional[float], new: float) -> bool:
    if not kb.expands or old is None:
        return False
    return new > old if kb.expands == "up" else new < old


def _audit(**fields: Any) -> None:
    fields["ts"] = round(time.time(), 3)
    logger.info("[AUDIT] 调参 | %s", json.dumps(fields, ensure_ascii=False))
    try:
        from core.data_paths import data_path

        with open(data_path("tuning_log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fields, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — 留痕写不进文件，日志里那一行仍在
        logger.debug("调参留痕写文件失败: %s", exc)


_changes_this_turn: Dict[str, int] = {}


def _count_turn(turn_id: str) -> int:
    if len(_changes_this_turn) > 256:
        _changes_this_turn.clear()
    _changes_this_turn[turn_id] = _changes_this_turn.get(turn_id, 0) + 1
    return _changes_this_turn[turn_id]


def _after_note(key: str) -> str:
    from core.routes.config_restart import restart_reason

    if is_import_time(key) or restart_reason(key):
        return "要重启一次才生效（它在启动时才读）；我不会替你重启"
    return "多数在下一次用到时就按新值；如果没看到变化，重启一次"


async def apply(key: str, value: Optional[str], *, reason: str = "", session_id: str = "") -> Dict[str, Any]:
    """调一个参数；``value=None`` 表示撤销（回到出厂默认）。返回的 ``tell_user`` 是该原样告诉人的话。"""
    from core.device_onboarding.conversation import HUMAN_REQUEST_SOURCES, _current_turn
    from core.routes.config_labels import OPTION_LABELS, label_for

    kb = KNOBS.get(key)
    if kb is None:
        return {"success": False, "error": f"{key} 不在可调的参数里（密钥、地址、路径、端口、安全与模式类不能这样调）"}

    turn_id, source, _text = _current_turn()
    if not turn_id or source not in HUMAN_REQUEST_SOURCES:
        return {"success": False, "error": "只有用户自己发起的对话里才能调参（这是后台自发的回合，没有人在要求）"}
    if _count_turn(turn_id) > MAX_CHANGES_PER_TURN:
        return {
            "success": False,
            "error": f"一个回合最多改 {MAX_CHANGES_PER_TURN} 个参数；先把这几个的效果告诉用户，等他再说",
        }

    name, old = label_for(key), current_value(key)
    default = _schema(key)["default"]

    if value is None:  # 撤销
        new = default
    else:
        parsed, err = _parse(kb, value)
        if err:
            return {"success": False, "error": f"「{name}」{err}"}
        new = str(parsed)
        bad = _order_violation(key, new)
        if bad:
            return {"success": False, "error": bad}
        if new != old and kb.kind != "c":
            try:
                if _moves_toward_more_autonomy(kb, float(old), float(new)):
                    from core.device_onboarding.agent_tools import _ask

                    what = f"把「{name}」从 {old} 调到 {new}（这会让我更主动 / 动手更多）"
                    stop = await _ask(what, session_id)
                    if stop:  # 还没点头：把要问的话交回给智能体，让它原样问人
                        return {"success": False, **stop, "error": stop.get("error") or stop.get("ask_user", "")}
            except ValueError:
                pass  # 旧值是「自动」（空）：没有可比的数，按不放大处理

    if new == old and (value is not None or key not in os.environ):
        return {"success": True, "unchanged": True, "tell_user": f"「{name}」本来就是 {old}，没动。"}

    await _write(key, new, default)
    shown = (OPTION_LABELS.get(key, {}).get(new) if kb.kind == "c" else None) or (new or "自动")
    _audit(key=key, old=old, new=new, reset=value is None, reason=(reason or "")[:200], turn=turn_id, source=source)
    verb = "已恢复成出厂调校（系统自己适应）" if value is None else f"已从 {old or '自动'} 调到 {shown}"
    tell = f"「{name}」{verb}。{_after_note(key)}。想撤销随时说，我会恢复默认。"
    return {"success": True, "key": key, "old": old, "new": new, "tell_user": tell, "result": tell}


async def _write(key: str, new: str, default: str) -> None:
    """写入走面板「保存设置」同一个函数；回到出厂值时是**删掉覆盖**，不是把默认值钉进 .env。"""
    from core.routes import config as _cfg

    if new == default:
        os.environ.pop(key, None)
        _cfg._write_env_file_with(None)  # 没覆盖了：落盘时这个键不再出现（见 config._write_env_file_with）
        return
    await _cfg.update_config(_cfg.ConfigUpdateRequest(config={key: new}))


# ── 给智能体的两个工具 ───────────────────────────────────────────────────────────


def _fn(name: str, desc: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


TUNING_BUILTIN_TOOLS: List[Dict[str, Any]] = [
    _fn(
        LIST_TOOL,
        "The system's behaviour tuning knobs (echo cancellation and interruption, speech pace, how often it speaks up "
        "by itself, timeouts, concurrency, model/planning) are NOT in the settings panel; you adjust them when the "
        "user asks. Call with no query to see topics; with a query (topic or words like 回声/打断/超时/主动) to get the "
        "matching knobs with current value, default and allowed range.",
        {"query": {"type": "string"}},
        [],
    ),
    _fn(
        SET_TOOL,
        "Adjust one tuning knob because the user asked for a change in behaviour (or complained about it). Use "
        "tuning__list first to find the right knob. Make the smallest change that addresses it (usually within 2x of "
        "the default), one knob at a time. Only call from a turn the user started. Values outside the allowed range "
        "are refused. If it needs the user's OK you get a question back: ask it and stop. Afterwards tell the user "
        "exactly what changed (old -> new), whether a restart is needed, and that they can ask you to undo it "
        "(reset=true restores the factory tuning, which is the system's own adaptive default).",
        {
            "key": {"type": "string", "description": "knob key from tuning__list"},
            "value": {"type": "string", "description": "new value (a number, or one of the listed choices)"},
            "reset": {"type": "boolean", "description": "true = undo, back to the factory tuning"},
            "reason": {"type": "string", "description": "what the user said / why"},
        },
        ["key"],
    ),
]


def tuning_tools_for_agent() -> List[Dict[str, Any]]:
    return list(TUNING_BUILTIN_TOOLS)


async def dispatch_tuning_tool(action: str, arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    args = dict(arguments or {})
    try:
        if action == "list":
            return {"success": True, **list_for_agent(str(args.get("query") or ""))}
        if action == "set":
            key = str(args.get("key") or "").strip()
            if args.get("reset"):
                return await apply(key, None, reason=str(args.get("reason") or ""), session_id=session_id)
            if "value" not in args or args.get("value") in (None, ""):
                return {"success": False, "error": "需要 value（或 reset=true）"}
            return await apply(key, str(args["value"]), reason=str(args.get("reason") or ""), session_id=session_id)
    except Exception as exc:  # noqa: BLE001 — 失败作为结果回给智能体，不炸对话
        logger.warning("tuning__%s 失败: %s", action, exc)
        return {"success": False, "error": str(exc)}
    return {"success": False, "error": f"未知的调参工具: tuning__{action}"}
