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
from typing import Union

from .aip_v3 import AIPMessage, MessageType, parse_message

logger = logging.getLogger(__name__)

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
}


def _detect_version(data: dict) -> str:
    """Return the detected protocol version string ('1.0', '2.0', '3.0')."""
    raw_version = str(data.get("version", "1.0"))
    if raw_version.startswith("3"):
        return "3.0"
    if raw_version.startswith("2"):
        return "2.0"
    return "1.0"


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


def parse_message_compat(data: Union[str, dict]) -> AIPMessage:
    """
    Parse an incoming message from any supported AIP protocol version.

    :param data: Raw JSON string or already-decoded dict.
    :returns: A validated :class:`AIPMessage` instance.
    :raises: ``ValueError`` / ``pydantic.ValidationError`` if the message
             cannot be interpreted.
    """
    if isinstance(data, str):
        data = json.loads(data)

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
