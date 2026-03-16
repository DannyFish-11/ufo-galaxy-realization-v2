"""
AIP Protocol Compatibility Layer
==================================

Accepts messages from AIP v1.0, v2.0 and v3.0 clients and normalises them
into the canonical AIP v3 :class:`AIPMessage` before they are dispatched to
the application handlers.

Protocol detection rules
------------------------

* **AIP/1.0**  – no ``version`` field, or ``version`` starts with ``"1"``.
  ``type`` may be a legacy alias:

  ============================================================  ==============================
  Legacy type string                                            Normalised ``MessageType``
  ============================================================  ==============================
  ``register`` / ``agent_register`` / ``device_register``
  / ``registration``                                            ``device_register``
  ``heartbeat`` / ``agent_heartbeat`` / ``device_heartbeat``   ``heartbeat``
  ``task_execute``                                              ``task_submit``
  ``command_result``                                            ``task_result``
  ``status_update`` / ``update_status``                        ``device_status``
  ============================================================  ==============================

* **AIP/2.0**  – ``version == "2.0"``.  Field names are the same as v3;
  the message is accepted as-is after the version tag is bumped to ``"3.0"``.

* **AIP/3.0**  – ``version == "3.0"`` (or any ``"3.x"``).  Passed through
  to :func:`~galaxy_gateway.protocol.aip_v3.parse_message` directly.

Usage::

    from galaxy_gateway.protocol.compat import parse_message_compat
    message = parse_message_compat(raw_text_or_dict)
"""

import json
import logging
import uuid
from typing import Optional, Union

from .aip_v3 import AIPMessage, MessageType, parse_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AIP v3 enforcement helpers
# ---------------------------------------------------------------------------

# Minimum required major version for strict enforcement.
_MIN_REQUIRED_VERSION = (3, 0)

# Default route_mode when the field is absent from an incoming message.
_DEFAULT_ROUTE_MODE = "cross_device"


class AIPVersionError(ValueError):
    """Raised when an incoming message does not meet the minimum AIP version."""


def _parse_version(version_str: str) -> tuple:
    """Parse a version string like '3.0' or '3.1' into a comparable tuple."""
    try:
        parts = str(version_str).split(".")
        return tuple(int(p) for p in parts[:2])
    except (ValueError, AttributeError):
        logger.warning(
            "Could not parse AIP version string %r; treating as (0, 0)", version_str
        )
        return (0, 0)


def enforce_aip_v3(data: dict) -> None:
    """
    Validate that *data* carries a protocol version >= 3.0.

    :raises AIPVersionError: when the ``version`` field is absent or lower
        than 3.0.  The caller is responsible for rejecting the connection /
        request and logging the structured rejection event.
    """
    raw_version = data.get("version")
    if raw_version is None:
        raise AIPVersionError(
            "Missing 'version' field; AIP v3.0+ is required"
        )
    parsed = _parse_version(str(raw_version))
    if parsed < _MIN_REQUIRED_VERSION:
        raise AIPVersionError(
            f"AIP version {raw_version!r} is below the required minimum 3.0"
        )


def inject_trace_metadata(data: dict) -> dict:
    """
    Ensure *data* contains ``trace_id`` and ``route_mode``.

    * ``trace_id``   – generated as a new UUID when absent.
    * ``route_mode`` – defaults to :data:`_DEFAULT_ROUTE_MODE` when absent.

    A structured log entry is emitted for each injected field so that
    operators can identify clients that do not send these fields.

    :param data: Raw (already-decoded) message dict.  **Not mutated.**
    :returns: A new dict with the metadata fields guaranteed to be present.
    """
    out = dict(data)
    injected: list = []

    if not out.get("trace_id"):
        out["trace_id"] = str(uuid.uuid4())
        injected.append("trace_id")

    if not out.get("route_mode"):
        out["route_mode"] = _DEFAULT_ROUTE_MODE
        injected.append("route_mode")

    if injected:
        logger.info(
            "Injected missing AIP metadata fields",
            extra={
                "event": "aip_metadata_injected",
                "injected_fields": injected,
                "trace_id": out["trace_id"],
                "route_mode": out["route_mode"],
                "device_id": out.get("device_id", "unknown"),
                "message_type": out.get("type", "unknown"),
            },
        )

    return out

# ---------------------------------------------------------------------------
# Legacy type-string → canonical MessageType mapping
# ---------------------------------------------------------------------------

_LEGACY_TYPE_MAP: dict = {
    # registration aliases
    "register": MessageType.DEVICE_REGISTER,
    "agent_register": MessageType.DEVICE_REGISTER,
    "device_register": MessageType.DEVICE_REGISTER,
    "registration": MessageType.DEVICE_REGISTER,       # Android AIPClient/EnhancedAIPClient send this
    # heartbeat aliases
    "heartbeat": MessageType.DEVICE_HEARTBEAT,
    "agent_heartbeat": MessageType.DEVICE_HEARTBEAT,
    "device_heartbeat": MessageType.DEVICE_HEARTBEAT,
    # task aliases – Android clients historically send "task_execute"
    # which maps to the v3 standard "task_submit"
    "task_execute": MessageType.TASK_SUBMIT,
    # task result aliases – Android clients send this after executing commands
    "command_result": MessageType.TASK_RESULT,
    # status aliases
    "status_update": MessageType.DEVICE_STATUS,
    "update_status": MessageType.DEVICE_STATUS,
    # high-level autonomous task aliases
    "goal_execute": MessageType.GOAL_EXECUTION,
    "goal": MessageType.GOAL_EXECUTION,
    "parallel_task": MessageType.PARALLEL_SUBTASK,
    # parallel result alias – devices/nodes may send "parallel_result"
    "parallel_result": MessageType.PARALLEL_RESULT,
    # v2 transport-layer aliases (used by core/device_communication.py local protocol)
    # These are normalised here so the routing layer only sees v3 type names.
    "handshake": MessageType.DEVICE_REGISTER,      # legacy registration handshake
    "text": MessageType.COMMAND,                   # wire-format "TEXT" (lowercased in _normalise_v1)
    "response": MessageType.COMMAND_RESULT,        # v2 command response → v3 command_result
    "status": MessageType.DEVICE_STATUS,           # v2 status update → v3 device_status
    "event": MessageType.WAKE_EVENT,               # v2 generic event → v3 wake_event
}


def _detect_version(data: dict) -> str:
    """Return the detected protocol version string ('1.0', '2.0', '3.0')."""
    raw_version = str(data.get("version", "1.0"))
    if raw_version.startswith("3"):
        return "3.0"
    if raw_version.startswith("2"):
        return "2.0"
    return "1.0"


def normalise_legacy_payload(data: dict) -> dict:
    """
    Map legacy field names in a raw payload dict to the canonical AIP v3
    :class:`~galaxy_gateway.protocol.aip_v3.AIPMessage` field names.

    This helper is safe to call on any dict before passing it to
    :class:`AIPMessage` or :func:`parse_message_compat`.  It only
    promotes / renames fields; it never removes existing ones.

    Mappings applied:

    * ``message_type`` → ``type`` (when ``type`` is absent)
    * ``payload["device_id"]`` → ``device_id`` (when ``device_id`` is absent
      at the top level but present inside the ``payload`` sub-dict)

    :param data: Raw input dict (not mutated).
    :returns: A new dict with legacy fields translated to v3 equivalents.
    """
    out = dict(data)

    # Map message_type → type when type is absent
    if "message_type" in out and "type" not in out:
        raw = out["message_type"]
        # Accept both enum instances and plain strings
        out["type"] = raw.value if hasattr(raw, "value") else str(raw)

    # Promote device_id from payload when absent at top level
    if "device_id" not in out:
        payload = out.get("payload")
        if isinstance(payload, dict) and "device_id" in payload:
            out["device_id"] = payload["device_id"]

    return out


# American-spelling alias for callers who prefer the standard spelling.
normalize_legacy_payload = normalise_legacy_payload


def _normalise_v1(data: dict) -> dict:
    """
    Normalise an AIP/1.0 message dict so it can be parsed by
    :func:`~galaxy_gateway.protocol.aip_v3.parse_message`.

    Changes applied:
    - Map legacy ``type`` strings to canonical ``MessageType`` values.
    - Set ``version`` to ``"3.0"``.
    - Ensure ``device_id`` is present (defaults to ``"unknown"``).
    """
    normalised = dict(data)
    normalised["version"] = "3.0"

    raw_type = str(normalised.get("type", "")).lower()
    canonical = _LEGACY_TYPE_MAP.get(raw_type)
    if canonical is not None:
        normalised["type"] = canonical.value
    # else: leave the type as-is; parse_message will raise if it is invalid.

    normalised.setdefault("device_id", "unknown")
    return normalised


def _normalise_v2(data: dict) -> dict:
    """
    Normalise an AIP/2.0 message dict.

    AIP v2 uses the same field names as v3; only the version tag differs.
    """
    normalised = dict(data)
    normalised["version"] = "3.0"
    normalised.setdefault("device_id", "unknown")
    return normalised


def aip_v2_binary_to_v3(raw_bytes: bytes) -> Optional[dict]:
    """Convert AIP v2.0 binary-encoded message to v3 JSON dict.

    Uses :class:`enhancements.multidevice.device_protocol.AIPMessage` which
    extends the v3 Pydantic ``AIPMessage`` with legacy ``from_bytes()`` binary
    deserialization.  The v2 wire format is:

        Header(16 bytes): magic(4) + version(2) + msg_type(2) + payload_len(4) + seq(4)
        Payload:          JSON-encoded body
        Footer(8 bytes):  crc32(4) + reserved(4)

    Returns ``None`` if the bytes don't match AIP v2.0 format.
    """
    try:
        from enhancements.multidevice.device_protocol import (
            AIPMessage as V2BinaryMessage,
            _V2_TO_V3_MSG_TYPE,
        )

        v2_msg = V2BinaryMessage.from_bytes(raw_bytes)

        # v2_msg is already a Pydantic AIPMessage; extract v3 JSON dict
        v3_type_str = v2_msg.type.value if hasattr(v2_msg.type, "value") else str(v2_msg.type)
        timestamp = v2_msg.timestamp
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        else:
            timestamp = str(timestamp)

        return {
            "version": "3.0",
            "type": v3_type_str,
            "device_id": v2_msg.device_id,
            "payload": v2_msg.payload,
            "timestamp": timestamp,
            "message_id": v2_msg.message_id,
            "correlation_id": v2_msg.correlation_id,
        }
    except Exception:
        return None


def parse_message_compat(data: Union[str, dict]) -> AIPMessage:
    """
    Parse an incoming message from any supported AIP protocol version.

    trace_id and route_mode are injected when absent so that every
    :class:`AIPMessage` exiting this layer always carries both fields in
    its ``payload``.

    :param data: Raw JSON string or already-decoded dict.
    :returns: A validated :class:`AIPMessage` instance.
    :raises: ``ValueError`` / ``pydantic.ValidationError`` if the message
             cannot be interpreted.
    """
    if isinstance(data, str):
        data = json.loads(data)

    # Ensure trace_id and route_mode are present before normalisation so that
    # the injected values survive the version-translation step unchanged.
    data = inject_trace_metadata(data)

    version = _detect_version(data)

    if version == "3.0":
        logger.debug("Protocol version detected: AIP/3.0")
        return parse_message(data)

    if version == "2.0":
        logger.info("Protocol version detected: AIP/2.0 — normalising to v3")
        return parse_message(_normalise_v2(data))

    # AIP/1.0
    logger.info(
        "Protocol version detected: AIP/1.0 — normalising type=%r to v3",
        data.get("type"),
    )
    return parse_message(_normalise_v1(data))


def normalise_to_v3_dict(data: Union[str, dict]) -> dict:
    """
    Normalise an incoming message from any supported AIP protocol version to a
    v3-shaped **dict**, preserving all extra application-level fields.

    Unlike :func:`parse_message_compat`, this function does **not** create a
    Pydantic :class:`AIPMessage` object.  Extra fields (e.g. ``platform``,
    ``model``, ``os_version``) that are not part of the :class:`AIPMessage`
    schema are therefore retained in the returned dict, making it suitable for
    downstream handlers that read non-schema fields directly.

    Normalisation applied:

    * JSON string input is decoded first.
    * ``trace_id`` and ``route_mode`` are injected when absent.
    * ``version`` is set to ``"3.0"`` for v1 and v2 input.
    * ``type`` is mapped from legacy aliases to canonical v3 names for v1 input.
    * ``device_id`` defaults to ``"unknown"`` when absent (v1/v2 only).

    :param data: Raw JSON string or already-decoded dict.
    :returns: A normalised dict with ``version="3.0"`` and canonical type name.
    :raises: ``json.JSONDecodeError`` if *data* is a malformed JSON string.
    """
    if isinstance(data, str):
        data = json.loads(data)

    data = inject_trace_metadata(data)
    version = _detect_version(data)

    if version == "3.0":
        logger.debug("Protocol version detected: AIP/3.0 (dict pass-through)")
        return dict(data)

    if version == "2.0":
        logger.info("Protocol version detected: AIP/2.0 — normalising to v3 dict")
        return _normalise_v2(data)

    # AIP/1.0
    logger.info(
        "Protocol version detected: AIP/1.0 — normalising type=%r to v3 dict",
        data.get("type"),
    )
    return _normalise_v1(data)


def parse_message_strict(data: Union[str, dict]) -> AIPMessage:
    """
    Parse an incoming message and **enforce** AIP v3.0 or higher.

    Unlike :func:`parse_message_compat`, this function raises
    :class:`AIPVersionError` when the message carries a version below 3.0
    or omits the ``version`` field entirely.  Use this at WebSocket / HTTP
    ingress points that must reject legacy clients.

    trace_id and route_mode are still injected when absent so that all
    downstream handlers always see both fields.

    :param data: Raw JSON string or already-decoded dict.
    :returns: A validated :class:`AIPMessage` instance.
    :raises AIPVersionError: when version < 3.0 or version is absent.
    :raises ValueError / pydantic.ValidationError: for other parse errors.
    """
    if isinstance(data, str):
        data = json.loads(data)

    # Version gate — raises AIPVersionError for < 3.0 or missing version.
    enforce_aip_v3(data)

    # Inject missing metadata fields before parsing.
    data = inject_trace_metadata(data)

    logger.debug("Protocol version enforced: AIP/3.0")
    return parse_message(data)


# ---------------------------------------------------------------------------
# Parallel-result payload extraction helper
# ---------------------------------------------------------------------------

def extract_parallel_result_payload(message: AIPMessage):
    """
    Extract a :class:`~galaxy_gateway.protocol.aip_v3.ParallelResultPayload`
    from an :class:`AIPMessage` of type ``parallel_result``.

    Works for both AIP v3 messages that carry the full payload dict and for
    legacy messages that may carry a flat ``group_id`` / ``subtask_results``
    structure.

    Returns ``None`` if the message is not a ``parallel_result`` type or the
    payload cannot be parsed.
    """
    from .aip_v3 import ParallelResultPayload

    if message.type != MessageType.PARALLEL_RESULT:
        return None

    payload = message.payload or {}

    # Normalise: some legacy senders put subtask_results at top-level payload.
    # Shallow copy is intentional — we only read/rename top-level keys (group_id,
    # subtask_results/device_results) and never mutate nested structures.
    import copy as _copy
    data: dict = _copy.deepcopy(dict(payload))
    if "group_id" not in data and message.task_id:
        data["group_id"] = message.task_id
    data.setdefault("group_id", "unknown")

    # subtask_results vs device_results compatibility
    if "subtask_results" in data and "device_results" not in data:
        data["device_results"] = data.pop("subtask_results")

    try:
        return ParallelResultPayload.from_tracker_dict(data)
    except Exception as exc:
        logger.warning("extract_parallel_result_payload: parse failed: %s", exc)
        return None
