"""
tests/integration/_ws_e2e_server_helper.py
===========================================

Standalone server entry point for separated-process WebSocket E2E tests.

Run as:
    python tests/integration/_ws_e2e_server_helper.py <port>

Starts a real uvicorn server on the given port hosting:
- ``/ws/device/{device_id}`` — canonical Android device ingress
- ``POST /test/dispatch-task/{device_id}`` — test-only V2 dispatch trigger

This file is intentionally minimal — it is invoked via ``subprocess.Popen``
from ``test_separated_process_ws_e2e.py`` to guarantee a clean Python
interpreter with no inherited event-loop or asyncio state from the test runner
(avoids the ``fork``-inherited event-loop issue that causes HTTP 403 responses
from uvicorn when ``multiprocessing.Process`` is used under pytest-asyncio).
"""

import asyncio
import sys
import time
import uuid
from typing import Any, Dict


def run(port: int) -> None:
    """Start uvicorn on *port* with the canonical device ingress handler."""
    # Explicitly set a fresh event loop — belt-and-suspenders guard in case
    # this module is ever imported in a non-subprocess context.
    asyncio.set_event_loop(asyncio.new_event_loop())

    import uvicorn
    from fastapi import FastAPI, Request, WebSocket

    from galaxy_gateway.android_bridge import android_bridge as _bridge
    from galaxy_gateway.routes.websocket import _handle_android_ws

    app = FastAPI()

    @app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str) -> None:
        await _handle_android_ws(websocket, device_id)

    @app.post("/test/dispatch-task/{device_id}")
    async def dispatch_task(device_id: str, req: Request) -> Dict[str, Any]:
        """Push a ``task_assign`` to a connected Android device.

        Accepts an optional JSON body::

            {"task_id": "<uuid>", "command": "screenshot"}

        The dispatch is fire-and-forget so the HTTP call returns immediately
        while the ``task_assign`` travels over the live WebSocket session.
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

        # Fire-and-forget — avoids blocking the event loop
        asyncio.ensure_future(
            _bridge.send_to_device(device_id, task_assign_msg, wait_response=False)
        )
        return {"dispatched": True, "task_id": task_id}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <port>", file=sys.stderr)
        sys.exit(1)
    run(int(sys.argv[1]))
