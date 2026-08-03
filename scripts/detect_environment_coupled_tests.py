#!/usr/bin/env python3
"""detect_environment_coupled_tests.py — 找出"结论取决于机器上有什么"的测试。

原理
----
同一批用例跑两遍:一遍**干净环境**,一遍**起着环境桩**(见
``scripts/ambient_service_stubs.py``)。两次结果的**差集就是环境耦合**:

    干净通过 ∧ 带桩失败   → 环境耦合(本工具报告的主要目标)
    干净失败 ∧ 带桩通过   → 反向耦合,同样是耦合(用例在"依赖某服务存在")

为什么值得单开一个工具
----------------------
这类缺陷有三个共同点,决定了它逃得过一切常规手段:

1. **CI 恒绿**。runner 是干净的,所以问题永远只砸本机开发者。
2. **失败信息不提环境**。你看到的是 ``partial != native`` 或
   ``assert True is False``,不会有任何一行说"因为你装了 Ollama"。
3. **归因代价极高**。得先怀疑到环境,再想到是哪个服务,再去关掉它验证 ——
   而人的第一反应永远是"我刚改的东西弄坏了"。

本仓已确认两起(mesh worker toggle 的 nats-server、pr52 路由的 Ollama),
两起都是花了可观的时间才归因到环境。与其指望下次也想得到,不如让它**自动**暴露。

用法::

    python scripts/detect_environment_coupled_tests.py --shard 1 --of 4
    python scripts/detect_environment_coupled_tests.py --paths tests/test_foo.py
    python scripts/detect_environment_coupled_tests.py --strict   # 发现耦合就非零退出

刻意的设计
----------
* **不做增量**:两遍都跑完整的目标集合。只跑"上次失败的"会漏掉反向耦合。
* **按用例 id 比对**,不看计数 —— 计数相同不代表是同一批用例。
* 默认**只告警不失败**(与仓库里其它 guardrail 的引入方式一致);要当闸用加
  ``--strict``。新引入一个闸就让 CI 变红,只会让人学会无视它。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_SCRIPT = REPO_ROOT / "scripts" / "ambient_service_stubs.py"


def collect_target_files(shard: int, of: int, paths: List[str]) -> List[str]:
    """确定这次要跑哪些测试文件。"""
    if paths:
        return paths
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "ci_test_shard.py"), "--shard", str(shard), "--of", str(of)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def run_pytest(files: List[str], report: Path, extra_env: Dict[str, str]) -> None:
    """跑一遍 pytest 并落 junit 报告。**不关心退出码** —— 有失败是预期内的。"""
    env = {**os.environ, **extra_env}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            "not slow and not manual",
            f"--junitxml={report}",
            *files,
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )


def parse_outcomes(report: Path) -> Tuple[Set[str], Set[str]]:
    """从 junit 报告里读出 (通过集合, 失败集合)。

    junit 里 skipped 既不算通过也不算失败 —— 一个用例从"跑"变成"跳过"不是耦合,
    把它算进任一侧都会产生假阳性。
    """
    passed: Set[str] = set()
    failed: Set[str] = set()
    if not report.is_file():
        return passed, failed
    root = ET.parse(report).getroot()
    for case in root.iter("testcase"):
        node_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        children = {child.tag for child in case}
        if "skipped" in children:
            continue
        if children & {"failure", "error"}:
            failed.add(node_id)
        else:
            passed.add(node_id)
    return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shard", type=int, default=1)
    parser.add_argument("--of", type=int, default=1)
    parser.add_argument("--paths", nargs="*", default=[], help="直接指定测试路径(给了就忽略分片)")
    parser.add_argument("--strict", action="store_true", help="发现耦合就以非零码退出")
    args = parser.parse_args()

    files = collect_target_files(args.shard, args.of, args.paths)
    if not files:
        print("没有要跑的测试文件。")
        return 0
    print(f"目标:{len(files)} 个测试文件\n")

    with tempfile.TemporaryDirectory(prefix="env-coupling-") as tmp:
        clean_report = Path(tmp) / "clean.xml"
        stubbed_report = Path(tmp) / "stubbed.xml"

        print("── 第 1 遍:干净环境 ──", flush=True)
        run_pytest(files, clean_report, {})

        print("\n── 第 2 遍:起着环境桩 ──", flush=True)
        stub_proc = subprocess.Popen(
            [sys.executable, str(STUB_SCRIPT)],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            # 等桩就绪。用轮询而不是固定 sleep:固定 sleep 短了会漏起、长了白等,
            # 而"漏起"会让第二遍其实跑在干净环境里 —— 那就成了一个永远报"无耦合"
            # 的假绿工具,比没有更糟。
            import time

            sys.path.insert(0, str(REPO_ROOT / "scripts"))
            from ambient_service_stubs import OLLAMA_PORT, port_in_use  # noqa: PLC0415

            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not port_in_use(OLLAMA_PORT):
                time.sleep(0.2)
            if not port_in_use(OLLAMA_PORT):
                print("环境桩没能起来 —— 中止,免得产出一个假的『无耦合』结论。", file=sys.stderr)
                return 2

            # 同时把 NATS 总线的全局关闭撤掉:conftest 默认设 false(那是对的,
            # 见 tests/conftest.py),但本工具要探的正是"环境变了会怎样"。
            run_pytest(files, stubbed_report, {"GALAXY_NATS_ENABLED": "true"})
        finally:
            stub_proc.terminate()
            try:
                stub_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stub_proc.kill()

        clean_pass, clean_fail = parse_outcomes(clean_report)
        stub_pass, stub_fail = parse_outcomes(stubbed_report)

    broke = sorted(clean_pass & stub_fail)
    healed = sorted(clean_fail & stub_pass)

    print("\n" + "=" * 72)
    print(f"干净环境:  {len(clean_pass)} 通过 / {len(clean_fail)} 失败")
    print(f"带桩环境:  {len(stub_pass)} 通过 / {len(stub_fail)} 失败")
    print("=" * 72)

    if broke:
        print(f"\n❌ 环境耦合({len(broke)} 条):干净环境通过,起了环境桩就失败\n")
        for node_id in broke:
            print(f"  {node_id}")
        print("\n  这些用例的结论取决于机器上恰好有没有某个服务。CI 上恒绿,只砸本机开发者。")
        print("  修法不是让 CI 装那个服务,而是让用例**自己钉死前提**(注入桩/显式关掉那条通路)。")

    if healed:
        print(f"\n⚠️  反向耦合({len(healed)} 条):干净环境失败,起了环境桩才通过\n")
        for node_id in healed:
            print(f"  {node_id}")
        print("\n  这些用例在依赖某个服务**存在**。同样是耦合,只是方向相反。")

    if not broke and not healed:
        print("\n✅ 未发现环境耦合:两种环境下的通过/失败集合完全一致。")
        return 0

    if args.strict:
        print("\n以 --strict 运行,判定为失败。")
        return 1
    print("\n仅告警(加 --strict 可让它成为闸)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
