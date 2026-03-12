
import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional

import uvicorn
import httpx
from fastapi import FastAPI, HTTPException

try:
    from googlesearch import search as google_search
    _GOOGLESEARCH_AVAILABLE = True
except ImportError:
    google_search = None  # type: ignore
    _GOOGLESEARCH_AVAILABLE = False

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
    port: int = 8026

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
            description="一个用于执行Google搜索的Galaxy节点",
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
        self._app.post("/search/images", tags=["核心功能"], summary="图片搜索")(
            self.perform_image_search
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

    async def perform_search(self, query: str, num_results: Optional[int] = None) -> Dict[str, Any]:
        """执行 Google 网页搜索。优先使用 Custom Search API，否则回退至 googlesearch-python 库。"""
        self.logger.info(f"收到网页搜索请求: 查询='{query}'")
        try:
            results = await self._perform_search_impl(query, num_results, search_type="web")
            self.logger.info(f"为查询 '{query}' 成功获取 {len(results)} 条结果")
            return {"query": query, "search_type": "web", "results": results}
        except Exception as e:
            self.logger.error(f"执行搜索时发生严重错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            raise HTTPException(status_code=500, detail=f"搜索服务内部错误: {e}")

    async def perform_image_search(self, query: str, num_results: Optional[int] = None) -> Dict[str, Any]:
        """执行 Google 图片搜索（需要 GOOGLE_API_KEY 和 GOOGLE_CSE_ID）。"""
        self.logger.info(f"收到图片搜索请求: 查询='{query}'")
        api_key = os.getenv("GOOGLE_API_KEY", "")
        cse_id = os.getenv("GOOGLE_CSE_ID", "")
        if not api_key or not cse_id:
            raise HTTPException(
                status_code=503,
                detail="图片搜索需要 GOOGLE_API_KEY 和 GOOGLE_CSE_ID 环境变量",
            )
        try:
            results = await self._perform_search_impl(query, num_results, search_type="image")
            return {"query": query, "search_type": "image", "results": results}
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"图片搜索时发生错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            raise HTTPException(status_code=500, detail=f"图片搜索服务内部错误: {e}")

    async def _perform_search_impl(self, query: str, num_results: Optional[int], search_type: str = "web") -> List[str]:
        """统一搜索实现：优先 Custom Search API，回退 googlesearch-python（仅限网页）。"""
        cfg = self.config.search_config
        effective_num = num_results if num_results is not None else cfg.num_results
        api_key = os.getenv("GOOGLE_API_KEY", "")
        cse_id = os.getenv("GOOGLE_CSE_ID", "")

        if api_key and cse_id:
            return await self._perform_custom_search(query, effective_num, api_key, cse_id, search_type)

        if search_type == "image":
            raise HTTPException(
                status_code=503,
                detail="图片搜索需要 GOOGLE_API_KEY 和 GOOGLE_CSE_ID 环境变量",
            )
        return await self._perform_web_search(query, effective_num)

    async def _perform_custom_search(
        self, query: str, num_results: int, api_key: str, cse_id: str, search_type: str
    ) -> List[str]:
        """使用 Google Custom Search JSON API 执行搜索。"""
        self.logger.info(f"使用 Custom Search API 执行 {search_type} 搜索，结果数: {num_results}")
        params: Dict[str, Any] = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": min(num_results, 10),
        }
        if search_type == "image":
            params["searchType"] = "image"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if search_type == "image":
            return [item.get("link", "") for item in items]
        return [item.get("link", "") for item in items]

    async def _perform_web_search(self, query: str, num_results: int) -> List[str]:
        """使用 googlesearch-python 库执行网页搜索（同步库，通过 run_in_executor 包装）。"""
        if not _GOOGLESEARCH_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="googlesearch-python 库不可用，且未配置 GOOGLE_API_KEY/GOOGLE_CSE_ID",
            )
        loop = asyncio.get_running_loop()
        cfg = self.config.search_config
        self.logger.info(f"使用 googlesearch-python 搜索，目标结果数: {num_results}")
        try:
            search_results = await loop.run_in_executor(
                None,
                lambda: list(google_search(
                    query=query,
                    num=num_results,
                    stop=num_results,
                    pause=cfg.pause,
                    lang=cfg.lang,
                    user_agent=cfg.user_agent,
                )),
            )
            return search_results
        except Exception as e:
            self.logger.error(f"googlesearch库调用失败: {e}", exc_info=True)
            if "HTTP Error 429" in str(e):
                self.logger.warning("收到HTTP 429，可能需要增加 pause 时间或更换 IP")
                self.status = NodeStatus.DEGRADED
            else:
                self.status = NodeStatus.ERROR
            raise

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
        port=int(os.getenv("API_PORT", 8026))
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
    logging.info("            Galaxy - Google Search Node      ")
    logging.info("==================================================")
    
    # 使用asyncio.run来运行异步主函数
    # 注意：uvicorn.run()本身是阻塞的，所以这里实际上不会在main()返回后继续执行
    # 这种结构是为了保持异步代码的一致性
    asyncio.run(main())

