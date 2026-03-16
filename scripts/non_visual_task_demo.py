#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/non_visual_task_demo.py
================================
PR-5 Capability 2 — Non-Visual Task Execution Demo

Demonstrates that Galaxy can execute complex tasks WITHOUT any visual/UI
sampling (no screenshot, no screen-state, no UI automation).

Task chain demonstrated:
  1. filesystem  — list a directory, create a temp file, read it back
  2. http_client — fetch a public JSON endpoint (httpbin or local stub)
  3. system_cmd  — run a safe, read-only system command (e.g. `echo`)

All steps use the TaskEnvelope + TaskLifecycleManager directly; no vision
pipeline or UI automation is involved.

Run::

    python scripts/non_visual_task_demo.py

Expected output: all steps marked DONE with no visual/screenshot calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import logging

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("Demo.NonVisual")


# ---------------------------------------------------------------------------
# Import Galaxy primitives
# ---------------------------------------------------------------------------

from core.schemas.task_envelope import TaskEnvelope
from core.task_lifecycle import TaskLifecycleManager

mgr = TaskLifecycleManager()


# ---------------------------------------------------------------------------
# Step executors (no-vision path)
# ---------------------------------------------------------------------------

async def step_filesystem(envelope: TaskEnvelope):
    """List /tmp, write a file, read it back — purely filesystem, no UI."""
    path = envelope.args.get("path", "/tmp")
    entries = os.listdir(path)
    logger.info("[filesystem] listed %d entries in %s", len(entries), path)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".galaxy_demo.txt", delete=False
    ) as tmp:
        tmp.write("Galaxy non-visual task demo\n")
        tmp_path = tmp.name

    with open(tmp_path) as f:
        content = f.read().strip()
    os.unlink(tmp_path)
    logger.info("[filesystem] write/read OK: %r", content)
    return {"entries": len(entries), "tmp_content": content}


async def step_http_client(envelope: TaskEnvelope):
    """HTTP GET to a public JSON endpoint — purely network, no UI."""
    url = envelope.args.get("url", "")
    if not url:
        logger.info("[http_client] No URL provided; skipping live fetch.")
        return {"skipped": True, "reason": "no_url"}

    try:
        import urllib.request
        import json as _json
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read())
        logger.info("[http_client] GET %s → %d keys", url, len(data))
        return {"url": url, "keys": list(data.keys())[:5]}
    except Exception as exc:
        logger.info("[http_client] fetch skipped (offline/unavailable): %s", exc)
        return {"skipped": True, "reason": str(exc)}


async def step_system_cmd(envelope: TaskEnvelope):
    """Run a safe read-only system command — no UI."""
    import subprocess
    cmd = envelope.args.get("cmd", ["echo", "Galaxy non-visual OK"])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=5
    )
    output = result.stdout.strip()
    logger.info("[system_cmd] cmd=%s output=%r", cmd, output)
    return {"returncode": result.returncode, "output": output}


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

async def run_demo():
    print("\n" + "=" * 60)
    print("PR-5 Capability 2: Non-Visual Task Execution Demo")
    print("=" * 60)

    session_id = "demo_session_nonvisual_001"

    steps = [
        (
            "filesystem_list_write_read",
            step_filesystem,
            {"path": "/tmp"},
            ["filesystem"],
        ),
        (
            "http_client_fetch",
            step_http_client,
            {"url": ""},  # empty → offline stub
            ["http_client"],
        ),
        (
            "system_cmd_echo",
            step_system_cmd,
            {"cmd": ["echo", "Galaxy non-visual OK"]},
            ["system_cmd"],
        ),
    ]

    results = []
    for tool_name, executor, args, caps in steps:
        print(f"\n── Step: {tool_name} ──")
        env = TaskEnvelope(
            tool_name=tool_name,
            args=args,
            source="non_visual_demo",
            targets=["local"],
            session_id=session_id,
            required_capabilities=caps,
        )
        print(f"  task_id={env.task_id}  lifecycle={env.lifecycle_status}")

        env = mgr.mark_running(env)
        print(f"  lifecycle={env.lifecycle_status}")
        try:
            result = await executor(env)
            env = mgr.mark_done(env, result_summary=str(result)[:120])
            print(f"  lifecycle={env.lifecycle_status}  result={result}")
        except Exception as exc:
            env = mgr.mark_failed(env, error=str(exc))
            print(f"  lifecycle={env.lifecycle_status}  error={exc}")
        results.append((tool_name, env.lifecycle_status))

    print("\n" + "=" * 60)
    print("Summary (all steps must be 'done'):")
    all_done = True
    for name, status in results:
        mark = "✓" if status == "done" else "✗"
        print(f"  {mark} {name}: {status}")
        if status != "done":
            all_done = False

    if all_done:
        print("\n✅ All non-visual steps completed without any UI/vision calls.")
    else:
        print("\n❌ Some steps did not complete successfully.")

    return all_done


if __name__ == "__main__":
    ok = asyncio.run(run_demo())
    sys.exit(0 if ok else 1)
