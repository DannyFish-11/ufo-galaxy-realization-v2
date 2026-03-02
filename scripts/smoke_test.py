#!/usr/bin/env python3
"""
UFO Galaxy — Deployment Smoke Test
====================================

Quick post-deploy validation that critical components work.

Usage:
    python scripts/smoke_test.py                  # test localhost:8080
    python scripts/smoke_test.py --host 1.2.3.4   # test remote host
    python scripts/smoke_test.py --port 9000      # custom port
"""

import sys
import os
import json
import time
import argparse
import importlib

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
WARN = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def warn(name: str, detail: str = ""):
    global WARN
    WARN += 1
    print(f"  [WARN] {name}" + (f" — {detail}" if detail else ""))


def test_imports():
    """Test that all core modules can be imported."""
    print("\n=== Core Module Imports ===")
    modules = [
        "core.api_routes",
        "core.scheduler",
        "core.llm_manager",
        "core.agent_factory",
        "core.security_middleware",
        "core.proxy_relay",
        "core.hybrid_executor",
        "core.rag_memory",
        "core.safe_executor",
        "core.mesh_coordinator",
        "core.node_protocol",
        "core.connection_manager",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as e:
            check(f"import {mod}", False, str(e)[:80])


def test_config():
    """Test configuration loading."""
    print("\n=== Configuration ===")
    config_files = [
        "config/unified_config.json",
        "config/capabilities.json",
        ".env.example",
    ]
    for f in config_files:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), f)
        exists = os.path.exists(path)
        check(f"config: {f}", exists)
        if exists and f.endswith(".json"):
            try:
                with open(path) as fp:
                    json.load(fp)
                check(f"  valid JSON: {f}", True)
            except json.JSONDecodeError as e:
                check(f"  valid JSON: {f}", False, str(e)[:60])


def test_http(host: str, port: int):
    """Test HTTP endpoints."""
    print(f"\n=== HTTP Endpoints ({host}:{port}) ===")
    try:
        import httpx
    except ImportError:
        warn("httpx not installed, skipping HTTP tests")
        return

    base = f"http://{host}:{port}"
    endpoints = [
        ("/health/live", 200),
        ("/health/ready", 200),
        ("/metrics", 200),
        ("/api/v1/status", 200),
        ("/api/v1/nodes", 200),
    ]

    for path, expected_status in endpoints:
        try:
            r = httpx.get(f"{base}{path}", timeout=5.0)
            check(f"GET {path}", r.status_code == expected_status,
                  f"status={r.status_code}" if r.status_code != expected_status else "")
        except httpx.ConnectError:
            check(f"GET {path}", False, "connection refused")
        except Exception as e:
            check(f"GET {path}", False, str(e)[:60])


def test_tests():
    """Run core unit tests."""
    print("\n=== Unit Tests ===")
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_phase234.py",
         "tests/test_phase5_mesh.py", "tests/test_agent_migration.py",
         "-v", "--tb=line", "-q"],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(__file__))
    )
    passed = "passed" in result.stdout
    check("pytest (Phase 2-5 + Agent Migration)", passed,
          result.stdout.strip().split("\n")[-1] if not passed else "")


def main():
    parser = argparse.ArgumentParser(description="UFO Galaxy Smoke Test")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--skip-http", action="store_true",
                        help="Skip HTTP endpoint tests")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip running pytest")
    args = parser.parse_args()

    print("=" * 50)
    print("  UFO Galaxy — Smoke Test")
    print("=" * 50)

    test_imports()
    test_config()

    if not args.skip_http:
        test_http(args.host, args.port)

    if not args.skip_tests:
        test_tests()

    print("\n" + "=" * 50)
    print(f"  Results: {PASS} passed, {FAIL} failed, {WARN} warnings")
    print("=" * 50)

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
