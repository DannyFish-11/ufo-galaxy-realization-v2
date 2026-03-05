#!/usr/bin/env python3
"""
PixVerse API 适配器 (Node 48)
负责调用 PixVerse.ai API 生成视频和图片，并自动下载结果
"""

import os
import time
import json
import logging
import requests
from typing import Dict, Any, Optional
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PixVerseAdapter")

# PixVerse API 配置
PIXVERSE_API_KEY = os.getenv("PIXVERSE_API_KEY", "sk-f5c7177f35ee6cceab5d97d6ffae26d0")
PIXVERSE_API_BASE = "https://api.pixverse.ai/v1"

# 下载目录
DOWNLOAD_DIR = Path(os.getenv("PIXVERSE_DOWNLOAD_DIR", "/app/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

class PixVerseAdapter:
    """
    PixVerse.ai 视频生成适配器
    
    支持的功能：
    1. 文本生成视频 (Text-to-Video)
    2. 图片生成视频 (Image-to-Video)
    3. 任务状态查询
    4. 自动下载生成的视频
    """
    
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or PIXVERSE_API_KEY
        self.base_url = base_url or PIXVERSE_API_BASE
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
        logger.info(f"PixVerse Adapter initialized with API Key: {self.api_key[:8]}...")
    
    def generate_video(
        self,
        prompt: str,
        style: str = "realistic",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        生成视频（文本到视频）
        
        Args:
            prompt: 视频生成提示词
            style: 视频风格 (realistic, anime, 3d, etc.)
            duration: 视频时长（秒），通常为 4-8 秒
            aspect_ratio: 视频比例 (16:9, 9:16, 1:1)
            seed: 随机种子，用于复现结果
        
        Returns:
            包含任务 ID 和状态的字典
        """
        logger.info(f"Generating video: '{prompt}' (Style: {style}, Duration: {duration}s)")
        
        try:
            # 构建请求
            payload = {
                "prompt": prompt,
                "style": style,
                "duration": duration,
                "aspect_ratio": aspect_ratio
            }
            if seed:
                payload["seed"] = seed
            
            # 提交任务
            response = self.session.post(
                f"{self.base_url}/video/generate",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                task_id = result.get("task_id")
                logger.info(f"Video generation task submitted: {task_id}")
                
                # 等待任务完成
                video_result = self._wait_for_completion(task_id)
                
                # 自动下载视频
                if video_result.get("status") == "COMPLETED":
                    video_url = video_result.get("video_url")
                    if video_url:
                        local_path = self._download_video(video_url, task_id)
                        video_result["local_path"] = str(local_path)
                        logger.info(f"Video downloaded to: {local_path}")
                
                return video_result
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                return {
                    "status": "ERROR",
                    "error": f"API returned {response.status_code}",
                    "details": response.text
                }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {e}")
            return {
                "status": "ERROR",
                "error": "Network error",
                "details": str(e)
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {
                "status": "ERROR",
                "error": "Unexpected error",
                "details": str(e)
            }
    
    def generate_video_from_image(
        self,
        image_url: str,
        prompt: str = "",
        motion_strength: float = 0.5,
        duration: int = 4
    ) -> Dict[str, Any]:
        """
        从图片生成视频（图片到视频）
        
        Args:
            image_url: 输入图片的 URL
            prompt: 运动描述提示词（可选）
            motion_strength: 运动强度 (0.0-1.0)
            duration: 视频时长（秒）
        
        Returns:
            包含任务 ID 和状态的字典
        """
        logger.info(f"Generating video from image: {image_url}")
        
        try:
            payload = {
                "image_url": image_url,
                "prompt": prompt,
                "motion_strength": motion_strength,
                "duration": duration
            }
            
            response = self.session.post(
                f"{self.base_url}/video/image-to-video",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                task_id = result.get("task_id")
                logger.info(f"Image-to-video task submitted: {task_id}")
                
                # 等待任务完成
                video_result = self._wait_for_completion(task_id)
                
                # 自动下载视频
                if video_result.get("status") == "COMPLETED":
                    video_url = video_result.get("video_url")
                    if video_url:
                        local_path = self._download_video(video_url, task_id)
                        video_result["local_path"] = str(local_path)
                
                return video_result
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                return {
                    "status": "ERROR",
                    "error": f"API returned {response.status_code}"
                }
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return {
                "status": "ERROR",
                "error": str(e)
            }
    
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        查询任务状态
        
        Args:
            task_id: 任务 ID
        
        Returns:
            任务状态字典
        """
        try:
            response = self.session.get(
                f"{self.base_url}/video/status/{task_id}",
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "status": "ERROR",
                    "error": f"Status query failed: {response.status_code}"
                }
        
        except Exception as e:
            logger.error(f"Error querying status: {e}")
            return {
                "status": "ERROR",
                "error": str(e)
            }
    
    def _wait_for_completion(
        self,
        task_id: str,
        max_wait_time: int = 300,
        poll_interval: int = 5
    ) -> Dict[str, Any]:
        """
        等待任务完成
        
        Args:
            task_id: 任务 ID
            max_wait_time: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
        
        Returns:
            最终任务状态
        """
        logger.info(f"Waiting for task {task_id} to complete...")
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            status = self.get_task_status(task_id)
            current_status = status.get("status")
            
            if current_status == "COMPLETED":
                logger.info(f"Task {task_id} completed successfully")
                return status
            elif current_status == "FAILED":
                logger.error(f"Task {task_id} failed: {status.get('error')}")
                return status
            elif current_status in ["PENDING", "PROCESSING"]:
                logger.info(f"Task {task_id} status: {current_status}, waiting...")
                time.sleep(poll_interval)
            else:
                logger.warning(f"Unknown status: {current_status}")
                time.sleep(poll_interval)
        
        logger.error(f"Task {task_id} timed out after {max_wait_time}s")
        return {
            "status": "TIMEOUT",
            "task_id": task_id,
            "error": f"Task did not complete within {max_wait_time} seconds"
        }
    
    def _download_video(self, video_url: str, task_id: str) -> Path:
        """
        下载生成的视频
        
        Args:
            video_url: 视频 URL
            task_id: 任务 ID
        
        Returns:
            本地文件路径
        """
        logger.info(f"Downloading video from {video_url}")
        
        try:
            # 下载视频
            response = requests.get(video_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # 保存到本地
            filename = f"{task_id}.mp4"
            filepath = DOWNLOAD_DIR / filename
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Video downloaded successfully: {filepath}")
            return filepath
        
        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            raise

def run_node_48_main(aip_command: Dict) -> Dict:
    """
    Node 48 主处理函数
    处理来自 Node 50 的 AIP 命令
    """
    adapter = PixVerseAdapter()
    
    try:
        payload = aip_command.get("payload", {})
        action = payload.get("action", "")
        parameters = payload.get("parameters", {})
        
        if action == "generate_video":
            # 文本生成视频
            result = adapter.generate_video(
                prompt=parameters.get("prompt", "A futuristic robot working in a lab"),
                style=parameters.get("style", "realistic"),
                duration=parameters.get("duration", 5),
                aspect_ratio=parameters.get("aspect_ratio", "16:9")
            )
            return result
        
        elif action == "generate_video_from_image":
            # 图片生成视频
            result = adapter.generate_video_from_image(
                image_url=parameters.get("image_url"),
                prompt=parameters.get("prompt", ""),
                motion_strength=parameters.get("motion_strength", 0.5),
                duration=parameters.get("duration", 4)
            )
            return result
        
        elif action == "get_status":
            # 查询任务状态
            task_id = parameters.get("task_id")
            if not task_id:
                return {"status": "ERROR", "error": "Missing task_id"}
            result = adapter.get_task_status(task_id)
            return result
        
        else:
            return {
                "status": "ERROR",
                "error": f"Unknown action: {action}"
            }
    
    except Exception as e:
        logger.error(f"Error in run_node_48_main: {e}")
        return {
            "status": "ERROR",
            "error": str(e)
        }

if __name__ == "__main__":
    # 测试代码
    print("=" * 60)
    print("Testing PixVerse Adapter")
    print("=" * 60)
    
    test_command = {
        "protocol": "AIP/1.0",
        "type": "command",
        "from": "Node_50",
        "to": "Node_48",
        "payload": {
            "action": "generate_video",
            "parameters": {
                "prompt": "A beautiful animation of the UFO³ Galaxy system: quantum computers, 3D printers, and AI agents working together in harmony",
                "style": "cinematic",
                "duration": 5,
                "aspect_ratio": "16:9"
            }
        }
    }
    
    result = run_node_48_main(test_command)
    print("\n--- Test Result ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
