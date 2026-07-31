#!/usr/bin/env python3
"""把 tests/ 切成若干份,给 CI 的 matrix 分片用。

## 修的是什么

`test` 作业在一个进程里跑完 4 万多条用例。跑到尾部(~99%)时 runner 被回收,
GitHub 打出 "The runner has received a shutdown signal"。**连续 5 次同一形态。**

日志时间戳给出了根因 —— 同一文件里两条相邻的**纯结构断言**(读源码、比字符串,
本该是毫秒级):

    02:15:08  test_delegation_helpers_are_not_public_api  PASSED [99%]
    02:27:09  ##[error] runner has received a shutdown signal
    02:27:10  test_intent_handler_map_present             PASSED [100%]

两条之间隔了 **12 分钟**。这不是"慢",是机器在换页(thrash):一个进程扛了
4 万多条用例累积下来的内存,到尾部把 runner 压垮。

## 为什么已有的两套机制救不回来

仓库里已经装了 `pytest-timeout`(per-test 120s,signal 方式)并加了
`faulthandler_timeout`(独立看门狗线程)。pytest.ini 里如实记着它们在 CI 上
**都没走通**,一条 Timeout 行都没打出来。

原因现在清楚了:**两套都是 per-test 的**,而停顿发生在两条用例**之间** ——
两条各自都 PASSED,卡在收集/拆解/GC 那段。没有任何一条单独用例超时,
per-test 计时器自然永远不触发。

所以对症的修法不是再加一个 per-test 计时器,而是**让单个进程少扛一点**。

## 切法

按**排序后的文件名轮转**(round-robin)分配,而不是按目录切:

- 目录切会极不均匀(tests/ 顶层近千个文件,子目录寥寥);
- 轮转让重的文件天然散开到各分片;
- 纯函数、不需要先 collect(collect 本身在这个仓库就要几十秒),
  给定 (文件全集, n) 结果完全确定,任何机器上都一样。

**完整性由 tests/test_ci_test_shard.py 守住**:并集必须等于全集、两两不相交。
分片最怕的不是慢,是**悄悄漏掉一批用例还显示绿灯**。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


def all_test_files(tests_dir: Path = TESTS_DIR) -> List[str]:
    """全部测试文件,仓库相对路径,已排序。

    排序是分片确定性的前提 —— 文件系统的遍历顺序不保证稳定,不排序的话
    同一次提交在两台机器上会切出不同的分片。
    """
    files = [
        str(p.relative_to(REPO_ROOT).as_posix()) for p in tests_dir.rglob("test_*.py") if "__pycache__" not in p.parts
    ]
    return sorted(files)


def shard(files: List[str], index: int, total: int) -> List[str]:
    """取第 ``index`` 份(1-based),共 ``total`` 份。

    轮转分配:第 i 个文件归第 ``i % total`` 份。
    """
    if total < 1:
        raise ValueError(f"分片总数必须 >= 1,收到 {total}")
    if not 1 <= index <= total:
        raise ValueError(f"分片序号必须在 1..{total} 内,收到 {index}")
    return [f for i, f in enumerate(files) if i % total == (index - 1)]


def main() -> int:
    ap = argparse.ArgumentParser(description="打印本分片应跑的测试文件")
    ap.add_argument("--shard", type=int, required=True, help="分片序号(1-based)")
    ap.add_argument("--of", type=int, required=True, help="分片总数")
    args = ap.parse_args()

    files = all_test_files()
    if not files:
        print("未找到任何测试文件 —— 分片脚本拒绝输出空集合", file=sys.stderr)
        return 1

    picked = shard(files, args.shard, args.of)
    if not picked:
        # 分片数大于文件数时可能为空。空集合会让 pytest 退出码 5(no tests
        # collected)把作业判红 —— 那是配置错误,要报出来而不是静默通过。
        print(f"分片 {args.shard}/{args.of} 为空(共 {len(files)} 个文件)", file=sys.stderr)
        return 1

    print("\n".join(picked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
