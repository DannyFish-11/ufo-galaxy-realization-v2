"""
UFO³ Galaxy - 多模态传输模块

功能：
1. 图片传输（JPEG、PNG、WebP）
2. 视频传输（MP4、WebM）
3. 音频传输（MP3、WAV、Opus）
4. 文件传输（任意格式）
5. 屏幕截图传输
6. 自动选择传输方式（Gateway 或 P2P）

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import os
import io
import base64
import hashlib
import mimetypes
from typing import Dict, List, Any, Optional, Union, BinaryIO
from dataclasses import dataclass
from enum import Enum
from PIL import Image
import asyncio
import aiohttp
from pathlib import Path

from aip_protocol_v2 import (
    AIPMessage, MessageBuilder, DeviceInfo,
    MessageType, TransferMethod, ContentType
)

# ============================================================================
# 配置
# ============================================================================

class TransferConfig:
    """传输配置"""
    # 小于此大小的文件通过 Gateway 传输（Base64 编码）
    GATEWAY_MAX_SIZE = 1024 * 1024  # 1MB
    
    # 分块大小
    CHUNK_SIZE = 1024 * 1024  # 1MB per chunk
    
    # 图片压缩质量
    IMAGE_QUALITY = 85
    
    # 支持的图片格式
    SUPPORTED_IMAGE_FORMATS = ['jpeg', 'jpg', 'png', 'webp', 'gif', 'bmp']
    
    # 支持的视频格式
    SUPPORTED_VIDEO_FORMATS = ['mp4', 'webm', 'avi', 'mov', 'mkv']
    
    # 支持的音频格式
    SUPPORTED_AUDIO_FORMATS = ['mp3', 'wav', 'opus', 'ogg', 'aac', 'm4a']

# ============================================================================
# 多模态传输管理器
# ============================================================================

class MultimodalTransferManager:
    """多模态传输管理器"""
    
    def __init__(self, gateway_url: str = "http://localhost:8000"):
        self.gateway_url = gateway_url
        self.config = TransferConfig()
    
    # ========================================================================
    # 图片传输
    # ========================================================================
    
    async def send_image(
        self,
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        image_path: str = None,
        image_data: bytes = None,
        compress: bool = True,
        quality: int = None
    ) -> AIPMessage:
        """
        发送图片
        
        Args:
            from_device: 发送设备
            to_device: 接收设备
            image_path: 图片路径（与 image_data 二选一）
            image_data: 图片数据（与 image_path 二选一）
            compress: 是否压缩
            quality: 压缩质量（1-100）
        
        Returns:
            AIPMessage: 图片消息
        """
        # 读取图片
        if image_path:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            filename = os.path.basename(image_path)
        else:
            filename = "image.jpg"
        
        # 压缩图片（如果需要）
        if compress:
            image_data = await self._compress_image(
                image_data,
                quality=quality or self.config.IMAGE_QUALITY
            )
        
        # 获取图片信息
        image = Image.open(io.BytesIO(image_data))
        width, height = image.size
        format = image.format.lower()
        
        # 创建消息
        message = MessageBuilder.create_image_message(
            from_device=from_device,
            to_device=to_device,
            image_data=image_data,
            format=format,
            metadata={
                "width": width,
                "height": height,
                "filename": filename,
                "compressed": compress
            }
        )
        
        return message
    
    async def _compress_image(self, image_data: bytes, quality: int) -> bytes:
        """压缩图片"""
        image = Image.open(io.BytesIO(image_data))
        
        # 转换为 RGB（如果是 RGBA）
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        
        # 压缩
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()
    
    async def receive_image(self, message: AIPMessage, save_path: str = None) -> bytes:
        """
        接收图片
        
        Args:
            message: 图片消息
            save_path: 保存路径（可选）
        
        Returns:
            bytes: 图片数据
        """
        if not message.payload or not message.payload.data:
            raise ValueError("No image data in message")
        
        # 解码 Base64
        image_data = base64.b64decode(message.payload.data)
        
        # 验证校验和
        calculated_checksum = self._calculate_checksum(image_data)
        if calculated_checksum != message.payload.checksum:
            raise ValueError(f"Checksum mismatch: expected {message.payload.checksum}, got {calculated_checksum}")
        
        # 保存（如果指定了路径）
        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
        
        return image_data
    
    # ========================================================================
    # 视频传输
    # ========================================================================
    
    async def send_video(
        self,
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        video_path: str,
        metadata: Dict[str, Any] = None
    ) -> AIPMessage:
        """
        发送视频
        
        Args:
            from_device: 发送设备
            to_device: 接收设备
            video_path: 视频路径
            metadata: 元数据（可选）
        
        Returns:
            AIPMessage: 视频消息
        """
        # 获取文件信息
        file_size = os.path.getsize(video_path)
        file_checksum = self._calculate_file_checksum(video_path)
        filename = os.path.basename(video_path)
        
        # 计算分块数
        chunks = (file_size + self.config.CHUNK_SIZE - 1) // self.config.CHUNK_SIZE
        
        # 创建消息
        from aip_protocol_v2 import MessagePayload
        payload = MessagePayload(
            data_type="video",
            format=Path(video_path).suffix[1:],  # 去掉点号
            size=file_size,
            checksum=file_checksum,
            transfer_method=TransferMethod.P2P.value,
            chunks=chunks,
            chunk_size=self.config.CHUNK_SIZE,
            metadata={
                "filename": filename,
                **(metadata or {})
            }
        )
        
        message = AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.VIDEO,
            content_type=ContentType.MP4,
            payload=payload,
            requires_ack=True
        )
        
        return message
    
    # ========================================================================
    # 音频传输
    # ========================================================================
    
    async def send_audio(
        self,
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        audio_path: str = None,
        audio_data: bytes = None,
        format: str = "mp3",
        metadata: Dict[str, Any] = None
    ) -> AIPMessage:
        """
        发送音频
        
        Args:
            from_device: 发送设备
            to_device: 接收设备
            audio_path: 音频路径（与 audio_data 二选一）
            audio_data: 音频数据（与 audio_path 二选一）
            format: 音频格式
            metadata: 元数据（可选）
        
        Returns:
            AIPMessage: 音频消息
        """
        # 读取音频
        if audio_path:
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            filename = os.path.basename(audio_path)
        else:
            filename = f"audio.{format}"
        
        size = len(audio_data)
        transfer_method = TransferMethod.GATEWAY.value if size < self.config.GATEWAY_MAX_SIZE else TransferMethod.P2P.value
        
        # 创建消息
        from aip_protocol_v2 import MessagePayload
        payload = MessagePayload(
            data_type="audio",
            format=format,
            size=size,
            checksum=self._calculate_checksum(audio_data),
            transfer_method=transfer_method,
            metadata={
                "filename": filename,
                **(metadata or {})
            },
            data=base64.b64encode(audio_data).decode('utf-8') if size < self.config.GATEWAY_MAX_SIZE else None
        )
        
        message = AIPMessage(
            from_device=from_device,
            to_device=to_device,
            message_type=MessageType.AUDIO,
            content_type=ContentType.MP3,
            payload=payload,
            requires_ack=True
        )
        
        return message
    
    # ========================================================================
    # 文件传输
    # ========================================================================
    
    async def send_file(
        self,
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        file_path: str,
        metadata: Dict[str, Any] = None
    ) -> AIPMessage:
        """
        发送文件
        
        Args:
            from_device: 发送设备
            to_device: 接收设备
            file_path: 文件路径
            metadata: 元数据（可选）
        
        Returns:
            AIPMessage: 文件消息
        """
        # 获取文件信息
        file_size = os.path.getsize(file_path)
        file_checksum = self._calculate_file_checksum(file_path)
        filename = os.path.basename(file_path)
        
        # 计算分块数
        chunks = (file_size + self.config.CHUNK_SIZE - 1) // self.config.CHUNK_SIZE
        
        # 创建消息
        message = MessageBuilder.create_file_message(
            from_device=from_device,
            to_device=to_device,
            file_path=file_path,
            file_size=file_size,
            file_checksum=file_checksum,
            chunks=chunks,
            metadata={
                "filename": filename,
                **(metadata or {})
            }
        )
        
        return message
    
    async def send_file_chunk(
        self,
        file_path: str,
        chunk_index: int,
        chunk_size: int
    ) -> bytes:
        """
        发送文件分块
        
        Args:
            file_path: 文件路径
            chunk_index: 分块索引（从 0 开始）
            chunk_size: 分块大小
        
        Returns:
            bytes: 分块数据
        """
        offset = chunk_index * chunk_size
        
        with open(file_path, 'rb') as f:
            f.seek(offset)
            chunk_data = f.read(chunk_size)
        
        return chunk_data
    
    async def receive_file_chunk(
        self,
        file_path: str,
        chunk_index: int,
        chunk_data: bytes
    ):
        """
        接收文件分块
        
        Args:
            file_path: 文件路径
            chunk_index: 分块索引
            chunk_data: 分块数据
        """
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # 写入分块
        offset = chunk_index * self.config.CHUNK_SIZE
        
        with open(file_path, 'r+b' if os.path.exists(file_path) else 'wb') as f:
            f.seek(offset)
            f.write(chunk_data)
    
    # ========================================================================
    # 屏幕截图
    # ========================================================================
    
    async def send_screenshot(
        self,
        from_device: DeviceInfo,
        to_device: DeviceInfo,
        screenshot_data: bytes,
        metadata: Dict[str, Any] = None
    ) -> AIPMessage:
        """
        发送屏幕截图
        
        Args:
            from_device: 发送设备
            to_device: 接收设备
            screenshot_data: 截图数据
            metadata: 元数据（可选）
        
        Returns:
            AIPMessage: 截图消息
        """
        return await self.send_image(
            from_device=from_device,
            to_device=to_device,
            image_data=screenshot_data,
            compress=True,
            quality=self.config.IMAGE_QUALITY
        )
    
    # ========================================================================
    # 工具方法
    # ========================================================================
    
    def _calculate_checksum(self, data: bytes) -> str:
        """计算校验和"""
        return f"sha256:{hashlib.sha256(data).hexdigest()}"
    
    def _calculate_file_checksum(self, file_path: str) -> str:
        """计算文件校验和"""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        
        return f"sha256:{sha256.hexdigest()}"
    
    def get_file_type(self, file_path: str) -> str:
        """获取文件类型"""
        ext = Path(file_path).suffix[1:].lower()
        
        if ext in self.config.SUPPORTED_IMAGE_FORMATS:
            return "image"
        elif ext in self.config.SUPPORTED_VIDEO_FORMATS:
            return "video"
        elif ext in self.config.SUPPORTED_AUDIO_FORMATS:
            return "audio"
        else:
            return "file"

# ============================================================================
# 使用示例
# ============================================================================

async def example_usage():
    """使用示例"""
    
    # 创建设备信息
    phone_a = DeviceInfo(
        device_id="phone_a",
        device_name="手机A",
        device_type="android",
        ip_address="192.168.1.100"
    )
    
    pc = DeviceInfo(
        device_id="pc",
        device_name="电脑",
        device_type="windows",
        ip_address="192.168.1.10"
    )
    
    # 创建传输管理器
    manager = MultimodalTransferManager()
    
    print("="*80)
    print("多模态传输示例")
    print("="*80)
    
    # 示例 1: 发送图片（小图片，通过 Gateway）
    print("\n示例 1: 发送小图片")
    print("-"*80)
    
    # 创建一个假的图片数据
    fake_image = Image.new('RGB', (100, 100), color='red')
    image_bytes = io.BytesIO()
    fake_image.save(image_bytes, format='JPEG')
    image_data = image_bytes.getvalue()
    
    image_msg = await manager.send_image(
        from_device=phone_a,
        to_device=pc,
        image_data=image_data,
        compress=False
    )
    
    print(f"消息 ID: {image_msg.message_id}")
    print(f"传输方式: {image_msg.payload.transfer_method}")
    print(f"图片大小: {image_msg.payload.size} 字节")
    print(f"图片尺寸: {image_msg.payload.metadata['width']}x{image_msg.payload.metadata['height']}")
    
    # 示例 2: 发送音频（小音频，通过 Gateway）
    print("\n示例 2: 发送音频")
    print("-"*80)
    
    fake_audio_data = b"fake_audio_data" * 100
    
    audio_msg = await manager.send_audio(
        from_device=phone_a,
        to_device=pc,
        audio_data=fake_audio_data,
        format="mp3",
        metadata={"duration": 30}
    )
    
    print(f"消息 ID: {audio_msg.message_id}")
    print(f"传输方式: {audio_msg.payload.transfer_method}")
    print(f"音频大小: {audio_msg.payload.size} 字节")
    print(f"音频时长: {audio_msg.payload.metadata.get('duration')} 秒")
    
    # 示例 3: 发送大文件（通过 P2P）
    print("\n示例 3: 发送大文件")
    print("-"*80)
    
    # 创建一个临时大文件
    temp_file = "/tmp/large_file.bin"
    with open(temp_file, 'wb') as f:
        f.write(b"x" * (10 * 1024 * 1024))  # 10MB
    
    file_msg = await manager.send_file(
        from_device=phone_a,
        to_device=pc,
        file_path=temp_file,
        metadata={"description": "Large binary file"}
    )
    
    print(f"消息 ID: {file_msg.message_id}")
    print(f"传输方式: {file_msg.payload.transfer_method}")
    print(f"文件大小: {file_msg.payload.size / 1024 / 1024:.2f} MB")
    print(f"分块数: {file_msg.payload.chunks}")
    print(f"每块大小: {file_msg.payload.chunk_size / 1024:.2f} KB")
    
    # 清理
    os.remove(temp_file)
    
    print("\n" + "="*80)
    print("多模态传输示例完成")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(example_usage())
