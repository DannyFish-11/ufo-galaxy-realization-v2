"""
Node 15: OCR - 光学字符识别
"""
import os, tempfile, base64
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 15 - OCR", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

pytesseract = None
PIL = None
try:
    import pytesseract as _pytesseract
    from PIL import Image
    pytesseract = _pytesseract
    PIL = Image
except ImportError:
    pass

class OCRRequest(BaseModel):
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    language: str = "eng+chi_sim"

@app.get("/health")
async def health():
    tesseract_available = pytesseract is not None
    return {"status": "healthy" if tesseract_available else "degraded", "node_id": "15", "name": "OCR", "tesseract_available": tesseract_available, "timestamp": datetime.now().isoformat()}

@app.post("/recognize")
async def recognize_text(request: OCRRequest):
    if not pytesseract or not PIL:
        raise HTTPException(status_code=503, detail="pytesseract or PIL not installed")
    
    if request.image_path:
        if not os.path.exists(request.image_path):
            raise HTTPException(status_code=404, detail="Image not found")
        image = PIL.open(request.image_path)
    elif request.image_base64:
        import io
        image_data = base64.b64decode(request.image_base64)
        image = PIL.open(io.BytesIO(image_data))
    else:
        raise HTTPException(status_code=400, detail="Provide image_path or image_base64")
    
    try:
        text = pytesseract.image_to_string(image, lang=request.language)
        data = pytesseract.image_to_data(image, lang=request.language, output_type=pytesseract.Output.DICT)
        
        words = []
        for i, word in enumerate(data["text"]):
            if word.strip():
                words.append({"text": word, "confidence": data["conf"][i], "x": data["left"][i], "y": data["top"][i], "width": data["width"][i], "height": data["height"][i]})
        
        return {"success": True, "text": text.strip(), "words": words, "word_count": len(words)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/upload")
async def upload_and_recognize(file: UploadFile = File(...), language: str = "eng+chi_sim"):
    if not pytesseract or not PIL:
        raise HTTPException(status_code=503, detail="pytesseract or PIL not installed")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        image = PIL.open(tmp_path)
        text = pytesseract.image_to_string(image, lang=language)
        return {"success": True, "filename": file.filename, "text": text.strip()}
    finally:
        os.unlink(tmp_path)

@app.get("/languages")
async def list_languages():
    if not pytesseract:
        raise HTTPException(status_code=503, detail="pytesseract not installed")
    try:
        langs = pytesseract.get_languages()
        return {"success": True, "languages": langs}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "recognize": return await recognize_text(OCRRequest(**params))
    elif tool == "languages": return await list_languages()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8015)
