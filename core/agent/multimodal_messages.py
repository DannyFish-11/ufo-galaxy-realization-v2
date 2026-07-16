"""
core/agent/multimodal_messages.py -- Native multimodal message construction for general chat paths.

Constructs OpenAI-style content arrays (text + image_url data URL) from
MultiModalContext images, allowing images to be delivered natively to the model
(rather than being text-summarized).

Warning: Only safe for **OpenAI-compatible providers** (they forward messages as-is).
Gemini and other adapters concatenate ``m["content"]`` as strings, which breaks
when receiving arrays -- therefore defaults to **disabled**, requires OpenAI-compatible
main chain and explicit ``GALAXY_NATIVE_MM_CHAT=1`` to enable. When disabled, returns
plain text with behavior identical to before.

Bug-fix #5: Added message format version check to ensure compatibility between versions.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final, List, Optional, Union

logger = logging.getLogger("Galaxy.Agent.MultimodalMessages")

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------

# Bug-fix #5: Message format version constants
MM_MESSAGE_FORMAT_VERSION: Final[str] = "1.0"
MM_MIN_SUPPORTED_VERSION: Final[str] = "1.0"

# Maximum number of images to include in a message (cost control)
_MAX_IMAGES_PER_MESSAGE: Final[int] = 4

# Default MIME type for images
_DEFAULT_IMAGE_MIME: Final[str] = "image/jpeg"

# Environment variable to enable native multimodal chat
_ENV_NATIVE_MM_CHAT: Final[str] = "GALAXY_NATIVE_MM_CHAT"


# ------------------------------------------------------------------------------
# Version checking
# ------------------------------------------------------------------------------


def _check_format_version(version: str) -> bool:
    """Check if message format version is compatible.

    Bug-fix #5: Version compatibility check. Current version and target version
    must have matching major version numbers.

    Args:
        version: Target format version string (e.g., "1.0").

    Returns:
        True if versions are compatible, False otherwise.
    """
    if not version:
        return False
    try:
        current_major = MM_MESSAGE_FORMAT_VERSION.split(".")[0]
        target_major = version.split(".")[0]
        return current_major == target_major
    except (ValueError, IndexError):
        return False


# ------------------------------------------------------------------------------
# Feature flag
# ------------------------------------------------------------------------------


def native_mm_enabled() -> bool:
    """Check if native multimodal chat is enabled via environment variable.

    Returns:
        True if GALAXY_NATIVE_MM_CHAT is set to a truthy value.
    """
    return os.getenv(_ENV_NATIVE_MM_CHAT, "0").strip().lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------------------------
# Message content builder
# ------------------------------------------------------------------------------


def build_user_message_content(
    text: str,
    multimodal_context: Any,
    *,
    format_version: str = "",
) -> Union[str, List[dict]]:
    """Build user message content with optional multimodal support.

    Returns OpenAI-style content array when images are present and native
    multimodal is enabled; otherwise returns plain text.

    Args:
        text: User text message.
        multimodal_context: Multimodal context object containing images.
        format_version: Bug-fix #5 -- explicit message format version for
            compatibility checking. Empty string means no version check
            (backward compatible).

    Returns:
        Either a plain text string or an OpenAI content array
        (list of dicts with type and content).

    Bug-fix #5: Added version checking to ensure message format compatibility
    with the processing endpoint.
    """
    # Bug-fix #5: Version compatibility check
    if format_version and not _check_format_version(format_version):
        logger.warning(
            "Message format version incompatible: current=%s, target=%s, falling back to plain text",
            MM_MESSAGE_FORMAT_VERSION,
            format_version,
        )
        return text

    if not native_mm_enabled() or multimodal_context is None:
        return text

    images: List[Any] = getattr(multimodal_context, "images", None) or []
    if not images:
        return text

    content: List[dict] = [{"type": "text", "text": text}]
    for im in images[:_MAX_IMAGES_PER_MESSAGE]:
        mime: str = getattr(im, "mime", _DEFAULT_IMAGE_MIME) or _DEFAULT_IMAGE_MIME
        data: str = getattr(im, "data", "") or ""
        if data:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                }
            )

    return content if len(content) > 1 else text
