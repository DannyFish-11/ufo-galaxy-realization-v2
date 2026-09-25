#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/meta_rsi.py — 元层的命令行入口。

用法
====
    python scripts/meta_rsi.py status                      # 档位、存储、各型数量、生效记录
    python scripts/meta_rsi.py artifacts --type verdict    # 列 artifact
    python scripts/meta_rsi.py show verdict:0123456789abcdef   # 一件 artifact 及其祖先
    python scripts/meta_rsi.py run --operator harness_rsi  # 跑一轮（受 GALAXY_META_RSI 约束）
    python scripts/meta_rsi.py revert patch:0123456789abcdef --yes  # 整包回退一个已生效的补丁

``run`` 在 ``GALAXY_META_RSI=off``（默认）时什么都不做。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.meta import META_MODE_ENV, meta_rsi_mode  # noqa: E402
from core.meta.artifacts import ARTIFACT_TYPES  # noqa: E402
from core.meta.store import ArtifactStore  # noqa: E402


def _status(store: ArtifactStore) -> int:
    from core.meta.operators import registered_operators

    counts = {t: len(store.list(t)) for t in ARTIFACT_TYPES}
    payload = {
        "mode": meta_rsi_mode(),
        "mode_env": META_MODE_ENV,
        "store": str(store.root),
        "artifacts": counts,
        "commits": store.commits()[-10:],
        "operators": registered_operators(),
        "recent_lessons": [a.payload for a in store.list("lesson", limit=5)],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run(store: ArtifactStore, operator_name: str) -> int:
    from core.meta.kernel import SignalBundle, run_cycle
    from core.meta.operators import build_operator

    operator = build_operator(operator_name)
    signals = operator.collect(store) if hasattr(operator, "collect") else SignalBundle()
    report = run_cycle(operator, signals, store=store)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.status in ("ok", "disabled") else 1


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", help="存储根目录（默认 runtime/meta）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    arts = sub.add_parser("artifacts")
    arts.add_argument("--type", choices=ARTIFACT_TYPES)
    arts.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show")
    show.add_argument("artifact_id")
    run = sub.add_parser("run")
    run.add_argument("--operator", required=True)
    rev = sub.add_parser("revert")
    rev.add_argument("patch_id")
    rev.add_argument("--yes", action="store_true", help="确认回退（会改真实目录里的文件）")
    args = parser.parse_args(argv)

    store = ArtifactStore(Path(args.store)) if args.store else ArtifactStore()
    if args.command == "status":
        return _status(store)
    if args.command == "artifacts":
        for a in store.list(args.type, limit=args.limit):
            print(f"{a.artifact_id}  {a.created_at}  {a.lineage.operator or '-'}")
        return 0
    if args.command == "show":
        artifact = store.get(args.artifact_id)
        if artifact is None:
            print(f"找不到 {args.artifact_id}", file=sys.stderr)
            return 1
        print(json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2))
        for ancestor in store.ancestry(args.artifact_id):
            print(f"  ← {ancestor.artifact_id} ({ancestor.lineage.operator or '-'})")
        return 0
    if args.command == "run":
        return _run(store, args.operator)
    if args.command == "revert":
        if not args.yes:
            print("回退会改真实目录里的文件；确认请加 --yes", file=sys.stderr)
            return 2
        from core.meta.kernel import revert_patch

        reason = revert_patch(args.patch_id, store=store)
        print(reason or f"已回退 {args.patch_id}")
        return 1 if reason else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
