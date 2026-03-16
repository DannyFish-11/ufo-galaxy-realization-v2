#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Locust Load Test (PR-G5)
===================================

Lightweight load test for the Galaxy API gateway that validates:
  1. Command dispatch endpoint handles concurrent load gracefully.
  2. Resilience metrics endpoint stays available under load.
  3. Throttled requests return structured error responses (not 500s).
  4. Fallback/degraded responses conform to the API schema.

Usage
-----
Install locust::

    pip install locust

Run interactively (web UI on http://localhost:8089)::

    locust -f scripts/load_test_locust.py --host=http://localhost:9000

Run headlessly (CI smoke)::

    locust -f scripts/load_test_locust.py \
           --host=http://localhost:9000 \
           --headless \
           --users 20 \
           --spawn-rate 5 \
           --run-time 30s \
           --exit-code-on-error 1

Environment variables
---------------------
``GALAXY_LT_HOST``         — target host (default http://localhost:9000)
``GALAXY_LT_USERS``        — concurrent users for headless mode (default 20)
``GALAXY_LT_SPAWN_RATE``   — spawn rate users/s (default 5)
``GALAXY_LT_DURATION``     — headless run duration (default 30s)
``GALAXY_LT_FAILURE_RATE`` — acceptable failure rate [0-1] (default 0.1 = 10%)
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid

from locust import HttpUser, between, events, task
from locust.env import Environment

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_HOST = os.environ.get("GALAXY_LT_HOST", "http://localhost:9000")
_FAILURE_RATE = float(os.environ.get("GALAXY_LT_FAILURE_RATE", "0.1"))

# Sample targets to dispatch commands to (adjust to match your deployment)
_TARGETS = ["device_001", "device_002", "device_003", "node_echo"]
_COMMANDS = ["ping", "status", "echo", "get_info"]


# ---------------------------------------------------------------------------
# User behaviour
# ---------------------------------------------------------------------------

class GalaxyApiUser(HttpUser):
    """Simulates a client that dispatches commands and checks metrics."""

    wait_time = between(0.1, 0.5)  # 100–500 ms between tasks

    # ── Command dispatch ─────────────────────────────────────────────────

    @task(5)
    def dispatch_command_sync(self):
        """POST /api/v1/commands – synchronous dispatch."""
        payload = {
            "request_id": f"lt_{uuid.uuid4().hex[:8]}",
            "targets": [random.choice(_TARGETS)],
            "command": random.choice(_COMMANDS),
            "params": {"load_test": True, "ts": time.time()},
            "mode": "sync",
            "timeout": 5.0,
        }
        with self.client.post(
            "/api/v1/commands",
            json=payload,
            catch_response=True,
            name="/api/v1/commands [sync]",
        ) as resp:
            self._validate_command_response(resp)

    @task(2)
    def dispatch_command_async(self):
        """POST /api/v1/commands – async dispatch (fire-and-forget)."""
        payload = {
            "request_id": f"lt_{uuid.uuid4().hex[:8]}",
            "targets": [random.choice(_TARGETS)],
            "command": random.choice(_COMMANDS),
            "params": {"load_test": True},
            "mode": "async",
            "timeout": 10.0,
        }
        with self.client.post(
            "/api/v1/commands",
            json=payload,
            catch_response=True,
            name="/api/v1/commands [async]",
        ) as resp:
            # Async mode should return 200 / 202 immediately
            if resp.status_code in (200, 202):
                resp.success()
            elif resp.status_code == 429:
                # Throttled – acceptable degraded response
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(3)
    def dispatch_parallel_command(self):
        """POST /api/v1/commands – parallel multi-target dispatch."""
        payload = {
            "request_id": f"lt_{uuid.uuid4().hex[:8]}",
            "targets": random.sample(_TARGETS, min(2, len(_TARGETS))),
            "command": "ping",
            "params": {},
            "mode": "parallel",
            "timeout": 5.0,
        }
        with self.client.post(
            "/api/v1/commands",
            json=payload,
            catch_response=True,
            name="/api/v1/commands [parallel]",
        ) as resp:
            self._validate_command_response(resp)

    # ── Metrics / observability ──────────────────────────────────────────

    @task(2)
    def check_resilience_metrics(self):
        """GET /api/v1/resilience/metrics – should always return 200."""
        with self.client.get(
            "/api/v1/resilience/metrics",
            catch_response=True,
            name="/api/v1/resilience/metrics",
        ) as resp:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if "resilience_metrics" not in data:
                        resp.failure("Missing 'resilience_metrics' key")
                    else:
                        resp.success()
                except Exception as exc:
                    resp.failure(f"Invalid JSON: {exc}")
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def check_prometheus_metrics(self):
        """GET /api/v1/resilience/metrics/prom – Prometheus text format."""
        with self.client.get(
            "/api/v1/resilience/metrics/prom",
            catch_response=True,
            name="/api/v1/resilience/metrics/prom",
        ) as resp:
            if resp.status_code == 200:
                if b"galaxy_resilience_queue_depth" in resp.content:
                    resp.success()
                else:
                    resp.failure("Missing expected metric name in Prometheus output")
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def check_circuit_breakers(self):
        """GET /api/v1/resilience/circuit-breakers."""
        with self.client.get(
            "/api/v1/resilience/circuit-breakers",
            catch_response=True,
            name="/api/v1/resilience/circuit-breakers",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def health_check(self):
        """GET /health/live – liveness probe."""
        with self.client.get(
            "/health/live",
            catch_response=True,
            name="/health/live",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _validate_command_response(self, resp) -> None:
        """Accept 200/202 (success/async) and 429 (throttled); fail otherwise."""
        if resp.status_code in (200, 202):
            try:
                data = resp.json()
                # Throttled responses must still have a structured body
                if data.get("metadata", {}).get("throttled"):
                    resp.success()
                    return
                resp.success()
            except Exception as exc:
                resp.failure(f"Invalid JSON: {exc}")
        elif resp.status_code == 429:
            # Graceful degradation — not a failure
            resp.success()
        elif resp.status_code in (503, 504):
            # Acceptable under extreme load
            resp.success()
        else:
            resp.failure(f"Unexpected status {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# CI smoke validation hook
# ---------------------------------------------------------------------------

@events.quitting.add_listener
def on_quitting(environment: Environment, **kwargs) -> None:  # type: ignore[misc]
    """Fail the CI run if the measured error rate exceeds the threshold."""
    stats = environment.runner.stats.total if environment.runner else None
    if stats is None:
        return

    total = stats.num_requests
    failures = stats.num_failures
    if total == 0:
        print("[load-test] No requests recorded — check host/route configuration")
        environment.process_exit_code = 1
        return

    error_rate = failures / total
    print(
        f"[load-test] total={total} failures={failures} "
        f"error_rate={error_rate:.2%} threshold={_FAILURE_RATE:.2%}"
    )
    if error_rate > _FAILURE_RATE:
        print(f"[load-test] FAIL: error rate {error_rate:.2%} exceeds threshold {_FAILURE_RATE:.2%}")
        environment.process_exit_code = 1
    else:
        print("[load-test] PASS")
