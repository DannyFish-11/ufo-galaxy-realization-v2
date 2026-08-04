#!/usr/bin/env python3
"""
Galaxy 一键安装脚本
===================
自动检测平台，安装所需依赖，确保启动时依赖都在位。

用法:
    python install.py              # 只装核心
    python install.py --all        # 核心 + 增强 + Windows
    python install.py --core       # 只装核心
    python install.py --enhance    # 核心 + 增强

安装逻辑本身在 ``launcher/deps.py``
-----------------------------------
本文件现在只做**参数解析与呈现**，装什么、怎么装都问 :mod:`launcher.deps`。
这么改是因为原实现有一个真缺陷：它**一个镜像候选都没有**（``install.sh`` 有一个、
``main.py`` Phase 2 有三个），在国内网络下 ``pip install`` 基本必失败，而它自己
不会告诉你"换个源试试"。同一件事四份实现、四种抗弱网强度，谁也不知道别人有什么。

顺带修掉的第二个问题：原来 requirements 文件不存在时 ``install_file()`` 直接
``return True``，于是"跳过"和"装好了"在返回值上无法区分 —— 一个改名/打错的档位
会被报成安装成功。现在 :class:`~launcher.deps.InstallResult` 把
``skipped_reason`` 单独拿出来。
"""

import argparse
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from launcher import deps  # noqa: E402  (必须在 sys.path 调整之后)


def _report(label: str, result: deps.InstallResult) -> bool:
    """打印一条结果。返回它算不算成功（跳过也算，不阻塞）。"""
    if result.skipped_reason:
        print(f"  → {label}: 跳过（{result.skipped_reason}）")
        return True
    if result.ok:
        via = f"（源：{result.index_used}）" if result.index_used else ""
        print(f"  → {label}: ✓ {via}")
        return True
    print(f"  → {label}: ✗ 试了 {result.attempts} 个源都失败")
    if result.stderr_tail:
        print(f"    {result.stderr_tail.strip()[:200]}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Galaxy 依赖安装")
    parser.add_argument("--all", action="store_true", help="安装所有依赖")
    parser.add_argument("--core", action="store_true", help="只安装核心")
    parser.add_argument("--enhance", action="store_true", help="核心+增强")
    args = parser.parse_args()

    is_win = platform.system() == "Windows"

    print("=" * 60)
    print("  Galaxy 依赖安装")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  平台: {platform.system()} {platform.machine()}")
    candidates = deps.pip_index_candidates()
    print(f"  pip 源候选: {len(candidates)} 个（GALAXY_PIP_INDEX 可覆盖）")
    print("=" * 60)

    install_enhance = args.all or args.enhance
    install_windows = args.all and is_win
    if args.core:
        install_enhance = False
        install_windows = False

    results = []

    print("\n[1/4] 升级 pip...")
    results.append(_report("升级 pip", deps.pip_install(["pip"], upgrade=True, timeout=300)))

    print("\n[2/4] 安装核心依赖...")
    results.append(_report("核心依赖", deps.install_requirements("core")))

    if install_enhance:
        print("\n[3/4] 安装增强依赖...")
        results.append(_report("增强依赖", deps.install_requirements("enhance")))
    else:
        print("\n[3/4] 增强依赖: 跳过 (--enhance 或 --all 启用)")

    if install_windows:
        print("\n[4/4] 安装 Windows 依赖...")
        results.append(_report("Windows 依赖", deps.install_requirements("windows")))
    elif is_win:
        print("\n[4/4] Windows 依赖: 跳过 (--all 启用)")
    else:
        print("\n[4/4] Windows 依赖: 非 Windows 平台，跳过")

    print("\n" + "=" * 60)
    if all(results):
        print("  ✓ 全部安装成功")
        print("\n  启动命令:")
        print("    python main.py")
    else:
        print("  ⚠ 部分安装失败，但核心应该可用")
        print("  如需完整功能，运行: python install.py --all")
        print("  国内网络可指定源: GALAXY_PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
