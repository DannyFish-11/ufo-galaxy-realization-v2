"""
PixVerse API 适配器 (Node 71)
负责调用 PixVerse.ai API 生成视频和图片，并自动下载结果
"""

import os
import time
import json
import logging
import requests
import uuid
from typing import Dict, Any, Optional
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PixVerseAdapter")

# PixVerse API 配置（真实端点）
PIXVERSE_API_KEY = os.getenv("PIXVERSE_API_KEY", "")
PIXVERSE_API_BASE = "https://app-api.pixverse.ai"  # 真实的 API 端点

# 下载目录
DOWNLOAD_DIR = Path(os.getenv("PIXVERSE_DOWNLOAD_DIR", "./downloads"))
try:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    DOWNLOAD_DIR = Path("./downloads")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

class PixVerseAdapter:
    """
    PixVerse.ai 视频生成适配器
    
    支持的功能：
    1. 文本生成视频 (Text-to-Video)
    2. 图片生成视频 (Image-to-Video)
    3. 任务状态查询
    4. 自动下载生成的视频
    
    官方文档: https://docs.platform.pixverse.ai/
    """
    
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or PIXVERSE_API_KEY
        if not self.api_key:
            logger.warning("⚠️ PIXVERSE_API_KEY 未设置，请在环境变量中配置")
        
        self.base_url = base_url or PIXVERSE_API_BASE
        self.session = requests.Session()
        self._update_headers()
        logger.info(f"✅ PixVerse Adapter initialized with base URL: {self.base_url}")
    
    def _update_headers(self, ai_trace_id: str = None):
        """更新请求头，包含必需的 ai-trace-id"""
        if not ai_trace_id:
            ai_trace_id = str(uuid.uuid4())
        
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "ai-trace-id": ai_trace_id  # 必需：每次请求唯一
        })
    
    def generate_video(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        duration: int = 5,
        model: str = "v5.5",
        quality: str = "540p",
        negative_prompt: str = "",
        seed: int = None,
        water_mark: bool = False,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        文本生成视频 (Text-to-Video)
        
        参数:
            prompt: 视频描述文本
            aspect_ratio: 宽高比 (16:9, 9:16, 1:1)
            duration: 视频时长（秒）
            model: 模型版本 (v3.5, v4, v5, v5.5)
            quality: 视频质量 (540p, 720p, 1080p)
            negative_prompt: 负面提示词
            seed: 随机种子
            water_mark: 是否添加水印
            timeout: 超时时间（秒）
        
        返回:
            包含 video_id 和 video_url 的字典
        """
        logger.info(f"📝 生成视频: {prompt[:50]}...")
        
        # 生成新的 ai-trace-id
        self._update_headers()
        
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": duration,
            "model": model,
            "quality": quality,
            "water_mark": water_mark
        }
        
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = seed
        
        try:
            # 提交生成任务（真实端点）
            response = self.session.post(
                f"{self.base_url}/openapi/v2/text2video",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get("ErrCode") != 0:
                logger.error(f"❌ API 错误: {result.get('ErrMsg')}")
                return {"error": result.get("ErrMsg")}
            
            video_id = result["Resp"]["video_id"]
            logger.info(f"✅ 任务已提交，video_id: {video_id}")
            
            # 等待生成完成
            video_result = self._wait_for_completion(video_id, timeout)
            
            if video_result and video_result.get("status") == 1:
                video_url = video_result.get("url")
                if video_url:
                    local_path = self._download_video(video_url, str(video_id))
                    return {
                        "video_id": video_id,
                        "video_url": video_url,
                        "local_path": str(local_path),
                        "status": "completed"
                    }
            
            return {"video_id": video_id, "status": "processing"}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 请求失败: {e}")
            return {"error": str(e)}
    
    def generate_video_from_image(
        self,
        image_path: str,
        prompt: str = "",
        duration: int = 5,
        model: str = "v5.5",
        quality: str = "540p",
        seed: int = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        图片生成视频 (Image-to-Video)
        
        参数:
            image_path: 输入图片的本地路径或 URL
            prompt: 视频描述文本（可选）
            duration: 视频时长（秒）
            model: 模型版本
            quality: 视频质量
            seed: 随机种子
            timeout: 超时时间（秒）
        
        返回:
            包含 video_id 和 video_url 的字典
        """
        logger.info(f"🖼️ 从图片生成视频: {image_path}")
        
        # 生成新的 ai-trace-id
        self._update_headers()
        
        # 如果是本地文件，需要先上传
        if os.path.exists(image_path):
            image_url = self._upload_image(image_path)
            if not image_url:
                return {"error": "图片上传失败"}
        else:
            image_url = image_path  # 假设是 URL
        
        payload = {
            "image_url": image_url,
            "duration": duration,
            "model": model,
            "quality": quality
        }
        
        if prompt:
            payload["prompt"] = prompt
        if seed is not None:
            payload["seed"] = seed
        
        try:
            # 提交生成任务（真实端点）
            response = self.session.post(
                f"{self.base_url}/openapi/v2/img2video",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get("ErrCode") != 0:
                logger.error(f"❌ API 错误: {result.get('ErrMsg')}")
                return {"error": result.get("ErrMsg")}
            
            video_id = result["Resp"]["video_id"]
            logger.info(f"✅ 任务已提交，video_id: {video_id}")
            
            # 等待生成完成
            video_result = self._wait_for_completion(video_id, timeout)
            
            if video_result and video_result.get("status") == 1:
                video_url = video_result.get("url")
                if video_url:
                    local_path = self._download_video(video_url, str(video_id))
                    return {
                        "video_id": video_id,
                        "video_url": video_url,
                        "local_path": str(local_path),
                        "status": "completed"
                    }
            
            return {"video_id": video_id, "status": "processing"}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 请求失败: {e}")
            return {"error": str(e)}
    
    def _upload_image(self, image_path: str) -> Optional[str]:
        """上传图片到 PixVerse"""
        try:
            with open(image_path, 'rb') as f:
                files = {'file': f}
                response = self.session.post(
                    f"{self.base_url}/openapi/v2/upload/image",
                    files=files,
                    timeout=60
                )
                response.raise_for_status()
                result = response.json()
                
                if result.get("ErrCode") == 0:
                    return result["Resp"]["url"]
                else:
                    logger.error(f"❌ 上传失败: {result.get('ErrMsg')}")
                    return None
        except Exception as e:
            logger.error(f"❌ 上传图片失败: {e}")
            return None
    
    def _wait_for_completion(self, video_id: int, timeout: int = 300) -> Optional[Dict]:
        """等待视频生成完成"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 查询状态（真实端点）
                response = self.session.get(
                    f"{self.base_url}/openapi/v2/video/result/{video_id}",
                    timeout=10
                )
                response.raise_for_status()
                result = response.json()
                
                if result.get("ErrCode") != 0:
                    logger.error(f"❌ 查询失败: {result.get('ErrMsg')}")
                    return None
                
                video_info = result["Resp"]
                status = video_info.get("status")
                
                if status == 1:  # 完成
                    logger.info(f"✅ 视频生成完成！")
                    return video_info
                elif status == -1:  # 失败
                    logger.error(f"❌ 视频生成失败")
                    return video_info
                else:  # 处理中
                    logger.info(f"⏳ 生成中... (已等待 {int(time.time() - start_time)}秒)")
                    time.sleep(10)
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ 查询状态失败: {e}")
                time.sleep(10)
        
        logger.warning(f"⏰ 等待超时（{timeout}秒）")
        return None
    
    def _download_video(self, video_url: str, video_id: str) -> Path:
        """下载生成的视频"""
        try:
            logger.info(f"⬇️ 下载视频: {video_url}")
            
            response = requests.get(video_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # 保存到本地
            local_path = DOWNLOAD_DIR / f"pixverse_{video_id}.mp4"
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"✅ 视频已保存到: {local_path}")
            return local_path
            
        except Exception as e:
            logger.error(f"❌ 下载失败: {e}")
            return None

# 测试代码
if __name__ == "__main__":
    adapter = PixVerseAdapter()
    
    # 测试文本生成视频
    result = adapter.generate_video(
        prompt="A cat playing piano in a cozy room",
        duration=5,
        quality="540p"
    )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
