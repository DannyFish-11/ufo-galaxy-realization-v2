"""launcher/record.py — 启动过程的**事实**（不含任何显示逻辑）

要解决什么
----------
启动器现在是"一边判断一边 ``print``"：判断结果只以彩色文本的形式存在过一瞬，
**不留任何结构化痕迹**。后果很具体：

* 启动失败时能拿到的只有一段截图或复制的彩色文本，排障只能靠读那段文字猜；
* 托盘、面板、``entrypoint.json`` 各自再去问一遍状态，同一件事问三遍；
* "上次启动降级了什么"没有任何地方记着。

本模块把事实从呈现里剥出来。判断只做一次，结果落成 :class:`StartupRecord`，
再由 ``launcher/ui.py`` 的三个渲染器分别渲染给人、给机器、给日志。

刻意的边界
----------
**这里不许 import 任何渲染相关的东西**，也不许有颜色、缩进、图标的概念。
一旦事实层知道了自己会被怎么显示，分离就失效了 —— 那正是现在这套代码的病根。
``tests/test_launcher_record_and_ui.py`` 有一条测试钉住这件事。
"""

from __future__ import annotations

import dataclasses
import time
from enum import Enum
from typing import Any, Dict, List, Optional


class Column(str, Enum):
    """五个栏目。

    按**用户关心什么**取名，不按代码结构 —— 此前 ``main.py`` 打 Phase 0/2、
    ``SystemOrchestrator`` 打 Phase 1–7、``unified_launcher`` 又自成一套，
    三套编号在同一屏里交错出现，而"Phase 4"对用户没有任何意义。
    """

    ENV = "环境"  # 这台机器能不能跑
    DEPS = "依赖"  # 缺的东西补齐了吗
    FABRIC = "骨干"  # 通信层通了吗
    BRAIN = "大脑"  # 用哪个模型、能不能用
    PRESENCE = "在场"  # 我能看见它了吗

    @property
    def order(self) -> int:
        """栏目的固定显示顺序（与启动时序一致）。"""
        return _COLUMN_ORDER[self]


_COLUMN_ORDER: Dict["Column", int] = {}


class Status(str, Enum):
    """一项检查的结论。

    与 ``core.cli_render._STATUS`` 的图标词汇是**两回事**：那边是显示符号，
    这里是事实。映射关系写在 ``launcher/ui.py``，事实层不该知道图标长什么样。
    """

    OK = "ok"
    DEGRADED = "degraded"  # 能跑，但打了折
    FAILED = "failed"  # 这一项没成
    SKIPPED = "skipped"  # 按配置/平台跳过，不算问题


#: 确定性退出码。此前只有 0/1 两档，且 ``main.py`` 里 8 处 ``return 1`` 混着
#: 完全不同的失败原因 —— 自动化分不清，你自己排障也分不清。
EXIT_OK = 0
EXIT_ERROR = 1  # 一般错误（未归类）
EXIT_USAGE = 2  # 参数用法错误
EXIT_DEPENDENCY = 3  # 依赖缺失且无法自动补齐
EXIT_PORT_IN_USE = 4  # 端口被占，且不是本进程
EXIT_ENVIRONMENT = 5  # 环境不满足（Python 版本、缺 .env 等）
EXIT_INTERRUPTED = 130  # SIGINT（沿用 shell 惯例 128+2）

#: 退出码 → 人话。渲染器与错误提示都读它，避免两处各写一份。
EXIT_MEANING: Dict[int, str] = {
    EXIT_OK: "成功",
    EXIT_ERROR: "一般错误",
    EXIT_USAGE: "参数用法错误",
    EXIT_DEPENDENCY: "依赖缺失",
    EXIT_PORT_IN_USE: "端口被占用",
    EXIT_ENVIRONMENT: "环境不满足",
    EXIT_INTERRUPTED: "被中断",
}


@dataclasses.dataclass(frozen=True)
class StepResult:
    """一项检查的完整事实。"""

    column: Column
    name: str
    status: Status
    value: str = ""
    """给人看的一句话，如 ``"3.11.15"``、``"已就位（3 项跳过）"``。"""

    hint: Optional[str] = None
    """降级/失败时的**专属**修复建议。

    刻意是每项各带一条，而不是所有降级共用一句 —— ``cli_render.summary_card``
    的注释里论证过：``"装后重跑即恢复"`` 只对 Docker 那类场景成立，换成
    "模型没拉好"就文不对题。没有可靠建议时留 ``None``，不编。
    """

    detail: Dict[str, Any] = dataclasses.field(default_factory=dict)
    """机器可读的原始事实。排障时真正想立刻看到的东西放这里。"""

    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["column"] = self.column.value
        d["status"] = self.status.value
        return d


@dataclasses.dataclass
class StartupRecord:
    """一次启动的完整事实。"""

    version: str
    started_at: float = dataclasses.field(default_factory=time.time)
    steps: List[StepResult] = dataclasses.field(default_factory=list)
    exit_code: int = EXIT_OK
    finished_at: Optional[float] = None

    # ── 排障时最想第一眼看到的几个数（不必翻 steps） ──
    shell: Optional[str] = None
    """``"tauri"`` | ``"electron"`` | ``None``（无桌面壳）。"""

    gateway_url: Optional[str] = None
    brain: Optional[str] = None
    """选中的主脑，如 ``"qwen3:8b"``、``"api-only"``。"""

    mode: Optional[str] = None
    """系统模式（``core.system_mode`` 解析出的那个）。"""

    def add(self, step: StepResult) -> StepResult:
        self.steps.append(step)
        return step

    # ── 汇总（给总结卡用；这里只算数，不决定怎么显示） ──

    def count(self, status: Status) -> int:
        return sum(1 for s in self.steps if s.status is status)

    @property
    def ok_count(self) -> int:
        return self.count(Status.OK)

    @property
    def degraded(self) -> List[StepResult]:
        return [s for s in self.steps if s.status is Status.DEGRADED]

    @property
    def failed(self) -> List[StepResult]:
        return [s for s in self.steps if s.status is Status.FAILED]

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.time()
        return max(0.0, end - self.started_at)

    def by_column(self, column: Column) -> List[StepResult]:
        return [s for s in self.steps if s.column is column]

    def columns_in_order(self) -> List[Column]:
        """出现过的栏目，按固定顺序。空栏目不显示。"""
        seen = {s.column for s in self.steps}
        return [c for c in Column if c in seen]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": round(self.elapsed_s, 3),
            "exit_code": self.exit_code,
            "exit_meaning": EXIT_MEANING.get(self.exit_code, "未知"),
            "shell": self.shell,
            "gateway_url": self.gateway_url,
            "brain": self.brain,
            "mode": self.mode,
            "counts": {s.value: self.count(s) for s in Status},
            "steps": [s.to_dict() for s in self.steps],
        }


# Column.order 依赖枚举定义完成，放在这里初始化。
_COLUMN_ORDER.update({c: i for i, c in enumerate(Column)})
