"""
tests/integration/_ws_e2e_multi_device_server_helper.py
=========================================================

Standalone server entry point for multi-device, takeover, and
failure-recovery separated-process WebSocket E2E tests.

Run as:
    python tests/integration/_ws_e2e_multi_device_server_helper.py <port>

Extends the base server helper with additional test-support endpoints:

- ``/ws/device/{device_id}``              — canonical Android device ingress
  (same as base helper)
- ``POST /test/dispatch-task/{device_id}``
  — dispatch a task_assign to a specific device (same as base helper)
- ``POST /test/takeover-dispatch/{task_id}/{takeover_device_id}``
  — re-dispatch an existing task to a takeover device; used to simulate
  the delegated-takeover path where the primary participant has failed
- ``GET  /test/device-state/{device_id}``
  — return whether a device is currently connected (bridge view)
- ``GET  /test/connected-devices``
  — return a summary of all bridge-registered connected devices

Architecture
------------
The server uses the production ``_handle_android_ws`` handler and the
global ``android_bridge`` singleton — the same objects that run in
production — so every message travels through the real code paths.

The extra endpoints are test-only scaffolding that allow test coroutines
running in the *client* process to drive server-side behaviour (e.g.
trigger a takeover dispatch) without having to modify production code.

This module is intentionally kept minimal — all complex orchestration
logic lives in the test file.
"""

import asyncio
import sys
import time
import uuid
from typing import Any, Dict


def run(port: int) -> None:
    """Start uvicorn on *port* with the canonical device ingress handler
    and the additional multi-device test-support endpoints."""
    # Explicitly set a fresh event loop — prevents event-loop state
    # inheritance when this module is invoked via subprocess.Popen under
    # a pytest-asyncio test runner.
    asyncio.set_event_loop(asyncio.new_event_loop())

    import uvicorn
    from fastapi import FastAPI, Request, WebSocket

    from galaxy_gateway.android_bridge import android_bridge as _bridge
    from galaxy_gateway.routes.websocket import _handle_android_ws

    app = FastAPI()

    # ------------------------------------------------------------------
    # Canonical device WebSocket ingress (production handler)
    # ------------------------------------------------------------------

    @app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str) -> None:
        await _handle_android_ws(websocket, device_id)

    # ------------------------------------------------------------------
    # Test-only HTTP endpoints
    # ------------------------------------------------------------------

    @app.post("/test/dispatch-task/{device_id}")
    async def dispatch_task(device_id: str, req: Request) -> Dict[str, Any]:
        """Push a ``task_assign`` to a connected Android device.

        Accepts an optional JSON body::

            {"task_id": "<uuid>", "command": "screenshot"}

        The dispatch is fire-and-forget; the HTTP response returns
        immediately while ``task_assign`` travels over the live WebSocket.
        """
        try:
            body: Dict[str, Any] = await req.json()
        except Exception:
            body = {}

        task_id: str = body.get("task_id") or str(uuid.uuid4())
        command: str = body.get("command", "screenshot")

        task_assign_msg: Dict[str, Any] = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "payload": {"command": command},
        }

        asyncio.ensure_future(
            _bridge.send_to_device(device_id, task_assign_msg, wait_response=False)
        )
        return {"dispatched": True, "task_id": task_id, "target_device_id": device_id}

    @app.post("/test/takeover-dispatch/{task_id}/{takeover_device_id}")
    async def takeover_dispatch(
        task_id: str,
        takeover_device_id: str,
        req: Request,
    ) -> Dict[str, Any]:
        """Re-dispatch a task to a takeover device.

        Used to simulate the delegated-takeover path: the primary
        participant has failed (disconnected without sending task_result),
        and the task must be handed off to a capable backup participant.

        The ``task_id`` is preserved so that result-tracking can correlate
        the takeover result with the original task.

        Accepts an optional JSON body::

            {"command": "screenshot"}

        Returns::

            {
              "dispatched": true,
              "task_id": "<task_id>",
              "takeover_device_id": "<device_id>",
              "takeover": true
            }
        """
        try:
            body: Dict[str, Any] = await req.json()
        except Exception:
            body = {}

        command: str = body.get("command", "execute")

        # Preserve the original task_id so result correlation is possible.
        task_assign_msg: Dict[str, Any] = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": takeover_device_id,
            "timestamp": int(time.time() * 1000),
            "payload": {
                "command": command,
                "takeover": True,
                "original_device_id": body.get("original_device_id", ""),
            },
        }

        asyncio.ensure_future(
            _bridge.send_to_device(
                takeover_device_id, task_assign_msg, wait_response=False
            )
        )
        return {
            "dispatched": True,
            "task_id": task_id,
            "takeover_device_id": takeover_device_id,
            "takeover": True,
        }

    @app.get("/test/device-state/{device_id}")
    async def device_state(device_id: str) -> Dict[str, Any]:
        """Return whether *device_id* is currently connected (bridge view).

        Returns::

            {"device_id": "...", "connected": true|false, "found": true|false}
        """
        device = _bridge.get_device(device_id)
        if device is None:
            return {"device_id": device_id, "connected": False, "found": False}
        return {
            "device_id": device_id,
            "connected": device.connected,
            "found": True,
        }

    @app.get("/test/connected-devices")
    async def connected_devices() -> Dict[str, Any]:
        """Return a summary of all bridge-registered connected devices.

        Returns::

            {
              "count": 2,
              "devices": [
                {"device_id": "...", "platform": "android", "connected": true},
                ...
              ]
            }
        """
        devices = _bridge.get_connected_devices()
        return {
            "count": len(devices),
            "devices": [
                {
                    "device_id": d.device_id,
                    "platform": (
                        d.platform.value
                        if hasattr(d.platform, "value")
                        else str(d.platform)
                    ),
                    "connected": d.connected,
                }
                for d in devices
            ],
        }

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <port>", file=sys.stderr)
        sys.exit(1)
    run(int(sys.argv[1]))
