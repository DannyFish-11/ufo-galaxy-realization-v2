#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node_42_CANbus: CAN 总线通信节点

该节点负责与车辆的 CAN (Controller Area Network) 总线进行通信，
支持发送和接收 CAN 报文（帧），为上层应用提供标准化的总线数据接口。

主要功能:
- 初始化和配置 CAN 总线接口 (如 socketcan)。
- 异步发送 CAN 报文，支持标准帧和扩展帧。
- 异步接收 CAN 报文，并进行解析和分发。
- 提供健康检查和状态查询的 HTTP 接口。
- 详细的日志记录和错误处理机制。
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Type

# -- 日志配置 --
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("node_42_canbus.log", mode="a")
    ]
)
logger = logging.getLogger("CANbusService")

# -- 枚举定义 --

class ServiceStatus(Enum):
    """服务运行状态枚举"""
    STOPPED = "stopped"         # 已停止
    STARTING = "starting"       # 启动中
    RUNNING = "running"         # 运行中
    STOPPING = "stopping"       # 停止中
    DEGRADED = "degraded"       # 降级运行（部分功能异常）
    ERROR = "error"             # 严重错误

class CANFrameType(Enum):
    """CAN 报文类型枚举"""
    STANDARD = "standard"       # 标准帧 (11-bit ID)
    EXTENDED = "extended"       # 扩展帧 (29-bit ID)

# -- 数据类定义 --

@dataclass
class CANbusConfig:
    """CAN 总线配置数据类"""
    interface: str = "can0"              # CAN 接口名称，例如 'can0', 'vcan0'
    bitrate: int = 500000                # 比特率，例如 500000 (500 kbit/s)
    reconnect_delay: float = 5.0         # 连接失败后的重试延迟（秒）
    receive_timeout: float = 1.0         # 接收超时时间（秒）
    health_check_port: int = 8042        # 健康检查 HTTP 服务器端口

@dataclass
class CANFrame:
    """CAN 报文数据结构"""
    arbitration_id: int                  # 仲裁 ID
    data: bytes                          # 数据负载 (0-8 bytes)
    is_extended_id: bool = False         # 是否为扩展帧
    is_remote_frame: bool = False        # 是否为远程帧
    timestamp: float = field(default_factory=asyncio.get_running_loop().time) # 报文时间戳

    def to_dict(self) -> Dict[str, Any]:
        """将 CAN 报文转换为字典格式，便于序列化"""
        return {
            "arbitration_id": self.arbitration_id,
            "data": self.data.hex(),
            "is_extended_id": self.is_extended_id,
            "is_remote_frame": self.is_remote_frame,
            "timestamp": self.timestamp
        }

# -- 主服务类 --

class CANbusService:
    """CAN 总线通信主服务类"""

    def __init__(self, config_path: str = "config.json"):
        """初始化服务"""
        self.config_path = config_path
        self.config: CANbusConfig = self._load_config()
        self.status: ServiceStatus = ServiceStatus.STOPPED
        self._bus = None
        self._listener_task: Optional[asyncio.Task] = None
        self._http_server: Optional[asyncio.AbstractServer] = None
        logger.info(f"服务已初始化，配置从 {self.config_path} 加载。")

    def _load_config(self) -> CANbusConfig:
        """从 JSON 文件加载配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    logger.info("成功加载配置文件。")
                    return CANbusConfig(**config_data)
            else:
                logger.warning("配置文件不存在，将使用默认配置并创建文件。")
                default_config = CANbusConfig()
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config.__dict__, f, indent=4)
                return default_config
        except (IOError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"加载或创建配置文件失败: {e}，将使用默认配置。")
            return CANbusConfig()

    async def start(self) -> None:
        """启动服务，包括 CAN 总线连接和后台任务"""
        if self.status == ServiceStatus.RUNNING:
            logger.warning("服务已在运行中，无需重复启动。")
            return

        self.status = ServiceStatus.STARTING
        logger.info("服务正在启动...")

        try:
            # 在真实环境中，这里会初始化 python-can 库
            # import can
            # self._bus = can.interface.Bus(channel=self.config.interface, bustype='socketcan')
            logger.info(f"模拟连接到 CAN 接口: {self.config.interface}")
            self._bus = "mock_bus"  # 模拟总线对象

            self._listener_task = asyncio.create_task(self._listen_for_can_frames())
            logger.info("CAN 报文监听任务已启动。")

            await self._start_http_server()
            logger.info(f"健康检查服务器已在端口 {self.config.health_check_port} 启动。")

            self.status = ServiceStatus.RUNNING
            logger.info("服务已成功启动并进入运行状态。")

        except Exception as e:
            self.status = ServiceStatus.ERROR
            logger.critical(f"服务启动过程中发生严重错误: {e}", exc_info=True)
            await self.stop()

    async def stop(self) -> None:
        """停止服务，释放所有资源"""
        if self.status == ServiceStatus.STOPPED:
            return

        self.status = ServiceStatus.STOPPING
        logger.info("服务正在停止...")

        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                logger.info("CAN 报文监听任务已取消。")

        if self._http_server:
            self._http_server.close()
            await self._http_server.wait_closed()
            logger.info("健康检查服务器已关闭。")

        if self._bus:
            # self._bus.shutdown()
            logger.info("CAN 总线接口已关闭。")
            self._bus = None

        self.status = ServiceStatus.STOPPED
        logger.info("服务已完全停止。")

    async def _listen_for_can_frames(self) -> None:
        """后台任务，模拟持续接收 CAN 报文"""
        logger.info("开始监听模拟 CAN 报文...")
        frame_counter = 0
        while True:
            try:
                # 在真实环境中: msg = self._bus.recv(timeout=self.config.receive_timeout)
                # if msg:
                #     frame = CANFrame(...)
                #     await self._process_frame(frame)
                await asyncio.sleep(0.5) # 模拟接收间隔
                mock_frame = CANFrame(
                    arbitration_id=0x123 + frame_counter % 10,
                    data=b'\xde\xad\xbe\xef\xca\xfe\xba\xbe',
                    is_extended_id=False
                )
                await self._process_frame(mock_frame)
                frame_counter += 1

            except asyncio.CancelledError:
                logger.info("监听任务被正常取消。")
                break
            except Exception as e:
                logger.error(f"接收 CAN 报文时发生错误: {e}", exc_info=True)
                self.status = ServiceStatus.DEGRADED
                await asyncio.sleep(self.config.reconnect_delay)

    async def _process_frame(self, frame: CANFrame) -> None:
        """处理接收到的 CAN 报文"""
        # 在这里可以根据 arbitration_id 或数据内容进行分发或处理
        logger.debug(f"接收到 CAN 报文: {frame.to_dict()}")
        # 示例：可以将报文放入队列，供其他任务消费
        # await self.frame_queue.put(frame)

    async def send_can_frame(self, frame: CANFrame) -> bool:
        """发送一个 CAN 报文"""
        if self.status != ServiceStatus.RUNNING:
            logger.error("服务未运行，无法发送 CAN 报文。")
            return False
        try:
            # 在真实环境中:
            # import can
            # message = can.Message(
            #     arbitration_id=frame.arbitration_id,
            #     data=frame.data,
            #     is_extended_id=frame.is_extended_id,
            #     is_remote_frame=frame.is_remote_frame
            # )
            # self._bus.send(message)
            logger.info(f"成功发送模拟 CAN 报文: {frame.to_dict()}")
            return True
        except Exception as e:
            logger.error(f"发送 CAN 报文失败: {e}", exc_info=True)
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取服务的当前状态"""
        return {
            "service": "Node_42_CANbus",
            "status": self.status.value,
            "config": self.config.__dict__,
            "timestamp": asyncio.get_running_loop().time()
        }

    async def _handle_http_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """处理传入的 HTTP 请求"""
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            method, path, _ = request_line.decode('utf-8').strip().split()
            addr = writer.get_extra_info('peername')
            logger.info(f"接收到来自 {addr} 的 HTTP 请求: {method} {path}")

            if method == "GET" and path == "/health":
                response_body = self.get_status()
                response_code = 200
            elif method == "GET" and path == "/status":
                response_body = self.get_status()
                response_code = 200
            else:
                response_body = {"error": "Not Found"}
                response_code = 404

            response_data = json.dumps(response_body, indent=2).encode('utf-8')
            headers = (
                f"HTTP/1.1 {response_code} OK\r\n"
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(response_data)}\r\n"
                f"Connection: close\r\n\r\n"
            )

            writer.write(headers.encode('utf-8'))
            writer.write(response_data)
            await writer.drain()
        except Exception as e:
            logger.error(f"处理 HTTP 请求时出错: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _start_http_server(self) -> None:
        """启动用于健康检查和状态查询的 HTTP 服务器"""
        self._http_server = await asyncio.start_server(
            self._handle_http_request, '0.0.0.0', self.config.health_check_port
        )

async def main():
    """主执行函数"""
    service = CANbusService()
    try:
        await service.start()
        # 保持服务运行，直到被外部中断
        while service.status == ServiceStatus.RUNNING:
            # 模拟发送一条周期性心跳报文
            heartbeat_frame = CANFrame(arbitration_id=0x700, data=b'\x01')
            await service.send_can_frame(heartbeat_frame)
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        logger.info("接收到中断信号，准备关闭服务。")
    finally:
        await service.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已终止。")
