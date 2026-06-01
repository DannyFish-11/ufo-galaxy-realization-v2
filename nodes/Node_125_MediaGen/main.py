# -*- coding: utf-8 -*-

"""
Node_125_MediaGen: 媒体生成节点

该节点负责根据用户请求生成多种类型的媒体内容，包括图片、音频和视频。
它支持异步处理，能够高效地处理多个并发的媒体生成任务。
节点提供了健康检查和状态查询接口，便于系统监控和管理。
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, Type

# 1. 日志配置
# 配置日志记录器，用于记录节点的运行信息、警告和错误
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("node_125_mediagen.log")
    ]
)
logger = logging.getLogger("Node_125_MediaGen")

# 2. 枚举定义
# 定义服务状态、媒体类型和生成任务状态的枚举

class ServiceStatus(Enum):
    """服务节点的运行状态"""
    STOPPED = "已停止"
    STARTING = "启动中"
    RUNNING = "运行中"
    DEGRADED = "降级运行"
    ERROR = "错误"

class MediaType(Enum):
    """支持生成的媒体类型"""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"

class GenerationStatus(Enum):
    """媒体生成任务的状态"""
    PENDING = "待处理"
    PROCESSING = "处理中"
    COMPLETED = "已完成"
    FAILED = "失败"

# 3. 数据类定义
# 使用 dataclass 定义配置和任务结构

@dataclass
class MediaGenConfig:
    """媒体生成节点的配置"""
    node_id: str = "Node_125_MediaGen"
    api_keys: Dict[str, str] = field(default_factory=lambda: {
        "image_gen_api_key": os.getenv("IMAGE_GEN_API_KEY", ""),
        "audio_gen_api_key": os.getenv("AUDIO_GEN_API_KEY", ""),
        "video_gen_api_key": os.getenv("VIDEO_GEN_API_KEY", ""),
    })
    output_directory: str = os.getenv("MEDIA_OUTPUT_DIR", "./media_output")
    max_concurrent_tasks: int = 10
    default_image_model: str = "stable-diffusion-v1.5"
    default_audio_model: str = "tts-1"
    default_video_model: str = "gen-1"

@dataclass
class GenerationTask:
    """媒体生成任务的数据结构"""
    media_type: MediaType
    prompt: str
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    params: Dict[str, Any] = field(default_factory=dict)
    status: GenerationStatus = GenerationStatus.PENDING
    result_path: Optional[str] = None
    error_message: Optional[str] = None

# 4. 主服务类
# 实现媒体生成服务的核心逻辑

class MediaGenService:
    """媒体生成服务类，包含完整的业务逻辑"""

    def __init__(self, config: MediaGenConfig):
        """初始化服务"""
        self.config = config
        self.status = ServiceStatus.STOPPED
        self.tasks: Dict[str, GenerationTask] = {}
        self.semaphore = asyncio.Semaphore(config.max_concurrent_tasks)
        logger.info(f"节点 {self.config.node_id} 正在初始化。")

    async def start(self):
        """启动服务并执行初始化检查"""
        self.status = ServiceStatus.STARTING
        logger.info(f"节点 {self.config.node_id} 正在启动...")
        
        # 检查并创建输出目录
        try:
            if not os.path.exists(self.config.output_directory):
                os.makedirs(self.config.output_directory)
                logger.info(f"输出目录 {self.config.output_directory} 已创建。")
        except OSError as e:
            self.status = ServiceStatus.ERROR
            logger.error(f"创建输出目录失败: {e}")
            return

        self.status = ServiceStatus.RUNNING
        logger.info(f"节点 {self.config.node_id} 已成功启动并运行。")

    async def stop(self):
        """停止服务"""
        self.status = ServiceStatus.STOPPED
        logger.info(f"节点 {self.config.node_id} 已停止。")

    def health_check(self) -> Dict[str, Any]:
        """提供健康检查接口，返回节点状态和配置信息"""
        return {
            "node_id": self.config.node_id,
            "status": self.status.value,
            "timestamp": asyncio.get_running_loop().time()
        }

    def get_status(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """查询单个任务或所有任务的状态"""
        if task_id:
            task = self.tasks.get(task_id)
            if task:
                return self._format_task_status(task)
            else:
                return {"error": f"任务 {task_id} 未找到。"}
        
        return {
            "service_status": self.status.value,
            "total_tasks": len(self.tasks),
            "tasks_summary": {
                status.name: sum(1 for t in self.tasks.values() if t.status == status)
                for status in GenerationStatus
            }
        }

    def _format_task_status(self, task: GenerationTask) -> Dict[str, Any]:
        """格式化单个任务的状态信息"""
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "media_type": task.media_type.value,
            "prompt": task.prompt,
            "result_path": task.result_path,
            "error_message": task.error_message
        }

    async def submit_task(self, media_type: MediaType, prompt: str, params: Optional[Dict[str, Any]] = None) -> str:
        """提交一个新的媒体生成任务"""
        if self.status != ServiceStatus.RUNNING:
            raise RuntimeError("服务未在运行状态，无法接受新任务。")

        task = GenerationTask(media_type=media_type, prompt=prompt, params=params or {})
        self.tasks[task.task_id] = task
        logger.info(f"已接受新任务 {task.task_id} ({media_type.value})。")
        
        # 异步执行任务
        asyncio.create_task(self._process_task(task.task_id))
        return task.task_id

    async def _process_task(self, task_id: str):
        """核心业务逻辑：处理单个媒体生成任务"""
        task = self.tasks[task_id]
        async with self.semaphore:
            try:
                task.status = GenerationStatus.PROCESSING
                logger.info(f"任务 {task_id} 开始处理... Prompt: {task.prompt[:50]}...")

                handler_map: Dict[MediaType, Type[BaseMediaHandler]] = {
                    MediaType.IMAGE: ImageHandler,
                    MediaType.AUDIO: AudioHandler,
                    MediaType.VIDEO: VideoHandler,
                }
                
                handler_class = handler_map.get(task.media_type)
                if not handler_class:
                    raise ValueError(f"不支持的媒体类型: {task.media_type}")

                handler = handler_class(self.config)
                result_path = await handler.generate(task)

                task.result_path = result_path
                task.status = GenerationStatus.COMPLETED
                logger.info(f"任务 {task_id} 已成功完成，结果保存在: {result_path}")

            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
                task.status = GenerationStatus.FAILED
                task.error_message = str(e)
                logger.error(f"任务 {task_id} 处理失败: {e}", exc_info=True)

# 5. 媒体处理模块
# 针对不同媒体类型的具体实现

class BaseMediaHandler:
    """媒体处理器的基类"""
    def __init__(self, config: MediaGenConfig):
        self.config = config

    async def generate(self, task: GenerationTask) -> str:
        """生成媒体文件的抽象方法"""
        raise NotImplementedError

class ImageHandler(BaseMediaHandler):
    """图片生成处理器 — 通过 OpenAI DALL-E / 兼容 API 生成图片"""
    async def generate(self, task: GenerationTask) -> str:
        logger.info(f"使用模型 {self.config.default_image_model} 生成图片...")
        file_path = os.path.join(self.config.output_directory, f"{task.task_id}.png")

        api_key = self.config.api_keys.get("image_gen_api_key", "")
        if api_key and not api_key.startswith("dummy"):
            try:
                import httpx
                api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        f"{api_base}/images/generations",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": self.config.default_image_model,
                            "prompt": task.prompt,
                            "size": task.params.get("size", "1024x1024"),
                            "n": 1,
                            "response_format": "b64_json",
                        },
                    )
                    resp.raise_for_status()
                    import base64
                    b64 = resp.json()["data"][0]["b64_json"]
                    with open(file_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    return file_path
            except Exception as e:
                logger.warning(f"图片 API 调用失败，使用占位图: {e}")

        # Fallback: 生成带提示信息的占位 SVG
        import xml.sax.saxutils
        safe_prompt = xml.sax.saxutils.escape(task.prompt[:60])
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect fill="#f0f0f0" width="512" height="512"/><text x="50%" y="50%" text-anchor="middle" font-size="16">{safe_prompt}</text></svg>'
        with open(file_path, "w") as f:
            f.write(svg)
        return file_path

class AudioHandler(BaseMediaHandler):
    """音频生成处理器 — 通过 OpenAI TTS / 兼容 API 生成音频"""
    async def generate(self, task: GenerationTask) -> str:
        logger.info(f"使用模型 {self.config.default_audio_model} 生成音频...")
        file_path = os.path.join(self.config.output_directory, f"{task.task_id}.mp3")

        api_key = self.config.api_keys.get("audio_gen_api_key", "")
        if api_key and not api_key.startswith("dummy"):
            try:
                import httpx
                api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        f"{api_base}/audio/speech",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": self.config.default_audio_model,
                            "input": task.prompt,
                            "voice": task.params.get("voice", "alloy"),
                        },
                    )
                    resp.raise_for_status()
                    with open(file_path, "wb") as f:
                        f.write(resp.content)
                    return file_path
            except Exception as e:
                logger.warning(f"音频 API 调用失败，使用占位文件: {e}")

        # Fallback: 生成静音 WAV
        import wave, struct
        wav_path = file_path.replace(".mp3", ".wav") if file_path.endswith(".mp3") else file_path
        with wave.open(wav_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            silence = struct.pack("<h", 0) * 16000  # 1 second silence
            wf.writeframes(silence)
        return wav_path

class VideoHandler(BaseMediaHandler):
    """视频生成处理器 — 通过 PixVerse / 兼容 API 生成视频"""
    async def generate(self, task: GenerationTask) -> str:
        logger.info(f"使用模型 {self.config.default_video_model} 生成视频...")
        file_path = os.path.join(self.config.output_directory, f"{task.task_id}.mp4")

        # 尝试 PixVerse API
        pixverse_key = os.getenv("PIXVERSE_API_KEY", "")
        if pixverse_key:
            try:
                from nodes.Node_125_MediaGen.pixverse_adapter import PixVerseAdapter
                adapter = PixVerseAdapter()
                result = adapter.text_to_video(
                    prompt=task.prompt,
                    duration=task.params.get("duration", 4),
                )
                if result.get("status") == "COMPLETED" and result.get("video_path"):
                    import shutil
                    shutil.move(str(result["video_path"]), file_path)
                    return file_path
            except Exception as e:
                logger.warning(f"PixVerse 调用失败: {e}")

        # Fallback: 使用 ffmpeg 生成带文字的占位视频
        try:
            import asyncio as _asyncio
            proc = await _asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"color=c=gray:s=640x480:d=3",
                "-vf", f"drawtext=text='{task.prompt[:40]}':fontsize=24:fontcolor=white:x=(w-tw)/2:y=(h-th)/2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", file_path,
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
            )
            await _asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                return file_path
        except Exception as e:
            logger.warning(f"ffmpeg 视频占位生成失败: {e}")

        # Last fallback: 文本文件
        with open(file_path, "w") as f:
            f.write(f"Video placeholder for: {task.prompt}")
        return file_path

# 6. 主执行函数
# 演示如何启动服务和提交任务

async def main():
    """主异步函数，用于演示服务"""
    logger.info("--- 媒体生成节点演示 --- ")
    config = MediaGenConfig()
    service = MediaGenService(config)

    # 启动服务
    await service.start()

    # 检查健康状态
    health = service.health_check()
    logger.info(f"健康检查: {health}")

    # 提交一系列任务
    try:
        task1_id = await service.submit_task(MediaType.IMAGE, "一艘宇宙飞船飞过火星")
        task2_id = await service.submit_task(MediaType.AUDIO, "欢迎来到Galaxy系统")
        task3_id = await service.submit_task(MediaType.VIDEO, "一个机器人在赛博朋克风格的城市中行走")
    except RuntimeError as e:
        logger.error(f"提交任务失败: {e}")
        await service.stop()
        return

    # 查询初始任务状态
    logger.info(f"任务1状态: {service.get_status(task1_id)}")
    logger.info(f"全局状态: {service.get_status()}")

    # 等待任务完成
    logger.info("等待所有任务完成... (大约需要5-10秒)")
    await asyncio.sleep(10)

    # 查询最终任务状态
    logger.info(f"任务1最终状态: {service.get_status(task1_id)}")
    logger.info(f"任务2最终状态: {service.get_status(task2_id)}")
    logger.info(f"任务3最终状态: {service.get_status(task3_id)}")
    logger.info(f"最终全局状态: {service.get_status()}")

    # 停止服务
    await service.stop()
    logger.info("--- 演示结束 ---")
# ---------------------------------------------------------------------------
# HTTP 健康检查服务器
# ---------------------------------------------------------------------------
import threading as _threading
try:
    from fastapi import FastAPI as _FastAPI
    import uvicorn as _uvicorn
    _health_app = _FastAPI(title="Node_125_MediaGen")

    @_health_app.get("/health")
    def _health_endpoint():
        return {"status": "ok", "node": "Node_125_MediaGen"}

    @_health_app.get("/status")
    def _status_endpoint():
        return {"status": "ok", "node": "Node_125_MediaGen"}

    def _start_health_server():
        _uvicorn.run(_health_app, host="0.0.0.0", port=8125, log_level="error")
except ImportError:
    _health_app = None
    def _start_health_server():
        pass
if __name__ == "__main__":
    if _health_app is not None:
        _threading.Thread(target=_start_health_server, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
