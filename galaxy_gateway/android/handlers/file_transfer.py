"""
galaxy_gateway/android/handlers/file_transfer.py
=================================================
PR-8: Canonical stateful handler for FILE_TRANSFER messages.

Replaces the generic-forward placeholder with a handler that:

* Records transfer metadata (transfer_id, file_name, file_size,
  checksum) in the response.
* Routes the request to DeviceOrchestrator when source and target
  device IDs are provided (two-phase: file_read → file_write).
* Returns a structured ACK with lifecycle fields so downstream
  systems can track transfer state rather than ignoring the message.

This is the Android-bridge ingress side of the file transfer path.
Outbound transfers initiated by the server use
``DeviceOrchestrator.transfer_file()`` directly.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-8 sentinel — canonical handler authority for FILE_TRANSFER messages.
FILE_TRANSFER_HANDLER_IS_CANONICAL_PR8: str = (
    "FILE_TRANSFER_HANDLER::CANONICAL_STATEFUL_PR8"
)


async def handle_file_transfer(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle a FILE_TRANSFER message from an Android device.

    This handler replaces the generic-forward placeholder.  It returns a
    structured response carrying transfer lifecycle state so that both the
    device and the server can track the transfer rather than treating it as
    an opaque ACK.

    Two modes
    ---------
    1. **Inbound transfer announcement** — the device notifies the server
       that it has a file ready for transfer.  The handler acknowledges
       with a ``transfer_id`` that the device should include in subsequent
       progress / result messages.

    2. **Cross-device transfer request** — the message includes both
       ``source_device`` and ``target_device`` fields.  The handler
       delegates to ``DeviceOrchestrator.transfer_file()`` and returns the
       transfer result.
    """
    device_id = message.get("device_id", "unknown")
    payload = message.get("payload") or {}

    # Extract file metadata from the message.
    file_name: str = (
        payload.get("file_name")
        or message.get("file_name")
        or ""
    )
    file_size: int = int(payload.get("file_size") or message.get("file_size") or 0)
    checksum: str = payload.get("checksum") or message.get("checksum") or ""
    file_path: str = (
        payload.get("file_path")
        or message.get("file_path")
        or ""
    )

    # Cross-device transfer fields.
    source_device: Optional[str] = (
        payload.get("source_device") or message.get("source_device")
    )
    target_device: Optional[str] = (
        payload.get("target_device") or message.get("target_device")
    )

    # Generate a transfer ID for tracking.
    transfer_id: str = (
        payload.get("transfer_id")
        or message.get("transfer_id")
        or uuid.uuid4().hex[:12]
    )

    logger.info(
        "FILE_TRANSFER from device_id=%s transfer_id=%s file_name=%r"
        " file_size=%d source=%s target=%s",
        device_id,
        transfer_id,
        file_name,
        file_size,
        source_device,
        target_device,
    )

    # If both source and target are provided, attempt orchestrated transfer.
    if source_device and target_device and file_path:
        orchestrated_result = await _try_orchestrated_transfer(
            device_id=device_id,
            transfer_id=transfer_id,
            source_device=source_device,
            target_device=target_device,
            file_path=file_path,
        )
        if orchestrated_result is not None:
            return orchestrated_result

    # Default: acknowledge the transfer announcement with lifecycle metadata.
    return {
        "version": "3.0",
        "type": "file_transfer_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "transfer_id": transfer_id,
        "status": "accepted",
        "file_name": file_name,
        "file_size": file_size,
        "checksum": checksum,
        "correlation_id": message.get("message_id"),
        "lifecycle_state": "transfer_accepted",
    }


async def _try_orchestrated_transfer(
    device_id: str,
    transfer_id: str,
    source_device: str,
    target_device: str,
    file_path: str,
) -> Optional[Dict[str, Any]]:
    """Attempt a two-phase orchestrated transfer via DeviceOrchestrator.

    Returns a structured result dict on success or failure, or ``None``
    if the orchestrator is not available (in which case the caller falls
    back to the announcement ACK).
    """
    try:
        from core.device_orchestrator import DeviceOrchestrator

        orchestrator = DeviceOrchestrator()
        result = await orchestrator.transfer_file(
            source_device=source_device,
            target_device=target_device,
            file_path=file_path,
        )

        status = result.get("status", "unknown")
        logger.info(
            "Orchestrated FILE_TRANSFER transfer_id=%s source=%s target=%s"
            " result_status=%s",
            transfer_id,
            source_device,
            target_device,
            status,
        )

        return {
            "version": "3.0",
            "type": "file_transfer_ack",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "transfer_id": transfer_id,
            "status": status,
            "source_device": source_device,
            "target_device": target_device,
            "file_path": file_path,
            "elapsed_ms": result.get("elapsed_ms"),
            "lifecycle_state": "transfer_complete" if status == "success" else "transfer_error",
            "error": result.get("error"),
        }

    except ImportError:
        logger.debug(
            "DeviceOrchestrator not available; falling back to transfer ACK "
            "for transfer_id=%s",
            transfer_id,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Orchestrated FILE_TRANSFER failed (non-fatal): transfer_id=%s"
            " error=%s",
            transfer_id,
            exc,
        )
        return {
            "version": "3.0",
            "type": "file_transfer_ack",
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "transfer_id": transfer_id,
            "status": "error",
            "error": str(exc),
            "lifecycle_state": "transfer_error",
        }
