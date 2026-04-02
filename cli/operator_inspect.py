#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli/operator_inspect.py
========================
PR-510: Minimal operator-surface CLI diagnostic consumer.

Provides a lightweight command-line interface for reading operator
inspection data from a running Galaxy instance via the
``/api/v1/operator/*`` endpoints.

All data is consumed through the **operator API contract** — this consumer
MUST NOT reach into raw subsystem internals (CanonicalTaskRuntime,
CapabilityAssimilationLayer, etc.) directly.

Usage
-----
::

    # Snapshot — compact runtime overview
    python -m cli.operator_inspect snapshot

    # Inspect a specific task
    python -m cli.operator_inspect task <task_id>

    # Inspect routing decisions for a task
    python -m cli.operator_inspect route <task_id>

    # Inspect an executor/provider node
    python -m cli.operator_inspect executor <node_id>

    # Inspect failure domain for a task
    python -m cli.operator_inspect failure <task_id>

    # Inspect task lineage
    python -m cli.operator_inspect lineage <task_id>

Environment variables
---------------------
``GALAXY_OPERATOR_BASE_URL``
    Base URL of the Galaxy API server.  Defaults to
    ``http://localhost:8000``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

OPERATOR_INSPECT_CLI_AUTHORITY: str = (
    "OPERATOR_INSPECT_CLI_V1: cli/operator_inspect.py is the canonical "
    "minimal operator-surface diagnostic consumer.  It uses only "
    "/api/v1/operator/* endpoints — no raw subsystem internals."
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "http://localhost:8000"


def _base_url() -> str:
    return os.environ.get("GALAXY_OPERATOR_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


# ---------------------------------------------------------------------------
# HTTP helpers — use stdlib only to avoid extra dependencies
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"http", "https"}


def _validated_url(path: str) -> str:
    """Construct and validate the request URL.

    Ensures the base URL uses an allowed scheme (http or https) before
    appending *path*.  Raises ``ValueError`` if the scheme is not allowed.
    """
    from urllib.parse import urlparse
    base = _base_url()
    parsed = urlparse(base)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Disallowed scheme '{parsed.scheme}' in base URL '{base}'. "
            f"Only {_ALLOWED_SCHEMES} are permitted."
        )
    return f"{base}{path}"


def _get_json(path: str) -> tuple[Optional[Dict[str, Any]], int]:
    """Perform a GET request and return ``(data, status_code)``.

    On network errors a ``(None, 0)`` tuple is returned and the error is
    printed to stderr.
    """
    try:
        url = _validated_url(path)
    except ValueError as exc:
        print(f"URL validation error: {exc}", file=sys.stderr)
        return None, 0
    try:
        with urlopen(url, timeout=10) as resp:  # noqa: S310 — URL scheme validated above
            status = resp.status
            body = resp.read().decode("utf-8")
            return json.loads(body), status
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return json.loads(body), exc.code
        except Exception:
            return {"detail": body or str(exc)}, exc.code
    except URLError as exc:
        print(f"Connection error: {exc.reason}", file=sys.stderr)
        return None, 0
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return None, 0


# ---------------------------------------------------------------------------
# Pretty-printing helpers
# ---------------------------------------------------------------------------

def _print_json(data: Any, label: str = "") -> None:
    if label:
        print(f"\n=== {label} ===")
    print(json.dumps(data, indent=2, default=str))


def _print_error(data: Optional[Dict[str, Any]], status: int) -> None:
    if data is None:
        print("No response received from server.", file=sys.stderr)
    else:
        print(
            f"Error {status}: {data.get('detail', data.get('error', data))}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Sub-command handlers — each calls an operator API endpoint
# ---------------------------------------------------------------------------

def cmd_snapshot(_args: argparse.Namespace) -> int:
    """Fetch and display the compact operator runtime snapshot."""
    data, status = _get_json("/api/v1/operator/snapshot")
    if status == 200 and data is not None:
        _print_json(data, "Operator Snapshot")
        # Print a brief human-readable summary
        print(
            f"\nSummary: {data.get('active_task_count', 0)} active tasks | "
            f"{data.get('online_device_count', 0)} online devices | "
            f"{data.get('online_provider_count', 0)} online providers | "
            f"topology {data.get('topology_node_count', 0)}N/{data.get('topology_edge_count', 0)}E"
        )
        return 0
    _print_error(data, status)
    return 1


def cmd_task(args: argparse.Namespace) -> int:
    """Fetch and display a TaskInspection for the given task_id."""
    data, status = _get_json(f"/api/v1/operator/inspect/task/{args.id}")
    if status == 200 and data is not None:
        _print_json(data, f"Task Inspection — {args.id}")
        return 0
    _print_error(data, status)
    return 1


def cmd_route(args: argparse.Namespace) -> int:
    """Fetch and display a RouteInspection for the given task_id."""
    data, status = _get_json(f"/api/v1/operator/inspect/route/{args.id}")
    if status == 200 and data is not None:
        _print_json(data, f"Route Inspection — {args.id}")
        return 0
    _print_error(data, status)
    return 1


def cmd_executor(args: argparse.Namespace) -> int:
    """Fetch and display an ExecutorInspection for the given node_id."""
    data, status = _get_json(f"/api/v1/operator/inspect/executor/{args.id}")
    if status == 200 and data is not None:
        _print_json(data, f"Executor Inspection — {args.id}")
        return 0
    _print_error(data, status)
    return 1


def cmd_failure(args: argparse.Namespace) -> int:
    """Fetch and display a FailureDomainInspection for the given task_id."""
    data, status = _get_json(f"/api/v1/operator/inspect/failure/{args.id}")
    if status == 200 and data is not None:
        _print_json(data, f"Failure Domain Inspection — {args.id}")
        return 0
    _print_error(data, status)
    return 1


def cmd_lineage(args: argparse.Namespace) -> int:
    """Fetch and display a LineageInspection for the given task_id."""
    data, status = _get_json(f"/api/v1/operator/inspect/lineage/{args.id}")
    if status == 200 and data is not None:
        _print_json(data, f"Lineage Inspection — {args.id}")
        return 0
    _print_error(data, status)
    return 1


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="operator_inspect",
        description=(
            "Galaxy operator-surface diagnostic CLI.\n"
            "Reads runtime state via /api/v1/operator/* endpoints."
        ),
    )
    parser.add_argument(
        "--base-url",
        metavar="URL",
        default=None,
        help=(
            f"Galaxy API base URL (default: {_DEFAULT_BASE_URL} or "
            "GALAXY_OPERATOR_BASE_URL env var)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # snapshot
    subparsers.add_parser("snapshot", help="Compact runtime snapshot overview")

    # task
    p_task = subparsers.add_parser("task", help="Inspect a task by task_id")
    p_task.add_argument("id", metavar="TASK_ID")

    # route
    p_route = subparsers.add_parser("route", help="Inspect route decisions for a task")
    p_route.add_argument("id", metavar="TASK_ID")

    # executor
    p_exec = subparsers.add_parser("executor", help="Inspect an executor/provider node")
    p_exec.add_argument("id", metavar="NODE_ID")

    # failure
    p_fail = subparsers.add_parser("failure", help="Inspect failure domain for a task")
    p_fail.add_argument("id", metavar="TASK_ID")

    # lineage
    p_lin = subparsers.add_parser("lineage", help="Inspect task lineage / timeline")
    p_lin.add_argument("id", metavar="TASK_ID")

    return parser


_COMMAND_MAP = {
    "snapshot": cmd_snapshot,
    "task": cmd_task,
    "route": cmd_route,
    "executor": cmd_executor,
    "failure": cmd_failure,
    "lineage": cmd_lineage,
}


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Allow --base-url to override env var at runtime
    if args.base_url:
        os.environ["GALAXY_OPERATOR_BASE_URL"] = args.base_url

    handler = _COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
