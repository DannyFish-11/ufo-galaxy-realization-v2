"""
galaxy_gateway/android/handlers/__init__.py

Re-exports all handler functions for convenient import.
Each handler has the signature:
    async def handle_*(bridge, websocket, message) -> Optional[Dict[str, Any]]
where ``bridge`` is the AndroidBridge instance providing state and UDM helpers.
"""

from galaxy_gateway.android.handlers.registration import (
    handle_device_register,
    handle_unregistered,
)
from galaxy_gateway.android.handlers.heartbeat import (
    handle_heartbeat,
    handle_device_status,
    handle_agent_ping,
)
from galaxy_gateway.android.handlers.task_lifecycle import (
    handle_task_result,
    handle_task_end,
    handle_task_progress,
    handle_command_result,
    handle_error,
)
from galaxy_gateway.android.handlers.task_submit import (
    handle_task_execute,
    handle_task_submit,
)
from galaxy_gateway.android.handlers.goal_execution import (
    handle_goal_execution,
    handle_parallel_subtask,
    handle_goal_execution_result,
)
from galaxy_gateway.android.handlers.capability_report import handle_capability_report
from galaxy_gateway.android.handlers.diagnostics import handle_diagnostics_payload
from galaxy_gateway.android.handlers.vision import handle_vision_request
from galaxy_gateway.android.handlers.generic import handle_generic_forward

__all__ = [
    "handle_device_register",
    "handle_unregistered",
    "handle_heartbeat",
    "handle_device_status",
    "handle_agent_ping",
    "handle_task_result",
    "handle_task_end",
    "handle_task_progress",
    "handle_command_result",
    "handle_error",
    "handle_task_execute",
    "handle_task_submit",
    "handle_goal_execution",
    "handle_parallel_subtask",
    "handle_goal_execution_result",
    "handle_capability_report",
    "handle_diagnostics_payload",
    "handle_vision_request",
    "handle_generic_forward",
]
