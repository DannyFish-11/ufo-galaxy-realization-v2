# -*- coding: utf-8 -*-

"""
Node_47_Audio: 音频处理节点

该节点负责处理各种音频任务，包括录音、播放、格式转换和简单的音频效果处理。
它通过一个主服务类来管理音频设备、处理音频流以及响应外部命令。
"""

import asyncio
import logging
import os
import wave
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

# --- 配置和状态定义 ---

# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("node_47_audio.log", mode="a", encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

class NodeStatus(Enum):
    """
    节点运行状态枚举
    """
    INITIALIZING = "初始化中"
    RUNNING = "运行中"
    STOPPED = "已停止"
    ERROR = "错误"
    MAINTENANCE = "维护中"

class AudioFormat(Enum):
    """
    支持的音频格式
    """
    WAV = "wav"
    MP3 = "mp3"  # 实际转换需要外部库如 pydub
    RAW = "raw"

@dataclass
class AudioConfig:
    """
    音频节点配置
    """
    node_name: str = "Node_47_Audio"
    node_version: str = "1.0.0"
    log_level: str = "INFO"
    default_device_id: int = 0
    default_sample_rate: int = 44100
    default_channels: int = 2
    default_chunk_size: int = 1024
    supported_formats: list[str] = field(default_factory=lambda: [f.value for f in AudioFormat])

# --- 主服务类 ---

class AudioService:
    """
    音频处理主服务类
    """
    def __init__(self, config: AudioConfig):
        """
        初始化音频服务

        :param config: 音频节点配置
        """
        self.config = config
        self.status = NodeStatus.INITIALIZING
        self.current_task = None
        self._is_recording = False
        self._is_playing = False
        self._audio_stream = None

        self._setup_logging()
        logger.info(f"节点 {self.config.node_name} (版本 {self.config.node_version}) 正在初始化...")

    def _setup_logging(self):
        """
        根据配置设置日志级别
        """
        level = logging.getLevelName(self.config.log_level.upper())
        logger.setLevel(level)

    async def start(self):
        """
        启动音频服务，进入运行状态
        """
        if self.status == NodeStatus.RUNNING:
            logger.warning("服务已在运行中。")
            return

        logger.info("音频服务正在启动...")
        # 在实际应用中，这里会初始化音频设备接口，例如 PyAudio
        # 此处为模拟实现
        await asyncio.sleep(1)
        self.status = NodeStatus.RUNNING
        logger.info("音频服务已成功启动，处于运行状态。")

    async def stop(self):
        """
        停止音频服务
        """
        if self.status != NodeStatus.RUNNING:
            logger.warning("服务未在运行中。")
            return

        logger.info("音频服务正在停止...")
        if self._is_recording:
            await self.stop_recording()
        if self._is_playing:
            await self.stop_playback()
        
        await asyncio.sleep(1)
        self.status = NodeStatus.STOPPED
        logger.info("音频服务已停止。")

    async def record_audio(self, output_path: str, duration: int, sample_rate: int = 44100, channels: int = 2) -> bool:
        """
        录制音频到文件

        :param output_path: 输出文件路径 (.wav)
        :param duration: 录制时长（秒）
        :param sample_rate: 采样率
        :param channels: 声道数
        :return: 录制是否成功
        """
        if self._is_recording:
            logger.error("已有一个录制任务在进行中。")
            return False

        logger.info(f"开始录制音频，时长 {duration} 秒，保存至 {output_path}")
        self._is_recording = True
        self.current_task = "recording"

        try:
            # 模拟录制过程
            frames = []
            total_frames = int(sample_rate / self.config.default_chunk_size * duration)
            for i in range(total_frames):
                if not self._is_recording:
                    logger.info("录制被中断。")
                    return False
                # 模拟从音频缓冲区读取数据
                await asyncio.sleep(self.config.default_chunk_size / sample_rate)
                frames.append(os.urandom(self.config.default_chunk_size * channels * 2)) # 16-bit audio

            logger.info("录制完成，正在保存文件...")

            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(b''.join(frames))
            
            logger.info(f"音频文件已成功保存到 {output_path}")
            return True
        except Exception as e:
            logger.error(f"录制过程中发生错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            return False
        finally:
            self._is_recording = False
            self.current_task = None

    async def stop_recording(self):
        """
        手动停止当前录制任务
        """
        if not self._is_recording:
            logger.warning("当前没有录制任务。")
            return
        logger.info("正在停止录制...")
        self._is_recording = False

    async def play_audio(self, file_path: str) -> bool:
        """
        播放音频文件

        :param file_path: 音频文件路径
        :return: 播放是否成功
        """
        if self._is_playing:
            logger.error("已有一个播放任务在进行中。")
            return False
        if not os.path.exists(file_path):
            logger.error(f"音频文件不存在: {file_path}")
            return False

        logger.info(f"开始播放音频文件: {file_path}")
        self._is_playing = True
        self.current_task = "playing"

        try:
            with wave.open(file_path, 'rb') as wf:
                # 模拟播放过程
                while self._is_playing and (data := wf.readframes(self.config.default_chunk_size)):
                    await asyncio.sleep(self.config.default_chunk_size / wf.getframerate())
            logger.info("音频播放结束。")
            return True
        except Exception as e:
            logger.error(f"播放过程中发生错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            return False
        finally:
            self._is_playing = False
            self.current_task = None

    async def stop_playback(self):
        """
        手动停止当前播放任务
        """
        if not self._is_playing:
            logger.warning("当前没有播放任务。")
            return
        logger.info("正在停止播放...")
        self._is_playing = False

    async def convert_format(self, input_path: str, output_path: str, target_format: AudioFormat) -> bool:
        """
        转换音频格式 (模拟功能)
        实际实现需要 pydub, ffmpeg 等库

        :param input_path: 输入文件路径
        :param output_path: 输出文件路径
        :param target_format: 目标格式
        :return: 转换是否成功
        """
        if not os.path.exists(input_path):
            logger.error(f"输入文件不存在: {input_path}")
            return False
        
        logger.info(f"请求转换 {input_path} 到 {target_format.value} 格式，输出至 {output_path}")
        logger.warning("格式转换功能为模拟实现，仅复制文件。")

        try:
            # 模拟转换过程
            await asyncio.sleep(2)
            with open(input_path, 'rb') as f_in, open(output_path, 'wb') as f_out:
                f_out.write(f_in.read())
            logger.info(f"文件已'转换'并保存至 {output_path}")
            return True
        except Exception as e:
            logger.error(f"格式转换过程中发生错误: {e}", exc_info=True)
            self.status = NodeStatus.ERROR
            return False

    def get_health_status(self) -> Dict[str, Any]:
        """
        获取节点健康状态

        :return: 包含状态信息的字典
        """
        return {
            "node_name": self.config.node_name,
            "status": self.status.value,
            "version": self.config.node_version,
            "is_busy": self._is_recording or self._is_playing,
            "current_task": self.current_task
        }

    def get_node_info(self) -> Dict[str, Any]:
        """
        获取节点详细信息和配置

        :return: 包含节点信息的字典
        """
        return {
            "config": self.config.__dict__,
            "status": self.get_health_status()
        }

# --- 示例和主程序入口 ---

async def main():
    """
    主函数，用于演示和测试 AudioService 的功能
    """
    logger.info("--- Audio 节点功能演示 ---")

    # 1. 加载配置并初始化服务
    config = AudioConfig()
    audio_service = AudioService(config)

    # 2. 启动服务
    await audio_service.start()
    logger.info(f"健康检查: {audio_service.get_health_status()}")

    # 3. 演示录制功能
    output_wav_path = "test_recording.wav"
    logger.info("\n--- 演示: 录制 5 秒音频 ---")
    record_task = asyncio.create_task(audio_service.record_audio(output_wav_path, duration=5))
    
    # 模拟在录制过程中检查状态
    await asyncio.sleep(2)
    logger.info(f"录制中... 健康检查: {audio_service.get_health_status()}")
    
    # 等待录制完成
    success = await record_task
    if success:
        logger.info("录制成功。")
    else:
        logger.error("录制失败。")

    logger.info(f"健康检查: {audio_service.get_health_status()}")

    # 4. 演示播放功能
    if os.path.exists(output_wav_path):
        logger.info("\n--- 演示: 播放录制的音频 ---")
        play_task = asyncio.create_task(audio_service.play_audio(output_wav_path))

        # 模拟在播放2秒后停止
        await asyncio.sleep(2)
        logger.info("将在1秒后中断播放...")
        await asyncio.sleep(1)
        await audio_service.stop_playback()
        await play_task # 等待任务结束
        logger.info("播放已手动停止。")
    
    logger.info(f"健康检查: {audio_service.get_health_status()}")

    # 5. 演示格式转换功能
    if os.path.exists(output_wav_path):
        logger.info("\n--- 演示: 转换音频格式 (模拟) ---")
        converted_path = "test_converted.mp3"
        await audio_service.convert_format(output_wav_path, converted_path, AudioFormat.MP3)

    # 6. 查询节点信息
    logger.info(f"\n--- 节点详细信息 ---\n{audio_service.get_node_info()}")

    # 7. 停止服务
    await audio_service.stop()
    logger.info(f"健康检查: {audio_service.get_health_status()}")

    logger.info("--- 演示结束 ---")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
    finally:
        # 清理生成的测试文件
        if os.path.exists("test_recording.wav"):
            os.remove("test_recording.wav")
        if os.path.exists("test_converted.mp3"):
            os.remove("test_converted.mp3")
        if os.path.exists("node_47_audio.log"):
            os.remove("node_47_audio.log")
        logger.info("清理完成。")

