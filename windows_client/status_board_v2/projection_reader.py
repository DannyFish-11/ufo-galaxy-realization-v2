"""
windows_client/status_board_v2/projection_reader.py
=====================================================
ProjectionReader — fetches RuntimeProjection data for the Status Board V2.

READ-ONLY: This module only reads data.  It never sends commands or writes
state back to the server.

Three input modes are supported (tried in priority order):
1. **HTTP endpoint** — polls ``GET <base_url>/api/v1/projection/runtime``
2. **File path**     — reads a JSON file on disk (useful for offline testing)
3. **stdin**         — reads a single JSON blob from standard input

In all cases the returned dict conforms to the :class:`~core.projection.RuntimeProjection`
schema so that the surface renderers can consume it without modification.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


# Default endpoint path (appended to the base URL).
PROJECTION_ENDPOINT = "/api/v1/projection/runtime"

# Fields required in every valid projection dict.
_REQUIRED_FIELDS = frozenset(
    [
        "tri_state_phase",
        "runtime_domain",
        "presence_intensity",
        "coherence",
        "collapse_tendency",
        "retreat_tendency",
        "primary_model_id",
        "support_model_ids",
        "active_weights",
        "active_device_ids",
        "execution_stage",
        "timestamp",
    ]
)


class ProjectionReader:
    """Reads a RuntimeProjection from an HTTP endpoint, a file, or stdin.

    READ-ONLY: this class never writes to the server or triggers any actions.

    Parameters
    ----------
    base_url:
        Base URL of the Galaxy server, e.g. ``"http://127.0.0.1:8299"``.
        Used for HTTP polling.  ``None`` disables HTTP mode.
    file_path:
        Path to a local JSON file containing a serialised projection.
        ``None`` disables file mode.
    from_stdin:
        When ``True``, read a single JSON blob from ``sys.stdin`` and cache
        it for all subsequent calls to :meth:`read`.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: Optional[str] = "http://127.0.0.1:8299",
        file_path: Optional[str] = None,
        from_stdin: bool = False,
        timeout: float = 3.0,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._file_path = file_path
        self._from_stdin = from_stdin
        self._timeout = timeout
        self._stdin_cache: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> Dict[str, Any]:
        """Return the latest projection dict.

        Tries each source in priority order:
        1. HTTP endpoint (if ``base_url`` is set)
        2. File (if ``file_path`` is set)
        3. stdin (if ``from_stdin`` is ``True``)

        Returns a valid minimal projection on any error so that callers
        always receive something renderable.

        Raises
        ------
        ProjectionReadError
            When all configured sources fail and no fallback is available.
            (In practice the board catches this and shows OFFLINE.)
        """
        last_error: Optional[Exception] = None

        if self._base_url is not None:
            try:
                return self._read_http()
            except Exception as exc:
                last_error = exc

        if self._file_path is not None:
            try:
                return self._read_file()
            except Exception as exc:
                last_error = exc

        if self._from_stdin:
            try:
                return self._read_stdin()
            except Exception as exc:
                last_error = exc

        raise ProjectionReadError(
            f"All projection sources failed. Last error: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Source implementations
    # ------------------------------------------------------------------

    def _read_http(self) -> Dict[str, Any]:
        """Fetch the projection from the HTTP endpoint."""
        url = f"{self._base_url}{PROJECTION_ENDPOINT}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        _validate(data)
        return data

    def _read_file(self) -> Dict[str, Any]:
        """Read projection JSON from a file."""
        with open(self._file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        _validate(data)
        return data

    def _read_stdin(self) -> Dict[str, Any]:
        """Read projection JSON from stdin (cached after first read)."""
        if self._stdin_cache is not None:
            return self._stdin_cache
        raw = sys.stdin.read()
        data = json.loads(raw)
        _validate(data)
        self._stdin_cache = data
        return data


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _validate(data: Any) -> None:
    """Raise :exc:`ProjectionReadError` if *data* is not a valid projection dict."""
    if not isinstance(data, dict):
        raise ProjectionReadError(
            f"Expected a JSON object, got {type(data).__name__}"
        )
    missing = _REQUIRED_FIELDS - data.keys()
    if missing:
        raise ProjectionReadError(
            f"Projection dict is missing required fields: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class ProjectionReadError(RuntimeError):
    """Raised when a projection cannot be read from any configured source."""
