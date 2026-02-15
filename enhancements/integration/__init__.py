"""
Integration Module for UFO Galaxy Realization.

This module provides end-to-end integration between:
- Natural Language Understanding
- Physical Device Control
- Cross-Device Scheduling
"""

from .end_to_end_controller import (
    EndToEndController,
    VoiceCommandProcessor,
    DeviceCommandExecutor
)

__all__ = [
    "EndToEndController",
    "VoiceCommandProcessor",
    "DeviceCommandExecutor"
]
