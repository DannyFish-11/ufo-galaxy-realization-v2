#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node_40_SFTP: UFO Galaxy 系统中的 SFTP 文件传输节点

该节点负责通过 SFTP (SSH File Transfer Protocol) 安全地进行文件上传、下载和管理。
它支持异步操作，并提供了健康检查和状态查询接口。
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

import asyncssh

# --- 配置和枚举 --- #

# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("Node_40_SFTP")

class NodeStatus(Enum):
    """定义节点的运行状态"""
    INITIALIZING = "INITIALIZING"  # 初始化中
    RUNNING = "RUNNING"          # 运行中
    STOPPED = "STOPPED"          # 已停止
    ERROR = "ERROR"              # 发生错误
    DEGRADED = "DEGRADED"        # 降级运行

class OperationType(Enum):
    """定义支持的 SFTP 操作类型"""
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"
    LIST_DIR = "LIST_DIR"

@dataclass
class SFTPConfig:
    """SFTP 连接的配置信息"""
    host: str
    port: int = 22
    username: str = "anonymous"
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    known_hosts_path: Optional[str] = None
    connection_timeout: int = 10  # 连接超时时间（秒）
    keepalive_interval: int = 30  # Keep-alive 间隔

# --- 主服务类 --- #

class SFTPNodeService:
    """
    SFTP 节点主服务类，封装了所有核心业务逻辑。
    """

    def __init__(self, config: SFTPConfig):
        """初始化服务，加载配置"""
        self.config = config
        self._status = NodeStatus.INITIALIZING
        self._connection: Optional[asyncssh.SSHClientConnection] = None
        self._sftp_client: Optional[asyncssh.SFTPClient] = None
        self._lock = asyncio.Lock()
        logger.info(f"节点 {self.get_node_name()} 正在初始化...")
        self._status = NodeStatus.STOPPED

    @staticmethod
    def get_node_name() -> str:
        """返回节点的标准名称"""
        return "Node_40_SFTP"

    async def _connect(self) -> None:
        """内部方法，用于建立 SSH 和 SFTP 连接"""
        if self._connection and not self._connection.is_closing():
            logger.info("已存在有效连接，无需重复建立。")
            return

        logger.info(f"正在连接到 SFTP 服务器: {self.config.host}:{self.config.port}")
        try:
            client_keys = [self.config.private_key_path] if self.config.private_key_path else None
            known_hosts = self.config.known_hosts_path if self.config.known_hosts_path else None

            self._connection = await asyncio.wait_for(
                asyncssh.connect(
                    self.config.host,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    client_keys=client_keys,
                    known_hosts=known_hosts,
                    server_host_key_algs=["ssh-rsa"], # 兼容旧服务器
                    keepalive_interval=self.config.keepalive_interval
                ),
                timeout=self.config.connection_timeout
            )
            self._sftp_client = await self._connection.start_sftp_client()
            self._status = NodeStatus.RUNNING
            logger.info("SFTP 连接成功建立。")
        except asyncio.TimeoutError:
            self._status = NodeStatus.ERROR
            logger.error(f"连接 SFTP 服务器超时 ({self.config.connection_timeout}秒)。")
            raise ConnectionError("SFTP connection timed out.")
        except Exception as e:
            self._status = NodeStatus.ERROR
            logger.error(f"建立 SFTP 连接时发生未知错误: {e}", exc_info=True)
            raise ConnectionError(f"Failed to connect to SFTP server: {e}")

    async def disconnect(self) -> None:
        """断开 SFTP 连接"""
        async with self._lock:
            if self._sftp_client:
                self._sftp_client.exit()
                self._sftp_client = None
            if self._connection and not self._connection.is_closing():
                self._connection.close()
                await self._connection.wait_closed()
                self._connection = None
            self._status = NodeStatus.STOPPED
            logger.info("SFTP 连接已断开。")

    async def upload_file(self, local_path: str, remote_path: str) -> bool:
        """上传单个文件到 SFTP 服务器"""
        async with self._lock:
            if not self._sftp_client:
                await self._connect()
            
            if not self._sftp_client:
                logger.error("无法获取 SFTP 客户端，上传失败。")
                return False

            try:
                logger.info(f"开始上传文件: {local_path} -> {remote_path}")
                await self._sftp_client.put(local_path, remote_path)
                logger.info("文件上传成功。")
                return True
            except Exception as e:
                logger.error(f"上传文件时发生错误: {e}", exc_info=True)
                self._status = NodeStatus.DEGRADED
                return False

    async def download_file(self, remote_path: str, local_path: str) -> bool:
        """从 SFTP 服务器下载单个文件"""
        async with self._lock:
            if not self._sftp_client:
                await self._connect()

            if not self._sftp_client:
                logger.error("无法获取 SFTP 客户端，下载失败。")
                return False

            try:
                logger.info(f"开始下载文件: {remote_path} -> {local_path}")
                await self._sftp_client.get(remote_path, local_path)
                logger.info("文件下载成功。")
                return True
            except Exception as e:
                logger.error(f"下载文件时发生错误: {e}", exc_info=True)
                self._status = NodeStatus.DEGRADED
                return False

    async def list_directory(self, remote_path: str) -> Optional[List[str]]:
        """列出远程目录的内容"""
        async with self._lock:
            if not self._sftp_client:
                await self._connect()

            if not self._sftp_client:
                logger.error("无法获取 SFTP 客户端，列出目录失败。")
                return None

            try:
                logger.info(f"正在列出远程目录: {remote_path}")
                files = await self._sftp_client.listdir(remote_path)
                logger.info(f"成功列出 {len(files)} 个文件/目录。")
                return files
            except Exception as e:
                logger.error(f"列出目录时发生错误: {e}", exc_info=True)
                self._status = NodeStatus.DEGRADED
                return None

    async def health_check(self) -> bool:
        """执行健康检查，尝试连接服务器"""
        logger.info("执行健康检查...")
        try:
            async with self._lock:
                await self._connect()
                if self._sftp_client and await self._sftp_client.exists("."):
                    logger.info("健康检查通过。")
                    return True
                else:
                    logger.warning("健康检查失败：无法验证 SFTP 客户端状态。")
                    return False
        except Exception as e:
            logger.error(f"健康检查失败: {e}", exc_info=True)
            return False
        finally:
            await self.disconnect()

    def get_status(self) -> Dict[str, Any]:
        """查询当前节点的状态"""
        return {
            "node_name": self.get_node_name(),
            "status": self._status.value,
            "connection": "connected" if self._connection and not self._connection.is_closing() else "disconnected",
            "config": self.config.__dict__
        }

# --- 示例和主程序入口 --- #

async def main():
    """主函数，用于演示节点功能"""
    logger.info("--- SFTP 节点功能演示 ---")

    # 注意：请根据你的 SFTP 服务器信息修改以下配置
    # 这是一个示例配置，你需要一个可用的 SFTP 测试服务器
    # 你可以使用 `python -m http.server` 启动一个本地服务器，但这不适用于 SFTP
    # 可以使用 `docker run -p 2222:22 -d atmoz/sftp user:pass:::upload` 快速启动一个测试服务器
    sftp_config = SFTPConfig(
        host="localhost",
        port=2222,
        username="user",
        password="pass",
    )

    service = SFTPNodeService(sftp_config)

    # 1. 健康检查
    is_healthy = await service.health_check()
    logger.info(f"初始健康检查结果: {'通过' if is_healthy else '失败'}")
    if not is_healthy:
        logger.error("无法连接到 SFTP 服务器，请检查配置或服务器状态。演示终止。")
        return

    # 2. 状态查询
    logger.info(f"当前状态: {service.get_status()}")

    # 3. 创建一个本地测试文件并上传
    local_file = "test_upload.txt"
    remote_file = "upload/test_remote.txt"
    with open(local_file, "w") as f:
        f.write("Hello, SFTP from Node_40_SFTP!")
    
    upload_success = await service.upload_file(local_file, remote_file)
    if upload_success:
        logger.info(f"文件 '{local_file}' 成功上传到 '{remote_file}'")
    else:
        logger.error("文件上传失败。")

    # 4. 列出远程目录
    remote_dir_contents = await service.list_directory("upload")
    if remote_dir_contents:
        logger.info(f"远程目录 'upload' 内容: {remote_dir_contents}")

    # 5. 下载文件
    local_download_file = "test_download.txt"
    if upload_success: # 只有上传成功才尝试下载
        download_success = await service.download_file(remote_file, local_download_file)
        if download_success:
            logger.info(f"文件 '{remote_file}' 成功下载到 '{local_download_file}'")
            with open(local_download_file, "r") as f:
                logger.info(f"下载的文件内容: '{f.read()}'")
        else:
            logger.error("文件下载失败。")

    # 6. 清理本地文件和断开连接
    if os.path.exists(local_file):
        os.remove(local_file)
    if os.path.exists(local_download_file):
        os.remove(local_download_file)

    await service.disconnect()
    logger.info(f"最终状态: {service.get_status()}")
    logger.info("--- 演示结束 ---")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
    except Exception as e:
        logger.critical(f"主程序发生未捕获的异常: {e}", exc_info=True)
