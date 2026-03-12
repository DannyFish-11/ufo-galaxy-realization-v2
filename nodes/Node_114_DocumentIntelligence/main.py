"""
Node 114: DocumentIntelligence
================================
Document understanding and intelligence: PDF/Word/text parsing, information
extraction, document summarization, table extraction, Q&A over documents,
and document classification using OpenAI.
"""

import asyncio
import os
import re
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from nodes.common.cors_config import get_cors_origins
except Exception:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_114_DocumentIntelligence")
except Exception:
    _DEFAULT_PORT = 8114

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NODE_ID = "114"
NODE_NAME = "DocumentIntelligence"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_DOCUMENT_SIZE_MB = int(os.getenv("MAX_DOCUMENT_SIZE_MB", "10"))

_start_time = datetime.now()

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ParseRequest(BaseModel):
    content: str
    format: str = "text"  # text | markdown | html


class SummarizeRequest(BaseModel):
    text: str
    max_length: int = 200
    style: str = "brief"  # brief | detailed | bullets


class ExtractInfoRequest(BaseModel):
    text: str
    fields: List[str] = ["date", "entities", "keywords"]


class QARequest(BaseModel):
    document: str
    question: str


class ClassifyRequest(BaseModel):
    text: str
    categories: List[str]


class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_openai():
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured. Set the environment variable to use AI features.",
        )


def _clean_text(raw: str, fmt: str) -> str:
    if fmt == "html":
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"&[a-zA-Z]+;", " ", raw)
    elif fmt == "markdown":
        raw = re.sub(r"!\[.*?\]\(.*?\)", "", raw)
        raw = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw)
        raw = re.sub(r"[#*`_~>]+", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


async def _openai_chat(system_prompt: str, user_content: str) -> str:
    _require_openai()
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_114_DocumentIntelligence",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "uptime_seconds": uptime,
        "config": {
            "model": OPENAI_MODEL,
            "openai_base_url": OPENAI_BASE_URL,
            "openai_configured": bool(OPENAI_API_KEY),
            "max_document_size_mb": MAX_DOCUMENT_SIZE_MB,
        },
    }


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    params = req.parameters
    dispatch = {
        "parse": lambda: _parse_text(params.get("content", ""), params.get("format", "text")),
        "summarize": lambda: _summarize(
            params.get("text", ""),
            params.get("max_length", 200),
            params.get("style", "brief"),
        ),
        "extract_info": lambda: _extract_info(params.get("text", ""), params.get("fields", [])),
        "qa": lambda: _qa(params.get("document", ""), params.get("question", "")),
        "classify": lambda: _classify(params.get("text", ""), params.get("categories", [])),
    }
    handler = dispatch.get(tool)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool}")
    result = handler()
    if asyncio.iscoroutine(result):
        result = await result
    return {"tool": tool, "result": result}


@app.post("/parse")
async def parse_document(request: Optional[ParseRequest] = None, file: Optional[UploadFile] = File(None)):
    if file is not None:
        max_bytes = MAX_DOCUMENT_SIZE_MB * 1024 * 1024
        raw_bytes = await file.read(max_bytes + 1)
        if len(raw_bytes) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File exceeds {MAX_DOCUMENT_SIZE_MB} MB limit")
        raw = raw_bytes.decode("utf-8", errors="replace")
        fmt = "text"
        if file.filename:
            if file.filename.endswith(".html") or file.filename.endswith(".htm"):
                fmt = "html"
            elif file.filename.endswith(".md"):
                fmt = "markdown"
    elif request is not None:
        raw = request.content
        fmt = request.format
    else:
        raise HTTPException(status_code=422, detail="Provide JSON body or file upload")

    text = _parse_text(raw, fmt)
    return text


def _parse_text(content: str, fmt: str) -> Dict[str, Any]:
    text = _clean_text(content, fmt)
    words = text.split()
    return {
        "text": text,
        "word_count": len(words),
        "char_count": len(text),
    }


@app.post("/summarize")
async def summarize(req: SummarizeRequest):
    return await _summarize(req.text, req.max_length, req.style)


async def _summarize(text: str, max_length: int, style: str) -> Dict[str, Any]:
    style_instructions = {
        "brief": f"Provide a brief summary in no more than {max_length} words.",
        "detailed": f"Provide a detailed summary in no more than {max_length} words.",
        "bullets": f"Summarize as bullet points (max {max_length} words total).",
    }
    instruction = style_instructions.get(style, style_instructions["brief"])
    system = f"You are a document summarization assistant. {instruction} Return only the summary."
    summary = await _openai_chat(system, text[:8000])
    return {
        "summary": summary,
        "original_length": len(text),
        "summary_length": len(summary),
    }


@app.post("/extract_info")
async def extract_info(req: ExtractInfoRequest):
    return await _extract_info(req.text, req.fields)


async def _extract_info(text: str, fields: List[str]) -> Dict[str, Any]:
    if not fields:
        fields = ["date", "entities", "keywords"]
    fields_desc = ", ".join(fields)
    system = (
        "You are an information extraction assistant. Extract the requested fields from the document. "
        f"Fields to extract: {fields_desc}. "
        "Return a valid JSON object where each key is one of the requested fields. "
        "If a field is not found, use null. For list fields (entities, keywords, tables), return arrays."
    )
    raw = await _openai_chat(system, text[:8000])
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        result = json.loads(json_match.group(0)) if json_match else {}
    except Exception:
        result = {"raw": raw}
    return result


@app.post("/qa")
async def qa(req: QARequest):
    return await _qa(req.document, req.question)


async def _qa(document: str, question: str) -> Dict[str, Any]:
    system = (
        "You are a document Q&A assistant. Answer the question using only information "
        "from the provided document. If the answer is not in the document, say so clearly."
    )
    user_content = f"Document:\n{document[:6000]}\n\nQuestion: {question}"
    answer = await _openai_chat(system, user_content)
    return {"question": question, "answer": answer}


@app.post("/classify")
async def classify(req: ClassifyRequest):
    return await _classify(req.text, req.categories)


async def _classify(text: str, categories: List[str]) -> Dict[str, Any]:
    if not categories:
        raise HTTPException(status_code=422, detail="At least one category is required")
    cats_list = ", ".join(f'"{c}"' for c in categories)
    system = (
        f"You are a document classification assistant. Classify the document into exactly one of: {cats_list}. "
        "Return a JSON object with keys: 'category' (the chosen category string) and 'confidence' (0.0-1.0) "
        "and 'reasoning' (brief explanation)."
    )
    raw = await _openai_chat(system, text[:4000])
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        result = json.loads(json_match.group(0)) if json_match else {"category": raw, "confidence": 1.0}
    except Exception:
        result = {"category": raw.strip(), "confidence": 1.0, "reasoning": ""}
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_114_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting Node {NODE_ID} - {NODE_NAME} on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
