#!/usr/bin/env python3
"""校验 audit/completion_matrix.json 里引用的证据文件仍然存在（新-11 / P18）。

## 修的是什么

`audit/completion_matrix.json` 记录了各领域的完成度评分，每条都带 `evidence_file`
指向支撑该评分的源码位置。但审查发现：

    $ grep -rn "completion_matrix" .github/workflows/ scripts/ Makefile
    (零命中)

**没有任何 CI 引用它**。对照之下 `check_repo_hygiene` / `check_debt_freeze` /
`check_import_boundaries` / `check_legacy_regression` /
`check_mainline_routing_enforcement` 五个脚本都在 CI 里。

于是它是一份一次性审计产物，而不是强制门。文件被移走或删掉时，矩阵会**静默过期** ——
和 `final_validation_probe.py` 的 SPLIT-01 长期误报红是同一类病：审计资产比代码老，
久而久之团队就不再相信它。

## 这个脚本校验什么

只校验一件**能被机器判定**的事：矩阵引用的每个源码路径是否真的存在。

刻意**不**校验评分是否"正确" —— 那是人的判断，机器判不了，硬做只会制造噪音。
目标是"矩阵不会在无人察觉时腐烂"，不是"矩阵永远正确"。

`evidence_file` 的写法是自由文本（如 ``a.py:Symbol + b/c.kt``），所以这里按
分隔符切开、抽出看起来像路径的片段再逐个检查。抽不出路径的条目跳过并计数，
不当作失败 —— 宁可漏报也不要因为格式自由就误报。

Android/WearOS 侧的路径（``*.kt``）不在本仓，默认跳过；传 --android-root 可一并校验。

用法::

    python scripts/check_completion_matrix.py            # 校验
    python scripts/check_completion_matrix.py --strict   # 有缺失即非零退出（CI 用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATRIX = PROJECT_ROOT / "audit" / "completion_matrix.json"

#: 携带证据路径的键名
_EVIDENCE_KEYS = {"evidence_file", "evidence", "file"}

#: 看起来像仓库内源码路径的片段：含 / 或以已知扩展名结尾
_PATH_LIKE = re.compile(r"^[\w./\-]+\.(py|kt|kts|js|ts|tsx|yml|yaml|json|md|sh|bat|gradle)$")


def _iter_evidence(node: object, path: str = "") -> Iterator[tuple[str, str]]:
    """遍历矩阵，产出 (json 路径, 证据字符串)。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _EVIDENCE_KEYS and isinstance(value, str):
                yield f"{path}/{key}", value
            yield from _iter_evidence(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_evidence(value, f"{path}[{index}]")


def _extract_paths(evidence: str) -> list[str]:
    """从自由文本的证据串里抽出路径片段。

    典型形态::

        "main.py:SystemOrchestrator + unified_launcher.py"
        "galaxy_gateway/android/handlers/registration.py:handle_device_reconnect"
        "network/OfflineTaskQueue.kt + GalaxyWebSocketClient.kt"

    切分依据是 ``+``、``,``、空白；再去掉 ``:符号`` 后缀。
    """
    out: list[str] = []
    for chunk in re.split(r"[+,\s]+", evidence.strip()):
        if not chunk:
            continue
        candidate = chunk.split(":", 1)[0].strip()  # 去掉 :Symbol / :func 后缀
        if _PATH_LIKE.match(candidate):
            out.append(candidate)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="有缺失即非零退出（CI 用）")
    parser.add_argument(
        "--android-root",
        default="",
        help="ufo-galaxy-android 仓库根；给了才校验 .kt 路径",
    )
    args = parser.parse_args()

    if not MATRIX.is_file():
        print(f"❌ 找不到 {MATRIX.relative_to(PROJECT_ROOT)}")
        return 1

    try:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"❌ {MATRIX.relative_to(PROJECT_ROOT)} 不是合法 JSON: {exc}")
        return 1

    android_root = Path(args.android_root).resolve() if args.android_root else None

    checked = 0
    missing: list[tuple[str, str]] = []
    skipped_no_path = 0
    skipped_android = 0

    for json_path, evidence in _iter_evidence(matrix):
        candidates = _extract_paths(evidence)
        if not candidates:
            skipped_no_path += 1
            continue
        for rel in candidates:
            if rel.endswith((".kt", ".kts")):
                if android_root is None:
                    skipped_android += 1
                    continue
                # Android 侧路径在矩阵里是相对包目录写的，做后缀匹配即可
                if not any(android_root.rglob(Path(rel).name)):
                    missing.append((json_path, rel))
                checked += 1
                continue
            checked += 1
            if not (PROJECT_ROOT / rel).exists():
                missing.append((json_path, rel))

    print("audit/completion_matrix.json 证据路径校验")
    print(f"  已检查 : {checked}")
    print(f"  缺失   : {len(missing)}")
    print(f"  跳过(抽不出路径) : {skipped_no_path}")
    if skipped_android:
        print(f"  跳过(Android 侧,未给 --android-root) : {skipped_android}")

    if missing:
        print("\n❌ 以下证据文件已不存在 —— 矩阵已过期，请更新或删除对应条目：")
        for json_path, rel in missing:
            print(f"    {rel}")
            print(f"        ↳ {json_path}")
        if args.strict:
            return 1
        return 0

    print("\n✅ 全部证据路径均存在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
