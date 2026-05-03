#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于主链真实代码生成 Galaxy 仓库现状报告。

目标：
1. 只抓当前主链的权威运行时路径，不复述历史文档噪音。
2. 用中文给出“这是什么系统 / 当前完成度 / 还差什么”。
3. 所有结论尽量来自可执行代码中的权威状态面，而不是手写估计。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class LegacySurfaceSummary:
    path: str
    status: str
    superseded_by: str


@dataclass(frozen=True)
class MainlineRealityReport:
    system_type: str
    repo_role: str
    startup_entrypoint: str
    canonical_runtime_chain: List[str]
    projection_surfaces: List[str]
    node_count: int
    completion_pct: float
    runtime_readiness: str
    canonical_dimension_count: int
    total_dimensions: int
    legacy_ambiguity_dimensions: List[str] = field(default_factory=list)
    main_blockers: List[str] = field(default_factory=list)
    active_legacy_surfaces: List[LegacySurfaceSummary] = field(default_factory=list)
    key_code_evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_type": self.system_type,
            "repo_role": self.repo_role,
            "startup_entrypoint": self.startup_entrypoint,
            "canonical_runtime_chain": list(self.canonical_runtime_chain),
            "projection_surfaces": list(self.projection_surfaces),
            "node_count": self.node_count,
            "completion_pct": round(self.completion_pct, 2),
            "runtime_readiness": self.runtime_readiness,
            "canonical_dimension_count": self.canonical_dimension_count,
            "total_dimensions": self.total_dimensions,
            "legacy_ambiguity_dimensions": list(self.legacy_ambiguity_dimensions),
            "main_blockers": list(self.main_blockers),
            "active_legacy_surfaces": [asdict(item) for item in self.active_legacy_surfaces],
            "key_code_evidence": list(self.key_code_evidence),
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)


def _count_canonical_nodes(repo_root: Path) -> int:
    nodes_dir = repo_root / "nodes"
    if not nodes_dir.exists():
        return 0
    return sum(1 for path in nodes_dir.iterdir() if path.is_dir() and path.name.startswith("Node_"))


def build_mainline_reality_report(repo_root: Path = REPO_ROOT) -> MainlineRealityReport:
    from tools.architecture.architecture_completion import get_architecture_completion_scorecard
    from tools.architecture.architecture_live_status import get_architecture_live_status

    scorecard = get_architecture_completion_scorecard(force_rebuild=True)
    live_status = get_architecture_live_status(force_rebuild=True)

    blockers: List[str] = []
    for dimension_item in scorecard.dimensions:
        if dimension_item.legacy_ambiguity_remains or dimension_item.maturity_level.is_blocking():
            for blocker in dimension_item.blockers or []:
                blockers.append(f"{dimension_item.dimension.value}: {blocker}")

    legacy_surfaces = [
        LegacySurfaceSummary(
            path=zone.path,
            status=zone.status,
            superseded_by=zone.superseded_by or "",
        )
        for zone in live_status.legacy_zones[:5]
    ]

    return MainlineRealityReport(
        system_type=(
            "跨设备 L4 自主智能运行时 / 编排系统："
            "以 Windows 桌面运行时为外壳，以 OpenClawd 为主体核心，"
            "向下连接 AgentKernel、CommandRouter、节点系统和跨设备链路。"
        ),
        repo_role=(
            "这是一个以 Python 为主的主运行时仓库，不是单纯 Demo 或文档仓。"
            "主链职责覆盖启动编排、主体认知执行、API/投影、节点体系、"
            "设备路由与跨设备扩展。"
        ),
        startup_entrypoint="main.py → unified_launcher.py",
        canonical_runtime_chain=[
            "main.py",
            "unified_launcher.py",
            "core.desktop_presence_runtime",
            "core.openclawd",
            "core.agent.kernel",
            "core.command_router",
            "core.routes.projection",
        ],
        projection_surfaces=[
            "GET /api/v1/projection/runtime",
            "GET /api/v1/projection/runtime-truth",
            "windows_client.status_board_v2",
        ],
        node_count=_count_canonical_nodes(repo_root),
        completion_pct=scorecard.overall_completion_pct,
        runtime_readiness=live_status.runtime_readiness,
        canonical_dimension_count=scorecard.canonical_count,
        total_dimensions=scorecard.total_dimensions,
        legacy_ambiguity_dimensions=[
            dimension.dimension.value for dimension in scorecard.legacy_ambiguity_dimensions()
        ],
        main_blockers=blockers,
        active_legacy_surfaces=legacy_surfaces,
        key_code_evidence=[
            "main.py",
            "unified_launcher.py",
            "core/desktop_presence_runtime.py",
            "core/openclawd.py",
            "core/agent/kernel.py",
            "core/routes/projection.py",
            "tools/architecture/architecture_completion.py",
            "tools/architecture/architecture_live_status.py",
        ],
    )


def render_text_report(report: MainlineRealityReport) -> str:
    legacy_lines = [
        f"- {item.path}（{item.status}）→ {item.superseded_by or '无'}"
        for item in report.active_legacy_surfaces
    ] or ["- 当前未发现需要特别提示的遗留表层"]

    blocker_lines = [f"- {item}" for item in report.main_blockers] or ["- 当前无 blocking 级阻塞，但仍有收尾项"]

    return "\n".join(
        [
            "Galaxy 主链真实现状（基于代码，不基于历史文档快照）",
            "",
            "1. 这是什么系统",
            f"- {report.system_type}",
            f"- {report.repo_role}",
            "",
            "2. 当前真正的主链",
            f"- 启动入口：{report.startup_entrypoint}",
            f"- 运行主链：{' → '.join(report.canonical_runtime_chain)}",
            f"- 对外状态面：{', '.join(report.projection_surfaces)}",
            f"- 当前 Node 目录数：{report.node_count}",
            "",
            "3. 真实完成度",
            f"- 架构完成度：{report.completion_pct:.1f}%",
            f"- 运行时就绪度：{report.runtime_readiness}",
            f"- 已达到 canonicalized/complete 的维度：{report.canonical_dimension_count}/{report.total_dimensions}",
            (
                "- 需要注意：这个百分比是“主链架构完成度”，"
                "不是“真实全场景产品化/硬件落地完成度”。"
            ),
            "",
            "4. 还没有真正收口的地方",
            *blocker_lines,
            (
                "- 当前遗留模糊维度："
                + (", ".join(report.legacy_ambiguity_dimensions) if report.legacy_ambiguity_dimensions else "无")
            ),
            "",
            "5. 可以忽略的噪音 / 非主线",
            *legacy_lines,
            "",
            "6. 结论",
            (
                "- 这个仓库已经不是空壳：主运行时、认知内核、投影状态面、"
                "节点体系和跨设备链条都在。"
            ),
            (
                "- 但它也不是完全收官的成品：按代码里的权威评分，"
                "现在更接近“主链已成型、仍在收口”的 partial 状态。"
            ),
        ]
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 Galaxy 主链真实现状报告")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    report = build_mainline_reality_report()
    if args.json:
        print(report.to_json(indent=2))
    else:
        print(render_text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
