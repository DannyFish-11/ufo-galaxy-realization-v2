"""
Galaxy Bridge - 零破坏性桥接模块

功能：
1. 作为独立的"外骨骼"模块，不修改任何现有代码
2. 实现 galaxy 与微软 UFO 之间的双向互调
3. 自动检测两个系统的存在并建立连接
4. 提供统一的 API 接口供两个系统调用

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
import sys

# 添加路径以便导入两个系统的模块
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "galaxy_gateway"))

from core.port_config import get_service_port

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GalaxyBridge:
    """
    零破坏性桥接器
    
    作为独立的"外骨骼"，连接 galaxy 和微软 UFO
    """
    
    def __init__(self):
        self.galaxy_available = False
        self.microsoft_ufo_available = False
        self.galaxy_client = None
        self.microsoft_ufo_client = None
        
    async def initialize(self):
        """初始化桥接器，检测两个系统的可用性"""
        logger.info("🌉 初始化 Galaxy Bridge...")
        
        # 检测 galaxy
        await self._detect_galaxy()
        
        # 检测微软 UFO
        await self._detect_microsoft_ufo()
        
        if not self.galaxy_available and not self.microsoft_ufo_available:
            logger.warning("⚠️ 两个系统都不可用，桥接器将以离线模式运行")
        elif self.galaxy_available and self.microsoft_ufo_available:
            logger.info("✅ 两个系统都可用，桥接器已就绪")
        else:
            available = "galaxy" if self.galaxy_available else "微软 UFO"
            logger.info(f"ℹ️ 仅 {available} 可用")
    
    async def _detect_galaxy(self):
        """检测 galaxy 系统"""
        try:
            # 尝试导入 galaxy 的模块
            from aip_protocol_v2 import AIPMessage, MessageType
            
            # 尝试连接 Galaxy Gateway
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{get_service_port('state_machine')}/health", timeout=2) as resp:
                    if resp.status == 200:
                        self.galaxy_available = True
                        logger.info("✅ galaxy 系统已检测到")
                        return
        except Exception as e:
            logger.debug(f"galaxy 不可用: {e}")
        
        self.galaxy_available = False
    
    async def _detect_microsoft_ufo(self):
        """检测微软 UFO 系统"""
        try:
            # 尝试导入微软 UFO 的模块
            # 注意：这里假设微软 UFO 已安装在系统中
            import importlib.util
            spec = importlib.util.find_spec("galaxy")
            if spec is not None:
                # 尝试连接微软 UFO 的 Galaxy 服务
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://localhost:9000/health", timeout=2) as resp:
                        if resp.status == 200:
                            self.microsoft_ufo_available = True
                            logger.info("✅ 微软 UFO 系统已检测到")
                            return
        except Exception as e:
            logger.debug(f"微软 UFO 不可用: {e}")
        
        self.microsoft_ufo_available = False
    
    async def call_galaxy(self, node_id: int, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 galaxy 的节点
        
        Args:
            node_id: 节点 ID (如 90 表示 Node_90_MultimodalVision)
            action: 动作名称 (如 "analyze_screen")
            params: 参数字典
            
        Returns:
            执行结果
        """
        if not self.galaxy_available:
            return {"error": "galaxy 系统不可用"}
        
        try:
            import aiohttp
            url = f"http://localhost:{get_service_port('state_machine')}/node/{node_id}/{action}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params) as resp:
                    result = await resp.json()
                    logger.info(f"✅ 成功调用 galaxy Node_{node_id}.{action}")
                    return result
        except Exception as e:
            logger.error(f"❌ 调用 galaxy 失败: {e}")
            return {"error": str(e)}
    
    async def call_microsoft_ufo(self, agent_name: str, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用微软 UFO 的 Agent
        
        Args:
            agent_name: Agent 名称 (如 "app_agent")
            task: 任务描述
            params: 参数字典
            
        Returns:
            执行结果
        """
        if not self.microsoft_ufo_available:
            return {"error": "微软 UFO 系统不可用"}
        
        try:
            import aiohttp
            url = f"http://localhost:9000/agent/{agent_name}/execute"
            
            payload = {
                "task": task,
                "params": params
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    result = await resp.json()
                    logger.info(f"✅ 成功调用微软 UFO {agent_name}")
                    return result
        except Exception as e:
            logger.error(f"❌ 调用微软 UFO 失败: {e}")
            return {"error": str(e)}
    
    async def unified_vision_analysis(self, image_path: str, query: str) -> Dict[str, Any]:
        """
        统一的视觉分析接口
        
        优先使用 galaxy 的 Node_90，回退到微软 UFO（如果可用）
        
        Args:
            image_path: 图片路径
            query: 分析问题
            
        Returns:
            分析结果
        """
        # 优先使用 galaxy
        if self.galaxy_available:
            result = await self.call_galaxy(
                node_id=90,
                action="analyze_screen",
                params={
                    "query": query,
                    "image_path": image_path,
                    "provider": "auto"
                }
            )
            if "error" not in result:
                return result
        
        # 回退到微软 UFO
        if self.microsoft_ufo_available:
            result = await self.call_microsoft_ufo(
                agent_name="app_agent",
                task=f"分析图片: {query}",
                params={"image_path": image_path}
            )
            return result
        
        return {"error": "两个系统都不可用"}

# ============================================================================
# 独立运行示例
# ============================================================================

async def main():
    """示例：如何使用桥接器"""
    bridge = GalaxyBridge()
    await bridge.initialize()
    
    # 示例 1: 调用 galaxy 的视觉节点
    print("\n示例 1: 调用 galaxy Node_90")
    print("-" * 80)
    result = await bridge.call_galaxy(
        node_id=90,
        action="analyze_screen",
        params={
            "query": "这个屏幕上显示的是什么？",
            "provider": "qwen"
        }
    )
    print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    # 示例 2: 统一视觉分析接口
    print("\n示例 2: 统一视觉分析")
    print("-" * 80)
    result = await bridge.unified_vision_analysis(
        image_path="/path/to/screenshot.png",
        query="总结这个页面的主要内容"
    )
    print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())
