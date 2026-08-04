#!/usr/bin/env python3
# PR-WIN-ENCODING: Defensive UTF-8 re-config for standalone launch on Windows.
import sys


def _configure_windows_console() -> None:
    """Windows 下把控制台切到 UTF-8;只在本文件被当作脚本运行时调用。

    与 main.py / unified_launcher.py / launch_desktop.py 同一处理:以前这段是
    无条件的模块级代码,``import system_manager`` 就会重写调用方的
    sys.stdout/sys.stderr 并改写进程环境变量。import 不该有这种越权副作用;
    脚本模式(``python system_manager.py``)行为不变。
    """
    if sys.platform != "win32":
        return
    try:
        import io, os

        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        os.environ["PYTHONIOENCODING"] = "utf-8:replace"
    except Exception:
        pass


if __name__ == "__main__":
    _configure_windows_console()
"""
Galaxy 系统管理器 v2.0 (修复版)
=================================

[NODE ORCHESTRATION HELPER — not a configuration authority]

This script is a node lifecycle manager.  It reads node metadata from
``config/unified_config.json`` but defers port resolution to the canonical
port authority: ``config/unified_ports.yaml`` via ``core.port_config``.

Port precedence applied by ConfigManager
-----------------------------------------
1. config/unified_ports.yaml (via core.port_config)  — canonical source
2. config/unified_config.json                         — fallback if port_config unavailable
3. Hardcoded defaults in _get_default_nodes()         — last resort

For the full configuration authority model see docs/CONFIGURATION_AUTHORITY.md.

修复内容:
- 使用 unified_config.json 统一配置
- 完整支持所有102个节点
- 端口配置与统一端口分配对齐

统一管理所有节点的启动、停止、监控和健康检查

功能：
1. 一键启动/停止所有节点
2. 分组管理（9个分组）
3. 实时监控节点状态
4. 自动重启失败的节点
5. 生成系统报告

作者: Manus AI
版本: 2.0
日期: 2026-01-23
"""

import asyncio
import json

# 颜色码从新家 re-export —— CLI 的输出风格要与搬迁前逐字一致。
from launcher.nodes import CYAN, RESET

# =============================================================================
# 实现体已搬到 launcher/nodes.py —— 本文件只剩 CLI 外壳
# =============================================================================
#
# 统一启动器的目标是"所有启动器收敛到 main.py 一个入口,各自真实有效的要素保留、
# 本体删掉"。节点生命周期(NodeConfig / ConfigManager / NODES / SystemManager)
# 已【原样搬迁】到 launcher/nodes.py —— 是移动,不是重写:这 500 多行里有大量真机
# 故障攒出来的细节(端口权威解析、能力/连接管理器的非致命降级、按组优先级启动、
# 健康探针……),手抄必丢。
#
# 本文件在步骤 8 与其余三个启动器本体一起删除。在那之前它保持可用,因为
# docs/guides/QUICKSTART.md 与 docs/CONFIGURATION_AUTHORITY.md 刚刚才把用户
# 指引改成 `python main.py nodes`,老命令要有一段并存期。
from launcher.nodes import (  # noqa: F401  (re-export,供既有 import 继续可用)
    NODES,
    ConfigManager,
    NodeConfig,
    SystemManager,
)

# =============================================================================
# CLI
# =============================================================================


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Galaxy 系统管理器 v2.0")
    parser.add_argument("command", choices=["start", "stop", "status", "monitor", "report"], help="命令")
    parser.add_argument(
        "--group",
        "-g",
        choices=[
            "core",
            "tools",
            "physical",
            "intelligence",
            "monitoring",
            "advanced",
            "orchestration",
            "multimodal",
            "academic",
            "all",
        ],
        default="all",
        help="节点组",
    )
    parser.add_argument("--interval", "-i", type=int, default=30, help="监控间隔（秒）")

    args = parser.parse_args()

    manager = SystemManager()

    if args.command == "start":
        if args.group == "all":
            await manager.start_all()
        else:
            await manager.start_group(args.group)

        # 保持运行
        print(f"\n{CYAN}系统正在运行，按 Ctrl+C 停止{RESET}\n")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            manager.stop_all()

    elif args.command == "stop":
        manager.stop_all()

    elif args.command == "status":
        await manager.check_all_nodes()

    elif args.command == "monitor":
        await manager.monitor(args.interval)

    elif args.command == "report":
        report = await manager.generate_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    print(f"""
{CYAN}╔═══════════════════════════════════════════════════════════════╗
║   Galaxy System Manager v2.0                             ║
║   102 Nodes | Unified Config | Port Conflict Fixed            ║
╚═══════════════════════════════════════════════════════════════╝{RESET}
""")
    asyncio.run(main())
