#!/usr/bin/env python3
"""
UFO Galaxy Fusion - Unified Startup Script (Reinforced)

统一启动脚本（加固版）

功能:
1. 启动统一节点网关 (Unified Node Gateway)
2. 启动统一编排引擎 (Unified Orchestrator)
3. 运行演示任务或进入交互模式
4. 优雅处理系统信号和资源清理

作者: Manus AI
日期: 2026-01-26
版本: 1.2.0 (加固版)
"""

import asyncio
import logging
import sys
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fusion.topology_manager import TopologyManager
from fusion.unified_orchestrator import UnifiedOrchestrator, Task, TaskType, TaskPriority
from fusion.node_executor import ExecutionPool

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / 'logs' / 'fusion.log', mode='a')
    ]
)
logger = logging.getLogger("FusionStartup")

class FusionSystem:
    """
    融合系统 - 统一的系统入口
    """
    
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.topology_manager: Optional[TopologyManager] = None
        self.execution_pool: Optional[ExecutionPool] = None
        self.orchestrator: Optional[UnifiedOrchestrator] = None
        self.gateway_process: Optional[subprocess.Popen] = None
        self.is_running = False
        
        # 创建日志目录
        (PROJECT_ROOT / 'logs').mkdir(exist_ok=True)

    async def start_gateway(self):
        """启动统一节点网关进程"""
        logger.info("🚀 Starting Unified Node Gateway...")
        gateway_script = PROJECT_ROOT / "galaxy_gateway" / "unified_node_gateway.py"
        
        # 使用 subprocess 启动网关
        self.gateway_process = subprocess.Popen(
            [sys.executable, str(gateway_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # 等待网关启动并检查状态
        logger.info("⏳ Waiting for gateway to initialize...")
        await asyncio.sleep(3)
        if self.gateway_process.poll() is None:
            logger.info("✅ Gateway process started (PID: %d)", self.gateway_process.pid)
        else:
            logger.error("❌ Gateway process failed to start")
            raise RuntimeError("Gateway failed to start")

    async def initialize(self):
        """初始化系统组件"""
        logger.info("📋 Initializing Fusion System Components...")
        
        # 1. 加载拓扑配置
        topology_config = self.config_path / "topology.json"
        self.topology_manager = TopologyManager(str(topology_config))
        
        # 2. 初始化执行池 (指向统一网关)
        self.execution_pool = ExecutionPool(gateway_url="http://localhost:8000")
        
        # 3. 初始化统一编排引擎
        self.orchestrator = UnifiedOrchestrator(
            topology_manager=self.topology_manager,
            execution_pool=self.execution_pool
        )
        
        await self.orchestrator.start()
        self.is_running = True
        logger.info("✅ Fusion System initialized successfully")

    async def stop(self):
        """优雅停止系统"""
        if not self.is_running:
            return
        
        logger.info("🛑 Stopping Fusion System...")
        self.is_running = False
        
        if self.orchestrator:
            await self.orchestrator.stop()
        
        if self.execution_pool:
            await self.execution_pool.close_all()
            
        if self.gateway_process:
            logger.info("Terminating gateway process...")
            self.gateway_process.terminate()
            try:
                self.gateway_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.gateway_process.kill()
            
        logger.info("✅ Fusion System stopped")

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """执行任务"""
        if not self.orchestrator:
            raise RuntimeError("Orchestrator not initialized")
        return await self.orchestrator.execute_task(task)

async def run_demo():
    """运行演示模式"""
    system = FusionSystem(str(PROJECT_ROOT / "config"))
    
    try:
        # 1. 启动网关
        await system.start_gateway()
        
        # 2. 初始化系统
        await system.initialize()
        
        # 3. 运行演示任务
        logger.info("="*80)
        logger.info("📝 Running Demo Task: Hybrid Analysis")
        logger.info("="*80)
        
        task = Task(
            task_id=f"demo_{int(time.time())}",
            description="Perform a cross-layer analysis of system state and security",
            task_type=TaskType.HYBRID,
            priority=TaskPriority.HIGH,
            required_capabilities=["vision", "analysis", "coordination"]
        )
        
        result = await system.execute_task(task)
        logger.info("🏁 Demo Task Result: %s", result)
        
    except Exception as e:
        logger.error("❌ Demo failed: %s", e, exc_info=True)
    finally:
        await system.stop()

def main():
    """主入口"""
    import argparse
    parser = argparse.ArgumentParser(description="UFO Galaxy Fusion System")
    parser.add_argument("--mode", choices=["demo", "interactive"], default="demo")
    args = parser.parse_args()
    
    try:
        if args.mode == "demo":
            asyncio.run(run_demo())
        else:
            logger.info("Interactive mode not implemented in reinforced version yet.")
    except KeyboardInterrupt:
        logger.info("\n🛑 Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
