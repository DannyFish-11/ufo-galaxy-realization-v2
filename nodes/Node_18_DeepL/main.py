"""
Node 18: DeepL - 专业翻译服务
"""
import os, requests
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 18 - DeepL", version="3.0.0", description="DeepL Translation API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"

class TranslateRequest(BaseModel):
    text: str | List[str]
    target_lang: str
    source_lang: Optional[str] = None
    formality: Optional[str] = "default"

SUPPORTED_LANGUAGES = {
    "ZH": "Chinese", "EN": "English", "DE": "German", "FR": "French",
    "ES": "Spanish", "IT": "Italian", "JA": "Japanese", "KO": "Korean",
    "RU": "Russian", "PT": "Portuguese", "NL": "Dutch", "PL": "Polish"
}

@app.get("/health")
async def health():
    return {
        "status": "healthy" if DEEPL_API_KEY else "degraded",
        "node_id": "18",
        "name": "DeepL",
        "api_key_configured": bool(DEEPL_API_KEY),
        "supported_languages": len(SUPPORTED_LANGUAGES)
    }

@app.post("/translate")
async def translate(request: TranslateRequest):
    """翻译文本"""
    if not DEEPL_API_KEY:
        raise HTTPException(status_code=503, detail="DEEPL_API_KEY not configured")
    
    texts = [request.text] if isinstance(request.text, str) else request.text
    
    payload = {
        "auth_key": DEEPL_API_KEY,
        "text": texts,
        "target_lang": request.target_lang.upper()
    }
    
    if request.source_lang:
        payload["source_lang"] = request.source_lang.upper()
    if request.formality != "default":
        payload["formality"] = request.formality
    
    try:
        response = requests.post(DEEPL_API_URL, data=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        translations = [t["text"] for t in result["translations"]]
        detected_langs = [t.get("detected_source_language", "unknown") for t in result["translations"]]
        
        return {
            "success": True,
            "translations": translations if len(translations) > 1 else translations[0],
            "detected_source_language": detected_langs[0] if detected_langs else "unknown",
            "target_language": request.target_lang
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/languages")
async def list_languages():
    """列出支持的语言"""
    return {"success": True, "languages": SUPPORTED_LANGUAGES}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "translate": return await translate(TranslateRequest(**params))
    elif tool == "languages": return await list_languages()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8018)
