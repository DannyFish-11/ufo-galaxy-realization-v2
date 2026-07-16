"""
Shared base utilities for Galaxy nodes.

Provides:
- Unified logging format
- Graceful shutdown signal handlers
- Prometheus /metrics endpoint
- Readiness /ready probe
- Standardized error response format
- Common constants and configuration
"""

import os
import sys
import signal
import time
import logging
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


# =============================================================================
# Constants - extracted from hardcoded values
# =============================================================================

# Default timeout values (in seconds)
DEFAULT_REQUEST_TIMEOUT = int(os.getenv("GALAXY_REQUEST_TIMEOUT", "30"))
DEFAULT_LOCK_TIMEOUT = int(os.getenv("GALAXY_LOCK_TIMEOUT", "30"))
DEFAULT_TASK_TIMEOUT = int(os.getenv("GALAXY_TASK_TIMEOUT", "300"))
DEFAULT_GIT_TIMEOUT = int(os.getenv("GALAXY_GIT_TIMEOUT", "60"))
DEFAULT_CLONE_TIMEOUT = int(os.getenv("GALAXY_CLONE_TIMEOUT", "300"))

# Heartbeat configuration
DEFAULT_HEARTBEAT_INTERVAL = int(os.getenv("GALAXY_HEARTBEAT_INTERVAL", "30"))
DEFAULT_HEALTH_CHECK_INTERVAL = int(os.getenv("GALAXY_HEALTH_CHECK_INTERVAL", "30"))

# File size limits
DEFAULT_MAX_FILE_SIZE = int(os.getenv("GALAXY_MAX_FILE_SIZE", "104857600"))  # 100MB

# Retry configuration
DEFAULT_MAX_RETRIES = int(os.getenv("GALAXY_MAX_RETRIES", "3"))

# =============================================================================
# Unified Logging Format
# =============================================================================

LOG_FORMAT = os.getenv(
    "GALAXY_LOG_FORMAT",
    "%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s"
)
LOG_DATE_FORMAT = os.getenv("GALAXY_LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S %Z")


def setup_logging(name: str, level: Optional[str] = None) -> logging.Logger:
    """Configure unified logging for a node."""
    log_level = level or os.getenv("GALAXY_LOG_LEVEL", "INFO")
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    return logger


# =============================================================================
# Graceful Shutdown
# =============================================================================

_shutdown_requested = False


def is_shutdown_requested() -> bool:
    """Check if graceful shutdown has been requested."""
    return _shutdown_requested


def setup_signal_handlers(logger: logging.Logger) -> None:
    """Set up graceful shutdown signal handlers."""
    def _handle_signal(signum, frame):
        global _shutdown_requested
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        _shutdown_requested = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    # Ignore SIGHUP by default (nodes handle it individually if needed)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)


# =============================================================================
# Standardized Error Response Format
# =============================================================================

class ErrorResponse:
    """Standardized error response format for all nodes."""

    @staticmethod
    def create(
        code: str,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a standardized error response."""
        return {
            "error": {
                "code": code,
                "message": message,
                "status_code": status_code,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": details or {}
            }
        }


async def standard_http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global HTTP exception handler for standardized error responses."""
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", str(exc))
    error_body = ErrorResponse.create(
        code=f"HTTP_{status_code}",
        message=detail,
        status_code=status_code
    )
    return JSONResponse(status_code=status_code, content=error_body)


# =============================================================================
# Prometheus Metrics (simple in-memory implementation)
# =============================================================================

class NodeMetrics:
    """Simple Prometheus-style metrics collector."""

    def __init__(self):
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, list] = {}
        self._start_time = time.time()

    def increment(self, name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        """Set a gauge metric."""
        self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        """Observe a histogram value."""
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus exposition format."""
        lines = []

        # Counters
        for name, value in self._counters.items():
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        # Gauges
        for name, value in self._gauges.items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

        # Histograms (simple sum/count rendering)
        for name, values in self._histograms.items():
            if values:
                lines.append(f"# TYPE {name} histogram")
                lines.append(f"{name}_sum {sum(values)}")
                lines.append(f"{name}_count {len(values)}")

        # Uptime gauge
        uptime = time.time() - self._start_time
        lines.append(f"# TYPE node_uptime_seconds gauge")
        lines.append(f"node_uptime_seconds {uptime:.3f}")

        return "\n".join(lines) + "\n"


# Global metrics instance
node_metrics = NodeMetrics()


# =============================================================================
# Node App Factory
# =============================================================================

def create_node_app(
    node_id: str,
    node_name: str,
    description: str = "",
    version: str = "1.0.0",
    lifespan: Optional[Callable] = None,
) -> FastAPI:
    """
    Create a standard FastAPI app for a Galaxy node.

    Includes:
    - Unified logging
    - Graceful shutdown signal handlers
    - CORS middleware
    - Standardized error responses
    - /health endpoint
    - /ready readiness probe
    - /metrics Prometheus endpoint
    """
    _start_time = time.time()
    logger = setup_logging(f"Galaxy.Node_{node_id}_{node_name}")

    # Set up graceful shutdown handlers
    setup_signal_handlers(logger)

    # Create default lifespan if none provided
    if lifespan is None:
        @asynccontextmanager
        async def _default_lifespan(app: FastAPI):
            logger.info(f"Node {node_id} ({node_name}) starting...")
            yield
            logger.info(f"Node {node_id} ({node_name}) shutting down...")
        lifespan_ctx = _default_lifespan
    else:
        lifespan_ctx = lifespan

    app = FastAPI(
        title=f"Galaxy Node {node_id}: {node_name}",
        description=description,
        version=version,
        lifespan=lifespan_ctx,
    )

    # Add global exception handler for standardized errors
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        error_body = ErrorResponse.create(
            code="INTERNAL_ERROR",
            message=str(exc),
            status_code=500
        )
        return JSONResponse(status_code=500, content=error_body)

    # CORS
    try:
        from nodes.common.cors_config import get_cors_origins
        origins = get_cors_origins()
    except ImportError:
        origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        """Health check endpoint - returns basic liveness."""
        return {
            "status": "healthy",
            "node_id": node_id,
            "node_name": node_name,
            "version": version,
            "uptime_seconds": round(time.time() - _start_time, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/ready")
    async def ready():
        """
        Readiness probe - returns 200 only when node is ready to serve.
        Checks if shutdown has been requested.
        """
        if is_shutdown_requested():
            return JSONResponse(
                status_code=503,
                content={
                    "ready": False,
                    "node_id": node_id,
                    "node_name": node_name,
                    "reason": "shutdown_in_progress",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        return {
            "ready": True,
            "node_id": node_id,
            "node_name": node_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=node_metrics.render_prometheus())

    logger.info(f"Node {node_id} ({node_name}) app created with standard endpoints")
    return app
