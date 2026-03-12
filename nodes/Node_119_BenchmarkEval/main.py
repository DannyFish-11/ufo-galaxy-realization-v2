"""
Node 119: BenchmarkEval
========================
AI model benchmarking and evaluation: run evaluation datasets, calculate
metrics (accuracy, F1, BLEU, ROUGE), compare model outputs, and generate
evaluation reports.
"""

import os
import json
import math
import uuid
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from nodes.common.cors_config import get_cors_origins
except Exception:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_119_BenchmarkEval")
except Exception:
    _DEFAULT_PORT = 8119

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NODE_ID = "119"
NODE_NAME = "BenchmarkEval"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EVAL_STORAGE_PATH = os.getenv("EVAL_STORAGE_PATH", "./eval_results")

_start_time = datetime.now()

Path(EVAL_STORAGE_PATH).mkdir(parents=True, exist_ok=True)

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

class EvaluateRequest(BaseModel):
    predictions: List[str]
    references: List[str]
    metrics: List[str] = ["exact_match", "f1"]


class LLMEvalRequest(BaseModel):
    model_output: str
    reference: str
    criteria: List[str] = ["accuracy", "fluency", "relevance"]


class BatchTask(BaseModel):
    id: str
    prompt: str
    reference: str


class BatchEvalRequest(BaseModel):
    tasks: List[BatchTask]
    model_url: str


class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Metric implementations (pure Python, no external NLP deps)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    return text.lower().split()


def _get_ngrams(tokens: List[str], n: int) -> Counter:
    return Counter(tuple(tokens[i: i + n]) for i in range(len(tokens) - n + 1))


def _clip_count(pred_ngrams: Counter, ref_ngrams: Counter) -> int:
    clipped = 0
    for ngram, count in pred_ngrams.items():
        clipped += min(count, ref_ngrams.get(ngram, 0))
    return clipped


def _bleu_score(prediction: str, reference: str, max_n: int = 4) -> float:
    pred_tokens = _tokenize(prediction)
    ref_tokens = _tokenize(reference)
    # Guard ensures len(pred_tokens) > 0 before the brevity-penalty division below.
    if not pred_tokens:
        return 0.0
    # Brevity penalty: safe because pred_tokens is non-empty at this point.
    bp = 1.0 if len(pred_tokens) >= len(ref_tokens) else math.exp(1 - len(ref_tokens) / len(pred_tokens))
    log_avg = 0.0
    for n in range(1, max_n + 1):
        pred_ng = _get_ngrams(pred_tokens, n)
        ref_ng = _get_ngrams(ref_tokens, n)
        total = sum(pred_ng.values())
        if total == 0:
            return 0.0
        clipped = _clip_count(pred_ng, ref_ng)
        precision = clipped / total
        if precision == 0:
            return 0.0
        log_avg += math.log(precision)
    return bp * math.exp(log_avg / max_n)


def _rouge1_score(prediction: str, reference: str) -> Dict[str, float]:
    pred_tokens = _tokenize(prediction)
    ref_tokens = _tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    pred_counts = Counter(pred_tokens)
    ref_counts = Counter(ref_tokens)
    overlap = sum(min(pred_counts[t], ref_counts[t]) for t in pred_counts)
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _token_f1(prediction: str, reference: str) -> float:
    pred_tokens = _tokenize(prediction)
    ref_tokens = _tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0
    pred_counts = Counter(pred_tokens)
    ref_counts = Counter(ref_tokens)
    overlap = sum(min(pred_counts[t], ref_counts[t]) for t in pred_counts)
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0


def _exact_match(prediction: str, reference: str) -> bool:
    return prediction.strip().lower() == reference.strip().lower()


def _compute_metrics(predictions: List[str], references: List[str], metrics: List[str]) -> Dict[str, Any]:
    if len(predictions) != len(references):
        raise ValueError("predictions and references must have equal length")
    results: Dict[str, Any] = {}
    n = len(predictions)

    if "exact_match" in metrics:
        matches = sum(_exact_match(p, r) for p, r in zip(predictions, references))
        results["exact_match"] = matches / n if n > 0 else 0.0

    if "f1" in metrics:
        f1_scores = [_token_f1(p, r) for p, r in zip(predictions, references)]
        results["f1"] = sum(f1_scores) / n if n > 0 else 0.0

    if "bleu" in metrics:
        bleu_scores = [_bleu_score(p, r) for p, r in zip(predictions, references)]
        results["bleu"] = sum(bleu_scores) / n if n > 0 else 0.0

    if "rouge" in metrics:
        rouge_scores = [_rouge1_score(p, r) for p, r in zip(predictions, references)]
        results["rouge_1"] = {
            "precision": sum(s["precision"] for s in rouge_scores) / n if n > 0 else 0.0,
            "recall": sum(s["recall"] for s in rouge_scores) / n if n > 0 else 0.0,
            "f1": sum(s["f1"] for s in rouge_scores) / n if n > 0 else 0.0,
        }

    return results


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _save_result(eval_id: str, data: Dict[str, Any]):
    path = Path(EVAL_STORAGE_PATH) / f"{eval_id}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Could not save eval result {eval_id}: {e}")


def _load_result(eval_id: str) -> Optional[Dict[str, Any]]:
    path = Path(EVAL_STORAGE_PATH) / f"{eval_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _list_results() -> List[Dict[str, Any]]:
    results = []
    for path in sorted(Path(EVAL_STORAGE_PATH).glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append({
                "eval_id": data.get("eval_id", path.stem),
                "type": data.get("type", "unknown"),
                "created_at": data.get("created_at", ""),
                "sample_count": data.get("sample_count", 0),
            })
        except Exception:
            continue
    return results


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# OpenAI helper
# ---------------------------------------------------------------------------

async def _openai_chat(system: str, user: str) -> str:
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured. Set the environment variable to use AI evaluation.",
        )
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{OPENAI_BASE_URL}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_119_BenchmarkEval",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    stored = len(list(Path(EVAL_STORAGE_PATH).glob("*.json")))
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "uptime_seconds": uptime,
        "config": {
            "model": OPENAI_MODEL,
            "openai_base_url": OPENAI_BASE_URL,
            "openai_configured": bool(OPENAI_API_KEY),
            "eval_storage_path": EVAL_STORAGE_PATH,
        },
        "stored_results": stored,
    }


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    p = req.parameters
    if tool == "list_eval_results":
        return {"tool": tool, "result": _list_results()}
    if tool == "get_eval_result":
        result = _load_result(p.get("eval_id", ""))
        if not result:
            raise HTTPException(status_code=404, detail="Evaluation result not found")
        return {"tool": tool, "result": result}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool}")


@app.post("/evaluate")
async def evaluate(req: EvaluateRequest):
    if len(req.predictions) != len(req.references):
        raise HTTPException(status_code=422, detail="predictions and references must have equal length")
    metrics = _compute_metrics(req.predictions, req.references, req.metrics)
    eval_id = str(uuid.uuid4())
    result = {
        "eval_id": eval_id,
        "type": "metrics",
        "created_at": _now_iso(),
        "metrics": metrics,
        "sample_count": len(req.predictions),
    }
    _save_result(eval_id, result)
    return result


@app.post("/llm_eval")
async def llm_eval(req: LLMEvalRequest):
    import re
    criteria_list = ", ".join(req.criteria)
    system = (
        "You are an expert evaluator. Score the model output on each criterion from 1 to 10. "
        f"Criteria: {criteria_list}. "
        "Return a JSON object with keys: 'scores' (object mapping criterion to integer 1-10), "
        "'overall' (average score as float), and 'reasoning' (brief explanation string)."
    )
    user = (
        f"Reference answer:\n{req.reference}\n\n"
        f"Model output:\n{req.model_output}"
    )
    raw = await _openai_chat(system, user)
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(json_match.group(0)) if json_match else {}
    except Exception:
        data = {"raw": raw}

    scores = data.get("scores", {})
    if scores and "overall" not in data:
        vals = [v for v in scores.values() if isinstance(v, (int, float))]
        data["overall"] = sum(vals) / len(vals) if vals else 0.0

    eval_id = str(uuid.uuid4())
    result = {
        "eval_id": eval_id,
        "type": "llm_eval",
        "created_at": _now_iso(),
        **data,
    }
    _save_result(eval_id, result)
    return result


@app.post("/batch_eval")
async def batch_eval(req: BatchEvalRequest):
    predictions: List[str] = []
    references: List[str] = []
    task_results: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for task in req.tasks:
            try:
                resp = await client.post(req.model_url, json={"prompt": task.prompt})
                resp.raise_for_status()
                resp_data = resp.json()
                prediction = resp_data.get("output") or resp_data.get("response") or resp_data.get("text", "")
            except Exception as e:
                prediction = ""
                logger.warning(f"Task {task.id} request failed: {e}")

            predictions.append(prediction)
            references.append(task.reference)
            task_results.append({
                "id": task.id,
                "prompt": task.prompt,
                "reference": task.reference,
                "prediction": prediction,
                "exact_match": _exact_match(prediction, task.reference),
                "f1": _token_f1(prediction, task.reference),
            })

    aggregate = _compute_metrics(predictions, references, ["exact_match", "f1"])
    eval_id = str(uuid.uuid4())
    result = {
        "eval_id": eval_id,
        "type": "batch_eval",
        "created_at": _now_iso(),
        "sample_count": len(req.tasks),
        "model_url": req.model_url,
        "aggregate_metrics": aggregate,
        "task_results": task_results,
    }
    _save_result(eval_id, result)
    return result


@app.get("/eval_results")
async def list_eval_results():
    return {"results": _list_results()}


@app.get("/eval_results/{eval_id}")
async def get_eval_result(eval_id: str):
    result = _load_result(eval_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Evaluation result '{eval_id}' not found")
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_119_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting Node {NODE_ID} - {NODE_NAME} on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
