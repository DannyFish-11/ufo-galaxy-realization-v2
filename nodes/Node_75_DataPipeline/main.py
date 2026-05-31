"""
Node 75: DataPipeline - ETL Data Processing Pipeline
Supports create, run, status, list, delete pipelines and data transformation.
"""
import os
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_75_DataPipeline")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8075"))

MAX_WORKERS = int(os.getenv("PIPELINE_MAX_WORKERS", "4"))
BATCH_SIZE = int(os.getenv("PIPELINE_BATCH_SIZE", "100"))

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    PANDAS_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 75 - DataPipeline", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()


# ---------------------------------------------------------------------------
# In-memory pipeline registry
# ---------------------------------------------------------------------------

class PipelineStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


_pipelines: Dict[str, Dict[str, Any]] = {}
_semaphore = asyncio.Semaphore(MAX_WORKERS)


def _apply_step(data: List[Dict], step: Dict[str, Any]) -> List[Dict]:
    """Apply a single pipeline step to data."""
    op = step.get("operation", "")
    if not PANDAS_AVAILABLE:
        # Fallback pure-Python operations
        if op == "filter":
            field = step.get("field", "")
            value = step.get("value")
            op_type = step.get("op", "eq")
            _ops = {
                "eq": lambda v: v == value,
                "neq": lambda v: v != value,
                "gt": lambda v: v is not None and v > value,
                "lt": lambda v: v is not None and v < value,
                "gte": lambda v: v is not None and v >= value,
                "lte": lambda v: v is not None and v <= value,
                "contains": lambda v: value in str(v),
            }
            match_fn = _ops.get(op_type, lambda v: True)
            return [row for row in data if match_fn(row.get(field))]
        elif op == "select":
            fields = step.get("fields", [])
            return [{f: row.get(f) for f in fields} for row in data]
        elif op == "rename":
            mapping = step.get("mapping", {})
            return [{mapping.get(k, k): v for k, v in row.items()} for row in data]
        elif op == "add_field":
            field = step.get("field", "new_field")
            default = step.get("default", None)
            return [{**row, field: default} for row in data]
        elif op == "drop_field":
            field = step.get("field", "")
            return [{k: v for k, v in row.items() if k != field} for row in data]
        elif op == "limit":
            n = step.get("n", BATCH_SIZE)
            return data[:n]
        elif op == "sort":
            field = step.get("field", "")
            reverse = step.get("descending", False)
            return sorted(data, key=lambda r: r.get(field, 0), reverse=reverse)
        return data

    # Pandas-based operations
    df = pd.DataFrame(data)
    if op == "filter":
        field = step.get("field", "")
        value = step.get("value")
        op_type = step.get("op", "eq")
        if field not in df.columns:
            return data
        if op_type == "eq": df = df[df[field] == value]
        elif op_type == "neq": df = df[df[field] != value]
        elif op_type == "gt": df = df[df[field] > value]
        elif op_type == "lt": df = df[df[field] < value]
        elif op_type == "gte": df = df[df[field] >= value]
        elif op_type == "lte": df = df[df[field] <= value]
        elif op_type == "contains": df = df[df[field].astype(str).str.contains(str(value))]
    elif op == "select":
        fields = [f for f in step.get("fields", []) if f in df.columns]
        if fields:
            df = df[fields]
    elif op == "rename":
        df = df.rename(columns=step.get("mapping", {}))
    elif op == "add_field":
        df[step.get("field", "new_field")] = step.get("default", None)
    elif op == "drop_field":
        field = step.get("field", "")
        if field in df.columns:
            df = df.drop(columns=[field])
    elif op == "limit":
        df = df.head(step.get("n", BATCH_SIZE))
    elif op == "sort":
        field = step.get("field", "")
        if field in df.columns:
            df = df.sort_values(by=field, ascending=not step.get("descending", False))
    elif op == "fillna":
        df = df.fillna(step.get("value", 0))
    elif op == "dropna":
        df = df.dropna()
    elif op == "deduplicate":
        df = df.drop_duplicates()
    return df.to_dict(orient="records")


async def _execute_pipeline(pipeline_id: str) -> None:
    pipeline = _pipelines.get(pipeline_id)
    if not pipeline:
        return

    async with _semaphore:
        pipeline["status"] = PipelineStatus.RUNNING
        pipeline["started_at"] = datetime.now().isoformat()
        try:
            data = list(pipeline.get("input_data", []))
            for i, step in enumerate(pipeline.get("steps", [])):
                data = _apply_step(data, step)
                pipeline["current_step"] = i + 1

            pipeline["output_data"] = data
            pipeline["status"] = PipelineStatus.COMPLETED
            pipeline["completed_at"] = datetime.now().isoformat()
            pipeline["output_rows"] = len(data)
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            pipeline["status"] = PipelineStatus.FAILED
            pipeline["error"] = str(e)
            pipeline["completed_at"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PipelineCreateRequest(BaseModel):
    name: str
    steps: List[Dict[str, Any]]
    description: str = ""


class PipelineRunRequest(BaseModel):
    pipeline_id: str
    data: List[Dict[str, Any]]


class TransformRequest(BaseModel):
    data: List[Dict[str, Any]]
    steps: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "75",
        "name": "DataPipeline",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    running = sum(1 for p in _pipelines.values() if p["status"] == PipelineStatus.RUNNING)
    completed = sum(1 for p in _pipelines.values() if p["status"] == PipelineStatus.COMPLETED)
    return {
        "status": "running",
        "node_id": "75",
        "name": "DataPipeline",
        "uptime_seconds": round(uptime, 2),
        "configuration": {
            "max_workers": MAX_WORKERS,
            "batch_size": BATCH_SIZE,
            "pandas_available": PANDAS_AVAILABLE,
        },
        "metrics": {
            "total_pipelines": len(_pipelines),
            "running": running,
            "completed": completed,
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/pipeline/create")
async def pipeline_create(request: PipelineCreateRequest):
    """Create a new pipeline definition."""
    pipeline_id = str(uuid.uuid4())
    _pipelines[pipeline_id] = {
        "id": pipeline_id,
        "name": request.name,
        "description": request.description,
        "steps": request.steps,
        "status": PipelineStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "current_step": 0,
        "input_data": [],
        "output_data": [],
        "output_rows": 0,
        "error": None,
    }
    return {"success": True, "pipeline_id": pipeline_id, "name": request.name}


@app.post("/pipeline/run")
async def pipeline_run(request: PipelineRunRequest):
    """Run a pipeline with provided data."""
    pipeline = _pipelines.get(request.pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {request.pipeline_id} not found")

    pipeline["input_data"] = request.data
    pipeline["status"] = PipelineStatus.PENDING
    pipeline["current_step"] = 0
    pipeline["error"] = None

    asyncio.create_task(_execute_pipeline(request.pipeline_id))
    return {
        "success": True,
        "pipeline_id": request.pipeline_id,
        "status": "started",
        "input_rows": len(request.data),
    }


@app.get("/pipeline/status/{pipeline_id}")
async def pipeline_status(pipeline_id: str):
    """Get status of a specific pipeline run."""
    pipeline = _pipelines.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    result = {k: v for k, v in pipeline.items() if k not in ("input_data", "output_data")}
    if pipeline["status"] == PipelineStatus.COMPLETED:
        result["output_data"] = pipeline["output_data"][:BATCH_SIZE]
    return {"success": True, "pipeline": result}


@app.get("/pipeline/list")
async def pipeline_list():
    """List all pipelines."""
    summaries = []
    for p in _pipelines.values():
        summaries.append({
            "id": p["id"],
            "name": p["name"],
            "status": p["status"],
            "created_at": p["created_at"],
            "output_rows": p.get("output_rows", 0),
        })
    return {"success": True, "pipelines": summaries, "total": len(summaries)}


@app.delete("/pipeline/delete/{pipeline_id}")
async def pipeline_delete(pipeline_id: str):
    """Delete a pipeline."""
    if pipeline_id not in _pipelines:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    del _pipelines[pipeline_id]
    return {"success": True, "pipeline_id": pipeline_id, "message": "Pipeline deleted"}


@app.post("/transform")
async def transform(request: TransformRequest):
    """Apply transformation steps to data inline (no pipeline stored)."""
    try:
        data = list(request.data)
        for step in request.steps:
            data = _apply_step(data, step)
        return {
            "success": True,
            "input_rows": len(request.data),
            "output_rows": len(data),
            "data": data,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "pipeline_create":
        return await pipeline_create(PipelineCreateRequest(**params))
    elif tool == "pipeline_run":
        return await pipeline_run(PipelineRunRequest(**params))
    elif tool == "pipeline_status":
        return await pipeline_status(params.get("pipeline_id", ""))
    elif tool == "pipeline_list":
        return await pipeline_list()
    elif tool == "pipeline_delete":
        return await pipeline_delete(params.get("pipeline_id", ""))
    elif tool == "transform":
        return await transform(TransformRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
