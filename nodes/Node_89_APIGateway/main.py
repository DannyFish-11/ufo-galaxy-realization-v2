"""
Node 89: API Gateway - API网关
Route, proxy, and manage requests to other nodes.
Features: route registration, node registry, rate limiting, request logging,
health checking and metrics.
"""

import os
import uuid
import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager
from collections import defaultdict, deque

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

try:
    from core.port_config import get_node_port
    _port_from_config = get_node_port("Node_89_APIGateway")
except Exception:
    _port_from_config = None

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins(): return ["*"]

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = "89"
NODE_NAME = "APIGateway"
PORT = _port_from_config or int(os.getenv("NODE_PORT", "8089"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

GATEWAY_RATE_LIMIT = int(os.getenv("GATEWAY_RATE_LIMIT", "100"))   # requests per minute per client
GATEWAY_TIMEOUT = int(os.getenv("GATEWAY_TIMEOUT", "30"))          # seconds
NODE_REGISTRY_URL = os.getenv("NODE_REGISTRY_URL", "")

START_TIME = datetime.now()

# =============================================================================
# Pydantic Models
# =============================================================================

class RouteDefinition(BaseModel):
    path: str = Field(..., description="Route path prefix, e.g. '/api/v1/search'")
    target_url: str = Field(..., description="Backend URL to forward to")
    methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE", "PATCH"])
    auth_required: bool = Field(default=False)
    rate_limit: Optional[int] = Field(None, description="Requests/min override (None = global limit)")
    strip_prefix: bool = Field(default=False, description="Strip route path prefix before forwarding")
    description: Optional[str] = None

class NodeDefinition(BaseModel):
    node_id: str
    name: str
    url: str = Field(..., description="Base URL of the node, e.g. 'http://localhost:8085'")
    capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}

# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Simple sliding-window in-memory rate limiter."""

    def __init__(self):
        # client_key -> deque of request timestamps
        self._windows: Dict[str, deque] = defaultdict(deque)

    def is_allowed(self, client_key: str, limit: int) -> bool:
        now = time.monotonic()
        window = self._windows[client_key]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def remaining(self, client_key: str, limit: int) -> int:
        now = time.monotonic()
        window = self._windows[client_key]
        cutoff = now - 60.0
        count = sum(1 for t in window if t >= cutoff)
        return max(0, limit - count)


rate_limiter = RateLimiter()

# =============================================================================
# Gateway Service
# =============================================================================

class GatewayService:
    def __init__(self):
        self.routes: Dict[str, dict] = {}
        self.nodes: Dict[str, dict] = {}
        self._metrics = {
            "total_requests": 0,
            "total_errors": 0,
            "total_proxied": 0,
            "rate_limited": 0,
            "latencies_ms": deque(maxlen=1000),
            "requests_per_node": defaultdict(int),
            "errors_per_node": defaultdict(int),
        }
        self._request_log: deque = deque(maxlen=500)

    # -------------------------------------------------------------------------
    # Route management
    # -------------------------------------------------------------------------

    def register_route(self, route: RouteDefinition) -> dict:
        route_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        entry = {
            "id": route_id,
            "path": route.path,
            "target_url": route.target_url.rstrip("/"),
            "methods": [m.upper() for m in route.methods],
            "auth_required": route.auth_required,
            "rate_limit": route.rate_limit,
            "strip_prefix": route.strip_prefix,
            "description": route.description,
            "created_at": now,
            "hit_count": 0,
        }
        self.routes[route_id] = entry
        logger.info(f"Registered route '{route.path}' -> '{route.target_url}' (id={route_id})")
        return {"success": True, "route_id": route_id, "route": entry}

    def delete_route(self, route_id: str) -> dict:
        if route_id not in self.routes:
            return {"success": False, "error": f"Route '{route_id}' not found"}
        self.routes.pop(route_id)
        return {"success": True, "deleted": route_id}

    def list_routes(self) -> List[dict]:
        return list(self.routes.values())

    def _match_route(self, path: str, method: str) -> Optional[dict]:
        """Find the best-matching route (longest prefix)."""
        best = None
        best_len = -1
        for route in self.routes.values():
            prefix = route["path"]
            if path.startswith(prefix) and method.upper() in route["methods"]:
                if len(prefix) > best_len:
                    best = route
                    best_len = len(prefix)
        return best

    # -------------------------------------------------------------------------
    # Node management
    # -------------------------------------------------------------------------

    def register_node(self, node: NodeDefinition) -> dict:
        now = datetime.now().isoformat()
        entry = {
            "node_id": node.node_id,
            "name": node.name,
            "url": node.url.rstrip("/"),
            "capabilities": node.capabilities,
            "metadata": node.metadata,
            "registered_at": now,
            "last_seen": now,
            "health": "unknown",
        }
        self.nodes[node.node_id] = entry
        logger.info(f"Registered node '{node.node_id}' ({node.name}) at {node.url}")
        return {"success": True, "node_id": node.node_id, "node": entry}

    def unregister_node(self, node_id: str) -> dict:
        if node_id not in self.nodes:
            return {"success": False, "error": f"Node '{node_id}' not found"}
        self.nodes.pop(node_id)
        return {"success": True, "deleted": node_id}

    async def list_nodes_with_health(self) -> List[dict]:
        nodes = list(self.nodes.values())
        tasks = [self._check_node_health(n) for n in nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for node, health in zip(nodes, results):
            if isinstance(health, Exception):
                node["health"] = "unhealthy"
                node["health_error"] = str(health)
            else:
                node["health"] = health
        return nodes

    async def _check_node_health(self, node: dict) -> str:
        url = f"{node['url']}/health"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    node["last_seen"] = datetime.now().isoformat()
                    return "healthy"
                return f"unhealthy (HTTP {resp.status_code})"
        except Exception as e:
            return f"unreachable ({e})"

    # -------------------------------------------------------------------------
    # Proxy
    # -------------------------------------------------------------------------

    async def proxy_to_node(self, node_id: str, path: str, request: Request) -> Response:
        node = self.nodes.get(node_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in registry")

        target_url = f"{node['url']}/{path.lstrip('/')}"
        return await self._forward_request(target_url, request, node_id=node_id)

    async def proxy_via_route(self, path: str, request: Request) -> Response:
        route = self._match_route(path, request.method)
        if not route:
            raise HTTPException(status_code=404, detail=f"No route found for {request.method} {path}")

        suffix = path[len(route["path"]):] if route["strip_prefix"] else path
        target_url = route["target_url"] + suffix

        route["hit_count"] = route.get("hit_count", 0) + 1
        return await self._forward_request(target_url, request)

    async def _forward_request(self, target_url: str, request: Request, node_id: str = None) -> Response:
        self._metrics["total_requests"] += 1
        self._metrics["total_proxied"] += 1
        if node_id:
            self._metrics["requests_per_node"][node_id] += 1

        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        query = str(request.url.query)
        full_url = f"{target_url}?{query}" if query else target_url

        start = time.monotonic()
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "path": str(request.url.path),
            "target": full_url,
            "status": None,
            "latency_ms": None,
            "error": None,
        }
        self._request_log.append(log_entry)

        try:
            async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT) as client:
                resp = await client.request(
                    method=request.method,
                    url=full_url,
                    headers=headers,
                    content=body,
                )
            latency_ms = int((time.monotonic() - start) * 1000)
            self._metrics["latencies_ms"].append(latency_ms)
            log_entry["status"] = resp.status_code
            log_entry["latency_ms"] = latency_ms

            resp_headers = dict(resp.headers)
            resp_headers.pop("content-encoding", None)
            resp_headers.pop("transfer-encoding", None)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )
        except httpx.TimeoutException:
            self._metrics["total_errors"] += 1
            if node_id:
                self._metrics["errors_per_node"][node_id] += 1
            log_entry["error"] = "timeout"
            raise HTTPException(status_code=504, detail=f"Gateway timeout forwarding to {target_url}")
        except httpx.RequestError as e:
            self._metrics["total_errors"] += 1
            if node_id:
                self._metrics["errors_per_node"][node_id] += 1
            log_entry["error"] = str(e)
            raise HTTPException(status_code=502, detail=f"Gateway error: {e}")

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    def get_metrics(self) -> dict:
        lats = list(self._metrics["latencies_ms"])
        avg_lat = sum(lats) / len(lats) if lats else 0
        p95_lat = sorted(lats)[int(len(lats) * 0.95)] if lats else 0
        return {
            "total_requests": self._metrics["total_requests"],
            "total_errors": self._metrics["total_errors"],
            "total_proxied": self._metrics["total_proxied"],
            "rate_limited_requests": self._metrics["rate_limited"],
            "error_rate": (
                self._metrics["total_errors"] / self._metrics["total_requests"]
                if self._metrics["total_requests"] else 0
            ),
            "latency": {
                "avg_ms": round(avg_lat, 2),
                "p95_ms": p95_lat,
                "samples": len(lats),
            },
            "requests_per_node": dict(self._metrics["requests_per_node"]),
            "errors_per_node": dict(self._metrics["errors_per_node"]),
            "recent_requests": list(self._request_log)[-20:],
        }

    def record_rate_limited(self):
        self._metrics["rate_limited"] += 1


gateway = GatewayService()

# =============================================================================
# App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚪 Node {NODE_ID} {NODE_NAME} starting on port {PORT}")
    logger.info(f"  Rate limit : {GATEWAY_RATE_LIMIT} req/min")
    logger.info(f"  Timeout    : {GATEWAY_TIMEOUT}s")
    if NODE_REGISTRY_URL:
        logger.info(f"  Registry   : {NODE_REGISTRY_URL}")
    yield
    logger.info(f"Node {NODE_ID} shutting down")


app = FastAPI(
    title=f"Node {NODE_ID} - {NODE_NAME}",
    description="API gateway: route registration, node registry, rate limiting, proxying, metrics",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for health/status/metrics endpoints
    path = request.url.path
    if path in ("/health", "/status", "/metrics"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    limit = GATEWAY_RATE_LIMIT
    if not rate_limiter.is_allowed(client_ip, limit):
        gateway.record_rate_limited()
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window": "1 minute",
                "client": client_ip,
            },
            headers={"Retry-After": "60"},
        )
    return await call_next(request)

# =============================================================================
# Routes
# =============================================================================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - START_TIME).total_seconds()
    return {
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "status": "running",
        "uptime_seconds": uptime,
        "configuration": {
            "rate_limit_per_min": GATEWAY_RATE_LIMIT,
            "timeout_seconds": GATEWAY_TIMEOUT,
            "node_registry_url": NODE_REGISTRY_URL or None,
        },
        "metrics_summary": {
            "total_requests": gateway._metrics["total_requests"],
            "total_errors": gateway._metrics["total_errors"],
            "registered_routes": len(gateway.routes),
            "registered_nodes": len(gateway.nodes),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/routes")
async def list_routes():
    return {"success": True, "routes": gateway.list_routes(), "count": len(gateway.routes)}


@app.post("/route/register")
async def register_route(route: RouteDefinition):
    return gateway.register_route(route)


@app.delete("/route/{route_id}")
async def delete_route(route_id: str):
    result = gateway.delete_route(route_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.get("/nodes")
async def list_nodes():
    nodes = await gateway.list_nodes_with_health()
    return {"success": True, "nodes": nodes, "count": len(nodes)}


@app.post("/node/register")
async def register_node(node: NodeDefinition):
    return gateway.register_node(node)


@app.delete("/node/{node_id}")
async def unregister_node(node_id: str):
    result = gateway.unregister_node(node_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.get("/metrics")
async def get_metrics():
    return {"success": True, "metrics": gateway.get_metrics()}


@app.api_route("/proxy/{node_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_to_node(node_id: str, path: str, request: Request):
    """Proxy a request directly to a registered node."""
    return await gateway.proxy_to_node(node_id, path, request)


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    params = req.parameters

    if tool == "register_route":
        return gateway.register_route(RouteDefinition(**params))
    elif tool == "delete_route":
        return gateway.delete_route(params.get("route_id", ""))
    elif tool == "list_routes":
        return {"success": True, "routes": gateway.list_routes()}
    elif tool == "register_node":
        return gateway.register_node(NodeDefinition(**params))
    elif tool == "unregister_node":
        return gateway.unregister_node(params.get("node_id", ""))
    elif tool == "list_nodes":
        nodes = await gateway.list_nodes_with_health()
        return {"success": True, "nodes": nodes}
    elif tool == "get_metrics":
        return {"success": True, "metrics": gateway.get_metrics()}
    elif tool == "check_node_health":
        node_id = params.get("node_id", "")
        node = gateway.nodes.get(node_id)
        if not node:
            return {"success": False, "error": f"Node '{node_id}' not found"}
        health_status = await gateway._check_node_health(node)
        return {"success": True, "node_id": node_id, "health": health_status}
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool '{tool}'. Available: register_route, delete_route, list_routes, "
                   "register_node, unregister_node, list_nodes, get_metrics, check_node_health"
        )


def get_instance():
    return gateway


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
