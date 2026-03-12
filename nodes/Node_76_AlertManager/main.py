"""
Node 76: AlertManager - Alert management with multi-channel notifications
Supports email (SMTP), Slack webhooks, and generic webhooks.
"""
import os
import uuid
import smtplib
import asyncio
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_76_AlertManager")
except Exception:
    PORT = int(os.getenv("PORT", "8076"))

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    HTTPX_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 76 - AlertManager", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()


# ---------------------------------------------------------------------------
# In-memory alert and rule storage
# ---------------------------------------------------------------------------

_alerts: Dict[str, Dict[str, Any]] = {}
_rules: Dict[str, Dict[str, Any]] = {}


class AlertSeverity:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus:
    ACTIVE = "active"
    RESOLVED = "resolved"
    SILENCED = "silenced"


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

async def _send_email(to: str, subject: str, body: str) -> Dict[str, Any]:
    if not SMTP_HOST:
        return {"success": False, "error": "SMTP not configured. Set SMTP_HOST environment variable."}
    if not SMTP_USER:
        return {"success": False, "error": "SMTP user not configured. Set SMTP_USER environment variable."}
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to
        msg.attach(MIMEText(body, "plain"))

        def _send():
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                if SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, [to], msg.as_string())

        await asyncio.get_event_loop().run_in_executor(None, _send)
        return {"success": True, "channel": "email", "recipient": to}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _send_slack(message: str) -> Dict[str, Any]:
    if not SLACK_WEBHOOK_URL:
        return {"success": False, "error": "Slack webhook not configured. Set SLACK_WEBHOOK_URL environment variable."}
    if not HTTPX_AVAILABLE:
        return {"success": False, "error": "httpx not installed"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(SLACK_WEBHOOK_URL, json={"text": message})
            resp.raise_for_status()
        return {"success": True, "channel": "slack"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _send_webhook(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not url:
        return {"success": False, "error": "Webhook URL not configured. Set WEBHOOK_URL environment variable."}
    if not HTTPX_AVAILABLE:
        return {"success": False, "error": "httpx not installed"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return {"success": True, "channel": "webhook", "url": url}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AlertCreateRequest(BaseModel):
    title: str
    message: str
    severity: str = AlertSeverity.MEDIUM
    source: str = ""
    labels: Dict[str, str] = {}


class RuleCreateRequest(BaseModel):
    name: str
    condition: str
    severity: str = AlertSeverity.MEDIUM
    channels: List[str] = []
    description: str = ""


class NotifyRequest(BaseModel):
    channel: str  # email, slack, webhook
    message: str
    recipient: str = ""
    subject: str = "Galaxy Alert"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "76",
        "name": "AlertManager",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    active = sum(1 for a in _alerts.values() if a["status"] == AlertStatus.ACTIVE)
    return {
        "status": "running",
        "node_id": "76",
        "name": "AlertManager",
        "uptime_seconds": round(uptime, 2),
        "configuration": {
            "smtp_configured": bool(SMTP_HOST and SMTP_USER),
            "slack_configured": bool(SLACK_WEBHOOK_URL),
            "webhook_configured": bool(WEBHOOK_URL),
        },
        "metrics": {
            "total_alerts": len(_alerts),
            "active_alerts": active,
            "total_rules": len(_rules),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/alerts")
async def list_alerts(status_filter: Optional[str] = None, severity: Optional[str] = None):
    """List all alerts with optional filters."""
    alerts = list(_alerts.values())
    if status_filter:
        alerts = [a for a in alerts if a["status"] == status_filter]
    if severity:
        alerts = [a for a in alerts if a["severity"] == severity]
    return {"success": True, "alerts": alerts, "total": len(alerts)}


@app.post("/alert/create")
async def alert_create(request: AlertCreateRequest):
    """Create a new alert."""
    alert_id = str(uuid.uuid4())
    alert = {
        "id": alert_id,
        "title": request.title,
        "message": request.message,
        "severity": request.severity,
        "source": request.source,
        "labels": request.labels,
        "status": AlertStatus.ACTIVE,
        "created_at": datetime.now().isoformat(),
        "resolved_at": None,
        "silenced_until": None,
    }
    _alerts[alert_id] = alert
    return {"success": True, "alert_id": alert_id, "alert": alert}


@app.get("/alert/{alert_id}")
async def alert_get(alert_id: str):
    """Get a specific alert."""
    alert = _alerts.get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"success": True, "alert": alert}


@app.delete("/alert/{alert_id}")
async def alert_delete(alert_id: str):
    """Delete an alert."""
    if alert_id not in _alerts:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    del _alerts[alert_id]
    return {"success": True, "alert_id": alert_id, "message": "Alert deleted"}


@app.post("/alert/{alert_id}/resolve")
async def alert_resolve(alert_id: str):
    """Resolve an alert."""
    alert = _alerts.get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    alert["status"] = AlertStatus.RESOLVED
    alert["resolved_at"] = datetime.now().isoformat()
    return {"success": True, "alert_id": alert_id, "status": AlertStatus.RESOLVED}


@app.post("/alert/{alert_id}/silence")
async def alert_silence(alert_id: str, duration_minutes: int = 60):
    """Silence an alert for a given duration."""
    alert = _alerts.get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    from datetime import timedelta
    until = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()
    alert["status"] = AlertStatus.SILENCED
    alert["silenced_until"] = until
    return {"success": True, "alert_id": alert_id, "silenced_until": until}


@app.get("/rules")
async def list_rules():
    """List all alert rules."""
    return {"success": True, "rules": list(_rules.values()), "total": len(_rules)}


@app.post("/rules")
async def create_rule(request: RuleCreateRequest):
    """Create an alert routing rule."""
    rule_id = str(uuid.uuid4())
    rule = {
        "id": rule_id,
        "name": request.name,
        "condition": request.condition,
        "severity": request.severity,
        "channels": request.channels,
        "description": request.description,
        "created_at": datetime.now().isoformat(),
    }
    _rules[rule_id] = rule
    return {"success": True, "rule_id": rule_id, "rule": rule}


@app.post("/notify")
async def notify(request: NotifyRequest):
    """Send a notification through the specified channel."""
    if request.channel == "email":
        result = await _send_email(request.recipient, request.subject, request.message)
    elif request.channel == "slack":
        result = await _send_slack(request.message)
    elif request.channel == "webhook":
        url = request.recipient or WEBHOOK_URL
        result = await _send_webhook(url, {"message": request.message, "subject": request.subject})
    else:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {request.channel}. Use email, slack, or webhook.")
    return result


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "list_alerts":
        return await list_alerts()
    elif tool == "alert_create":
        return await alert_create(AlertCreateRequest(**params))
    elif tool == "alert_get":
        return await alert_get(params.get("alert_id", ""))
    elif tool == "alert_delete":
        return await alert_delete(params.get("alert_id", ""))
    elif tool == "alert_resolve":
        return await alert_resolve(params.get("alert_id", ""))
    elif tool == "alert_silence":
        return await alert_silence(params.get("alert_id", ""), params.get("duration_minutes", 60))
    elif tool == "list_rules":
        return await list_rules()
    elif tool == "create_rule":
        return await create_rule(RuleCreateRequest(**params))
    elif tool == "notify":
        return await notify(NotifyRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
