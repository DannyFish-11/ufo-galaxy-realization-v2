"""dashboard/backend/main.py
==============================
Galaxy Dashboard backend — FastAPI application entry-point.

This module provides the HTTP API that powers the Galaxy operator dashboard.
It is a *hard* import consumer of :mod:`core.unified_response`; the
``UnifiedChatResponse`` class must never be re-defined inline as a fallback.

Optional dependencies use the ``_*_AVAILABLE`` flag pattern so that the
application degrades gracefully when auxiliary libraries are absent rather
than defining inline replacement classes or functions inside ``except``
blocks.

PR-3 (Batch) — configuration authority cleanup
----------------------------------------------
- Hard import of ``UnifiedChatResponse`` from :mod:`core.unified_response`.
- ``_CORS_ORIGINS_AVAILABLE`` flag guards the CORS-origins helper.
- ``_ASCII_ART_AVAILABLE`` flag guards the startup banner helper.
- No inline class / function definitions inside ``except ImportError`` blocks.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, List

# ---------------------------------------------------------------------------
# Hard dependencies — must be importable; failures surface at startup
# ---------------------------------------------------------------------------

from core.unified_response import UnifiedChatResponse  # noqa: F401 — hard dependency

# ---------------------------------------------------------------------------
# Optional: CORS origins helper
# ---------------------------------------------------------------------------

try:
    from nodes.common.cors_config import get_cors_origins as _get_cors_origins_impl
    _CORS_ORIGINS_AVAILABLE = True
except ImportError:
    _CORS_ORIGINS_AVAILABLE = False
    _get_cors_origins_impl = None  # type: ignore[assignment]


def get_cors_origins() -> List[str]:
    """Return the list of allowed CORS origins.

    Returns an empty list when the CORS-origins helper is unavailable so the
    application can still start in degraded mode.
    """
    if _CORS_ORIGINS_AVAILABLE and _get_cors_origins_impl is not None:
        try:
            return list(_get_cors_origins_impl())
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Optional: ASCII art / startup banner
# ---------------------------------------------------------------------------

try:
    from core.ascii_art import print_banner as _print_banner_impl
    _ASCII_ART_AVAILABLE = True
except ImportError:
    _ASCII_ART_AVAILABLE = False
    _print_banner_impl = None  # type: ignore[assignment]


def _print_banner() -> None:
    """Print the Galaxy startup banner if the ascii_art module is available."""
    if _ASCII_ART_AVAILABLE and _print_banner_impl is not None:
        try:
            _print_banner_impl()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

logger = logging.getLogger("Galaxy.Dashboard.Backend")


def create_app() -> Any:
    """Create and return the Galaxy Dashboard FastAPI application.

    Returns the application object.  Imports FastAPI lazily so that this
    module is importable even in environments where FastAPI is not installed
    (e.g., unit-test environments).
    """
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:  # pragma: no cover
        warnings.warn(
            f"FastAPI is not installed; Galaxy Dashboard backend unavailable: {exc}",
            ImportWarning,
            stacklevel=2,
        )
        return None

    app = FastAPI(
        title="Galaxy Dashboard API",
        description="Operator control surface for the Galaxy center-distributed agent system.",
        version="2.0.0",
    )

    origins = get_cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _print_banner()
    return app


# ---------------------------------------------------------------------------
# Module-level singleton (used when running with uvicorn directly)
# ---------------------------------------------------------------------------

app = create_app()
