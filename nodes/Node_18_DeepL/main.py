"""
Node 18: DeepL - 翻译服务节点
================================
提供文本翻译、文档翻译、语言检测功能
"""
import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 18 - DeepL", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# DeepL配置
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
DEEPL_API_URL = "https://api-free.deepl.com/v2" if DEEPL_API_KEY.endswith(":fx") else "https://api.deepl.com/v2"

# 支持的语言
LANGUAGES = {
    "BG": "Bulgarian", "CS": "Czech", "DA": "Danish", "DE": "German",
    "EL": "Greek", "EN": "English", "ES": "Spanish", "ET": "Estonian",
    "FI": "Finnish", "FR": "French", "HU": "Hungarian", "ID": "Indonesian",
    "IT": "Italian", "JA": "Japanese", "KO": "Korean", "LT": "Lithuanian",
    "LV": "Latvian", "NB": "Norwegian", "NL": "Dutch", "PL": "Polish",
    "PT": "Portuguese", "RO": "Romanian", "RU": "Russian", "SK": "Slovak",
    "SL": "Slovenian", "SV": "Swedish", "TR": "Turkish", "UK": "Ukrainian",
    "ZH": "Chinese"
}

class TranslateRequest(BaseModel):
    text: str
    target_lang: str
    source_lang: Optional[str] = None
    formality: Optional[str] = None  # default, more, less

class BatchTranslateRequest(BaseModel):
    texts: List[str]
    target_lang: str
    source_lang: Optional[str] = None

class DeepLManager:
    def __init__(self):
        self.api_key = DEEPL_API_KEY
        self.api_url = DEEPL_API_URL

    def _make_request(self, endpoint: str, data: Dict) -> Dict:
        """发送API请求"""
        if not self.api_key:
            raise RuntimeError("DeepL API key not configured")

        headers = {"Authorization": f"DeepL-Auth-Key {self.api_key}"}
        response = requests.post(f"{self.api_url}/{endpoint}", headers=headers, data=data)

        if response.status_code != 200:
            raise RuntimeError(f"DeepL API error: {response.text}")

        return response.json()

    def translate(self, text: str, target_lang: str, 
                  source_lang: Optional[str] = None,
                  formality: Optional[str] = None) -> Dict:
        """翻译文本"""
        data = {
            "text": text,
            "target_lang": target_lang.upper()
        }
        if source_lang:
            data["source_lang"] = source_lang.upper()
        if formality:
            data["formality"] = formality

        result = self._make_request("translate", data)

        if result.get("translations"):
            translation = result["translations"][0]
            return {
                "translated_text": translation["text"],
                "detected_source_language": translation.get("detected_source_language"),
                "source_lang": source_lang or translation.get("detected_source_language")
            }
        return {"error": "Translation failed"}

    def translate_batch(self, texts: List[str], target_lang: str,
                       source_lang: Optional[str] = None) -> List[Dict]:
        """批量翻译"""
        data = {"target_lang": target_lang.upper()}
        if source_lang:
            data["source_lang"] = source_lang.upper()

        for i, text in enumerate(texts):
            data[f"text[{i}]"] = text

        result = self._make_request("translate", data)

        translations = []
        for t in result.get("translations", []):
            translations.append({
                "translated_text": t["text"],
                "detected_source_language": t.get("detected_source_language")
            })
        return translations

    def get_usage(self) -> Dict:
        """获取API使用情况"""
        if not self.api_key:
            raise RuntimeError("DeepL API key not configured")

        headers = {"Authorization": f"DeepL-Auth-Key {self.api_key}"}
        response = requests.get(f"{self.api_url}/usage", headers=headers)

        if response.status_code == 200:
            return response.json()
        return {"error": "Failed to get usage"}

    def list_languages(self, type: str = "target") -> List[Dict]:
        """列出支持的语言"""
        if not self.api_key:
            return [{"code": k, "name": v} for k, v in LANGUAGES.items()]

        headers = {"Authorization": f"DeepL-Auth-Key {self.api_key}"}
        response = requests.get(f"{self.api_url}/languages?type={type}", headers=headers)

        if response.status_code == 200:
            return response.json()
        return [{"code": k, "name": v} for k, v in LANGUAGES.items()]

# 全局DeepL管理器
deepl_manager = DeepLManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "18",
        "name": "DeepL",
        "api_configured": bool(DEEPL_API_KEY),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/translate")
async def translate(request: TranslateRequest):
    """翻译文本"""
    try:
        result = deepl_manager.translate(
            text=request.text,
            target_lang=request.target_lang,
            source_lang=request.source_lang,
            formality=request.formality
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/translate/batch")
async def translate_batch(request: BatchTranslateRequest):
    """批量翻译"""
    try:
        results = deepl_manager.translate_batch(
            texts=request.texts,
            target_lang=request.target_lang,
            source_lang=request.source_lang
        )
        return {"translations": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/usage")
async def get_usage():
    """获取API使用情况"""
    try:
        usage = deepl_manager.get_usage()
        return usage
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/languages")
async def list_languages(type: str = "target"):
    """列出支持的语言"""
    try:
        languages = deepl_manager.list_languages(type)
        return {"languages": languages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8018)
