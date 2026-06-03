"""
Daemon Notifier — 守护进程状态通知

通知方式（按优先级）:
  1. WebSocket → Android/Wear OS (最优先，远程可收)
  2. Windows Toast 通知 (本地提示)
  3. 日志文件 fallback (始终可用)

通知场景:
  - Galaxy 进程崩溃后重启
  - 连续重启超过阈值
  - 系统异常 (CPU/内存/磁盘)
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DaemonNotifier:
    """守护进程状态通知器。

    不依赖外部服务——优先通过 WebSocket 推送到已连接的 Android/Wear OS
    设备，fallback 到本地通知。
    """

    # Notification severity
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    # Cooldown: same-type notification within this window is deduped
    _COOLDOWN_SECONDS = 300  # 5 min

    def __init__(self) -> None:
        self._last_notify_time: Dict[str, float] = {}
        self._android_bridge: Any = None  # lazy-imported

    # ------------------------------------------------------------------
    # Core: send notification
    # ------------------------------------------------------------------

    async def notify(
        self,
        message: str,
        severity: str = INFO,
        category: str = "daemon",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a notification through the best available channel."""

        # Dedup: skip if same category was notified recently
        now = time.time()
        last = self._last_notify_time.get(category, 0)
        if now - last < self._COOLDOWN_SECONDS:
            logger.debug("Notification deduped: %s", category)
            return
        self._last_notify_time[category] = now

        payload = {
            "type": "daemon_notification",
            "severity": severity,
            "category": category,
            "message": message,
            "details": details or {},
            "timestamp": time.time(),
        }

        # Channel 1: WebSocket → Android/Wear OS
        ws_ok = await self._try_websocket(payload)
        if ws_ok:
            logger.info("Notification sent via WebSocket: %s", message[:80])
            return

        # Channel 2: Windows Toast (local only)
        toast_ok = self._try_toast(message, severity)
        if toast_ok:
            logger.info("Notification sent via Toast: %s", message[:80])
            return

        # Channel 3: log fallback
        logger.info("[NOTIFY] %s: %s", severity.upper(), message)

    # ------------------------------------------------------------------
    # Channel 1: WebSocket → connected devices
    # ------------------------------------------------------------------

    async def _try_websocket(self, payload: Dict[str, Any]) -> bool:
        """Send notification to all connected Android/Wear OS devices."""
        try:
            if self._android_bridge is None:
                from galaxy_gateway.android_bridge import _CONNECTED_DEVICES
                self._android_bridge = _CONNECTED_DEVICES

            if not self._android_bridge:
                return False

            sent = 0
            for device_id, conn in list(self._android_bridge.items()):
                try:
                    # PR-AIP-UNIFIED: Route daemon notifications through AIPTransport
                    # instead of direct websocket access.
                    try:
                        from core.aip_transport import get_aip_transport
                        msg = {
                            "type": "daemon_notification",
                            "payload": payload,
                            "_transport": "auto",
                            "version": "3.0",
                        }
                        result = await get_aip_transport().send(msg, device_id)
                        if result.get("success"):
                            sent += 1
                            continue
                    except Exception:
                        pass
                    # Fallback: direct websocket
                    if hasattr(conn, "send_json"):
                        await conn.send_json(payload)
                        sent += 1
                    elif isinstance(conn, tuple) and len(conn) == 2:
                        serializer, websocket = conn
                        await serializer.send(websocket, payload)
                        sent += 1
                except Exception:
                    pass  # ignore per-device errors

            return sent > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Channel 2: Windows Toast notification
    # ------------------------------------------------------------------

    def _try_toast(self, message: str, severity: str) -> bool:
        """Show Windows toast notification (local only)."""
        if os.environ.get("GALAXY_DESKTOP_GUI_ENABLED", "").lower() == "false":
            return False  # daemon mode: skip toast

        try:
            import subprocess
            title = "Galaxy " + {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}.get(severity, "ℹ️")
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"[System.Windows.Forms.MessageBox]::Show('{message}', '{title}')",
                ],
                capture_output=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Convenience: pre-built notifications
    # ------------------------------------------------------------------

    async def notify_crash_restart(self, restart_count: int, exit_code: int) -> None:
        await self.notify(
            message=f"Galaxy 异常退出 (code {exit_code})，第 {restart_count} 次自动重启",
            severity=self.WARNING if restart_count <= 2 else self.CRITICAL,
            category="crash_restart",
            details={"restart_count": restart_count, "exit_code": exit_code},
        )

    async def notify_too_many_restarts(self, max_count: int) -> None:
        await self.notify(
            message=f"Galaxy 连续重启超过 {max_count} 次/小时，已停止守护。请检查系统。",
            severity=self.CRITICAL,
            category="too_many_restarts",
            details={"max_count": max_count},
        )

    async def notify_system_pressure(self, cpu: Optional[float], mem: Optional[float]) -> None:
        await self.notify(
            message=f"系统资源紧张: CPU {cpu:.0%}, 内存 {mem:.0%}",
            severity=self.WARNING,
            category="system_pressure",
            details={"cpu": cpu, "memory": mem},
        )
