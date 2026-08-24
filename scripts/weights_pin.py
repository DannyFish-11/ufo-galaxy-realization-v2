#!/usr/bin/env python3
"""权重自带代码的指纹钉子 —— 人显式做的那个动作。

为什么是个命令行工具,而不是一个 HTTP 端点
------------------------------------------
``core.weights_admission`` 里写死了"钉子必须是人显式做的动作":自动钉住等于
"第一次见到什么就信什么",那样只挡得住"上游后来改了",挡不住"上游一开始就是坏的"。

而它**不该是 HTTP 端点** —— 那等于让任何能打到这个端口的人给自己想执行的代码盖章。
钉子是本机操作,就该在本机做。

用法
----
看当前姿态(不改任何东西)::

    python3 scripts/weights_pin.py --report

看某个模型现在会被怎么判::

    python3 scripts/weights_pin.py --check Qwen/Qwen3-8B --path models/qwen3-8b

确认过那些 ``.py`` **之后**再钉住::

    python3 scripts/weights_pin.py --pin Qwen/Qwen3-8B --path models/qwen3-8b

注意 ``--pin`` 只记录"当前是什么样",它**不审查代码好坏** —— 那是你看那几个文件时
要做的事。这个工具会先把会被执行的文件列出来,就是为了让这一步没法跳过。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.weights_admission import (  # noqa: E402
    evaluate,
    pin_remote_code,
    remote_code_files,
    remote_code_fingerprint,
    weights_report,
)


def _cmd_report() -> int:
    print(json.dumps(weights_report(), ensure_ascii=False, indent=2))
    return 0


def _cmd_check(model: str, path: str | None) -> int:
    decision = evaluate(model, local_path=path)
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    # 判定本身不是失败:这个子命令是用来"看"的。返回 0,让它能进管道。
    return 0


def _cmd_pin(model: str, path: str | None) -> int:
    if not path:
        print("--pin 需要 --path:指纹是按本地文件算的,没有本地文件就算不出来", file=sys.stderr)
        return 2

    files = remote_code_files(path)
    if not files:
        print(f"{path} 里没有 .py —— 这个模型没有自带代码,不需要钉。")
        return 0

    print(f"以下 {len(files)} 个文件会在加载时**被执行**,钉住之前请逐个看过:")
    for entry in files:
        print(f"  {entry}")

    fingerprint = remote_code_fingerprint(path)
    if not fingerprint:
        print("指纹算不出来(文件读不动?)—— 没有钉。", file=sys.stderr)
        return 1

    if not pin_remote_code(model, fingerprint):
        print("钉子写不进去。", file=sys.stderr)
        return 1

    print(f"\n已钉住 {model}: {fingerprint[:16]}…")
    print("提醒:钉住只保证「以后变了会被发现」,不保证「现在这份是干净的」。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", action="store_true", help="打印当前权重准入姿态")
    group.add_argument("--check", metavar="MODEL", help="看这个模型现在会被怎么判")
    group.add_argument("--pin", metavar="MODEL", help="钉住这个模型自带代码的当前指纹")
    parser.add_argument("--path", help="模型的本地目录")
    args = parser.parse_args()

    if args.report:
        return _cmd_report()
    if args.check:
        return _cmd_check(args.check, args.path)
    return _cmd_pin(args.pin, args.path)


if __name__ == "__main__":
    raise SystemExit(main())
