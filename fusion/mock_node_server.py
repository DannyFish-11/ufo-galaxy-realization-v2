#!/usr/bin/env python3
"""
Galaxy Fusion - Mock Node Server

模拟节点服务器

用于演示和测试，模拟 102 个节点的 API 响应

作者: Galaxy Team
日期: 2026-01-25
版本: 1.0.0
"""

import asyncio
import logging
from pathlib import Path
import sys
import json
from typing import Dict, Any
from aiohttp import web
import random

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class MockNodeServer:
    """
    模拟节点服务器
    
    为每个节点提供基本的 HTTP API
    """
    
    def __init__(self, node_config: Dict[str, Any]):
        """
        初始化模拟节点服务器
        
        Args:
            node_config: 节点配置
        """
        self.node_id = node_config["id"]
        self.node_name = node_config["name"]
        self.layer = node_config["layer"]
        self.domain = node_config["domain"]
        self.capabilities = node_config.get("capabilities", [])
        # 使用更高的端口范围避免冲突 (9000+)
        original_port = int(node_config["api_url"].split(":")[-1])
        self.port = 9000 + (original_port - 8000)
        
        self.app = web.Application()
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_post('/execute', self.execute_command)
        self.app.router.add_get('/info', self.get_info)
        
        # 统计
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0
        }
    
    async def health_check(self, request):
        """健康检查"""
        return web.json_response({
            "status": "healthy",
            "node_id": self.node_id,
            "node_name": self.node_name,
            "layer": self.layer,
            "domain": self.domain
        })
    
    async def execute_command(self, request):
        """执行命令"""
        try:
            data = await request.json()
            command = data.get("command")
            params = data.get("params", {})
            
            self.stats["total_requests"] += 1
            
            # 模拟处理延迟
            await asyncio.sleep(random.uniform(0.01, 0.05))
            
            # 模拟执行结果
            result = {
                "node_id": self.node_id,
                "node_name": self.node_name,
                "command": command,
                "status": "success",
                "result": {
                    "message": f"Command '{command}' executed successfully on {self.node_name}",
                    "layer": self.layer,
                    "domain": self.domain,
                    "capabilities_used": params.get("capabilities", []),
                    "data": {
                        "processed": True,
                        "timestamp": asyncio.get_running_loop().time()
                    }
                }
            }
            
            self.stats["successful_requests"] += 1
            
            return web.json_response(result)
        
        except Exception as e:
            self.stats["failed_requests"] += 1
            
            logger.error(f"❌ Error executing command on {self.node_id}: {e}")
            
            return web.json_response({
                "node_id": self.node_id,
                "status": "error",
                "error": str(e)
            }, status=500)
    
    async def get_info(self, request):
        """获取节点信息"""
        return web.json_response({
            "node_id": self.node_id,
            "node_name": self.node_name,
            "layer": self.layer,
            "domain": self.domain,
            "capabilities": self.capabilities,
            "port": self.port,
            "stats": self.stats
        })
    
    async def start(self):
        """启动服务器"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', self.port)
        await site.start()
        logger.info(f"✅ Mock node started: {self.node_id} ({self.node_name}) on port {self.port}")


async def start_all_mock_nodes(topology_config_path: str):
    """
    启动所有模拟节点
    
    Args:
        topology_config_path: 拓扑配置文件路径
    """
    logger.info("="*80)
    logger.info("🚀 Starting Mock Node Servers")
    logger.info("="*80)
    
    # 加载拓扑配置
    with open(topology_config_path, 'r') as f:
        topology_data = json.load(f)
    
    nodes = topology_data.get("nodes", [])
    logger.info(f"📊 Total nodes to start: {len(nodes)}")
    
    # 创建所有模拟节点服务器
    servers = []
    for node_config in nodes:
        server = MockNodeServer(node_config)
        servers.append(server)
    
    # 启动所有服务器
    logger.info("🔄 Starting all mock nodes...")
    
    tasks = [server.start() for server in servers]
    await asyncio.gather(*tasks)
    
    logger.info("="*80)
    logger.info(f"✅ All {len(servers)} mock nodes started successfully!")
    logger.info("="*80)
    logger.info("")
    logger.info("📊 Node Distribution:")
    
    # 统计分布
    layer_counts = {}
    domain_counts = {}
    
    for node_config in nodes:
        layer = node_config["layer"]
        domain = node_config["domain"]
        
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
    
    logger.info(f"   Layers: {layer_counts}")
    logger.info(f"   Domains: {len(domain_counts)} unique domains")
    logger.info("")
    logger.info("🎯 Mock nodes are ready to accept requests!")
    logger.info("   Press Ctrl+C to stop all nodes")
    logger.info("")
    
    # 保持运行
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Stopping all mock nodes...")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Mock Node Server for Galaxy Fusion")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config" / "topology.json"),
        help="Path to topology config file"
    )
    
    args = parser.parse_args()
    
    try:
        asyncio.run(start_all_mock_nodes(args.config))
    except KeyboardInterrupt:
        logger.info("\n✅ All mock nodes stopped")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
