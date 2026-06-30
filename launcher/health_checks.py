"""
launcher/health_checks.py — Post-startup health verification.

Responsibilities:
- run_startup_health_check: probe key endpoints and ports **after** the unified
  FastAPI app has bound its HTTP socket (see ``UnifiedWebUI.start`` in
  ``unified_launcher.py``), emit structured diagnostics, and guide the operator
  when checks fail.
"""

import os
import socket
import subprocess
import sys
import logging

from .bootstrap import print_status, print_section

logger = logging.getLogger("Galaxy")


def _nats_tcp_failure_is_critical() -> bool:
    """Return True when unreachable NATS should fail the overall health summary."""
    try:
        from core.nats_posture import evaluate_nats_posture

        posture = evaluate_nats_posture()
        return bool(posture.get("required", False))
    except Exception:
        pass

    if os.environ.get("GALAXY_FABRIC_STRICT", "").lower() in ("true", "1", "yes"):
        return True
    cross = os.environ.get("GALAXY_CROSS_DEVICE_ENABLED", "").lower() in ("true", "1", "yes")
    mode = os.environ.get("GALAXY_SYSTEM_MODE", "").strip().lower()
    if cross or "cross_device" in mode:
        return True
    nats_on = os.environ.get("GALAXY_NATS_ENABLED", "").lower() in ("true", "1", "yes")
    if nats_on:
        return True
    try:
        from core.nats_bus import nats_bus
        stats = nats_bus.get_stats()
        if stats.get("noop_mode"):
            return False
    except Exception:
        pass
    return False


async def run_startup_health_check(web_ui_port: int) -> None:
    """HTTP 服务已 listen 后执行健康检查；失败时打印详细诊断。

    Probes:
      1. ``/health`` on the launcher's HTTP server.
      2. ``/api/v1/system/info`` on the launcher's HTTP server.
      3. Node_71 ``/health`` (port 8071).
      4. NATS port 4222 TCP reachability (non-fatal when bus is no-op / desktop-local).
      5. Docker container status (best-effort, if Docker is available).

    Args:
        web_ui_port: The port on which the unified launcher's HTTP server
            is listening (used for probes 1 and 2).
    """
    import urllib.request
    import asyncio

    # The uvicorn server now runs as a background task on THIS event loop, so the
    # probes MUST NOT block the loop — otherwise the server can't answer its own
    # /health and every HTTP probe times out.  Offload all blocking I/O to threads.
    def _http_code(url: str, timeout: float) -> int:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.getcode()

    base_url = f"http://localhost:{web_ui_port}"
    node71_url = "http://localhost:8071"
    nats_host = "localhost"
    nats_port = 4222
    all_ok = True

    # 1) Gateway / core health
    try:
        code = await asyncio.to_thread(_http_code, f"{base_url}/health", 5)
        logger.debug("Launcher /health: HTTP %d", code)
    except Exception as exc:
        print_status(f"Launcher /health: 失败 — {exc}", "error")
        all_ok = False

    # 2) system info
    try:
        code = await asyncio.to_thread(_http_code, f"{base_url}/api/v1/system/status", 5)
        logger.debug("system/status: HTTP %d", code)
    except Exception as exc:
        logger.debug("system/status: 失败 — %s", exc)

    # 3) Node_71 health
    try:
        code = await asyncio.to_thread(_http_code, f"{node71_url}/health", 3)
        logger.debug("Node_71 /health: HTTP %d", code)
    except Exception as exc:
        logger.debug("Node_71 /health: 不可达 — %s", exc)

    # 4) NATS port check (optional for single-machine / noop bus)
    try:
        await asyncio.to_thread(
            lambda: socket.create_connection((nats_host, nats_port), timeout=3).close()
        )
        logger.debug("NATS port %d: 已监听", nats_port)
    except Exception as exc:
        if _nats_tcp_failure_is_critical():
            print_status(f"NATS port {nats_port}: 未监听 — {exc}", "error")
            all_ok = False
        else:
            logger.debug("NATS port %d: 未监听（单机/no-op 模式可忽略）— %s", nats_port, exc)

    # 5) Docker container status (best-effort, log only)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker", "ps",
                "--filter", "name=nats",
                "--filter", "name=gateway",
                "--filter", "name=node_71",
                "--format", "{{.Names}}\t{{.Status}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.debug("Docker 容器状态:\n%s", result.stdout.strip())
    except Exception:
        pass  # Docker not available or not used

    if not all_ok:
        _is_win = sys.platform.startswith("win")
        print_status("健康检查失败，请检查以下内容:", "error")
        print_status("  1. NATS 服务: nats-server -p 4222", "error")
        if _is_win:
            print_status(f"  2. 端口冲突: netstat -ano | findstr :{nats_port}", "error")
            print_status(f"  2. 端口冲突: netstat -ano | findstr :{web_ui_port}", "error")
            print_status("  3. 运行完整诊断: .\\scripts\\health_check.ps1", "error")
        else:
            print_status(f"  2. 端口冲突: lsof -i :{nats_port} / lsof -i :{web_ui_port}", "error")
            print_status("  3. 运行完整诊断: bash scripts/health_check.sh", "error")
