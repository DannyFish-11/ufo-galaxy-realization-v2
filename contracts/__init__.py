"""contracts — Shared contract types for Galaxy execution lifecycle.

Exports the canonical execution trace contract introduced in PR-25, the
Registered Runtime Device contract introduced in PR-29, and the Local Runtime
Host contract introduced in PR-30.
"""

from contracts.execution_trace import (
    ExecutionTraceEnvelope,
    ExecutionTraceEvent,
    ExecutionTraceStage,
    ExecutionTraceStatus,
    build_trace_envelope,
    from_execution_intent,
    from_execution_result,
    from_fallback_trace,
    from_readiness_result,
)

# PR-29: Unified Registered Runtime Device Contract
from contracts.registered_runtime_device import (
    RegisteredRuntimeDevice,
    RuntimeConnectionSummary,
    RuntimeCapabilityProfile,
    RuntimeAutonomySummary,
    RuntimeSessionPresence,
    RuntimeParticipationHints,
    RuntimeDevicePlatform,
    RuntimeDeviceFormFactor,
    RuntimeDeviceStatus,
    RuntimeConnectionState,
    build_registered_runtime_device,
    from_udm_device,
    from_router_device,
    from_android_registration,
    from_device_registry_record,
)

# PR-30: Local Runtime Host Contract
from contracts.local_runtime_host import (
    LocalRuntimeHost,
    LocalRuntimeHostStatus,
    LocalRuntimeHostCapabilities,
    LocalRuntimeSessionSupport,
    LocalRuntimeHandoffSupport,
    LocalRuntimeExecutionSupport,
    LocalRuntimeExecutionMode,
    from_registered_runtime_device,
    from_runtime_bridge_config,
    build_local_runtime_host,
    summarize_local_runtime_host,
)

__all__ = [
    # PR-25: Execution Trace Contract
    "ExecutionTraceEnvelope",
    "ExecutionTraceEvent",
    "ExecutionTraceStage",
    "ExecutionTraceStatus",
    "build_trace_envelope",
    "from_execution_intent",
    "from_execution_result",
    "from_fallback_trace",
    "from_readiness_result",
    # PR-29: Registered Runtime Device Contract
    "RegisteredRuntimeDevice",
    "RuntimeConnectionSummary",
    "RuntimeCapabilityProfile",
    "RuntimeAutonomySummary",
    "RuntimeSessionPresence",
    "RuntimeParticipationHints",
    "RuntimeDevicePlatform",
    "RuntimeDeviceFormFactor",
    "RuntimeDeviceStatus",
    "RuntimeConnectionState",
    "build_registered_runtime_device",
    "from_udm_device",
    "from_router_device",
    "from_android_registration",
    "from_device_registry_record",
    # PR-30: Local Runtime Host Contract
    "LocalRuntimeHost",
    "LocalRuntimeHostStatus",
    "LocalRuntimeHostCapabilities",
    "LocalRuntimeSessionSupport",
    "LocalRuntimeHandoffSupport",
    "LocalRuntimeExecutionSupport",
    "LocalRuntimeExecutionMode",
    "from_registered_runtime_device",
    "from_runtime_bridge_config",
    "build_local_runtime_host",
    "summarize_local_runtime_host",
]
