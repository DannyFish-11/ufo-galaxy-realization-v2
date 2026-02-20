#!/usr/bin/env python3
"""
UFO Galaxy - 主入口
===================

启动方式:
    python main.py

功能:
    - 启动 Dashboard 后端
    - 启动设备协调器
    - 启动所有节点服务

版本: v2.3.19
"""

import os
import sys
import asyncio
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("UFO-Galaxy")

# 版本
VERSION = "2.3.19"

def print_banner():
    """打印启动横幅"""
    print("""
============================================================
    _   _  ___  ___  ___   ___  ___  ___ 
    | | | || __|| _ \\/ __| / __|| __|| _ \\
    | |_| || _| |  _/\\__ \\ \\__ \\| _| |   /
    |___|_||___||_|  |___/ |___/|___||_|_\\
    
    Galaxy - L4 级群智能系统
    版本: {}
============================================================
    """.format(VERSION))

def check_dependencies():
    """检查依赖"""
    required = ['fastapi', 'uvicorn', 'pydantic', 'httpx', 'websockets']
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    if missing:
        logger.warning(f"缺少依赖: {missing}")
        logger.info("正在安装依赖...")
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install'] + missing, check=True)
    
    return True

def load_config():
    """加载配置"""
    config = {
        'host': os.getenv('GALAXY_HOST', '0.0.0.0'),
        'port': int(os.getenv('GALAXY_PORT', '8080')),
        'reload': os.getenv('GALAXY_DEBUG', 'false').lower() == 'true',
    }
    
    # 加载 .env 文件
    env_file = '.env'
    if os.path.exists(env_file):
        logger.info(f"加载配置文件: {env_file}")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())
    
    return config

def main():
    """主函数"""
    print_banner()
    
    logger.info(f"版本: {VERSION}")
    logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查依赖
    check_dependencies()
    
    # 加载配置
    config = load_config()
    
    logger.info("")
    logger.info("启动 HTTP 服务...")
    logger.info(f"访问地址: http://{config['host']}:{config['port']}")
    logger.info(f"API 文档: http://{config['host']}:{config['port']}/docs")
    logger.info("")
    
    # 启动 Dashboard 后端
    import uvicorn
    from dashboard.backend.main import app
    
    logger.info("============================================================")
    logger.info("Galaxy 系统启动完成")
    logger.info("============================================================")
    logger.info("")
    logger.info("API 端点:")
    logger.info("  POST /api/v1/devices/register  - 设备注册")
    logger.info("  POST /api/v1/chat              - 对话接口")
    logger.info("  POST /api/v1/tasks             - 任务提交")
    logger.info("  GET  /api/v1/devices           - 设备列表")
    logger.info("  WS   /ws                       - WebSocket")
    logger.info("============================================================")
    
    # 启动服务
    uvicorn.run(
        app,
        host=config['host'],
        port=config['port'],
        reload=config['reload']
    )

if __name__ == "__main__":
    main()
