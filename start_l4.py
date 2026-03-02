#!/usr/bin/env python3
"""
UFO Galaxy L4 级自主性智能系统启动脚本
"""

import asyncio
import logging
import json
import sys
import os
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

from galaxy_main_loop_l4 import GalaxyMainLoopL4


def load_config(config_path: str = "config/l4_config.json") -> dict:
    """加载配置文件"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning(f"配置文件 {config_path} 不存在，使用默认配置")
        return {}
    except json.JSONDecodeError as e:
        logging.error(f"配置文件解析错误: {e}")
        return {}


def setup_logging(config: dict):
    """设置日志"""
    log_config = config.get("logging", {})
    
    # 创建日志目录
    log_file = log_config.get("file", "logs/galaxy_l4.log")
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )


def print_banner():
    """打印启动横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║              UFO Galaxy L4 自主性智能系统                      ║
║                                                              ║
║  • 自主发现工具和资源                                          ║
║  • 自主编写代码解决问题                                        ║
║  • 自主设定和分解目标                                          ║
║  • 跨设备协同（安卓、无人机、3D打印机、量子计算）                ║
║  • 自我学习和优化                                             ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


async def main():
    """主函数"""
    # 打印横幅
    print_banner()
    
    # 加载配置
    config = load_config()
    
    # 设置日志
    setup_logging(config)
    
    logger = logging.getLogger("L4Startup")
    logger.info("=" * 60)
    logger.info("启动 UFO Galaxy L4 系统")
    logger.info("=" * 60)
    
    # 显示配置
    system_config = config.get("system", {})
    logger.info(f"系统名称: {system_config.get('name', 'UFO Galaxy L4')}")
    logger.info(f"系统版本: {system_config.get('version', '4.0.0')}")
    logger.info(f"运行模式: {system_config.get('mode', 'autonomous')}")
    
    # 显示启用的功能
    logger.info("启用的 L4 功能:")
    
    perception_config = config.get("perception", {})
    if perception_config.get("environment_scan_on_startup", True):
        logger.info("  ✓ 环境扫描")
    
    reasoning_config = config.get("reasoning", {})
    if reasoning_config.get("enable_goal_decomposition", True):
        logger.info("  ✓ 目标分解")
    if reasoning_config.get("enable_autonomous_planning", True):
        logger.info("  ✓ 自主规划")
    if reasoning_config.get("enable_world_model", True):
        logger.info("  ✓ 世界模型")
    
    learning_config = config.get("learning", {})
    if learning_config.get("enable_autonomous_learning", True):
        logger.info("  ✓ 自主学习")
    
    metacog_config = config.get("metacognition", {})
    if metacog_config.get("enable_self_reflection", True):
        logger.info("  ✓ 自我反思")
    
    coding_config = config.get("coding", {})
    if coding_config.get("enable_autonomous_coding", True):
        logger.info("  ✓ 自主编程")
    
    # 显示支持的设备
    devices_config = config.get("devices", {})
    logger.info("支持的设备:")
    for device_name, device_config in devices_config.items():
        if device_config.get("enabled", False):
            logger.info(f"  ✓ {device_name}")
    
    logger.info("=" * 60)
    
    # 创建主循环
    main_loop_config = config.get("main_loop", {})
    galaxy = GalaxyMainLoopL4(main_loop_config)
    
    # 启动系统
    try:
        logger.info("启动主循环...")
        await galaxy.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"致命错误: {e}", exc_info=True)
        raise
    finally:
        logger.info("系统已停止")


if __name__ == "__main__":
    asyncio.run(main())
