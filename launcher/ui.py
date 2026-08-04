"""launcher/ui.py — 启动输出的**唯一通道**（三个渲染器读同一份事实）

数据与呈现分离
--------------
``launcher/record.py`` 持有事实（:class:`~launcher.record.StartupRecord`），
本模块把同一份事实渲染成三种形态：

    render_tui   人看的：横幅 + 五栏目 + 总结卡（复用 core.ascii_art / core.cli_render）
    render_json  机器读的：runtime/startup.json
    render_log   日志行

**判断逻辑一次都不重复** —— 这是与现状最大的区别。现在 ``main.py`` /
``unified_launcher`` / ``launch_desktop`` 各自一边判断一边 print，三份判据会漂，
而判断结果不留任何结构化痕迹。

为什么不给 CLI 造 ``--json`` 子命令树
------------------------------------
这个系统的机器面已经是 **388 条 HTTP 路径 + OpenAPI + 生成的 TS 类型 +
/ws/desktop-presence**，比任何 CLI 的 ``--json`` 都完整。再造一套平行的机器面，
正是这个仓库反复吃亏的模式（五套面板、两条配置链、四份依赖引导）。

``runtime/startup.json`` 不是"给 AI 的 flag"，它有具体消费方：

1. **排障** —— 启动失败时可以直接把这个文件发出来，看到的是事实不是截图；
2. **托盘** —— 现在自己去问状态，可以改读它；
3. **面板** —— ``/api/v1/panel/feed`` 可以带上"上次启动的降级项"；
4. **``entrypoint.json`` 的上位** —— 那个只有地址，这个有完整启动结论。

版面
----
所有几何与颜色都来自 ``core.ascii_art``（``BANNER_WIDTH`` / ``CONTENT_INDENT`` /
``RULE_WIDTH`` / ``LABEL_COL`` / ``VALUE_COL``、``gradient_rule``）。本模块
**不自己定义任何宽度、缩进或颜色** —— 三种线宽、三种线条着色、两套填充语义
的历史就是这么来的。
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional

from core.ascii_art import (
    GALAXY_VERSION,
    ansi_supported,
    print_banner,
)
from launcher.record import (
    EXIT_MEANING,
    Column,
    StartupRecord,
    Status,
    StepResult,
)

logger = logging.getLogger("Galaxy.Launcher.UI")

#: 事实的状态 → 显示图标词汇。**唯一的映射点**。
#: 事实层不知道图标长什么样，这是刻意的（见 record.py 的"刻意的边界"）。
_STATUS_GLYPH: Dict[Status, str] = {
    Status.OK: "ok",
    Status.DEGRADED: "warn",
    Status.FAILED: "fail",
    Status.SKIPPED: "info",
}

#: 结构化启动记录的落盘位置。与 ``runtime/entrypoint.json`` 同目录 —— 后者是
#: "网关在哪"，前者是"这次启动发生了什么"。
STARTUP_JSON_RELPATH = os.path.join("runtime", "startup.json")


# ---------------------------------------------------------------------------
# 当前记录（进程级单例）
# ---------------------------------------------------------------------------

_record: Optional[StartupRecord] = None


def begin(version: str = GALAXY_VERSION) -> StartupRecord:
    """开一份新的启动记录，并返回它。重复调用会重开（用于测试）。"""
    global _record
    _record = StartupRecord(version=version)
    return _record


def current() -> StartupRecord:
    """取当前记录；没有就懒创建。

    懒创建是刻意的：``main.py`` 的极早期阶段（编码修正、路径注入）可能先于
    显式 :func:`begin` 就产生输出，那时不该因为"还没 begin"而崩掉启动。
    """
    global _record
    if _record is None:
        _record = StartupRecord(version=GALAXY_VERSION)
    return _record


# ---------------------------------------------------------------------------
# 唯一咽喉：记一笔 + 立刻渲染一行
# ---------------------------------------------------------------------------


#: 当前栏目。``print_item`` 那 71 个老调用点不带栏目信息，靠 :func:`set_column`
#: 在阶段切换时设一次，后续的 step 就自动落到对的栏目里 —— 这样 71 个调用点
#: 一个都不用改，而栏目归属仍然准确。
_current_column: Column = Column.ENV


def set_column(column: Column | str) -> Column:
    """设定后续 :func:`step` 的默认栏目，返回设定后的值。"""
    global _current_column
    _current_column = column if isinstance(column, Column) else Column(column)
    return _current_column


#: 阶段标题里的关键词 → 栏目。按**先匹配先赢**的顺序排列。
#: 之所以做成关键词匹配而不是精确表：现存三套阶段编号（main 的 Phase 0/2、
#: SystemOrchestrator 的 Phase 1-7、unified_launcher 自成一套）标题各不相同，
#: 逐条硬编码会漏，而这些标题里的中文词是稳定的。
_TITLE_TO_COLUMN: List[tuple] = [
    ("依赖", Column.DEPS),
    ("环境", Column.ENV),
    ("预检", Column.ENV),
    ("配置", Column.ENV),
    ("大脑", Column.BRAIN),
    ("模型", Column.BRAIN),
    ("桌面", Column.PRESENCE),
    ("覆盖层", Column.PRESENCE),
    ("托盘", Column.PRESENCE),
    ("面板", Column.PRESENCE),
    ("在场", Column.PRESENCE),
    ("停止", Column.PRESENCE),
    ("网关", Column.FABRIC),
    ("服务", Column.FABRIC),
    ("节点", Column.FABRIC),
    ("启动", Column.FABRIC),
]


def column_for_title(title: str) -> Column:
    """把阶段标题映射到栏目。认不出来时归入「骨干」并留痕。

    刻意**不**在认不出来时抛异常：一个没见过的阶段标题不该让启动崩掉。
    但也不静默归到「环境」—— 那会让"环境"栏莫名其妙地长出无关项。归入
    「骨干」（运行时主体）并打 debug，是可恢复且可追查的失败方向。
    """
    for keyword, col in _TITLE_TO_COLUMN:
        if keyword in title:
            return col
    logger.debug("阶段标题 %r 没有匹配的栏目，归入「骨干」", title)
    return Column.FABRIC


def step(
    name: str,
    status: Status | str = Status.OK,
    value: str = "",
    *,
    column: Column | str | None = None,
    hint: Optional[str] = None,
    elapsed_ms: int = 0,
    **detail: Any,
) -> StepResult:
    """记录并立刻打印一项检查结果。

    这是启动路径上**唯一**该调用的输出函数。它同时做两件事：往
    :class:`StartupRecord` 里记一笔事实，用 ``cli_render.phase`` 打一行。

    之所以能一步到位地接进现有代码：``main.py`` 的 ``print_item()`` 已经是
    该文件 **71 处调用的唯一咽喉**，内部就走 ``cli_render.phase``。让它转调
    本函数，输出可以**逐字节不变**，而结构化记录是白得的。

    Args:
        name:   项目名（进标签列）。
        status: :class:`Status` 或其字符串值；也接受 ``"ok"/"warn"/"error"/"info"``
                这些 ``print_item`` 的老词汇（见 :func:`coerce_status`）。
        value:  给人看的一句话。
        column: 五栏目之一。
        hint:   降级/失败时的专属修复建议。
        detail: 机器可读的原始事实，原样进 ``startup.json``。
    """
    st = coerce_status(status)
    if column is None:
        col = _current_column
    else:
        col = column if isinstance(column, Column) else Column(column)
    result = StepResult(
        column=col,
        name=name,
        status=st,
        value=value,
        hint=hint,
        detail=dict(detail),
        elapsed_ms=elapsed_ms,
    )
    current().add(result)
    _print_step(result)
    return result


#: ``print_item`` 的老状态词汇 → 事实层的 :class:`Status`。
#: 保留这层翻译是为了让 71 个老调用点一个都不用改。
_LEGACY_STATUS: Dict[str, Status] = {
    "ok": Status.OK,
    "success": Status.OK,
    "warn": Status.DEGRADED,
    "warning": Status.DEGRADED,
    "degraded": Status.DEGRADED,
    "error": Status.FAILED,
    "fail": Status.FAILED,
    "failed": Status.FAILED,
    "info": Status.SKIPPED,
    "skip": Status.SKIPPED,
    "skipped": Status.SKIPPED,
}


def coerce_status(status: Status | str) -> Status:
    """把各处的状态词汇归一到 :class:`Status`。

    注意 ``"info"`` 映射到 ``SKIPPED`` 而不是 ``OK``：``print_item(..., "info")``
    在现有代码里表达的是"这项没做/仅提示"，把它算成 OK 会让总结卡的"N 正常"
    虚高 —— 而那个数字是用户判断"能不能用"的第一眼依据。
    """
    if isinstance(status, Status):
        return status
    return _LEGACY_STATUS.get(str(status).strip().lower(), Status.SKIPPED)


def _print_step(result: StepResult) -> None:
    """打一行。走 ``cli_render``；它不可用时降级为纯 ASCII（Windows cp1252 安全）。"""
    try:
        from core import cli_render as r

        r.phase(result.name, result.value, _STATUS_GLYPH[result.status])
        return
    except Exception:  # noqa: BLE001 — 渲染失败绝不能挡启动
        pass
    icon = {
        Status.OK: "[OK]",
        Status.DEGRADED: "[WARN]",
        Status.FAILED: "[ERR]",
        Status.SKIPPED: "[INFO]",
    }[result.status]
    line = f"  {icon} {result.name}" + (f"  ({result.value})" if result.value else "")
    try:
        print(line)
    except UnicodeEncodeError:
        try:
            print(line.encode("cp1252", errors="replace").decode("cp1252"))
        except Exception:  # noqa: BLE001
            pass


def section(title: str) -> None:
    """栏目小标题（``-v`` 展开时用）。走 ``cli_render.section``。"""
    try:
        from core import cli_render as r

        r.section(title)
    except Exception:  # noqa: BLE001
        print(f"\n  {title}")


def rule() -> None:
    """一条与横幅同渐变的横线。"""
    try:
        from core import cli_render as r

        r.rule()
    except Exception:  # noqa: BLE001
        from core.ascii_art import gradient_rule

        print(gradient_rule())


# ---------------------------------------------------------------------------
# 渲染器 A：人看的
# ---------------------------------------------------------------------------


def render_banner() -> None:
    """横幅。原样走 ``ascii_art.print_banner``，一个像素不改。"""
    print_banner()


def render_tui(rec: Optional[StartupRecord] = None, *, verbose: bool = False) -> None:
    """把整份记录渲染成栏目式概览 + 总结卡。

    与逐行 :func:`step` 的关系：``step`` 是**过程中**的即时反馈（一行一项），
    本函数是**结尾**的一屏概览（一栏一行）。两者都读同一份事实，不重复判断。
    """
    rec = rec if rec is not None else current()
    from core import cli_render as r

    print()
    for col in rec.columns_in_order():
        steps = rec.by_column(col)
        worst = _worst(steps)
        r.phase(col.value, _column_summary(steps), _STATUS_GLYPH[worst])
        if verbose:
            for s in steps:
                r.detail(s.name, s.value, _STATUS_GLYPH[s.status])

    degraded = [(s.name, s.hint) for s in rec.degraded + rec.failed]
    rows: List[tuple] = []
    if rec.gateway_url:
        rows.append(("网关", rec.gateway_url))
    if rec.brain:
        rows.append(("大脑", rec.brain))
    if rec.shell:
        rows.append(("桌面壳", rec.shell))

    r.summary_card(
        title=f"用时 {rec.elapsed_s:.1f}s",
        state_ok=rec.ok_count,
        state_degraded=len(rec.degraded) + len(rec.failed),
        rows=rows,
        degraded=degraded or None,
        hints=[("记录", STARTUP_JSON_RELPATH)],
    )


def _worst(steps: List[StepResult]) -> Status:
    """一栏的结论取其中**最差**的一项 —— 一栏里有失败就不能显示为正常。"""
    for st in (Status.FAILED, Status.DEGRADED, Status.OK):
        if any(s.status is st for s in steps):
            return st
    return Status.SKIPPED


def _column_summary(steps: List[StepResult]) -> str:
    """一栏折叠成一句话：优先显示有名有姓的正常项，降级/失败单独点名。"""
    bad = [s.name for s in steps if s.status in (Status.DEGRADED, Status.FAILED)]
    good = [s.value or s.name for s in steps if s.status is Status.OK and (s.value or s.name)]
    parts: List[str] = []
    if good:
        parts.append(" · ".join(good[:3]))
        if len(good) > 3:
            parts.append(f"等 {len(good)} 项")
    if bad:
        parts.append("降级：" + "、".join(bad))
    skipped = sum(1 for s in steps if s.status is Status.SKIPPED)
    if skipped and not parts:
        parts.append(f"{skipped} 项跳过")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# 渲染器 B：机器读的
# ---------------------------------------------------------------------------


def render_json(rec: Optional[StartupRecord] = None, *, root: Optional[str] = None) -> Optional[str]:
    """把记录写到 ``runtime/startup.json``，返回写入路径（失败返回 None）。

    写失败**绝不能挡启动** —— 这是排障辅助，不是启动的必要条件。失败只记
    warning：静默吞掉会让"文件为什么不见了"变成第二个谜。
    """
    rec = rec if rec is not None else current()
    try:
        base = pathlib.Path(root) if root else pathlib.Path(__file__).resolve().parent.parent
        out = base / STARTUP_JSON_RELPATH
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(rec.to_dict(), indent=2, ensure_ascii=False)
        try:
            from core.atomic_json import atomic_write_text  # type: ignore

            atomic_write_text(str(out), payload)
        except Exception:  # noqa: BLE001 — 没有原子写就退回普通写
            out.write_text(payload, encoding="utf-8")
        return str(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("写 %s 失败（不影响启动）：%s", STARTUP_JSON_RELPATH, exc)
        return None


# ---------------------------------------------------------------------------
# 渲染器 C：日志
# ---------------------------------------------------------------------------


def render_log(rec: Optional[StartupRecord] = None) -> None:
    """把记录逐行写进日志。日志里不带任何 ANSI。"""
    rec = rec if rec is not None else current()
    for s in rec.steps:
        try:
            logger.info(
                "[%s] %s = %s%s",
                s.column.value,
                s.name,
                s.status.value,
                f" ({s.value})" if s.value else "",
            )
        except UnicodeEncodeError:
            pass
    try:
        logger.info(
            "启动结束 exit=%s(%s) 用时=%.1fs 正常=%d 降级=%d 失败=%d",
            rec.exit_code,
            EXIT_MEANING.get(rec.exit_code, "未知"),
            rec.elapsed_s,
            rec.ok_count,
            len(rec.degraded),
            len(rec.failed),
        )
    except UnicodeEncodeError:
        pass


# ---------------------------------------------------------------------------
# 收尾
# ---------------------------------------------------------------------------


def finish(exit_code: int = 0, *, verbose: bool = False, tui: bool = True) -> StartupRecord:
    """封盘：定 exit_code、渲染总览、落盘、写日志。返回记录本身。"""
    import time

    rec = current()
    rec.exit_code = exit_code
    rec.finished_at = time.time()
    if tui:
        try:
            render_tui(rec, verbose=verbose)
        except Exception as exc:  # noqa: BLE001 — 渲染失败不该改变退出码
            logger.warning("启动总览渲染失败（不影响启动结果）：%s", exc)
    render_json(rec)
    render_log(rec)
    return rec


def color_enabled() -> bool:
    """当前是否会输出颜色。供调用方决定要不要走带色的分支。"""
    return ansi_supported()
