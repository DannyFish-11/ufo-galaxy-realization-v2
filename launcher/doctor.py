"""launcher/doctor.py — 启动器**自身**的体检

它检查的不是"被启动的服务健不健康"
------------------------------------
那是另外四个面的事（见 ``core/health_check.py`` 里写的分工）。本模块问的是一个
不同的问题：

    **这套统一启动器自己，还是不是完整、自洽、没退化的？**

统一启动器是把四个启动器（``unified_launcher`` / ``launch_desktop`` /
``system_manager`` / ``install``）的要素收敛到一处的结果。这种收敛有两类特有的
退化方式，而且**两类都不会让任何测试自然变红**：

1. **要素悄悄丢了**。搬迁时漏掉一条真机故障攒出来的判据 —— 代码照跑，只是某个
   边角场景又回到了修复前。这是整件事最大的风险，因为丢的东西"平时看不出来"。
2. **第二份实现又长出来了**。有人在 ``launcher/`` 之外重新写一份环境检查 / 依赖
   安装 / 节点表，于是漂移从头开始。四个启动器当初就是这么长出来的。

体检把这两类做成**可执行的检查**，而不是靠人记得。

为什么不复用现成的 pytest
--------------------------
测试跑在开发机和 CI 上。这套检查要能在**用户的真机**上跑 ——
``python main.py doctor`` —— 因为"要素还在不在""有没有第二份实现"这些问题，
恰恰是用户装完之后出问题时最该先问的。而且它复用的是 ``env_check`` / ``deps`` /
``shell`` / ``nodes`` 已经在产的判据，不另立一套。

退出码
------
0 = 全绿；:data:`~launcher.record.EXIT_DEPENDENCY` = 有 FAILED 项。
降级（DEGRADED）不改变退出码 —— 桌面壳没装好不该让 ``doctor && deploy`` 挂掉，
但环境不满足、模块 import 不了这类必须挂。
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from launcher.record import Column, Status, StepResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_DIR = PROJECT_ROOT / "launcher"

#: 统一启动器**必须**具备的模块。少一个就说明收敛没做完或者被删了。
REQUIRED_MODULES = (
    "bootstrap",
    "core_services",
    "deps",
    "dependency_resolver",
    "doctor",
    "env_check",
    "health_checks",
    "node_startup",
    "nodes",
    "record",
    "service_manager",
    "services",
    "shell",
    "shutdown",
    "ui",
)

#: 各启动器"真实有效的要素"逐条清单：``要素名 -> (模块, 里面必须出现的标识)``。
#:
#: 这张表是 ``docs/LAUNCHER_UNIFICATION_PLAN.md`` §2 那份人肉清单的**可执行版**。
#: 写成表而不是散在注释里，是因为"搬迁时漏了一条"正是这件事最大的风险，而人肉
#: 清单没人会在改完代码后回去逐条对。
PRESERVED_ELEMENTS: Dict[str, Dict[str, Any]] = {
    # ── unified_launcher 的 Electron npm 自愈链（约 100 行，全是真机故障攒的）──
    "自愈：清 npm 残留暂存目录": {"module": "launcher.shell", "needs": "purge_npm_staging_dirs"},
    "自愈：识别残留目录类失败": {"module": "launcher.shell", "needs": "is_npm_stale_dir_error"},
    "自愈：整体重建 node_modules": {"module": "launcher.shell", "needs": "重建 node_modules"},
    "自愈：补运行时二进制": {"module": "launcher.shell", "needs": "repair_electron_binary"},
    "自愈：包完整性判定": {"module": "launcher.shell", "needs": "electron_package_intact"},
    "自愈：网络失败换镜像": {"module": "launcher.shell", "needs": "NPM_MIRROR_REGISTRY"},
    "壳锁：.electron.pid 防重复拉起": {"module": "launcher.shell", "needs": "already_running"},
    "渲染降级：软件渲染": {"module": "launcher.shell", "needs": "GALAXY_ELECTRON_GPU"},
    "渲染降级：不透明 basic 小窗": {"module": "launcher.shell", "needs": "GALAXY_ELECTRON_BASIC"},
    "双壳选择：Tauri 优先": {"module": "launcher.shell", "needs": "preferred_shell"},
    # ── main.py Phase 0 / launch_desktop phase0 合并后的环境判据 ──
    "环境：Python 版本下限门": {"module": "launcher.env_check", "needs": "MIN_PYTHON"},
    "环境：pip 问当前解释器": {"module": "launcher.env_check", "needs": "sys.executable"},
    "环境：API Key 并入 secrets.env": {"module": "launcher.env_check", "needs": "read_secrets"},
    "环境：npm 绝对路径调用": {"module": "launcher.env_check", "needs": "shutil.which"},
    "环境：Electron 残缺识别": {"module": "launcher.env_check", "needs": "electron_package_intact"},
    "环境：Ollama 在跑吗 + 有哪些模型": {"module": "launcher.env_check", "needs": "ollama_models"},
    # ── 四份依赖引导合并后的要素 ──
    "依赖：pip 多镜像轮换": {"module": "launcher.deps", "needs": "pip_index_candidates"},
    "依赖：--trusted-host": {"module": "launcher.deps", "needs": "--trusted-host"},
    "依赖：requirements 三档分层": {"module": "launcher.deps", "needs": "REQUIREMENT_TIERS"},
    "依赖：语音包不在启动期现装": {"module": "launcher.deps", "needs": "VOICE_MODULES"},
    "依赖：electron 二进制镜像轮换": {"module": "launcher.deps", "needs": "ELECTRON_MIRROR_ATTEMPTS"},
    # ── system_manager 的节点生命周期 ──
    "节点：端口权威解析": {"module": "launcher.nodes", "needs": "_get_canonical_port"},
    "节点：按组启停": {"module": "launcher.nodes", "needs": "start_group"},
    "节点：健康巡检": {"module": "launcher.nodes", "needs": "check_all_nodes"},
    "节点：常驻监控": {"module": "launcher.nodes", "needs": "monitor"},
    "节点：JSON 报告": {"module": "launcher.nodes", "needs": "generate_report"},
    # ── unified_launcher 的服务编排（步骤 7 搬来）──
    "服务：Docker 基建": {"module": "launcher.services", "needs": "ensure_docker_infra"},
    "服务：NATS 三态": {"module": "launcher.services", "needs": "start_nats"},
    "服务：Tailscale": {"module": "launcher.services", "needs": "start_tailscale"},
    "服务：本地大脑": {"module": "launcher.services", "needs": "start_local_brain"},
    "服务：主脑选择与后台拉取": {"module": "launcher.services", "needs": "select_and_start_brain"},
    "服务：语音交互": {"module": "launcher.services", "needs": "start_voice_interaction"},
    "服务：系统托盘": {"module": "launcher.services", "needs": "start_system_tray"},
    "服务：进程看守（保活）": {"module": "launcher.services", "needs": "watch_processes"},
    "服务：entrypoint.json 写出": {"module": "launcher.services", "needs": "_write_entrypoint_json"},
    "服务：节点解析观察": {"module": "launcher.services", "needs": "_observe_node_resolutions"},
    "服务：端口可绑定探测": {"module": "launcher.services", "needs": "_probe_port_bindable"},
    "服务：AI 大脑就绪判据": {"module": "launcher.services", "needs": "ai_brain_readiness"},
    "服务：优雅停止": {"module": "launcher.services", "needs": "def stop"},
    # ── 启动事实与呈现分离 ──
    "记录：结构化启动事实": {"module": "launcher.record", "needs": "StartupRecord"},
    "记录：确定性退出码": {"module": "launcher.record", "needs": "EXIT_DEPENDENCY"},
}

#: 这些模块**不许**再出现"第二份实现"的标志性符号。
#: key = 独占该实现的模块，value = 标志性符号。
#:
#: 只列**行为判据**，不列路径常量 —— 这条区分是被自己的体检抓出来的：
#: 第一版把 ``ELECTRON_DIR`` 也列进来了，于是 ``main.py`` 与 ``launch_desktop.py``
#: 双双报"第二份实现"。核下来那是**误报**：步骤 2 合并环境检查时刻意把路径的
#: 所有权留在调用方（``check_environment(env_file=..., electron_dir=...)``），
#: 好让测试能注入临时目录 —— 否则 ``monkeypatch(main.ENV_FILE)`` 会静默失效、
#: 测试转而去读开发者的真 ``.env``（那个坑当时真踩过）。
#:
#: 所以判据是：**同一件事的判断逻辑**只能有一份（镜像表、版本门、模块清单、
#: 命令表）；**指向同一个文件的路径**可以各持一份，那是刻意的注入点。
SINGLE_IMPLEMENTATION: Dict[str, List[str]] = {
    "launcher.env_check": ["MIN_PYTHON"],
    "launcher.deps": ["REQUIREMENT_TIERS", "CORE_MODULES", "ELECTRON_MIRROR_ATTEMPTS"],
    "launcher.shell": ["NETWORK_FAILURE_MARKERS"],
    "launcher.nodes": ["NODE_COMMANDS", "NODE_GROUPS"],
}


@dataclasses.dataclass
class DoctorReport:
    steps: List[StepResult] = dataclasses.field(default_factory=list)

    def add(self, name: str, status: Status, value: str = "", hint: Optional[str] = None, **detail: Any) -> None:
        self.steps.append(
            StepResult(column=Column.ENV, name=name, status=status, value=value, hint=hint, detail=detail)
        )

    @property
    def failed(self) -> List[StepResult]:
        return [s for s in self.steps if s.status is Status.FAILED]

    @property
    def degraded(self) -> List[StepResult]:
        return [s for s in self.steps if s.status is Status.DEGRADED]

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": {s.value: sum(1 for x in self.steps if x.status is s) for s in Status},
            "steps": [s.to_dict() for s in self.steps],
        }


# ── 各项检查 ──────────────────────────────────────────────────────────


def _check_modules_import(report: DoctorReport) -> None:
    """``launcher/`` 下每个模块都必须真能 import。

    这条是有来历的：``dependency_resolver`` 曾经断了整整一次提交，因为所有测试
    都只**静态断言**、没有一条**执行**过它。
    """
    broken = []
    for path in sorted(LAUNCHER_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            importlib.import_module(f"launcher.{path.stem}")
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{path.stem}: {type(exc).__name__}: {exc}")
    if broken:
        report.add("launcher/ 模块可 import", Status.FAILED, f"{len(broken)} 个失败", "\n".join(broken)[:400])
    else:
        n = len(list(LAUNCHER_DIR.glob("*.py"))) - 1
        report.add("launcher/ 模块可 import", Status.OK, f"{n} 个")


def _check_required_modules(report: DoctorReport) -> None:
    missing = [m for m in REQUIRED_MODULES if not (LAUNCHER_DIR / f"{m}.py").is_file()]
    if missing:
        report.add("统一启动器模块齐全", Status.FAILED, f"缺 {len(missing)} 个", ", ".join(missing))
    else:
        report.add("统一启动器模块齐全", Status.OK, f"{len(REQUIRED_MODULES)} 个")


def _check_preserved_elements(report: DoctorReport) -> None:
    """逐条核"各启动器真实有效的要素"还在不在。

    这是整件事最大的风险：搬迁时漏掉一条判据，代码照跑，只是某个边角场景又回到
    了修复前 —— 而且**平时看不出来**。
    """
    lost = []
    for name, spec in PRESERVED_ELEMENTS.items():
        mod_path = PROJECT_ROOT / Path(*spec["module"].split(".")).with_suffix(".py")
        try:
            src = mod_path.read_text(encoding="utf-8")
        except OSError:
            lost.append(f"{name}（{spec['module']} 读不到）")
            continue
        if spec["needs"] not in src:
            lost.append(f"{name}（{spec['module']} 里找不到 {spec['needs']}）")
    if lost:
        report.add(
            "启动器要素逐条在位",
            Status.FAILED,
            f"丢了 {len(lost)}/{len(PRESERVED_ELEMENTS)} 条",
            "\n".join(lost)[:600],
        )
    else:
        report.add("启动器要素逐条在位", Status.OK, f"{len(PRESERVED_ELEMENTS)} 条")


def _check_single_implementation(report: DoctorReport) -> None:
    """``launcher/`` 之外不许再长出第二份实现。

    四个启动器当初就是这么长出来的：有人在别处又写了一份环境检查 / 依赖安装 /
    节点表，两份互不知情，然后开始漂。
    """
    offenders = []
    skip_dirs = {"__pycache__", ".venv", "venv", "node_modules", ".git", "external", "launcher", "tests"}
    for owner, symbols in SINGLE_IMPLEMENTATION.items():
        owner_file = PROJECT_ROOT / Path(*owner.split(".")).with_suffix(".py")
        for path in PROJECT_ROOT.rglob("*.py"):
            if path == owner_file or any(p in skip_dirs for p in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (SyntaxError, ValueError, OSError):
                continue
            # 只看**赋值定义**，不看引用 —— 引用是正常使用，定义才是第二份实现。
            defined = {
                t.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                for t in node.targets
                if isinstance(t, ast.Name)
            }
            dup = defined & set(symbols)
            if dup:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} 重新定义了 {', '.join(sorted(dup))}")
    if offenders:
        report.add("无第二份实现", Status.FAILED, f"{len(offenders)} 处", "\n".join(offenders)[:400])
    else:
        report.add("无第二份实现", Status.OK, f"{len(SINGLE_IMPLEMENTATION)} 个权威面")


def _check_exit_code_propagates(report: DoctorReport) -> None:
    """``main.py`` 的退出码必须真的到达 shell。

    此前 ``__main__`` 是裸 ``main()``，返回值被丢弃，进程永远 exit 0 ——
    ``record.py`` 那张退出码表读起来像生效的，实际一个都传不出去。
    """
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    guards = [
        n
        for n in tree.body
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and isinstance(n.test.left, ast.Name)
        and n.test.left.id == "__name__"
    ]
    bare = [
        n
        for g in guards
        for n in g.body
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "main"
    ]
    if bare or not guards:
        report.add("退出码传得到 shell", Status.FAILED, "裸调用 main()", "应 raise SystemExit(main())")
    else:
        report.add("退出码传得到 shell", Status.OK)


#: **事实层**：只产出事实，打印交给 ``launcher/ui.py`` 那个唯一咽喉。
#: 这些模块里出现 ``print(`` 就是退化 —— 同一份判断又会散成"只剩一行彩色文本"，
#: 那正是这次统一要消掉的老毛病。
FACT_LAYER_MODULES = ("record", "env_check", "deps", "shell", "doctor")

#: **编排/CLI 层**：面向用户的输出**就是**它们的职责，打印是对的。
#:
#: 这条分界必须写死成两张表，而不是"哪个报错就加进豁免名单" —— 后者会烂掉：
#: 加着加着，规则就变成了"谁都可以打印"。判据是：
#: 这个模块的产出是**事实**（给别人渲染）还是**界面**（给人看）。
PRESENTATION_MODULES = ("ui", "nodes", "services")


def _check_no_bare_print_on_startup_path(report: DoctorReport) -> None:
    """事实层不许绕过唯一输出咽喉直接 ``print``。

    只查 :data:`FACT_LAYER_MODULES`；:data:`PRESENTATION_MODULES` 的打印是它们
    的职责（``ui`` 就是那个咽喉；``nodes`` 要给 ``main.py nodes status`` 出运维
    界面；``services`` 拥有启动横幅与就绪摘要）。
    """
    offenders = []
    for name in FACT_LAYER_MODULES:
        path = LAUNCHER_DIR / f"{name}.py"
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lines = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
        ]
        if lines:
            offenders.append(f"{name}.py:{lines}")
    if offenders:
        report.add("事实层不直接打印", Status.FAILED, f"{len(offenders)} 个模块", "; ".join(offenders))
    else:
        report.add("事实层不直接打印", Status.OK, f"{len(FACT_LAYER_MODULES)} 个事实层模块")


def _check_fact_and_presentation_are_disjoint(report: DoctorReport) -> None:
    """两张表不许有交集，也不许漏掉 ``launcher/`` 里的模块没归类。

    没有这条，"新加的模块算哪一层"就没人回答 —— 于是它既不被查、也不被豁免，
    悄悄地既产事实又打印，分离就白做了。
    """
    both = set(FACT_LAYER_MODULES) & set(PRESENTATION_MODULES)
    if both:
        report.add("层次归类无歧义", Status.FAILED, f"同时在两张表：{', '.join(sorted(both))}")
        return
    classified = set(FACT_LAYER_MODULES) | set(PRESENTATION_MODULES)
    # 只要求"必需模块"都归了类；bootstrap/service_manager 这类既有模块不强制。
    unclassified = [
        m
        for m in REQUIRED_MODULES
        if m in {"record", "ui", "nodes", "services", "shell", "deps", "env_check", "doctor"} and m not in classified
    ]
    if unclassified:
        report.add("层次归类无歧义", Status.FAILED, f"没归类：{', '.join(unclassified)}")
    else:
        report.add("层次归类无歧义", Status.OK, f"事实 {len(FACT_LAYER_MODULES)} · 呈现 {len(PRESENTATION_MODULES)}")


def _check_runtime_surfaces(report: DoctorReport) -> None:
    """复用已在产的判据跑一遍：环境 / 依赖 / 桌面壳 / 节点表。

    刻意复用而不是另写 —— doctor 若自带一套判据，它本身就成了"第二份实现"。
    """
    try:
        from launcher import env_check

        env = env_check.check_environment()
        report.add(
            "环境检查（复用 env_check）",
            Status.OK if env.ready else Status.FAILED,
            f"Python {env.python_version} · {env.api_keys_configured} 个 Key",
            None if env.ready else "见 python main.py 的 Phase 0",
        )
    except Exception as exc:  # noqa: BLE001
        report.add("环境检查（复用 env_check）", Status.FAILED, f"{type(exc).__name__}: {exc}")

    try:
        from launcher import deps

        missing = deps.probe_missing(deps.platform_core_modules())
        report.add(
            "核心依赖（复用 deps）",
            Status.OK if not missing else Status.FAILED,
            "齐全" if not missing else f"缺 {len(missing)} 个：{', '.join(missing[:5])}",
            None if not missing else "python main.py install",
        )
        voice = deps.probe_missing(deps.VOICE_MODULES)
        report.add(
            "语音依赖（可选）",
            Status.OK if not voice else Status.DEGRADED,
            "齐全" if not voice else f"缺 {len(voice)} 个",
            None if not voice else f"pip install {' '.join(voice)}",
        )
    except Exception as exc:  # noqa: BLE001
        report.add("核心依赖（复用 deps）", Status.FAILED, f"{type(exc).__name__}: {exc}")

    try:
        from launcher import shell

        health = shell.diagnose()
        if health.blocked:
            report.add("桌面壳（复用 shell）", Status.DEGRADED, health.blocked, "无桌面壳仍可用远程/文字路径")
        elif health.ready:
            report.add("桌面壳（复用 shell）", Status.OK, shell.preferred_shell(health))
        else:
            report.add(
                "桌面壳（复用 shell）",
                Status.DEGRADED,
                "依赖未就位",
                "启动时会自动跑七级自愈；也可 python main.py doctor --heal",
            )
    except Exception as exc:  # noqa: BLE001
        report.add("桌面壳（复用 shell）", Status.FAILED, f"{type(exc).__name__}: {exc}")

    try:
        from launcher import nodes

        total = sum(len(v) for v in nodes.NODES.values())
        report.add(
            "节点表（复用 nodes）",
            Status.OK if total else Status.FAILED,
            f"{len(nodes.NODES)} 组 / {total} 个",
            None if total else "节点表扫空了 —— 检查 config/unified_config.json 与路径",
        )
    except Exception as exc:  # noqa: BLE001
        report.add("节点表（复用 nodes）", Status.FAILED, f"{type(exc).__name__}: {exc}")


def _check_layout_geometry(report: DoctorReport) -> None:
    """版面几何自洽：值列由常量派生，两套打印器落在同一列。"""
    try:
        from core.ascii_art import BANNER_WIDTH, CONTENT_INDENT, ICON_COL, LABEL_COL, RULE_WIDTH, VALUE_COL

        expected_value_col = CONTENT_INDENT + ICON_COL + LABEL_COL + 2
        expected_rule = BANNER_WIDTH - CONTENT_INDENT
        bad = []
        if VALUE_COL != expected_value_col:
            bad.append(f"VALUE_COL={VALUE_COL} 应为 {expected_value_col}")
        if RULE_WIDTH != expected_rule:
            bad.append(f"RULE_WIDTH={RULE_WIDTH} 应为 {expected_rule}")
        if bad:
            report.add("版面几何自洽", Status.FAILED, "; ".join(bad))
        else:
            report.add("版面几何自洽", Status.OK, f"值列 {VALUE_COL} · 线宽 {RULE_WIDTH}")
    except Exception as exc:  # noqa: BLE001
        report.add("版面几何自洽", Status.FAILED, f"{type(exc).__name__}: {exc}")


def run_doctor(*, include_runtime: bool = True) -> DoctorReport:
    """跑完整体检。**不打印**（呈现交给调用方）。

    Args:
        include_runtime: 是否跑环境/依赖/桌面壳/节点表这类**摸真实机器**的检查。
            关掉之后只剩纯静态的结构自检 —— 测试里用它，避免让体检的结论取决于
            跑它的那台机器装没装 Ollama。
    """
    report = DoctorReport()
    _check_required_modules(report)
    _check_modules_import(report)
    _check_preserved_elements(report)
    _check_single_implementation(report)
    _check_exit_code_propagates(report)
    _check_no_bare_print_on_startup_path(report)
    _check_fact_and_presentation_are_disjoint(report)
    _check_layout_geometry(report)
    if include_runtime:
        _check_runtime_surfaces(report)
    return report


__all__ = [
    "REQUIRED_MODULES",
    "FACT_LAYER_MODULES",
    "PRESENTATION_MODULES",
    "PRESERVED_ELEMENTS",
    "SINGLE_IMPLEMENTATION",
    "DoctorReport",
    "run_doctor",
]
