#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node_11_GitHub: UFO Galaxy 系统中的 GitHub API 集成节点。

该节点提供与 GitHub API 的交互能力，支持对仓库（Repository）和议题（Issue）的
管理操作。它被设计为一个异步服务，能够高效地处理 API 请求。

主要功能:
- 从配置文件或环境变量加载 GitHub API 令牌和默认仓库设置。
- 提供异步方法来获取仓库信息、创建、查询和关闭议题。
- 包含健康检查和状态查询接口，用于监控节点运行状况。
- 使用结构化日志记录所有操作和潜在错误。
- 支持通过 HTTP 服务器（如 aiohttp）暴露服务接口（此部分为示例）。
"""

import asyncio
import logging
import os
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List

import aiohttp

# --- 常量定义 ---
NODE_NAME = "Node_11_GitHub"
CONFIG_FILE_PATH = "config.json"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# --- 枚举类型定义 ---

class NodeStatus(Enum):
    """定义节点的健康状态"""
    HEALTHY = "HEALTHY"      # 节点正常运行
    DEGRADED = "DEGRADED"    # 节点功能部分受限
    UNHEALTHY = "UNHEALTHY"  # 节点完全无法工作

class IssueState(Enum):
    """定义 GitHub 议题的状态"""
    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"

# --- 数据类定义 ---

@dataclass
class GitHubConfig:
    """存储 GitHub 节点的配置信息"""
    api_token: str = field(default="")
    default_owner: str = field(default="")
    default_repo: str = field(default="")
    api_base_url: str = field(default="https://api.github.com")

    def __post_init__(self):
        """在初始化后进行数据验证"""
        if not self.api_token:
            raise ValueError("GitHub API token (api_token) 未在配置中设置。")
        if not self.default_owner or not self.default_repo:
            logging.warning("未设置默认的 owner 或 repo，每次调用时都需要指定。")

# --- 主服务类 ---

class GitHubNodeService:
    """GitHub 节点主服务类，封装了所有核心业务逻辑"""

    def __init__(self, config: Optional[GitHubConfig] = None):
        """初始化服务，加载配置并设置日志"""
        self._setup_logging()
        self.logger.info(f"正在初始化节点: {NODE_NAME}")
        try:
            self.config = config if config else self._load_config()
            self.status = NodeStatus.HEALTHY
            self.status_message = "节点初始化成功。"
            self.headers = {
                "Authorization": f"token {self.config.api_token}",
                "Accept": "application/vnd.github.v3+json",
            }
            self.logger.info("GitHub 配置加载成功。")
        except (ValueError, FileNotFoundError) as e:
            self.config = None
            self.status = NodeStatus.UNHEALTHY
            self.status_message = f"节点初始化失败: {e}"
            self.logger.error(self.status_message)

    def _setup_logging(self):
        """配置结构化日志记录器"""
        self.logger = logging.getLogger(NODE_NAME)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(LOG_FORMAT)
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def _load_config(self) -> GitHubConfig:
        """从环境变量或配置文件加载配置"""
        self.logger.info("正在加载配置...")
        # 优先从环境变量读取
        api_token = os.getenv("GITHUB_API_TOKEN")
        default_owner = os.getenv("GITHUB_DEFAULT_OWNER")
        default_repo = os.getenv("GITHUB_DEFAULT_REPO")

        if api_token:
            self.logger.info("从环境变量中成功加载 GitHub 配置。")
            return GitHubConfig(
                api_token=api_token,
                default_owner=default_owner or "",
                default_repo=default_repo or ""
            )
        
        # 如果环境变量中没有，则尝试从文件读取
        self.logger.info(f"未找到环境变量配置，尝试从 {CONFIG_FILE_PATH} 文件加载。")
        if os.path.exists(CONFIG_FILE_PATH):
            with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                self.logger.info("从配置文件中成功加载 GitHub 配置。")
                return GitHubConfig(**config_data)
        
        raise FileNotFoundError(f"配置文件 {CONFIG_FILE_PATH} 未找到，且未设置相关环境变量。")

    async def _make_api_request(
        self, method: str, url: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """通用的异步 API 请求方法"""
        if self.status == NodeStatus.UNHEALTHY:
            raise ConnectionError("节点处于不健康状态，无法处理请求。")

        async with aiohttp.ClientSession(headers=self.headers) as session:
            self.logger.info(f"发送 API 请求: {method} {url}")
            try:
                async with session.request(method, url, json=data) as response:
                    response.raise_for_status()  # 如果状态码是 4xx 或 5xx，则抛出异常
                    result = await response.json()
                    self.logger.info(f"成功接收到 API 响应，状态码: {response.status}")
                    return result
            except aiohttp.ClientResponseError as e:
                self.logger.error(f"API 请求失败: {e.status} {e.message}")
                self.status = NodeStatus.DEGRADED
                self.status_message = f"最近一次 API 请求失败: {e.message}"
                raise
            except Exception as e:
                self.logger.error(f"发生未知网络错误: {e}")
                self.status = NodeStatus.DEGRADED
                self.status_message = f"发生未知网络错误: {e}"
                raise

    def get_health(self) -> Dict[str, str]:
        """提供节点的健康检查接口"""
        self.logger.info("执行健康检查。")
        return {
            "node_name": NODE_NAME,
            "status": self.status.value,
            "message": self.status_message
        }

    def get_status(self) -> Dict[str, Any]:
        """提供节点详细状态的查询接口"""
        self.logger.info("查询节点状态。")
        return {
            "node_name": NODE_NAME,
            "status": self.status.value,
            "config": {
                "default_owner": self.config.default_owner if self.config else None,
                "default_repo": self.config.default_repo if self.config else None,
                "api_base_url": self.config.api_base_url if self.config else None,
            },
            "timestamp": asyncio.get_event_loop().time()
        }

    async def get_repository_info(
        self, owner: Optional[str] = None, repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取指定仓库的详细信息"""
        owner = owner or self.config.default_owner
        repo = repo or self.config.default_repo
        if not owner or not repo:
            raise ValueError("必须提供仓库所有者 (owner) 和仓库名称 (repo)。")
        
        url = f"{self.config.api_base_url}/repos/{owner}/{repo}"
        self.logger.info(f"正在获取仓库信息: {owner}/{repo}")
        return await self._make_api_request("GET", url)

    async def create_issue(
        self, title: str, body: str, owner: Optional[str] = None, repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """在指定仓库中创建一个新的议题"""
        owner = owner or self.config.default_owner
        repo = repo or self.config.default_repo
        if not owner or not repo:
            raise ValueError("必须提供仓库所有者 (owner) 和仓库名称 (repo)。")

        url = f"{self.config.api_base_url}/repos/{owner}/{repo}/issues"
        data = {"title": title, "body": body}
        self.logger.info(f"正在创建新议题: '{title}' 于 {owner}/{repo}")
        return await self._make_api_request("POST", url, data=data)

    async def list_issues(
        self, state: IssueState = IssueState.OPEN, owner: Optional[str] = None, repo: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """列出指定仓库中的议题"""
        owner = owner or self.config.default_owner
        repo = repo or self.config.default_repo
        if not owner or not repo:
            raise ValueError("必须提供仓库所有者 (owner) 和仓库名称 (repo)。")

        url = f"{self.config.api_base_url}/repos/{owner}/{repo}/issues?state={state.value}"
        self.logger.info(f"正在列出 '{state.value}' 状态的议题于 {owner}/{repo}")
        return await self._make_api_request("GET", url)

    async def close_issue(
        self, issue_number: int, owner: Optional[str] = None, repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """关闭一个指定的议题"""
        owner = owner or self.config.default_owner
        repo = repo or self.config.default_repo
        if not owner or not repo:
            raise ValueError("必须提供仓库所有者 (owner) 和仓库名称 (repo)。")

        url = f"{self.config.api_base_url}/repos/{owner}/{repo}/issues/{issue_number}"
        data = {"state": IssueState.CLOSED.value}
        self.logger.info(f"正在关闭议题 #{issue_number} 于 {owner}/{repo}")
        return await self._make_api_request("PATCH", url, data=data)

async def main():
    """主函数，用于演示和测试 GitHubNodeService 的功能"""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logger = logging.getLogger()
    
    logger.info("--- GitHub 节点服务演示 ---")

    # 准备一个模拟的配置文件，实际使用时应从环境变量或真实文件加载
    # 为避免真实 Token 泄露，这里使用占位符
    # 请在使用时替换为真实的 GitHub Personal Access Token
    # 并确保该 Token 具有 repo 权限
    mock_config_data = {
        "api_token": os.getenv("GITHUB_API_TOKEN", "YOUR_GITHUB_TOKEN_HERE"),
        "default_owner": "octocat",
        "default_repo": "Hello-World"
    }
    
    # 检查占位符
    if mock_config_data["api_token"] == "YOUR_GITHUB_TOKEN_HERE":
        logger.error("请在代码中或通过 GITHUB_API_TOKEN 环境变量设置您的 GitHub API Token。")
        return

    # 创建配置对象和节点服务实例
    try:
        config = GitHubConfig(**mock_config_data)
        service = GitHubNodeService(config=config)
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        return

    # 1. 检查健康状态
    logger.info("\n1. 健康检查:")
    health_status = service.get_health()
    logger.info(json.dumps(health_status, indent=2, ensure_ascii=False))
    if health_status['status'] != NodeStatus.HEALTHY.value:
        logger.error("节点不健康，演示中止。")
        return

    # 2. 获取仓库信息
    try:
        logger.info("\n2. 获取仓库信息 (octocat/Hello-World):")
        repo_info = await service.get_repository_info()
        logger.info(f"仓库名称: {repo_info['full_name']}")
        logger.info(f"仓库描述: {repo_info['description']}")
        logger.info(f"Stars: {repo_info['stargazers_count']}")
    except Exception as e:
        logger.error(f"获取仓库信息失败: {e}")

    # 3. 列出仓库的开放议题
    try:
        logger.info("\n3. 列出开放的议题:")
        issues = await service.list_issues(state=IssueState.OPEN)
        logger.info(f"找到 {len(issues)} 个开放的议题。")
        for issue in issues[:3]: # 只显示前3个
            logger.info(f"  - #{issue['number']}: {issue['title']}")
    except Exception as e:
        logger.error(f"列出议题失败: {e}")

    # 4. 创建一个新议题 (此部分默认注释，以免在公共仓库中创建垃圾信息)
    # try:
    #     logger.info("\n4. 创建一个新议题:")
    #     new_issue = await service.create_issue(
    #         title="[Test] 来自 UFO Galaxy 节点的问候",
    #         body="这是一个通过 Node_11_GitHub 自动创建的测试议题。"
    #     )
    #     logger.info(f"成功创建议题 #{new_issue['number']}: {new_issue['html_url']}")
    #     issue_to_close = new_issue['number']
    #
    #     # 5. 关闭刚刚创建的议题
    #     logger.info(f"\n5. 关闭议题 #{issue_to_close}:")
    #     closed_issue = await service.close_issue(issue_number=issue_to_close)
    #     logger.info(f"议题 #{closed_issue['number']} 状态已更新为: {closed_issue['state']}")
    # except Exception as e:
    #     logger.error(f"创建或关闭议题失败: {e}")

    logger.info("\n--- 演示结束 ---")

if __name__ == "__main__":
    # 设置事件循环策略以兼容 Windows 环境
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
