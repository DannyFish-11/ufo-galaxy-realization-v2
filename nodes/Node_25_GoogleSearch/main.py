
import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from googlesearch import search as google_search

# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("node_25_google_search.log")
    ]
)

# --- 枚举定义 ---

class NodeStatus(Enum):
    """定义节点的运行状态"""
    INITIALIZING = "初始化中"
    RUNNING = "运行中"
    STOPPED = "已停止"
    ERROR = "错误"
    DEGRADED = "降级运行"

class SearchType(Enum):
    """定义支持的搜索类型"""
    WEB = "web"
    IMAGE = "image" # 注意：googlesearch库本身不直接支持图片搜索，这里为API结构完整性

# --- 数据类定义 ---

@dataclass
class SearchConfig:
    """存储搜索相关的配置"""
    num_results: int = 10
    lang: str = "en"
    stop: int = 10
    pause: float = 2.0
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

@dataclass
class APIConfig:
    """存储API服务器的配置"""
    host: str = "0.0.0.0"
    port: int = 8000

@dataclass
class NodeConfig:
    """节点主配置"""
    node_name: str = "Node_25_GoogleSearch"
    search_config: SearchConfig = field(default_factory=SearchConfig)
    api_config: APIConfig = field(default_factory=APIConfig)

# --- 主服务类 ---

class GoogleSearchNode:
    """实现Google搜索功能的节点服务"""

    def __init__(self, config: NodeConfig):
        """初始化节点服务"""
        self.config = config
        self.status = NodeStatus.INITIALIZING
        self.logger = logging.getLogger(self.config.node_name)
        self.logger.info(f"节点 {self.config.node_name} 正在初始化...")
        self._app = FastAPI(
            title=self.config.node_name,
            description="一个用于执行Google搜索的UFO Galaxy节点",
            version="1.0.0"
        )
        self._setup_routes()
        self.status = NodeStatus.RUNNING
        self.logger.info(f"节点 {self.config.node_name} 初始化完成，状态: {self.status.value}")

    def _setup_routes(self):
        """配置FastAPI的路由"""
        self.logger.info("正在设置API路由...")
        self._app.get("/health", tags=["监控"], summary="健康检查")(
            self.health_check
        )
        self._app.get("/status", tags=["监控"], summary="状态查询")(
            self.get_status
        )
        self._app.post("/search", tags=["核心功能"], summary="执行搜索")(
            self.perform_search
        )
        self.logger.info("API路由设置完成")

    async def health_check(self) -> Dict[str, Any]:
        """提供节点的健康检查端点"""
        self.logger.debug("收到健康检查请求")
        return {"status": "ok", "node_name": self.config.node_name}

    async def get_status(self) -> Dict[str, Any]:
        """提供节点当前状态的查询端点"""
        self.logger.debug("收到状态查询请求")
        return {
            "node_name": self.config.node_name,
            "status": self.status.value,
            "config": self.config
        }

    async def perform_search(self, query: str, search_type: SearchType = SearchType.WEB, num_results: Optional[int] = None) -> Dict[str, Any]:
        """
        核心业务逻辑：执行Google搜索

        Args:
            query (str): 搜索查询词
            search_type (SearchType): 搜索类型 (web/image)
            num_results (Optional[int]): 需要返回的结果数量，如果未提供则使用默认配置

        Returns:
            Dict[str, Any]: 包含搜索结果的字典
        """
        self.logger.info(f"收到新的搜索请求: 类型='{search_type.value}', 查询='{query}'")

        if search_type == SearchType.IMAGE:
            self.logger.warning("图片搜索功能当前为模拟实现，返回结果为网页搜索结果。")
            # 实际项目中，这里应该替换为一个真正的图片搜索API或库
            # return await self._perform_image_search(query, num_results)

        try:
            results = await self._perform_web_search(query, num_results)
            self.logger.info(f"为查询 '{query}' 成功获取 {len(results)} 条结果")
            return {"query": query, "search_type": search_type.value, "results": results}
        except Exception as e:
            self.logger.error(f"执行搜索时发生严重错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            raise HTTPException(status_code=500, detail=f"搜索服务内部错误: {e}")

    async def _perform_web_search(self, query: str, num_results: Optional[int]) -> List[str]:
        """
        执行实际的网页搜索操作
        由于 `googlesearch` 库是同步的，我们在异步函数中通过 `run_in_executor` 运行它以避免阻塞事件循环
        """
        loop = asyncio.get_running_loop()
        cfg = self.config.search_config
        
        effective_num_results = num_results if num_results is not None else cfg.num_results
        
        self.logger.info(f"开始执行网页搜索，目标结果数: {effective_num_results}")

        try:
            # 在默认的executor中运行同步的搜索函数
            search_results = await loop.run_in_executor(
                None,  # 使用默认的ThreadPoolExecutor
                lambda: list(google_search(
                    query=query,
                    num=effective_num_results,
                    stop=effective_num_results,
                    pause=cfg.pause,
                    lang=cfg.lang,
                    user_agent=cfg.user_agent
                ))
            )
            return search_results
        except Exception as e:
            self.logger.error(f"googlesearch库调用失败: {e}", exc_info=True)
            # 这里可以根据错误类型进行更细致的处理，例如区分网络问题和请求被阻止
            if "HTTP Error 429" in str(e):
                self.logger.warning("收到HTTP 429 Too Many Requests错误，可能需要增加pause时间或更换IP")
                self.status = NodeStatus.DEGRADED
            else:
                self.status = NodeStatus.ERROR
            raise  # 重新抛出异常，由上层处理

    def run(self):
        """启动节点服务，运行FastAPI应用"""
        self.logger.info(f"准备在 {self.config.api_config.host}:{self.config.api_config.port} 启动API服务器...")
        try:
            uvicorn.run(
                self._app, 
                host=self.config.api_config.host, 
                port=self.config.api_config.port
            )
        except Exception as e:
            self.logger.critical(f"无法启动Uvicorn服务器: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
        finally:
            self.status = NodeStatus.STOPPED
            self.logger.info(f"节点 {self.config.node_name} 已停止")

# --- 辅助函数和主程序入口 ---

def load_config_from_env() -> NodeConfig:
    """从环境变量加载配置，提供默认值"""
    logging.info("从环境变量加载配置...")
    search_cfg = SearchConfig(
        num_results=int(os.getenv("SEARCH_NUM_RESULTS", 10)),
        lang=os.getenv("SEARCH_LANG", "en"),
        pause=float(os.getenv("SEARCH_PAUSE", 2.0))
    )
    api_cfg = APIConfig(
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000))
    )
    return NodeConfig(
        search_config=search_cfg,
        api_config=api_cfg
    )

async def main():
    """异步主函数，用于设置和运行节点"""
    try:
        # 1. 加载配置
        config = load_config_from_env()

        # 2. 创建节点实例
        node = GoogleSearchNode(config)

        # 3. 启动服务 (这是一个阻塞调用)
        # 在实际的异步应用中，我们可能会用更复杂的方式来管理服务的生命周期
        # 但对于uvicorn.run()，它会接管事件循环
        node.run()

    except Exception as e:
        logging.critical(f"节点启动过程中发生致命错误: {e}", exc_info=True)
        # 确保即使在启动失败时也能记录日志

if __name__ == "__main__":
    # 检查必要的依赖
    try:
        import fastapi
        import uvicorn
        import googlesearch
    except ImportError as e:
        logging.critical(f"缺少必要的依赖: {e}。请运行 'pip install fastapi uvicorn googlesearch-python' 安装。")
        exit(1)

    logging.info("==================================================")
    logging.info("            UFO Galaxy - Google Search Node      ")
    logging.info("==================================================")
    
    # 使用asyncio.run来运行异步主函数
    # 注意：uvicorn.run()本身是阻塞的，所以这里实际上不会在main()返回后继续执行
    # 这种结构是为了保持异步代码的一致性
    asyncio.run(main())

