#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Node_48_Serial: 串口通信节点

该节点负责处理与外部设备之间的串口（RS232/RS485）通信。
它支持异步读写操作，并提供状态查询和健康检查接口。
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List

import serial_asyncio

# --- 全局配置 ---
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
NODE_NAME = "Node_48_Serial"

# --- 日志配置 ---
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(NODE_NAME)


# --- 枚举定义 ---
class NodeStatus(Enum):
    """节点运行状态枚举"""
    INITIALIZING = "INITIALIZING"  # 正在初始化
    CONFIGURING = "CONFIGURING"    # 正在配置
    RUNNING = "RUNNING"            # 正在运行
    STOPPED = "STOPPED"            # 已停止
    ERROR = "ERROR"                # 出现错误
    DEGRADED = "DEGRADED"          # 降级运行


class Parity(str, Enum):
    """串口校验位枚举"""
    NONE = "N"
    EVEN = "E"
    ODD = "O"
    MARK = "M"
    SPACE = "S"


class StopBits(float, Enum):
    """串口停止位枚举"""
    ONE = 1
    ONE_POINT_FIVE = 1.5
    TWO = 2


# --- 数据类定义 ---
@dataclass
class SerialConfig:
    """串口配置参数"""
    port: str = "/dev/ttyUSB0"  # 串口设备路径
    baudrate: int = 9600  # 波特率
    bytesize: int = 8  # 数据位
    parity: Parity = Parity.NONE  # 校验位
    stopbits: StopBits = StopBits.ONE  # 停止位
    timeout: Optional[float] = 1.0  # 读取超时时间
    write_timeout: Optional[float] = 1.0 # 写入超时时间
    rtscts: bool = False # 是否启用RTS/CTS硬件流控
    dsrdtr: bool = False # 是否启用DSR/DTR硬件流控
    xonxoff: bool = False # 是否启用XON/XOFF软件流控

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "SerialConfig":
        """从字典加载配置"""
        return cls(
            port=config_dict.get("port", "/dev/ttyUSB0"),
            baudrate=config_dict.get("baudrate", 9600),
            bytesize=config_dict.get("bytesize", 8),
            parity=Parity(config_dict.get("parity", "N")),
            stopbits=StopBits(config_dict.get("stopbits", 1)),
            timeout=config_dict.get("timeout", 1.0),
            write_timeout=config_dict.get("write_timeout", 1.0),
            rtscts=config_dict.get("rtscts", False),
            dsrdtr=config_dict.get("dsrdtr", False),
            xonxoff=config_dict.get("xonxoff", False),
        )


# --- 主服务类 ---
class SerialService:
    """串口通信主服务类"""

    def __init__(self, config: Optional[SerialConfig] = None):
        """初始化服务"""
        self.status = NodeStatus.INITIALIZING
        logger.info(f"节点 {NODE_NAME} 正在初始化...")
        self.config = config if config else SerialConfig()
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.receive_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.send_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.main_task: Optional[asyncio.Task] = None
        self.error_message: Optional[str] = None

    async def load_config(self, config_source: Optional[Dict[str, Any]] = None):
        """加载配置，支持从外部字典源加载"""
        self.status = NodeStatus.CONFIGURING
        logger.info("正在加载配置...")
        if config_source:
            try:
                self.config = SerialConfig.from_dict(config_source)
                logger.info(f"从外部源成功加载配置: {self.config}")
            except (ValueError, KeyError) as e:
                self.status = NodeStatus.ERROR
                self.error_message = f"配置文件格式错误: {e}"
                logger.error(self.error_message)
                raise
        else:
            logger.info(f"使用默认配置: {self.config}")

    async def start(self):
        """启动服务，连接串口并开始异步读写"""
        if self.status == NodeStatus.RUNNING:
            logger.warning("服务已经在运行中。")
            return

        logger.info(f"正在启动串口服务，目标端口: {self.config.port}")
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=self.config.bytesize,
                parity=self.config.parity.value,
                stopbits=self.config.stopbits.value,
                timeout=self.config.timeout,
                write_timeout=self.config.write_timeout,
                rtscts=self.config.rtscts,
                dsrdtr=self.config.dsrdtr,
                xonxoff=self.config.xonxoff
            )
            self.status = NodeStatus.RUNNING
            self.error_message = None
            self.main_task = asyncio.gather(
                self._reader_task(),
                self._writer_task()
            )
            logger.info(f"串口 {self.config.port} 连接成功，服务已启动。")
        except serial.SerialException as e:
            self.status = NodeStatus.ERROR
            self.error_message = f"无法打开串口 {self.config.port}: {e}"
            logger.error(self.error_message)
        except Exception as e:
            self.status = NodeStatus.ERROR
            self.error_message = f"启动服务时发生未知错误: {e}"
            logger.error(self.error_message)

    async def stop(self):
        """停止服务，关闭串口连接和任务"""
        if self.status != NodeStatus.RUNNING:
            logger.warning("服务未在运行中。")
            return

        logger.info("正在停止串口服务...")
        if self.main_task:
            self.main_task.cancel()
            try:
                await self.main_task
            except asyncio.CancelledError:
                logger.debug("主任务已被取消。")

        if self.writer and not self.writer.is_closing():
            self.writer.close()
            await self.writer.wait_closed()
            logger.info("串口写入器已关闭。")

        self.status = NodeStatus.STOPPED
        logger.info("串口服务已停止。")

    async def _reader_task(self):
        """异步读取串口数据的后台任务"""
        logger.info("读取任务已启动。")
        while self.status == NodeStatus.RUNNING:
            try:
                if self.reader:
                    data = await self.reader.read(1024)
                    if data:
                        logger.debug(f"接收到数据: {data.hex()}")
                        await self.receive_queue.put(data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.status = NodeStatus.DEGRADED
                self.error_message = f"读取数据时发生错误: {e}"
                logger.error(self.error_message)
                await asyncio.sleep(5) # 发生错误后等待一段时间再重试
        logger.info("读取任务已停止。")

    async def _writer_task(self):
        """异步写入串口数据的后台任务"""
        logger.info("写入任务已启动。")
        while self.status == NodeStatus.RUNNING:
            try:
                data_to_send = await self.send_queue.get()
                if self.writer:
                    self.writer.write(data_to_send)
                    await self.writer.drain()
                    logger.debug(f"发送数据: {data_to_send.hex()}")
                self.send_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.status = NodeStatus.DEGRADED
                self.error_message = f"写入数据时发生错误: {e}"
                logger.error(self.error_message)
                await asyncio.sleep(5)
        logger.info("写入任务已停止。")

    async def send_data(self, data: bytes):
        """将数据放入发送队列"""
        if self.status != NodeStatus.RUNNING:
            logger.error("服务未运行，无法发送数据。")
            return False
        await self.send_queue.put(data)
        logger.info(f"数据已加入发送队列: {data.hex()}")
        return True

    async def read_data(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """从接收队列读取数据"""
        try:
            return await asyncio.wait_for(self.receive_queue.get(), timeout)
        except asyncio.TimeoutError:
            logger.debug("读取数据超时。")
            return None

    def get_status(self) -> Dict[str, Any]:
        """获取当前节点状态"""
        return {
            "node_name": NODE_NAME,
            "status": self.status.value,
            "config": self.config.__dict__,
            "receive_queue_size": self.receive_queue.qsize(),
            "send_queue_size": self.send_queue.qsize(),
            "error_message": self.error_message
        }

    def get_health(self) -> Dict[str, Any]:
        """执行健康检查"""
        is_healthy = self.status in [NodeStatus.RUNNING, NodeStatus.CONFIGURING, NodeStatus.INITIALIZING]
        details = self.get_status()
        if not is_healthy:
            details["reason"] = f"节点状态为 {self.status.value}。错误信息: {self.error_message}"
        return {
            "healthy": is_healthy,
            "details": details
        }


# --- 主程序入口 ---
async def main():
    """主异步函数，用于演示和测试服务"""
    logger.info(f"启动 {NODE_NAME} 节点...")
    
    # 1. 初始化服务
    service = SerialService()
    
    # 2. 加载配置 (此处使用默认配置)
    await service.load_config()
    
    # 3. 启动服务
    # 在实际环境中，需要确保串口设备存在
    # 此处为演示，如果串口不存在会报错并退出
    try:
        await service.start()
    except Exception as e:
        logger.critical(f"服务启动失败，无法继续。错误: {e}")
        return

    # 4. 模拟运行
    if service.status == NodeStatus.RUNNING:
        try:
            # 模拟发送一条指令
            await service.send_data(b'AT+INFO?\r\n')

            # 等待接收响应
            response = await service.read_data(timeout=5.0)
            if response:
                logger.info(f"接收到响应: {response.decode(errors='ignore')}")
            else:
                logger.warning("在5秒内未收到响应。")

            # 检查状态
            logger.info(f"当前状态: {service.get_status()}")
            logger.info(f"健康检查: {service.get_health()}")

            # 持续运行一段时间
            await asyncio.sleep(10)

        finally:
            # 5. 停止服务
            await service.stop()
            logger.info(f"最终状态: {service.get_status()}")
    else:
        logger.error("服务未能成功启动，请检查配置和硬件连接。")

if __name__ == "__main__":
    # 注意：在没有物理串口或虚拟串口对的情况下运行此脚本可能会失败。
    # 可以使用 `socat` 创建虚拟串口对进行测试:
    # socat -d -d pty,raw,echo=0 pty,raw,echo=0
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
    except Exception as e:
        logger.critical(f"程序顶层出现未捕获的异常: {e}")
