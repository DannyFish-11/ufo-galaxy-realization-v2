"""
Node 15: DeepSeek-OCR2 增强版视觉节点
集成 DeepSeek 最新的 OCR2 能力，为安卓集群提供高精度 UI 识别。
"""
import os
import base64
import httpx
import asyncio
from typing import Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException

app = FastAPI(title="Node 15 - DeepSeek OCR2", version="2.1.0")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "YOUR_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/ocr" # 示例 URL，实际根据官方文档调整

class DeepSeekOCR:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def recognize(self, image_data: bytes) -> Dict[str, Any]:
        """调用 DeepSeek-OCR2 接口"""
        encoded_image = base64.b64encode(image_data).decode('utf-8')
        
        payload = {
            "model": "deepseek-ocr-2",
            "image": encoded_image,
            "detect_orientation": True
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "status": "failed"}

ocr_engine = DeepSeekOCR(DEEPSEEK_API_KEY)

@app.post("/recognize")
async def recognize_ui(file: UploadFile = File(...)):
    content = await file.read()
    result = await ocr_engine.recognize(content)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.get("/health")
async def health():
    return {"status": "healthy", "model": "deepseek-ocr-2"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8015)
