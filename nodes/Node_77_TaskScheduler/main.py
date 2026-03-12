"""
Node 77: TaskScheduler - Cron-like task scheduling with asyncio execution
Supports basic cron expressions: minute, hour, day-of-week fields.
"""
import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_77_TaskScheduler")
except Exception:
    PORT = int(os.getenv("PORT", "8077"))

SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "UTC")
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "10"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 77 - TaskScheduler", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


# ---------------------------------------------------------------------------
# Cron expression parser (subset: minute hour dow)
# ---------------------------------------------------------------------------

def _parse_field(field: str, min_val: int, max_val: int) -> List[int]:
    """Parse a cron field into a list of matching values."""
    if field == "*":
        return list(range(min_val, max_val + 1))
    result = set()
    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            values = _parse_field(base, min_val, max_val)
            result.update(values[::step])
        elif "-" in part:
            start, end = part.split("-", 1)
            result.update(range(int(start), int(end) + 1))
        else:
            result.add(int(part))
    return sorted(result)


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime matches the cron expression (minute hour dow)."""
    parts = cron_expr.strip().split()
    if len(parts) < 3:
        return False
    minute_field, hour_field, dow_field = parts[0], parts[1], parts[2]
    minutes = _parse_field(minute_field, 0, 59)
    hours = _parse_field(hour_field, 0, 23)
    dows = _parse_field(dow_field, 0, 6)
    return dt.minute in minutes and dt.hour in hours and dt.weekday() in dows


# ---------------------------------------------------------------------------
# In-memory job registry and history
# ---------------------------------------------------------------------------

class JobStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    RUNNING = "running"
    COMPLETED = "completed"


_jobs: Dict[str, Dict[str, Any]] = {}
_history: List[Dict[str, Any]] = []
_scheduler_running = False
_scheduler_task: Optional[asyncio.Task] = None


async def _run_job(job: Dict[str, Any]) -> None:
    """Execute a single job."""
    if job["status"] == JobStatus.PAUSED:
        return

    async with _semaphore:
        job["status"] = JobStatus.RUNNING
        job["last_run"] = datetime.now().isoformat()
        run_record = {
            "job_id": job["id"],
            "job_name": job["name"],
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "success": False,
            "result": None,
            "error": None,
        }

        try:
            command = job.get("command", "")
            job_type = job.get("type", "echo")

            if job_type == "http":
                import httpx
                url = job.get("url", "")
                method = job.get("method", "GET").upper()
                payload = job.get("payload", {})
                async with httpx.AsyncClient(timeout=30) as client:
                    if method == "POST":
                        resp = await client.post(url, json=payload)
                    else:
                        resp = await client.get(url)
                    run_record["result"] = {
                        "status_code": resp.status_code,
                        "body": resp.text[:500],
                    }
            elif job_type == "python":
                # Safe evaluation of Python literals only (no arbitrary code execution)
                import ast
                result = ast.literal_eval(command)
                run_record["result"] = str(result)
            else:
                # Default: echo job
                run_record["result"] = f"Job '{job['name']}' executed: {command}"

            run_record["success"] = True
            job["run_count"] = job.get("run_count", 0) + 1
        except Exception as e:
            run_record["error"] = str(e)
            logger.error(f"Job {job['id']} failed: {e}")
        finally:
            run_record["completed_at"] = datetime.now().isoformat()
            _history.append(run_record)
            if len(_history) > 1000:
                _history.pop(0)

            # Restore status
            if job.get("repeat", True):
                job["status"] = JobStatus.ACTIVE
            else:
                job["status"] = JobStatus.COMPLETED


async def _scheduler_loop() -> None:
    """Main scheduler loop - checks jobs every 30 seconds."""
    global _scheduler_running
    _scheduler_running = True
    logger.info("Scheduler loop started")
    while _scheduler_running:
        now = datetime.now()
        for job in list(_jobs.values()):
            if job["status"] != JobStatus.ACTIVE:
                continue
            cron = job.get("cron", "")
            if cron and _cron_matches(cron, now):
                asyncio.create_task(_run_job(job))
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup():
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())


@app.on_event("shutdown")
async def shutdown():
    global _scheduler_running, _scheduler_task
    _scheduler_running = False
    if _scheduler_task:
        _scheduler_task.cancel()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class JobCreateRequest(BaseModel):
    name: str
    cron: str = "* * *"  # minute hour dow
    type: str = "echo"   # echo, http, python
    command: str = ""
    url: str = ""
    method: str = "GET"
    payload: Dict[str, Any] = {}
    repeat: bool = True
    description: str = ""


class JobUpdateRequest(BaseModel):
    name: Optional[str] = None
    cron: Optional[str] = None
    command: Optional[str] = None
    url: Optional[str] = None
    method: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    repeat: Optional[bool] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "77",
        "name": "TaskScheduler",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    active = sum(1 for j in _jobs.values() if j["status"] == JobStatus.ACTIVE)
    return {
        "status": "running",
        "node_id": "77",
        "name": "TaskScheduler",
        "uptime_seconds": round(uptime, 2),
        "configuration": {
            "timezone": SCHEDULER_TIMEZONE,
            "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
            "scheduler_running": _scheduler_running,
        },
        "metrics": {
            "total_jobs": len(_jobs),
            "active_jobs": active,
            "history_entries": len(_history),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/jobs")
async def list_jobs():
    """List all jobs."""
    return {"success": True, "jobs": list(_jobs.values()), "total": len(_jobs)}


@app.post("/job/create")
async def job_create(request: JobCreateRequest):
    """Create a new scheduled job."""
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "name": request.name,
        "cron": request.cron,
        "type": request.type,
        "command": request.command,
        "url": request.url,
        "method": request.method,
        "payload": request.payload,
        "repeat": request.repeat,
        "description": request.description,
        "status": JobStatus.ACTIVE,
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "run_count": 0,
    }
    _jobs[job_id] = job
    return {"success": True, "job_id": job_id, "job": job}


@app.get("/job/{job_id}")
async def job_get(job_id: str):
    """Get a specific job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"success": True, "job": job}


@app.delete("/job/{job_id}")
async def job_delete(job_id: str):
    """Delete a job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    del _jobs[job_id]
    return {"success": True, "job_id": job_id, "message": "Job deleted"}


@app.put("/job/{job_id}")
async def job_update(job_id: str, request: JobUpdateRequest):
    """Update an existing job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    for field, value in request.model_dump(exclude_none=True).items():
        job[field] = value
    return {"success": True, "job_id": job_id, "job": job}


@app.post("/job/{job_id}/run")
async def job_run_now(job_id: str):
    """Trigger immediate execution of a job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    asyncio.create_task(_run_job(job))
    return {"success": True, "job_id": job_id, "message": "Job triggered for immediate execution"}


@app.post("/job/{job_id}/pause")
async def job_pause(job_id: str):
    """Pause a job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job["status"] = JobStatus.PAUSED
    return {"success": True, "job_id": job_id, "status": JobStatus.PAUSED}


@app.post("/job/{job_id}/resume")
async def job_resume(job_id: str):
    """Resume a paused job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job["status"] == JobStatus.PAUSED:
        job["status"] = JobStatus.ACTIVE
    return {"success": True, "job_id": job_id, "status": job["status"]}


@app.get("/history")
async def get_history(limit: int = 50):
    """Get recent job execution history."""
    recent = list(reversed(_history))[:limit]
    return {"success": True, "history": recent, "total": len(_history)}


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "list_jobs":
        return await list_jobs()
    elif tool == "job_create":
        return await job_create(JobCreateRequest(**params))
    elif tool == "job_get":
        return await job_get(params.get("job_id", ""))
    elif tool == "job_delete":
        return await job_delete(params.get("job_id", ""))
    elif tool == "job_update":
        return await job_update(params.get("job_id", ""), JobUpdateRequest(**{k: v for k, v in params.items() if k != "job_id"}))
    elif tool == "job_run_now":
        return await job_run_now(params.get("job_id", ""))
    elif tool == "job_pause":
        return await job_pause(params.get("job_id", ""))
    elif tool == "job_resume":
        return await job_resume(params.get("job_id", ""))
    elif tool == "history":
        return await get_history(params.get("limit", 50))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
