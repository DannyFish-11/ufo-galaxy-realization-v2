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
import time
import uuid
from dataclasses import dataclass, field

# RUF006: 保住 fire-and-forget 的 create_task 句柄，否则事件循环只持弱引用，
# 任务可能在执行到一半时被 GC 掉。submit_task() 会往里加。
_BACKGROUND_TASKS: set = set()
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, Type

# 1. 日志配置

def _node_log_file(name: str) -> str:
    """节点日志的统一落点 ``<统一日志根>/nodes/<name>``。

    真 bug 修复:此前直接 ``logging.FileHandler("node_125_mediagen.log")`` 用裸文件名,日志会写到
    **进程当前工作目录** —— 从项目根启动、从节点目录启动、被服务拉起时落点各不
    相同,排障时经常"日志不见了"。现统一到 core.log_paths 的日志根下 nodes/ 子目录。
    """
    try:
        from core.log_paths import node_log_dir

        return str(node_log_dir() / name)
    except Exception:  # noqa: BLE001 — 日志落点问题不能阻断节点启动
        import os as _os

        d = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
            "logs",
            "nodes",
        )
        _os.makedirs(d, exist_ok=True)
        return _os.path.join(d, name)


# 配置日志记录器，用于记录节点的运行信息、警告和错误
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_node_log_file("node_125_mediagen.log"), encoding="utf-8")
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
        """提供健康检查接口，返回节点状态和配置信息

        时间戳用 ``time.monotonic()`` 而不是 ``asyncio.get_running_loop().time()``：
        后者要求**调用时正处在事件循环里**。这个方法原本只被演示流程从协程里调，
        所以一直没事；一旦被 HTTP 端点调用（FastAPI 把同步端点丢到线程池执行，
        那里没有 running loop）就直接 ``RuntimeError: no running event loop`` →
        /health 返回 500。健康检查自己把自己弄挂是最不该发生的一种。
        """
        return {
            "node_id": self.config.node_id,
            "status": self.status.value,
            "timestamp": time.monotonic(),
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
        _bt = asyncio.create_task(self._process_task(task.task_id))
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)
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
        with open(file_path, "w", encoding='utf-8') as f:
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
        with open(file_path, "w", encoding='utf-8') as f:
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
# HTTP 服务
# ---------------------------------------------------------------------------
#
# 这里原来是这样的：健康服务跑在一个 **daemon 线程**上，主线程 asyncio.run(main())
# 跑上面那段演示流程 —— 提交三个样例任务、等 10 秒、停服务、返回。主线程一返回，
# daemon 线程跟着死，进程 exit=0。
#
# 于是这个节点的真实行为是：**起来几秒钟，打完「--- 演示结束 ---」就没了**。
# 实测把 125 个节点逐个拉起来时它就是这么退的。启动器那边看到的是「进程起过、
# 端口一度通、然后消失」——最难查的一类，因为它不报错。
#
# 顺带两处：
#   * 端口写死 8125，不走权威表（见 nodes/common/node_port.py 的说明）。
#   * /status 返回的是常量 {"status": "ok"}，跟真实的 MediaGenService 没有关系 ——
#     队列里有多少任务、失败了几个，外面一律看不到。
#
# 现在：服务生命周期挂在 FastAPI lifespan 上，uvicorn 跑在**主线程**，进程常驻。
# 演示流程保留但改成显式 `--demo` —— 它是有用的自检，只是不该是默认行为。
import sys as _sys

from nodes.common.node_port import resolve_node_port

try:
    import uvicorn as _uvicorn
    from contextlib import asynccontextmanager as _asynccontextmanager
    from fastapi import FastAPI as _FastAPI, HTTPException as _HTTPException
    from pydantic import BaseModel as _BaseModel

    _service: Optional[MediaGenService] = None

    @_asynccontextmanager
    async def _lifespan(app):
        global _service
        _service = MediaGenService(MediaGenConfig())
        await _service.start()
        logger.info("Node_125_MediaGen 服务已就绪")
        try:
            yield
        finally:
            await _service.stop()
            _service = None

    _health_app = _FastAPI(title="Node_125_MediaGen", lifespan=_lifespan)

    class _GenerateRequest(_BaseModel):
        media_type: str
        prompt: str
        params: Optional[Dict[str, Any]] = None

    @_health_app.get("/health")
    def _health_endpoint():
        """健康检查。服务没起来时如实说 —— 不要恒返回 ok。"""
        if _service is None:
            return {"status": "starting", "node": "Node_125_MediaGen"}
        # 服务自身的状态放进 service 子对象，不要 ** 平铺上来 —— health_check()
        # 里也有一个 "status"（值是中文的「运行中」），平铺会把 HTTP 级的 "ok"
        # 顶掉，而外面按 status == "ok" 判活的消费方会因此判错。
        return {"status": "ok", "node": "Node_125_MediaGen", "service": _service.health_check()}

    @_health_app.get("/status")
    def _status_endpoint():
        """全局状态 —— 走真实的 MediaGenService，不是常量。"""
        if _service is None:
            raise _HTTPException(status_code=503, detail="service not started")
        return _service.get_status()

    @_health_app.get("/status/{task_id}")
    def _task_status_endpoint(task_id: str):
        if _service is None:
            raise _HTTPException(status_code=503, detail="service not started")
        return _service.get_status(task_id)

    @_health_app.post("/generate")
    async def _generate_endpoint(req: _GenerateRequest):
        if _service is None:
            raise _HTTPException(status_code=503, detail="service not started")
        try:
            media_type = MediaType(req.media_type)
        except ValueError:
            raise _HTTPException(
                status_code=400,
                detail=f"未知的 media_type {req.media_type!r}；可用：{[m.value for m in MediaType]}",
            )
        try:
            task_id = await _service.submit_task(media_type, req.prompt, req.params)
        except RuntimeError as exc:
            raise _HTTPException(status_code=503, detail=str(exc))
        return {"task_id": task_id}

except ImportError as _exc:  # fastapi/uvicorn 不在 —— 节点降级为「只能跑演示」
    logger.warning("FastAPI/uvicorn 不可用，HTTP 服务不启动：%s", _exc)
    _health_app = None


if __name__ == "__main__":
    if "--demo" in _sys.argv:
        # 原来的演示流程。它会跑完就退 —— 那是它该有的行为，只是不该是默认。
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("程序被用户中断。")
    elif _health_app is None:
        logger.error("FastAPI/uvicorn 不可用，无法提供服务；只能用 --demo 跑演示。")
        _sys.exit(1)
    else:
        _uvicorn.run(
            _health_app,
            host="0.0.0.0",
            port=resolve_node_port("Node_125_MediaGen", 8125),
            log_level="info",
        )
