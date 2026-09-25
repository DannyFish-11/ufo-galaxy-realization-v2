"""core/engineering_verification.py — 验证由 harness 跑，结果由 harness 读。

这个模块是 engineer 循环的**验证器**：它把一条验证命令真的跑一遍，把退出码与
stdout/stderr 原文落盘，然后交回一份**观测**（:class:`VerificationObservation`）。

它**不下裁决**。观测到裁决的那一步由权威边界做：
:mod:`core.self_improvement` 把观测翻译成证据状态，交给
:func:`core.execution_evidence_model.classify_execution_evidence` 定级，只有
``trusted`` 才算验证通过。两者分开是整个设计的枢纽 —— score 是被观测出来的数，
verdict 是只能由权威边界产生的判断，提案者两个都不能写。

为什么要有它
============
此前 ``engineer__validate`` 只登记模型报上来的 ``passed``（默认 true），验证本身
「用别的工具跑，拿到结果再如实登记」。模型可以不跑、可以跑错、可以报错，登记处
一律照收，然后以 ``validated`` 标签写进知识库。见 :mod:`core.verdict_independence`。

只跑白名单里的验证器
====================
模型可以**提议**跑哪条验证，但 harness 只执行认得的验证程序（见
:data:`RECOGNIZED_VERIFIERS`）。两个理由：

* **安全**：这是一个替模型执行命令的入口。执行任意程序应当走终端工具与它的权限链，
  不该从「跑一下验证」这扇侧门进来。
* **可信**：``true`` / ``echo ok`` 也会退出 0。只有认得的验证器，它的退出码才承载
  「检查过了」这层意思。

会改动验证器自身状态的参数一律拒绝（``--update-baseline`` 之类）：一次「验证」顺手
把守卫的基线改宽了，就是提案者在改判卷标准（规格 G6）。

观测 → 证据状态
===============
============================  ===========================  ===================
观测                          证据状态                     经执法函数后
============================  ===========================  ===================
命令被拒 / 没能启动           ``planned_not_started``      quarantine
超时                          ``interrupted``              provisional
退出码非 0                    ``failed``                   provisional
pytest 退出码 5（没收集到）   ``completed_degraded``       quarantine
退出码 0，但原文没落下盘      ``locally_executed``，链不全  provisional
退出码 0，认得的验证器，已落盘 ``locally_executed``，链完整  **trusted**
============================  ===========================  ===================

pytest 的 5 单列：``-k 不存在的名字`` 能让它「成功地什么都没测」。一次什么都没测的
验证不是通过。
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from core.execution_evidence_model import ExecutionEvidenceState

logger = logging.getLogger("Galaxy.EngineeringVerification")

REPO_ROOT = Path(__file__).resolve().parent.parent

ENGINEERING_VERIFICATION_IS_OBSERVATION_ONLY: str = (
    "ENGINEERING_VERIFICATION::OBSERVES_NEVER_ADJUDICATES: "
    "core/engineering_verification.py runs a recognised verification command, "
    "archives its raw output and returns a VerificationObservation (exit code, "
    "archive reference, timing).  It never decides whether a patch passed; that "
    "verdict is produced only by classify_execution_evidence() at the authority "
    "boundary in core.self_improvement."
)

#: 单次验证的默认超时（秒）。可用 ``GALAXY_ENGINEERING_VERIFY_TIMEOUT_S`` 覆盖。
DEFAULT_TIMEOUT_S: float = 600.0

#: 每条流落盘时保留的字符数：头 + 尾。失败摘要通常在尾部。
_KEEP_HEAD_CHARS = 4_000
_KEEP_TAIL_CHARS = 48_000

#: 认得的验证器。键是规范化之后 argv 的前缀（``python`` 已替换为模块调用形式），
#: 值是这一类验证器**必须**带的参数之一（空元组 = 无要求）。
RECOGNIZED_VERIFIERS: Dict[Tuple[str, ...], Tuple[str, ...]] = {
    ("-m", "pytest"): (),
    ("-m", "flake8"): (),
    ("-m", "mypy"): (),
    ("-m", "black"): ("--check",),
    ("-m", "isort"): ("--check-only", "--check", "-c"),
    ("node", "--test"): (),
    ("npm", "test"): (),
    ("npm", "run", "test"): (),
}

#: 仓库自带的守卫脚本：``python scripts/check_*.py``。
_REPO_GUARD_PREFIX = "scripts/check_"

#: 会改动验证器自身状态的参数。出现即拒。
FORBIDDEN_VERIFIER_FLAGS: frozenset = frozenset(
    {
        "--update-baseline",
        "--fix",
        "--write",
        "--snapshot-update",
        "--update-snapshots",
        "--inplace",
        "--in-place",
    }
)

#: 可以不带 ``python -m`` 直接写的工具名，规范化成模块调用。
_BARE_PYTHON_TOOLS = ("pytest", "flake8", "mypy", "black", "isort")
_PYTHON_ALIASES = ("python", "python3", "py")

#: pytest 的「一条用例都没收集到」。
_PYTEST_NO_TESTS_COLLECTED = 5


@dataclass(frozen=True)
class VerificationObservation:
    """harness 实跑一次验证观测到的事实 —— 规格里的 **score**。不含任何判断。

    Attributes:
        command:             规范化之后实际执行（或拒绝执行）的 argv。
        requested:           模型/调用方原样提出的命令文本。
        recognized_verifier: 是否在白名单内。
        executed:            是否真的启动了子进程。
        exit_code:           子进程退出码；没跑起来为 ``None``。
        timed_out:           是否超时被终止。
        duration_s:          墙钟耗时。
        evidence_ref:        原文归档引用（``context_archive:<会话>#<段号>``）；空串 = 没落盘。
        rejection:           被拒或没能启动的原因；正常执行为空串。
        started_at:          开始时间（epoch 秒）。
    """

    command: Tuple[str, ...]
    requested: str
    recognized_verifier: bool
    executed: bool
    exit_code: Optional[int]
    timed_out: bool
    duration_s: float
    evidence_ref: str
    rejection: str = ""
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["command"] = list(self.command)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationObservation":
        return cls(
            command=tuple(data.get("command") or ()),
            requested=str(data.get("requested", "")),
            recognized_verifier=bool(data.get("recognized_verifier", False)),
            executed=bool(data.get("executed", False)),
            exit_code=data.get("exit_code"),
            timed_out=bool(data.get("timed_out", False)),
            duration_s=float(data.get("duration_s", 0.0)),
            evidence_ref=str(data.get("evidence_ref", "")),
            rejection=str(data.get("rejection", "")),
            started_at=float(data.get("started_at", 0.0)),
        )


# ---------------------------------------------------------------------------
# 命令规范化与白名单
# ---------------------------------------------------------------------------


def _split(command: Union[str, Sequence[str]]) -> Tuple[str, ...]:
    if isinstance(command, str):
        return tuple(shlex.split(command))
    return tuple(str(part) for part in command)


def normalize_verification_command(
    command: Union[str, Sequence[str], None],
) -> Tuple[Optional[Tuple[str, ...]], str]:
    """把一条验证命令规范化成可执行的 argv，或者说明为什么拒绝。

    Returns:
        ``(argv, "")`` —— 认得、可以跑；``(None, 原因)`` —— 拒绝。
        argv 第一个元素是实际要执行的程序（Python 工具统一换成 ``sys.executable``）。
    """
    if command is None or (isinstance(command, str) and not command.strip()):
        return None, "没有给出验证命令 —— 什么都没验证"
    try:
        parts = _split(command)
    except ValueError as exc:
        return None, f"命令解析失败：{exc}"
    if not parts:
        return None, "没有给出验证命令 —— 什么都没验证"

    forbidden = sorted(FORBIDDEN_VERIFIER_FLAGS.intersection(p.split("=", 1)[0] for p in parts))
    if forbidden:
        return None, f"验证命令带了会改动验证器自身的参数 {forbidden} —— 提案者不得改判卷标准"

    head = Path(parts[0]).name
    if head in _BARE_PYTHON_TOOLS:
        tail: Tuple[str, ...] = ("-m", head) + parts[1:]
        program = sys.executable
    elif head in _PYTHON_ALIASES or parts[0] == sys.executable:
        tail = parts[1:]
        program = sys.executable
    else:
        tail = parts
        program = ""

    if program and len(tail) >= 1 and tail[0].replace("\\", "/").startswith(_REPO_GUARD_PREFIX):
        script = (REPO_ROOT / tail[0]).resolve()
        guard_root = (REPO_ROOT / "scripts").resolve()
        if script.parent != guard_root or not script.is_file():
            return None, f"守卫脚本不存在或不在 scripts/ 下：{tail[0]}"
        return (program, str(script)) + tail[1:], ""

    for prefix, required in RECOGNIZED_VERIFIERS.items():
        # Python 模块型（-m xxx）只在解释器调用下匹配，原生程序型只在非解释器调用下匹配。
        if (prefix[0] == "-m") != bool(program):
            continue
        candidate = tail if program else parts
        if tuple(candidate[: len(prefix)]) != prefix:
            continue
        if required and not any(flag in candidate for flag in required):
            return None, f"{' '.join(prefix)} 必须带 {required[0]}（只检查，不改写）"
        return ((program,) + tail) if program else parts, ""

    return None, (
        f"不是认得的验证器：{parts[0]!r}。harness 只执行 pytest / 仓库守卫脚本 / "
        "flake8 / mypy / black --check / isort --check-only / node --test / npm test；"
        "其它命令请用终端工具跑，但它的结果不能作为验证证据登记。"
    )


# ---------------------------------------------------------------------------
# 执行与归档
# ---------------------------------------------------------------------------


def _timeout_s(explicit: Optional[float]) -> float:
    if explicit is not None and explicit > 0:
        return float(explicit)
    raw = os.environ.get("GALAXY_ENGINEERING_VERIFY_TIMEOUT_S", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        value = DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def _clip(text: str) -> Dict[str, Any]:
    if len(text) <= _KEEP_HEAD_CHARS + _KEEP_TAIL_CHARS:
        return {"text": text, "total_chars": len(text), "clipped": False}
    return {
        "text": text[:_KEEP_HEAD_CHARS] + "\n…[中间省略]…\n" + text[-_KEEP_TAIL_CHARS:],
        "total_chars": len(text),
        "clipped": True,
    }


def _archive(proposal_id: str, record: Dict[str, Any]) -> str:
    """原文落盘，返回证据引用；落不下来返回空串 —— 调用方据此判定证据链不全。"""
    try:
        from core.context_archive import archive_segment

        session = f"engineering-verification:{proposal_id or 'anonymous'}"
        summary = f"exit={record.get('exit_code')} {' '.join(record.get('command') or [])}"[:300]
        message = {
            "role": "tool",
            "name": "engineering_verification",
            "content": json.dumps(record, ensure_ascii=False),
        }
        seg = archive_segment(session, [message], summary)
    except Exception as exc:  # noqa: BLE001 — 落盘失败只让证据链不全，不中断验证
        logger.warning("验证原文落盘失败，本次观测不可作为可信证据：%s", exc)
        return ""
    return f"context_archive:{session}#{seg}" if seg else ""


def run_verification(
    command: Union[str, Sequence[str], None],
    *,
    proposal_id: str = "",
    timeout_s: Optional[float] = None,
    cwd: Optional[Path] = None,
) -> VerificationObservation:
    """跑一次验证并落盘原文。**永不抛异常**：一切异常都成为观测的一部分。"""
    requested = command if isinstance(command, str) else " ".join(command or ())
    argv, rejection = normalize_verification_command(command)
    started = time.time()
    if argv is None:
        return VerificationObservation(
            command=(),
            requested=requested,
            recognized_verifier=False,
            executed=False,
            exit_code=None,
            timed_out=False,
            duration_s=0.0,
            evidence_ref="",
            rejection=rejection,
            started_at=started,
        )

    t0 = time.monotonic()
    exit_code: Optional[int] = None
    timed_out = False
    stdout = stderr = ""
    launch_error = ""
    try:
        proc = subprocess.run(  # noqa: S603 — argv 来自白名单，无 shell
            list(argv),
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=_timeout_s(timeout_s),
            check=False,
        )
        exit_code, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
    except (OSError, ValueError) as exc:
        launch_error = f"验证命令没能启动：{exc}"
    duration = time.monotonic() - t0

    if launch_error:
        return VerificationObservation(
            command=argv,
            requested=requested,
            recognized_verifier=True,
            executed=False,
            exit_code=None,
            timed_out=False,
            duration_s=duration,
            evidence_ref="",
            rejection=launch_error,
            started_at=started,
        )

    record = {
        "proposal_id": proposal_id,
        "command": list(argv),
        "requested": requested,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": round(duration, 3),
        "stdout": _clip(stdout),
        "stderr": _clip(stderr),
    }
    return VerificationObservation(
        command=argv,
        requested=requested,
        recognized_verifier=True,
        executed=True,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_s=duration,
        evidence_ref=_archive(proposal_id, record),
        started_at=started,
    )


# ---------------------------------------------------------------------------
# 观测 → 证据状态（事实翻译，不是裁决）
# ---------------------------------------------------------------------------


def _is_pytest(command: Tuple[str, ...]) -> bool:
    return len(command) >= 3 and command[1:3] == ("-m", "pytest")


def observation_to_evidence(obs: VerificationObservation) -> Tuple[ExecutionEvidenceState, bool]:
    """把观测翻译成 ``(证据状态, 证据链是否完整)``，交给执法函数定级。

    证据链完整 = 认得的验证器 + 真的跑了 + 原文已落盘。三者缺一，退出码再好看也只是
    provisional —— 没有证据的通过不予受理。
    """
    if not obs.executed:
        return ExecutionEvidenceState.planned_not_started, False
    if obs.timed_out:
        return ExecutionEvidenceState.interrupted, False
    if obs.exit_code is None:
        return ExecutionEvidenceState.aborted, False
    if _is_pytest(obs.command) and obs.exit_code == _PYTEST_NO_TESTS_COLLECTED:
        return ExecutionEvidenceState.completed_degraded, False
    if obs.exit_code != 0:
        return ExecutionEvidenceState.failed, bool(obs.evidence_ref)
    return ExecutionEvidenceState.locally_executed, bool(obs.recognized_verifier and obs.evidence_ref)


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "ENGINEERING_VERIFICATION_IS_OBSERVATION_ONLY",
    "FORBIDDEN_VERIFIER_FLAGS",
    "RECOGNIZED_VERIFIERS",
    "VerificationObservation",
    "normalize_verification_command",
    "observation_to_evidence",
    "run_verification",
]
