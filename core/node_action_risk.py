"""core/node_action_risk.py —— 节点上每个动作有多危险、模型调它之前要不要先问人(第 10 轮)。

为什么要有它
============
节点开放给模型(``core/node_tools.py`` 的 ``nodes__invoke``)之前,只有声明了动作白名单的 9 个节点过节点拨盘门
(``core/autonomy_policy.py``),其余 116 个节点上的动作 —— 跑命令、删文件、发邮件、推代码、起飞无人机 ——
调了就执行。所有者的决定(2026-11-01):**节点可以开放给模型,高权限、高危险的动作要交给人确认,跟之前那些一样。**

这里给 125 个节点上的每个动作一个档(与工具门 ``core.tool_permissions.ToolRiskLevel`` 同一套四档):

* ``critical`` 极危险 —— 跑代码 / 命令 / 脚本、装卸东西、起插件或进程、代别的节点或设备执行(编排、代理)、
  读出密钥或环境变量、让无人机解锁起飞、给打印机下 G-code;
* ``dangerous`` 危险 —— 删除 / 清空 / 重置 / 恢复、往外发(消息、邮件、PR、推送、上传、通知、广播)、
  操控设备(点击、输入、按键、点触、开关家电、开始打印)、开摄像头 / 录音、改账号与口令、改系统配置、扫描网络;
* ``moderate`` 会改东西 —— 其余会建、存、写、登记的;
* ``safe`` 只读 / 只算。

要不要问人(:func:`needs_human`):``critical`` 与 ``dangerous`` **总要问**(不看自治档位 —— 所有者明确要的);
``moderate`` 只在「谨慎」档(``GALAXY_AUTONOMY=safe``)问;``safe`` 不问。问人只经 :mod:`core.approval_gate`
一个口:电脑发起的在电脑面板上批,手机 / 手表发起的在那台设备上批;批一次记「同一个动作 + 同一个对象」到这段对话结束。

怎么判(只认确定的,判不准就往高处判)
==================================
一个动作的档 = 下面几条里最高的那一条:

1. 只读还是会改:HTTP ``GET``,或名字里有读 / 算的词(``list`` / ``search`` / ``analyze`` …)而没有改东西的词
   (``create`` / ``register`` / ``add`` …)→ ``safe``,否则 ``moderate``;
2. 名字里的词(动作名与处理函数名按下划线拆开):``execute`` / ``shell`` / ``install`` / ``proxy`` … → ``critical``;
   ``delete`` / ``send`` / ``push`` / ``upload`` / ``reset`` … → ``dangerous``;
3. 节点的类别(只对会改东西的动作):跑代码的节点 → ``critical``;操控设备、往外发、管密钥与账号、改系统配置的节点 → ``dangerous``;
4. 逐个点名的(:data:`_NAMED`):读出密钥原文、读环境变量、GET 也会开 PR 的、摄像头取帧 ……
5. 看参数的(:data:`_METHOD_PARAM_NODES`):通用 HTTP 请求节点,``method`` 不是 GET / HEAD 就是往别人那边写 → ``dangerous``。

纯函数,不做 I/O;给一个动作打档不需要把节点载进来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

SAFE = "safe"
MODERATE = "moderate"
DANGEROUS = "dangerous"
CRITICAL = "critical"

_ORDER = {SAFE: 0, MODERATE: 1, DANGEROUS: 2, CRITICAL: 3}
LEVELS: Tuple[str, ...] = (SAFE, MODERATE, DANGEROUS, CRITICAL)

#: 给人看的档名
LEVEL_TEXT = {SAFE: "只读", MODERATE: "会改东西", DANGEROUS: "危险", CRITICAL: "极危险"}


@dataclass(frozen=True)
class Grade:
    level: str
    why: str

    def at_least(self, other: "Grade") -> "Grade":
        return other if _ORDER[other.level] > _ORDER[self.level] else self

    def to_dict(self) -> Dict[str, str]:
        return {"risk": self.level, "risk_text": LEVEL_TEXT[self.level], "risk_why": self.why}


def higher(a: str, b: str) -> str:
    return a if _ORDER[a] >= _ORDER[b] else b


# ── 读 / 算的词 ────────────────────────────────────────────────────────────────
#: 名字里有这些词、又没有下面「会改东西」的词,就是只读 / 只算。宁少勿多:判不准的按「会改东西」。
_READ_WORDS: FrozenSet[str] = frozenset(
    {
        "get", "list", "read", "search", "find", "info", "show", "describe", "detect", "analyze", "analyse",
        "classify", "ocr", "recognize", "transcribe", "translate", "summarize", "parse", "understand",
        "compute", "calc", "calculate", "solve", "simplify", "verify", "check", "evaluate", "infer", "predict",
        "reason", "recall", "retrieve", "similarity", "rank", "embed", "interpret", "compare", "comprehend",
        "perceive", "assess", "ask", "qa", "chat", "completions", "suggest", "scrape", "fetch", "ping",
        "status", "stats", "health", "help", "screenshot", "locate", "devices", "packages", "position",
        "size", "query", "diff", "trend", "wait", "distance", "midpoint", "area", "centroid", "hash",
        "decompose", "plan", "estimate", "keywords", "recommend", "dialog", "debate", "states", "discover",
        "which", "cwd",
    }
)  # fmt: skip
#: 这些词一出现就不是只读(``register_device`` 里的 devices、``add_plan`` 里的 plan 不让它变成「只读」)。
_WRITE_WORDS: FrozenSet[str] = frozenset(
    {
        "create", "add", "set", "update", "save", "store", "record", "register", "write", "append", "insert",
        "upsert", "put", "post", "edit", "modify", "change", "rename", "move", "copy", "start", "stop", "pause",
        "resume", "cancel", "retry", "enable", "disable", "load", "unload", "reload", "import", "apply", "commit",
        "merge", "checkout", "clone", "pull", "init", "mkdir", "compress", "archive", "ingest", "emit", "report",
        "acknowledge", "train", "configure", "connect", "disconnect", "schedule", "submit", "assign", "dispatch",
        "trigger", "control", "define", "run", "stash", "switch", "snapshot", "cleanup", "backup", "vacuum",
        "heartbeat", "acquire", "release", "silence", "resolve", "generate", "render", "synthesize", "convert",
        "fix", "launch",
    }
)  # fmt: skip

# ── 名字里的词 ────────────────────────────────────────────────────────────────
_CRITICAL_WORDS: Dict[str, str] = {
    "execute": "执行代码、命令或别人的动作",
    "exec": "执行代码或命令",
    "shell": "跑系统命令",
    "script": "跑脚本",
    "install": "安装软件",
    "uninstall": "卸载软件",
    "sudo": "提权",
    "proxy": "代别的服务转发请求",
    "gcode": "直接给打印机下 G-code",
    "takeoff": "让飞行器起飞",
}
_DANGEROUS_WORDS: Dict[str, str] = {
    "delete": "删除",
    "remove": "删除",
    "unregister": "注销",
    "deregister": "注销",
    "destroy": "销毁",
    "drop": "删除",
    "purge": "清除",
    "wipe": "清空",
    "truncate": "清空",
    "clear": "清空",
    "reset": "重置",
    "restore": "用旧数据覆盖现在的",
    "rollback": "回滚",
    "kill": "结束进程",
    "send": "往外发",
    "push": "推送出去",
    "publish": "发布出去",
    "notify": "发通知",
    "broadcast": "广播给一组设备",
    "webhook": "往外发",
    "upload": "上传出去",
    "login": "用账号登录",
    "logout": "注销登录",
    "password": "改口令",
    "rotate": "轮换密钥",
    "recover": "对节点或故障做恢复动作",
}

# ── 节点的类别:会改东西的动作至少是这一档 ───────────────────────────────────────
_EXEC = (CRITICAL, "这个节点的写动作就是跑代码 / 命令 / 插件")
_DEVICE = (DANGEROUS, "这个节点会操控真实的设备")
_OUTWARD = (DANGEROUS, "这个节点会往外发(别人看得见、收不回来)")
_SECRETS = (DANGEROUS, "这个节点管密钥与账号")
_SYSTEM = (DANGEROUS, "这个节点改系统的配置与运行状态")
_DELEGATE = (DANGEROUS, "这个节点会替你调别的节点或设备(绕过它们各自的门)")

_CLASS_FLOOR: Dict[int, Tuple[str, str]] = {
    # 跑代码 / 命令 / 插件
    **{n: _EXEC for n in (9, 28, 29, 30, 31, 32, 35, 39, 115, 116, 117, 118, 122, 130)},
    # 操控真实设备(手机、电脑键鼠、家电、无人机、打印机、NFC、摄像头、麦克风)
    **{n: _DEVICE for n in (27, 33, 34, 36, 43, 44, 45, 46, 47, 49, 92, 95, 113, 124, 127)},
    # 往外发:聊天、邮件、代码托管、笔记、日历、Git、消息路由
    **{n: _OUTWARD for n in (7, 10, 11, 16, 21, 26, 96, 106, 123)},
    # 密钥与账号
    **{n: _SECRETS for n in (3, 5)},
    # 系统配置与运行状态
    **{n: _SYSTEM for n in (0, 66, 67, 82)},
    # 编排 / 派发:替你调别的节点或设备
    **{n: _DELEGATE for n in (71, 77, 81, 88, 89, 107, 110)},
}

# ── 逐个点名(节点编号, 动作名或处理函数名) ─────────────────────────────────────────
_NAMED: Dict[Tuple[int, str], Tuple[str, str]] = {
    (3, "get_secret"): (CRITICAL, "读出密钥原文"),
    (3, "decrypt_value"): (DANGEROUS, "把加密的内容解成明文"),
    (122, "get_env"): (CRITICAL, "读出环境变量(里面有各家的 API Key)"),
    (122, "get_environment"): (CRITICAL, "读出环境变量(里面有各家的 API Key)"),
    (122, "env"): (CRITICAL, "读出环境变量(里面有各家的 API Key)"),
    (43, "arm"): (CRITICAL, "让飞行器解锁电机"),
    (106, "workflow_issue_to_pr"): (DANGEROUS, "从 issue 直接开 PR(GET 也会改仓库)"),
    (106, "issue_to_pr"): (DANGEROUS, "从 issue 直接开 PR(GET 也会改仓库)"),
    (46, "get_stream_frame"): (DANGEROUS, "从摄像头取画面"),
    (46, "frame"): (DANGEROUS, "从摄像头取画面"),
    (95, "get_latest_frame"): (DANGEROUS, "取手机传来的摄像头画面"),
    (95, "stream_mjpeg"): (DANGEROUS, "取手机传来的摄像头画面"),
    (82, "scan_ports"): (DANGEROUS, "扫描网络上别的机器的端口"),
    (82, "scan"): (DANGEROUS, "扫描网络上别的机器的端口"),
    (34, "install_apk"): (CRITICAL, "往手机上装应用"),
    (107, "call"): (CRITICAL, "让模型挑一个登记过的工具并执行它"),
    (77, "job_run_now"): (CRITICAL, "立刻跑一个定时任务(任务里写的是什么就做什么)"),
    (77, "job_create"): (CRITICAL, "定一个以后自己跑的任务(任务里写的是什么就做什么)"),
    (77, "job_update"): (CRITICAL, "改一个以后自己跑的任务"),
    (110, "submit_task"): (CRITICAL, "把任务交给编排器去调别的节点"),
    (71, "assign_task"): (CRITICAL, "把任务派到设备上执行"),
    (71, "coordinate"): (CRITICAL, "协调多台设备执行"),
    (71, "broadcast_to_group"): (CRITICAL, "把同一个动作发给一组设备执行"),
    (121, "http_post"): (DANGEROUS, "向外部服务发 POST(会改别人那边的东西)"),
    (121, "post"): (DANGEROUS, "向外部服务发 POST(会改别人那边的东西)"),
}

#: 通用 HTTP 请求节点:``method`` 不是这些就是往别人那边写
_SAFE_HTTP = frozenset({"GET", "HEAD", "OPTIONS"})
_METHOD_PARAM_NODES: FrozenSet[int] = frozenset({8, 121})
_HTTP_WRITE = (DANGEROUS, "向外部服务发会改东西的 HTTP 请求(method 不是 GET/HEAD)")

_NODE_NUM = re.compile(r"^(?:Node_)?(\d+)(?:_|$)")


def node_number(node_id: str) -> Optional[int]:
    m = _NODE_NUM.match((node_id or "").strip())
    return int(m.group(1)) if m else None


def _words(*names: str) -> FrozenSet[str]:
    out = set()
    for name in names:
        for w in re.split(r"[_\-\s/.]+", str(name or "").lower()):
            if w:
                out.add(w)
    return frozenset(out)


def _first(words: Iterable[str], table: Mapping[str, str]) -> Optional[str]:
    for w in sorted(words):
        if w in table:
            return w
    return None


def _is_read(method: str, words: FrozenSet[str]) -> bool:
    if (method or "").upper() == "GET":
        return True
    return bool(words & _READ_WORDS) and not (words & _WRITE_WORDS)


def _http_methods(params: Optional[Mapping[str, Any]]) -> Iterable[str]:
    if not isinstance(params, Mapping):
        return []
    found = []
    if params.get("method") is not None:
        found.append(str(params.get("method")))
    for key in ("requests", "items", "batch"):
        seq = params.get(key)
        if isinstance(seq, list):
            found.extend(str(r.get("method") or "GET") for r in seq if isinstance(r, Mapping))
    return found


def grade(
    node_id: str,
    action: str,
    *,
    method: str = "",
    handler: str = "",
    params: Optional[Mapping[str, Any]] = None,
) -> Grade:
    """这个节点上的这个动作是哪一档、为什么。``method`` 是 HTTP 方法(节点自己的入口动作没有,给空串)。"""
    num = node_number(node_id)
    words = _words(action, handler)
    read = _is_read(method, words)
    hits = []

    critical = _first(words, _CRITICAL_WORDS)
    if critical:
        hits.append(Grade(CRITICAL, _CRITICAL_WORDS[critical]))
    dangerous = _first(words, _DANGEROUS_WORDS)
    if dangerous:
        hits.append(Grade(DANGEROUS, _DANGEROUS_WORDS[dangerous]))
        read = False
    if critical:
        read = False

    out = Grade(SAFE, "只读 / 只算") if read else Grade(MODERATE, "会改东西")
    if num is not None and not read and num in _CLASS_FLOOR:
        out = out.at_least(Grade(*_CLASS_FLOOR[num]))
    for name in {str(action or "").strip().lower(), str(handler or "").strip().lower()} - {""}:
        named = _NAMED.get((num, name)) if num is not None else None
        if named:
            out = out.at_least(Grade(*named))
    if num in _METHOD_PARAM_NODES and any(m.strip().upper() not in _SAFE_HTTP for m in _http_methods(params)):
        out = out.at_least(Grade(*_HTTP_WRITE))
    for hit in hits:
        out = out.at_least(hit)
    return out


def needs_human(level: str, dial: str) -> bool:
    """这一档在这个自治档位下要不要先问人。危险与极危险总要问 —— 所有者的决定,不看档位。"""
    if level in (CRITICAL, DANGEROUS):
        return True
    if level == MODERATE:
        return str(dial or "").strip().lower() == "safe"
    return False


def current_dial() -> str:
    try:
        from core.autonomy_policy import autonomy_level

        return autonomy_level().value
    except Exception:  # noqa: BLE001 — 读不到档位按「引导」(默认档)
        return "guided"


__all__ = [
    "CRITICAL",
    "DANGEROUS",
    "Grade",
    "LEVELS",
    "LEVEL_TEXT",
    "MODERATE",
    "SAFE",
    "current_dial",
    "grade",
    "higher",
    "needs_human",
    "node_number",
]
