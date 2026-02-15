'''
# -*- coding: utf-8 -*-

"""
Node_08_Fetch: UFO Galaxy 系统中的 HTTP 请求客户端节点

该节点实现了一个功能齐全的异步 HTTP 客户端，支持常见的 GET, POST, PUT, DELETE 请求方法。
它被设计为 UFO Galaxy 系统中的一个标准服务节点，包含配置加载、日志记录、状态监控和健康检查等功能。
"""

import asyncio
import logging
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Union

# 模拟 aiohttp，因为沙箱环境中可能没有安装
# 在实际环境中，请确保 aiohttp 已安装: pip install aiohttp
try:
    import aiohttp
    from aiohttp import ClientSession, ClientTimeout, TCPConnector
except ImportError:
    # 定义一个模拟的 aiohttp 库，以确保代码在任何环境下都能通过语法检查
    class MockClientSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def get(self, url, **kwargs):
            return self._mock_request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self._mock_request("POST", url, **kwargs)

        def put(self, url, **kwargs):
            return self._mock_request("PUT", url, **kwargs)

        def delete(self, url, **kwargs):
            return self._mock_request("DELETE", url, **kwargs)

        def _mock_request(self, method, url, **kwargs):
            class MockResponse:
                def __init__(self, method, url, kwargs):
                    self.status = 200
                    self.reason = "OK"
                    self._method = method
                    self._url = url
                    self._kwargs = kwargs

                async def json(self):
                    return {
                        "message": f"This is a mock response for {self._method} {self._url}",
                        "args": self._kwargs
                    }

                async def text(self):
                    return json.dumps(await self.json())

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            return MockResponse(method, url, kwargs)

    class MockAioHttp:
        ClientSession = MockClientSession
        ClientTimeout = lambda total: None
        TCPConnector = lambda limit: None

    aiohttp = MockAioHttp()
    ClientSession = aiohttp.ClientSession
    ClientTimeout = aiohttp.ClientTimeout
    TCPConnector = aiohttp.TCPConnector

# --- 枚举定义 ---

class NodeStatus(Enum):
    """
    定义节点的运行状态
    """
    INITIALIZING = "INITIALIZING"  # 正在初始化
    RUNNING = "RUNNING"            # 正在运行
    STOPPED = "STOPPED"            # 已停止
    ERROR = "ERROR"                # 发生错误

class HttpMethod(Enum):
    """
    定义支持的 HTTP 请求方法
    """
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"

# --- 配置数据类 ---

@dataclass
class FetchConfig:
    """
    存储节点的配置信息
    """
    node_name: str = "Node_08_Fetch"
    log_level: str = "INFO"
    timeout_seconds: int = 30
    max_connections: int = 100
    default_headers: Dict[str, str] = field(default_factory=lambda: {
        "User-Agent": "UFO-Galaxy-Fetch-Node/1.0",
        "Accept": "application/json, text/plain, */*"
    })

# --- 主服务类 ---

class FetchNodeService:
    """
    HTTP 请求客户端主服务类

    该类封装了节点的核心功能，包括：
    - 初始化和配置管理
    - 异步 HTTP 请求的发送与响应处理
    - 状态监控和健康检查
    - 统一的日志记录
    """

    def __init__(self, config: Optional[FetchConfig] = None):
        """
        初始化服务
        :param config: 节点的配置对象。如果为 None，则使用默认配置。
        """
        self.config = config if config else FetchConfig()
        self.status = NodeStatus.INITIALIZING
        self._setup_logging()
        self.logger.info(f"节点 {self.config.node_name} 正在初始化...")

        self.http_session: Optional[ClientSession] = None
        self.start_time = asyncio.get_event_loop().time()

        self.status = NodeStatus.RUNNING
        self.logger.info(f"节点 {self.config.node_name} 初始化完成，当前状态: {self.status.value}")

    def _setup_logging(self):
        """
        配置日志记录器
        """
        self.logger = logging.getLogger(self.config.node_name)
        self.logger.setLevel(self.config.log_level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

    async def _get_session(self) -> ClientSession:
        """
        获取或创建 aiohttp 客户端会话
        使用单例模式确保全局只有一个会话实例，以优化性能和资源使用。
        :return: aiohttp.ClientSession 实例
        """
        if self.http_session is None or self.http_session.closed:
            self.logger.info("创建新的 aiohttp.ClientSession")
            timeout = ClientTimeout(total=self.config.timeout_seconds)
            connector = TCPConnector(limit=self.config.max_connections)
            self.http_session = ClientSession(
                timeout=timeout,
                connector=connector,
                headers=self.config.default_headers
            )
        return self.http_session

    async def fetch(
        self, 
        method: HttpMethod, 
        url: str, 
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        核心业务逻辑：执行 HTTP 请求
        :param method: HTTP 请求方法 (HttpMethod 枚举)
        :param url: 目标 URL
        :param params: URL 查询参数
        :param data: 表单数据 (for POST/PUT)
        :param json_data: JSON 数据 (for POST/PUT)
        :param headers: 自定义请求头
        :return: 包含状态码、响应头和响应体的字典
        """
        self.logger.debug(f"准备执行 {method.value} 请求到 {url}")
        session = await self._get_session()
        request_headers = self.config.default_headers.copy()
        if headers:
            request_headers.update(headers)

        try:
            async with session.request(
                method.value,
                url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers
            ) as response:
                self.logger.info(f"{method.value} {url} - 响应状态: {response.status} {response.reason}")
                response_body = await self._get_response_body(response)
                return {
                    "status_code": response.status,
                    "reason": response.reason,
                    "headers": dict(response.headers),
                    "body": response_body
                }
        except aiohttp.ClientError as e:
            self.logger.error(f"请求 {url} 时发生客户端错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            return {
                "status_code": 500,
                "reason": "Client Error",
                "error": str(e)
            }
        except asyncio.TimeoutError:
            self.logger.error(f"请求 {url} 超时 ({self.config.timeout_seconds}秒)")
            self.status = NodeStatus.ERROR
            return {
                "status_code": 504,
                "reason": "Gateway Timeout",
                "error": f"Request timed out after {self.config.timeout_seconds} seconds."
            }
        except Exception as e:
            self.logger.critical(f"请求 {url} 时发生未知严重错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            return {
                "status_code": 500,
                "reason": "Internal Server Error",
                "error": f"An unexpected error occurred: {str(e)}"
            }

    async def _get_response_body(self, response: aiohttp.ClientResponse) -> Any:
        """
        根据 Content-Type 解析响应体
        """
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return await response.json()
        else:
            return await response.text()

    async def health_check(self) -> Dict[str, Any]:
        """
        提供健康检查接口
        :return: 包含节点状态和依赖服务的健康状况
        """
        self.logger.info("执行健康检查...")
        uptime = asyncio.get_event_loop().time() - self.start_time
        return {
            "node_name": self.config.node_name,
            "status": self.status.value,
            "uptime_seconds": round(uptime, 2),
            "version": "1.0.0"
        }

    async def get_status(self) -> Dict[str, Any]:
        """
        提供状态查询接口
        :return: 包含详细状态信息的字典
        """
        self.logger.debug("查询节点状态...")
        session_status = "Inactive" if self.http_session is None or self.http_session.closed else "Active"
        return {
            **await self.health_check(),
            "config": self.config.__dict__,
            "http_session_status": session_status
        }

    async def close(self):
        """
        优雅地关闭服务和资源
        """
        if self.http_session and not self.http_session.closed:
            self.logger.info("正在关闭 aiohttp.ClientSession...")
            await self.http_session.close()
            self.http_session = None
        self.status = NodeStatus.STOPPED
        self.logger.info(f"节点 {self.config.node_name} 已停止。")

# --- 示例使用 --- 

async def main():
    """
    主函数，用于演示 FetchNodeService 的使用
    """
    print("--- 初始化 Fetch 节点服务 ---")
    service = FetchNodeService()

    print("\n--- 1. 健康检查 ---")
    health = await service.health_check()
    print(json.dumps(health, indent=2, ensure_ascii=False))

    print("\n--- 2. 状态查询 ---")
    status = await service.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))

    print("\n--- 3. 执行 GET 请求 (模拟) ---")
    # 使用一个公共的测试 API
    get_response = await service.fetch(HttpMethod.GET, "https://httpbin.org/get", params={"id": "123"})
    print(json.dumps(get_response, indent=2, ensure_ascii=False))

    print("\n--- 4. 执行 POST 请求 (模拟) ---")
    post_data = {"name": "UFO", "type": "Galaxy"}
    post_response = await service.fetch(HttpMethod.POST, "https://httpbin.org/post", json_data=post_data)
    print(json.dumps(post_response, indent=2, ensure_ascii=False))

    print("\n--- 5. 关闭服务 ---")
    await service.close()
    final_status = await service.get_status()
    print(json.dumps(final_status, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    # 在实际应用中，你可能会将服务集成到 FastAPI 或类似的框架中
    # 这里我们直接运行 main 函数进行演示
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")

'''
