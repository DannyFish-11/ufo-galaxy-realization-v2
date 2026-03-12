# -*- coding: utf-8 -*-

"""
Node_73_Learning: 机器学习服务节点 (FastAPI)

支持模型注册、训练任务调度和推理。
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ---------------------------------------------------------------------------
# Port / CORS config (optional dependencies)
# ---------------------------------------------------------------------------

try:
    from core.port_config import get_service_port
    PORT = get_service_port("node_73") or 8073
except Exception:
    PORT = int(os.getenv("PORT", "8073"))

try:
    from nodes.common.cors_config import get_cors_origins
    CORS_ORIGINS = get_cors_origins()
except Exception:
    CORS_ORIGINS = ["*"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[Node_73] %(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Node_73_Learning")

# ---------------------------------------------------------------------------
# Enums & Data classes
# ---------------------------------------------------------------------------

class ServiceStatus(Enum):
    UNINITIALIZED = "uninitialized"
    INITIALIZING  = "initializing"
    RUNNING       = "running"
    STOPPED       = "stopped"
    ERROR         = "error"


class ModelType(Enum):
    CLASSIFICATION = "classification"
    REGRESSION     = "regression"
    CLUSTERING     = "clustering"
    CUSTOM         = "custom"


class TaskStatus(Enum):
    PENDING     = "pending"
    TRAINING    = "training"
    INFERENCING = "inferencing"
    COMPLETED   = "completed"
    FAILED      = "failed"


@dataclass
class ModelInfo:
    name: str
    model_type: str
    config: Dict[str, Any]
    version: str = "1.0.0"
    path: str = ""
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = "registered"


@dataclass
class TrainingJob:
    job_id: str
    model_name: str
    dataset: Any
    hyperparams: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class InferenceResult:
    result_id: str
    model_name: str
    input_data: Any
    prediction: Optional[Any] = None
    confidence: Optional[float] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------

class LearningService:
    """机器学习主服务"""

    def __init__(self):
        self.status = ServiceStatus.RUNNING
        self._models: Dict[str, ModelInfo] = {}
        self._jobs: Dict[str, TrainingJob] = {}
        self._results: List[InferenceResult] = []
        self._max_results = 100  # keep last 100 inference results
        logger.info("LearningService 初始化完成")

    # -- model management ----------------------------------------------------

    def register_model(self, name: str, model_type: str, config: Dict[str, Any], version: str = "1.0.0", path: str = "") -> ModelInfo:
        info = ModelInfo(name=name, model_type=model_type, config=config, version=version, path=path)
        self._models[name] = info
        logger.info(f"模型已注册: {name} (type={model_type})")
        return info

    def get_model(self, name: str) -> Optional[ModelInfo]:
        return self._models.get(name)

    def list_models(self) -> List[ModelInfo]:
        return list(self._models.values())

    # -- training ------------------------------------------------------------

    async def start_training(self, model_name: str, dataset: Any, hyperparams: Dict[str, Any]) -> TrainingJob:
        job_id = str(uuid.uuid4())
        job = TrainingJob(job_id=job_id, model_name=model_name, dataset=dataset, hyperparams=hyperparams)
        self._jobs[job_id] = job
        # Run asynchronously in background
        asyncio.create_task(self._run_training(job))
        return job

    async def _run_training(self, job: TrainingJob):
        """模拟训练过程"""
        try:
            job.status = TaskStatus.TRAINING
            logger.info(f"开始训练任务 {job.job_id} (model={job.model_name})")
            # Simulate training delay
            await asyncio.sleep(5)
            job.status = TaskStatus.COMPLETED
            job.completed_at = datetime.utcnow().isoformat()
            job.result = {
                "accuracy": round(0.85 + len(job.model_name) % 10 * 0.01, 4),
                "loss": round(0.15 - len(job.model_name) % 10 * 0.005, 4),
                "epochs": job.hyperparams.get("epochs", 10),
            }
            # Update model status if it exists
            if job.model_name in self._models:
                self._models[job.model_name].status = "trained"
            logger.info(f"训练任务 {job.job_id} 完成")
        except asyncio.CancelledError:
            job.status = TaskStatus.FAILED
            job.error = "任务被取消"
        except Exception as e:
            job.status = TaskStatus.FAILED
            job.error = str(e)
            logger.error(f"训练任务 {job.job_id} 失败: {e}")

    def get_training_job(self, job_id: str) -> Optional[TrainingJob]:
        return self._jobs.get(job_id)

    # -- inference -----------------------------------------------------------

    async def run_inference(self, model_name: str, input_data: Any) -> InferenceResult:
        result_id = str(uuid.uuid4())
        result = InferenceResult(result_id=result_id, model_name=model_name, input_data=input_data)
        self._results.append(result)
        # trim history
        if len(self._results) > self._max_results:
            self._results = self._results[-self._max_results:]
        # Run asynchronously in background
        asyncio.create_task(self._run_inference_task(result))
        return result

    async def _run_inference_task(self, result: InferenceResult):
        """模拟推理过程"""
        try:
            result.status = TaskStatus.INFERENCING
            logger.info(f"开始推理 {result.result_id} (model={result.model_name})")
            if result.model_name not in self._models:
                raise ValueError(f"模型未注册: {result.model_name}")
            await asyncio.sleep(1)  # simulate inference latency
            model = self._models[result.model_name]
            mt = model.model_type.lower()
            if mt == "classification":
                result.prediction = {"label": "positive", "confidence": 0.92}
            elif mt == "regression":
                result.prediction = {"value": round(42.0 + hash(str(result.input_data)) % 100 * 0.1, 4)}
            elif mt == "clustering":
                result.prediction = {"cluster": hash(str(result.input_data)) % 5}
            else:
                result.prediction = {"output": str(result.input_data)}
            result.confidence = 0.92
            result.status = TaskStatus.COMPLETED
            result.completed_at = datetime.utcnow().isoformat()
            logger.info(f"推理 {result.result_id} 完成")
        except Exception as e:
            result.status = TaskStatus.FAILED
            result.error = str(e)
            logger.error(f"推理 {result.result_id} 失败: {e}")

    def get_recent_results(self, limit: int = 20) -> List[InferenceResult]:
        return list(reversed(self._results[-limit:]))

    def to_dict(self, obj) -> Dict[str, Any]:
        from dataclasses import asdict
        d = asdict(obj)
        for k, v in d.items():
            if isinstance(v, Enum):
                d[k] = v.value
        return d


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class RegisterModelRequest(BaseModel):
    name: str
    model_type: str = "classification"
    config: Dict[str, Any] = {}
    version: str = "1.0.0"
    path: str = ""

class TrainRequest(BaseModel):
    model_name: str
    dataset: Any
    hyperparams: Dict[str, Any] = {}

class InferRequest(BaseModel):
    model_name: str
    input_data: Any

class MCPCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

_svc = LearningService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Node_73_Learning FastAPI 启动")
    # Register a couple of default demo models
    _svc.register_model("classifier_a", "classification", {"layers": 3, "units": 128})
    _svc.register_model("regressor_b", "regression", {"layers": 2, "units": 64})
    yield
    logger.info("Node_73_Learning FastAPI 关闭")

app = FastAPI(
    title="Node_73_Learning",
    description="机器学习服务 API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- routes ------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "node": "Node_73_Learning", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status")
def status():
    return {
        "status": _svc.status.value,
        "node": "Node_73_Learning",
        "model_count": len(_svc._models),
        "active_jobs": sum(1 for j in _svc._jobs.values() if j.status in (TaskStatus.PENDING, TaskStatus.TRAINING)),
        "total_jobs": len(_svc._jobs),
        "total_inference_results": len(_svc._results),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/models")
def list_models():
    models = _svc.list_models()
    return {"models": [_svc.to_dict(m) for m in models], "count": len(models)}


@app.post("/model/register", status_code=201)
def register_model(req: RegisterModelRequest):
    info = _svc.register_model(req.name, req.model_type, req.config, req.version, req.path)
    return _svc.to_dict(info)


@app.get("/model/{name}")
def get_model(name: str):
    info = _svc.get_model(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"模型不存在: {name}")
    return _svc.to_dict(info)


@app.post("/train", status_code=202)
async def start_train(req: TrainRequest):
    if _svc.get_model(req.model_name) is None:
        raise HTTPException(status_code=404, detail=f"模型未注册: {req.model_name}")
    job = await _svc.start_training(req.model_name, req.dataset, req.hyperparams)
    return _svc.to_dict(job)


@app.get("/train/{job_id}")
def get_training_job(job_id: str):
    job = _svc.get_training_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"训练任务不存在: {job_id}")
    return _svc.to_dict(job)


@app.post("/infer", status_code=202)
async def run_infer(req: InferRequest):
    if _svc.get_model(req.model_name) is None:
        raise HTTPException(status_code=404, detail=f"模型未注册: {req.model_name}")
    result = await _svc.run_inference(req.model_name, req.input_data)
    return _svc.to_dict(result)


@app.get("/results")
def get_results(limit: int = 20):
    results = _svc.get_recent_results(limit)
    return {"results": [_svc.to_dict(r) for r in results], "count": len(results)}


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    p = req.params
    try:
        if req.tool == "register_model":
            info = _svc.register_model(p["name"], p.get("model_type","classification"), p.get("config",{}), p.get("version","1.0.0"), p.get("path",""))
            return {"result": _svc.to_dict(info)}
        elif req.tool == "list_models":
            return {"result": [_svc.to_dict(m) for m in _svc.list_models()]}
        elif req.tool == "get_model":
            info = _svc.get_model(p["name"])
            if not info:
                raise HTTPException(status_code=404, detail="not found")
            return {"result": _svc.to_dict(info)}
        elif req.tool == "train":
            job = await _svc.start_training(p["model_name"], p.get("dataset"), p.get("hyperparams",{}))
            return {"result": _svc.to_dict(job)}
        elif req.tool == "infer":
            result = await _svc.run_inference(p["model_name"], p.get("input_data"))
            return {"result": _svc.to_dict(result)}
        elif req.tool == "get_status":
            return {"result": _svc.status.value}
        else:
            raise HTTPException(status_code=404, detail=f"未知工具: {req.tool}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
