#!/usr/bin/env python3
"""
audit/audit_summary.py
======================
Prints a structured completion summary from the audit completion matrix.

Usage:
    python audit/audit_summary.py
    python audit/audit_summary.py --gaps
    python audit/audit_summary.py --json
"""
import json
import sys
import os
from pathlib import Path

MATRIX_PATH = Path(__file__).parent / "completion_matrix.json"


def load_matrix():
    with open(MATRIX_PATH) as f:
        return json.load(f)


def print_summary(matrix, show_gaps=False):
    domains = matrix["completion_by_domain"]

    # Sort by score ascending (worst first)
    sorted_domains = sorted(domains.items(), key=lambda x: x[1]["score_pct"])

    print("=" * 72)
    print("Galaxy Dual-Repo System Audit — Completion Summary")
    print(f"Date: {matrix['audit_meta']['date']}")
    print("=" * 72)
    print()

    # Status emoji
    STATUS_EMOJI = {
        "closed": "✅",
        "partial_closed": "⚠️ ",
        "nominal_only": "🔴",
        "missing": "❌",
    }

    col_w = 45
    print(f"{'Domain':<{col_w}} {'Score':>6}  {'Status'}")
    print("-" * 72)

    total = 0
    for name, info in sorted_domains:
        score = info["score_pct"]
        total += score
        status = info["status"]
        emoji = STATUS_EMOJI.get(status, "  ")
        short_name = name.replace("_", " ")
        print(f"{short_name:<{col_w}} {score:>5}%  {emoji} {status}")

    avg = total / len(sorted_domains)
    print()
    print(f"{'Overall average':<{col_w}} {avg:>5.0f}%")
    print()

    if show_gaps:
        gaps = matrix["critical_gaps"]
        print("=" * 72)
        print("Critical Gaps")
        print("=" * 72)
        for gap in gaps:
            print(f"\n[{gap['id']}] {gap['priority']} — {gap['title']}")
            print(f"  Files   : {', '.join(gap['files'])}")
            print(f"  Impact  : {gap['impact']}")
            print(f"  Fix     : {gap['fix_direction']}")

    print()
    print("Full audit: audit/DUAL_REPO_SYSTEM_AUDIT.md")


def main():
    matrix = load_matrix()
    show_gaps = "--gaps" in sys.argv
    as_json = "--json" in sys.argv

    if as_json:
        print(json.dumps(matrix["completion_by_domain"], indent=2))
    else:
        print_summary(matrix, show_gaps=show_gaps)


if __name__ == "__main__":
    main()
