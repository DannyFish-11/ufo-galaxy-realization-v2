# -*- coding: utf-8 -*-

"""
Node_73_Learning: 机器学习服务节点 (FastAPI)

支持模型注册、训练任务调度和推理。
"""

import logging  # auto: ensure module logger is defined
logger = logging.getLogger(__name__)


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
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8073"))

try:
    from nodes.common.cors_config import get_cors_origins
    CORS_ORIGINS = get_cors_origins()
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    CORS_ORIGINS = ["*"]

MODEL_DIR = os.getenv("NODE_73_MODEL_DIR", os.path.join(os.path.dirname(__file__), "trained_models"))

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
        self._estimators: Dict[str, Any] = {}  # model_name -> fitted sklearn estimator
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info("LearningService 初始化完成")

    @staticmethod
    def _build_estimator(model_type: str, hyperparams: Dict[str, Any]):
        """按模型类型构建真实 sklearn 估计器（无匹配类型则抛错，不臆造）。"""
        mt = model_type.lower()
        if mt == "classification":
            from sklearn.ensemble import RandomForestClassifier
            return RandomForestClassifier(
                n_estimators=int(hyperparams.get("n_estimators", 100)),
                max_depth=hyperparams.get("max_depth"),
                random_state=hyperparams.get("random_state", 42),
            )
        elif mt == "regression":
            from sklearn.ensemble import RandomForestRegressor
            return RandomForestRegressor(
                n_estimators=int(hyperparams.get("n_estimators", 100)),
                max_depth=hyperparams.get("max_depth"),
                random_state=hyperparams.get("random_state", 42),
            )
        elif mt == "clustering":
            from sklearn.cluster import KMeans
            return KMeans(
                n_clusters=int(hyperparams.get("n_clusters", 3)),
                random_state=hyperparams.get("random_state", 42),
                n_init="auto",
            )
        raise ValueError(f"不支持的 model_type: {model_type}（支持: classification/regression/clustering）")

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
        """真实训练：用 scikit-learn 在提交的数据集上拟合模型，产出真实指标。

        dataset 期望形状: {"X": [[float, ...], ...], "y": [...]}（clustering 可省略 y）。
        """
        try:
            job.status = TaskStatus.TRAINING
            logger.info(f"开始训练任务 {job.job_id} (model={job.model_name})")

            model_info = self._models.get(job.model_name)
            if not model_info:
                raise ValueError(f"模型未注册: {job.model_name}")

            if not isinstance(job.dataset, dict) or "X" not in job.dataset:
                raise ValueError('dataset 必须是 {"X": [[...], ...], "y": [...]} 形状')
            X = job.dataset["X"]
            y = job.dataset.get("y")
            if not isinstance(X, list) or not X:
                raise ValueError("dataset.X 必须是非空的特征向量列表")

            mt = model_info.model_type.lower()
            if mt != "clustering" and y is None:
                raise ValueError(f"model_type={mt} 需要提供 dataset.y")

            estimator = await asyncio.to_thread(self._fit_estimator, mt, job.hyperparams, X, y)

            model_path = os.path.join(MODEL_DIR, f"{job.model_name}.joblib")
            import joblib
            await asyncio.to_thread(joblib.dump, estimator, model_path)
            self._estimators[job.model_name] = estimator

            job.result = self._score_estimator(mt, estimator, X, y)
            job.status = TaskStatus.COMPLETED
            job.completed_at = datetime.utcnow().isoformat()

            model_info.status = "trained"
            model_info.path = model_path
            logger.info(f"训练任务 {job.job_id} 完成: {job.result}")
        except asyncio.CancelledError:
            job.status = TaskStatus.FAILED
            job.error = "任务被取消"
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            job.status = TaskStatus.FAILED
            job.error = str(e)
            logger.error(f"训练任务 {job.job_id} 失败: {e}")

    @staticmethod
    def _fit_estimator(model_type: str, hyperparams: Dict[str, Any], X: List[List[float]], y: Optional[List[Any]]):
        estimator = LearningService._build_estimator(model_type, hyperparams)
        if model_type == "clustering":
            estimator.fit(X)
        else:
            estimator.fit(X, y)
        return estimator

    @staticmethod
    def _score_estimator(model_type: str, estimator, X: List[List[float]], y: Optional[List[Any]]) -> Dict[str, Any]:
        """在训练集上计算真实指标（无留出测试集时如实标注 in_sample）。"""
        if model_type == "classification":
            from sklearn.metrics import accuracy_score, f1_score
            preds = estimator.predict(X)
            return {
                "accuracy": round(float(accuracy_score(y, preds)), 4),
                "f1_weighted": round(float(f1_score(y, preds, average="weighted", zero_division=0)), 4),
                "n_samples": len(X),
                "metric_scope": "in_sample",
            }
        elif model_type == "regression":
            from sklearn.metrics import mean_squared_error, r2_score
            preds = estimator.predict(X)
            return {
                "r2": round(float(r2_score(y, preds)), 4),
                "mse": round(float(mean_squared_error(y, preds)), 4),
                "n_samples": len(X),
                "metric_scope": "in_sample",
            }
        else:  # clustering
            return {
                "inertia": round(float(estimator.inertia_), 4),
                "n_clusters": int(estimator.n_clusters),
                "n_samples": len(X),
            }

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
        """真实推理：用已训练好的 sklearn 估计器对输入特征向量做预测。"""
        try:
            result.status = TaskStatus.INFERENCING
            logger.info(f"开始推理 {result.result_id} (model={result.model_name})")
            model_info = self._models.get(result.model_name)
            if not model_info:
                raise ValueError(f"模型未注册: {result.model_name}")

            estimator = self._estimators.get(result.model_name)
            if estimator is None and model_info.path and os.path.exists(model_info.path):
                import joblib
                estimator = await asyncio.to_thread(joblib.load, model_info.path)
                self._estimators[result.model_name] = estimator
            if estimator is None:
                raise ValueError(f"模型尚未训练，无可用估计器: {result.model_name}")

            if not isinstance(result.input_data, list):
                raise ValueError("input_data 必须是特征向量（数值列表）")

            mt = model_info.model_type.lower()
            X = [result.input_data]
            prediction = await asyncio.to_thread(estimator.predict, X)

            # sklearn predictions are numpy scalars - convert to native
            # Python types so the FastAPI/dataclass JSON response doesn't
            # choke on non-serializable numpy int64/float64 values.
            def _native(v):
                return v.item() if hasattr(v, "item") else v

            if mt == "classification":
                result.prediction = {"label": _native(prediction[0])}
                if hasattr(estimator, "predict_proba"):
                    proba = await asyncio.to_thread(estimator.predict_proba, X)
                    result.confidence = round(float(max(proba[0])), 4)
            elif mt == "regression":
                result.prediction = {"value": round(float(prediction[0]), 4)}
            elif mt == "clustering":
                result.prediction = {"cluster": int(prediction[0])}
            else:
                result.prediction = {"output": _native(prediction[0]) if hasattr(prediction, "__getitem__") else prediction}

            result.status = TaskStatus.COMPLETED
            result.completed_at = datetime.utcnow().isoformat()
            logger.info(f"推理 {result.result_id} 完成")
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            result.status = TaskStatus.FAILED
            result.error = str(e)
            logger.error(f"推理 {result.result_id} 失败: {e}")

    def get_recent_results(self, limit: int = 20) -> List[InferenceResult]:
        return list(reversed(self._results[-limit:]))

    def to_dict(self, obj) -> Dict[str, Any]:
        from dataclasses import asdict
        d = asdict(obj)
        for k, v in list(d.items()):
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
