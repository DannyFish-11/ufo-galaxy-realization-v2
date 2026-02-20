# -*- coding: utf-8 -*-

"""
Node_71_MediaGen - 媒体生成节点

该节点负责根据请求生成不同类型的媒体文件，包括图片、音频和视频。
它提供了一个异步的、基于任务的管理系统，并可以通过 HTTP API 进行交互。

主要功能:
- 支持图片、音频、视频三种媒体类型的生成请求。
- 异步处理生成任务，避免阻塞。
- 提供任务状态查询和健康检查的 API 端点。
- 使用结构化的日志记录服务状态和事件。
- 可通过环境变量进行配置。
"""

import asyncio
import logging
import os
import uuid
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Type

from fastapi import FastAPI, HTTPException
import uvicorn

# --- 常量定义 ---
DEFAULT_OUTPUT_DIR = "/tmp/media_gen_output"
DEFAULT_LOG_LEVEL = "INFO"

# --- 枚举定义 ---

class ServiceStatus(Enum):
    """服务运行状态"""
    INITIALIZING = "初始化中"
    RUNNING = "运行中"
    STOPPED = "已停止"
    ERROR = "错误"

class MediaType(str, Enum):
    """支持的媒体类型"""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"

class GenerationStatus(Enum):
    """媒体生成任务状态"""
    PENDING = "排队中"
    PROCESSING = "处理中"
    COMPLETED = "已完成"
    FAILED = "失败"

# --- 配置与数据结构定义 ---

@dataclass
class MediaGenConfig:
    """节点配置类"""
    output_dir: str = DEFAULT_OUTPUT_DIR
    log_level: str = DEFAULT_LOG_LEVEL
    image_min_delay_ms: int = 500
    image_max_delay_ms: int = 2000
    audio_min_delay_ms: int = 2000
    audio_max_delay_ms: int = 5000
    video_min_delay_ms: int = 5000
    video_max_delay_ms: int = 15000

@dataclass
class GenerationTask:
    """媒体生成任务详情"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    media_type: MediaType
    status: GenerationStatus = GenerationStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result_path: Optional[str] = None
    error_message: Optional[str] = None

# --- 主服务类 ---

class MediaGenService:
    """媒体生成主服务类"""

    def __init__(self, config: MediaGenConfig):
        """初始化服务"""
        self.node_name = "Node_71_MediaGen"
        self.config = config
        self.status = ServiceStatus.INITIALIZING
        self.tasks: Dict[str, GenerationTask] = {}
        self._setup_logging()
        self._ensure_output_dir()
        self.status = ServiceStatus.RUNNING
        self.logger.info(f"{self.node_name} 服务已启动，输出目录: {self.config.output_dir}")

    def _setup_logging(self):
        """配置日志记录器"""
        logging.basicConfig(
            level=self.config.log_level,
            format=f"%(asctime)s - {self.node_name} - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        self.logger = logging.getLogger(self.node_name)

    def _ensure_output_dir(self):
        """确保输出目录存在"""
        try:
            os.makedirs(self.config.output_dir, exist_ok=True)
        except OSError as e:
            self.logger.error(f"创建输出目录 {self.config.output_dir} 失败: {e}")
            self.status = ServiceStatus.ERROR
            raise

    async def submit_generation_task(self, media_type: MediaType) -> GenerationTask:
        """提交一个新的媒体生成任务"""
        task = GenerationTask(media_type=media_type)
        self.tasks[task.task_id] = task
        self.logger.info(f"接收到新的生成任务: {task.task_id} (类型: {media_type.value})")
        # 异步执行任务
        asyncio.create_task(self._process_task(task.task_id))
        return task

    async def _process_task(self, task_id: str):
        """内部方法，处理单个生成任务"""
        task = self.tasks.get(task_id)
        if not task:
            return

        task.status = GenerationStatus.PROCESSING
        task.updated_at = time.time()
        self.logger.info(f"任务 {task_id} 开始处理...")

        try:
            generation_methods = {
                MediaType.IMAGE: self._simulate_image_generation,
                MediaType.AUDIO: self._simulate_audio_generation,
                MediaType.VIDEO: self._simulate_video_generation,
            }
            
            method = generation_methods[task.media_type]
            result_path = await method(task_id)
            
            task.result_path = result_path
            task.status = GenerationStatus.COMPLETED
            self.logger.info(f"任务 {task_id} 已成功完成，结果保存在: {result_path}")

        except Exception as e:
            task.status = GenerationStatus.FAILED
            task.error_message = str(e)
            self.logger.error(f"任务 {task_id} 处理失败: {e}", exc_info=True)
        
        finally:
            task.updated_at = time.time()

    async def _simulate_image_generation(self, task_id: str) -> str:
        """模拟图片生成过程"""
        delay = random.randint(self.config.image_min_delay_ms, self.config.image_max_delay_ms) / 1000.0
        await asyncio.sleep(delay)
        file_path = os.path.join(self.config.output_dir, f"{task_id}.png")
        with open(file_path, "w") as f:
            f.write(f"Simulated PNG image for task {task_id}")
        return file_path

    async def _simulate_audio_generation(self, task_id: str) -> str:
        """模拟音频生成过程"""
        delay = random.randint(self.config.audio_min_delay_ms, self.config.audio_max_delay_ms) / 1000.0
        await asyncio.sleep(delay)
        file_path = os.path.join(self.config.output_dir, f"{task_id}.mp3")
        with open(file_path, "w") as f:
            f.write(f"Simulated MP3 audio for task {task_id}")
        return file_path

    async def _simulate_video_generation(self, task_id: str) -> str:
        """模拟视频生成过程"""
        delay = random.randint(self.config.video_min_delay_ms, self.config.video_max_delay_ms) / 1000.0
        await asyncio.sleep(delay)
        file_path = os.path.join(self.config.output_dir, f"{task_id}.mp4")
        with open(file_path, "w") as f:
            f.write(f"Simulated MP4 video for task {task_id}")
        return file_path

    def get_service_status(self) -> dict:
        """获取当前服务的状态"""
        return {
            "node_name": self.node_name,
            "status": self.status.value,
            "total_tasks": len(self.tasks),
            "running_tasks": sum(1 for t in self.tasks.values() if t.status == GenerationStatus.PROCESSING)
        }

    def get_task_status(self, task_id: str) -> Optional[GenerationTask]:
        """根据任务 ID 获取任务状态"""
        return self.tasks.get(task_id)

    def get_health_status(self) -> dict:
        """提供健康检查响应"""
        if self.status == ServiceStatus.RUNNING:
            return {"status": "ok", "node": self.node_name}
        else:
            return {"status": "error", "node": self.node_name, "reason": self.status.value}

# --- 工厂函数和 API 定义 ---

def create_service_instance() -> MediaGenService:
    """从环境变量加载配置并创建服务实例"""
    config = MediaGenConfig(
        output_dir=os.getenv("MEDIA_GEN_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        image_min_delay_ms=int(os.getenv("IMAGE_MIN_DELAY_MS", 500)),
        image_max_delay_ms=int(os.getenv("IMAGE_MAX_DELAY_MS", 2000)),
        audio_min_delay_ms=int(os.getenv("AUDIO_MIN_DELAY_MS", 2000)),
        audio_max_delay_ms=int(os.getenv("AUDIO_MAX_DELAY_MS", 5000)),
        video_min_delay_ms=int(os.getenv("VIDEO_MIN_DELAY_MS", 5000)),
        video_max_delay_ms=int(os.getenv("VIDEO_MAX_DELAY_MS", 15000)),
    )
    return MediaGenService(config)

app = FastAPI(title="Node_71_MediaGen API")
service = create_service_instance()

@app.get("/health", tags=["Management"])
async def health_check():
    """健康检查接口，确认服务是否正常运行"""
    health = service.get_health_status()
    if health["status"] != "ok":
        raise HTTPException(status_code=503, detail=health)
    return health

@app.get("/status", tags=["Management"])
async def get_status():
    """查询服务整体运行状态"""
    return service.get_service_status()

@app.post("/generate/{media_type}", tags=["Core Logic"], status_code=202)
async def create_generation_task(media_type: MediaType):
    """创建一个新的媒体生成任务"""
    try:
        task = await service.submit_generation_task(media_type)
        return task
    except Exception as e:
        service.logger.error(f"提交任务失败: {e}")
        raise HTTPException(status_code=500, detail="Failed to create generation task.")

@app.get("/task/{task_id}", tags=["Core Logic"])
async def get_task(task_id: str):
    """根据 ID 查询特定任务的状态和结果"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task with ID '{task_id}' not found.")
    return task

# --- 主程序入口 ---

if __name__ == "__main__":
    """启动 FastAPI 应用服务器"""
    # 在实际部署中，通常会使用 Gunicorn 等更健壮的 ASGI 服务器
    # uvicorn.run(app, host="0.0.0.0", port=8000)
    # 为了简单起见，这里直接运行 uvicorn
    print("启动 Node_71_MediaGen 服务...")
    print("访问 http://127.0.0.1:8000/docs 查看 API 文档")
    uvicorn.run("__main__:app", host="0.0.0.0", port=8000, reload=True)

