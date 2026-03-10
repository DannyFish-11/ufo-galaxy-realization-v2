"""
Galaxy Agentic OS — Anti-Corruption Layer (ACL)
=================================================

Sits at every boundary where unstructured data enters the typed contract system:

1. LLM output → before publishing to NATS
2. Worker results → before feeding back to MasterBrain
3. MCP tool results → before consumption

Constraints (see plan 强约束):
  C2  — emits events through ``integration.event_bus.EventBus``
  C3  — uses ``resolve_device_type()`` for string→enum coercion
  C7  — returns ``{"success": bool, "error": str | None, ...}`` dicts
  C11 — uses stdlib ``logging`` (matching codebase convention)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("acl")

from core.device_types import resolve_device_type
from core.schemas.contracts import (
    MCPCallRequestModel,
    MCPToolRegistrationModel,
    TaskDispatchModel,
    TaskResultModel,
    WorkerRegistrationModel,
)

T = TypeVar("T", bound=BaseModel)

# Maximum stdout/stderr length before truncation (1 MB)
_MAX_OUTPUT_LEN = 1_048_576

# Maximum raw payload size we'll accept (10 MB)
_MAX_PAYLOAD_SIZE = 10_485_760


def _try_emit_event(event_type_name: str, data: dict) -> None:
    """Best-effort emit to EventBus.  Never raises."""
    try:
        from integration.event_bus import event_bus, EventType

        et = getattr(EventType, event_type_name, None)
        if et is not None:
            event_bus.publish_sync(et, "agentic_os", data)
    except Exception:
        pass


class AntiCorruptionLayer:
    """Validates, normalizes, and sanitizes all cross-boundary data.

    Usage::

        acl = AntiCorruptionLayer()
        result = await acl.validate_task_dispatch(raw_dict)
        if not result["success"]:
            logger.error(result["error"])
    """

    # ── Public API ──────────────────────────────────────────────────────────

    async def validate_task_dispatch(self, raw: dict) -> dict:
        """Validate & normalize brain output before publishing to NATS.

        Returns ``{"success": True, "data": TaskDispatchModel}``
        or ``{"success": False, "error": ..., "details": ...}``.
        """
        return await self._validate(raw, TaskDispatchModel, "task_dispatch")

    async def validate_task_result(self, raw: dict) -> dict:
        """Validate worker result before feeding back to brain."""
        normalized = self._normalize_task_result(raw)
        return await self._validate(normalized, TaskResultModel, "task_result")

    async def validate_mcp_call(self, raw: dict) -> dict:
        """Validate MCP tool call request from LLM."""
        return await self._validate(raw, MCPCallRequestModel, "mcp_call")

    async def validate_mcp_registration(self, raw: dict) -> dict:
        """Validate MCP tool registration (Self-Tool-Making)."""
        return await self._validate(raw, MCPToolRegistrationModel, "mcp_registration")

    async def validate_worker_registration(self, raw: dict) -> dict:
        """Validate worker registration on first connect."""
        return await self._validate(raw, WorkerRegistrationModel, "worker_registration")

    # ── Core validation pipeline ────────────────────────────────────────────

    async def _validate(
        self, raw: dict, model_cls: Type[T], label: str
    ) -> dict:
        """Generic validation pipeline.

        Steps:
        1. Size check
        2. Hallucination guard (pre-validation)
        3. Pydantic model_validate
        4. On failure: fallback field-by-field extraction
        5. Audit log + event emission
        """
        if not isinstance(raw, dict):
            return self._fail(label, "Input must be a dict", raw)

        raw_size = len(json.dumps(raw, default=str))
        if raw_size > _MAX_PAYLOAD_SIZE:
            return self._fail(label, f"Payload too large: {raw_size} bytes (max {_MAX_PAYLOAD_SIZE})", None)

        # Pre-validation normalization
        normalized = self._normalize_common(raw)
        hallucination_errors = self._hallucination_guard(normalized, label)
        if hallucination_errors:
            return self._fail(label, "Hallucination guard rejected input", raw, hallucination_errors)

        # Primary validation
        try:
            model = model_cls.model_validate(normalized)
            logger.debug(f"ACL: {label} validated successfully ({type(model).__name__})")
            return {"success": True, "data": model}
        except ValidationError as exc:
            logger.warning(f"ACL: {label} primary validation failed, attempting fallback")
            return await self._fallback_validate(raw, model_cls, label, exc)

    async def _fallback_validate(
        self,
        raw: dict,
        model_cls: Type[T],
        label: str,
        original_error: ValidationError,
    ) -> dict:
        """Attempt field-by-field extraction with defaults on validation failure."""
        fields = model_cls.model_fields
        extracted: Dict[str, Any] = {}

        for field_name, field_info in fields.items():
            if field_name in raw:
                extracted[field_name] = raw[field_name]

        try:
            model = model_cls.model_validate(extracted)
            logger.info(f"ACL: {label} fallback succeeded with {len(extracted)} fields")
            _try_emit_event("ACL_NORMALIZATION_APPLIED", {
                "label": label,
                "original_fields": len(raw),
                "extracted_fields": len(extracted),
            })
            return {"success": True, "data": model}
        except ValidationError as exc:
            error_details = [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
            _try_emit_event("ACL_VALIDATION_FAILED", {
                "label": label,
                "errors": error_details,
                "raw_keys": list(raw.keys()),
            })
            return self._fail(label, "ACL validation failed", raw, error_details)

    # ── Normalization helpers ───────────────────────────────────────────────

    def _normalize_common(self, raw: dict) -> dict:
        """Apply common normalizations to raw input."""
        out = dict(raw)

        # String→enum coercion for device_type fields
        for key in ("target_device_type", "device_type"):
            if key in out and isinstance(out[key], str):
                out[key] = resolve_device_type(out[key]).value

        # Priority normalization
        if "priority" in out and isinstance(out["priority"], (int, float)):
            _prio_map = {0: "unspecified", 1: "low", 2: "normal", 3: "high", 4: "critical"}
            out["priority"] = _prio_map.get(int(out["priority"]), "normal")

        # Status normalization
        if "status" in out and isinstance(out["status"], (int, float)):
            _status_map = {
                0: "unspecified", 1: "pending", 2: "queued", 3: "dispatched",
                4: "running", 5: "lsp_failed", 6: "success", 7: "failed",
                8: "timeout", 9: "cancelled", 10: "retrying",
            }
            out["status"] = _status_map.get(int(out["status"]), "unspecified")

        return out

    def _normalize_task_result(self, raw: dict) -> dict:
        """Normalize task result specific fields (truncate large outputs)."""
        out = dict(raw)

        # Truncate oversized stdout/stderr
        exec_output = out.get("execution_output")
        if isinstance(exec_output, dict):
            for key in ("stdout", "stderr"):
                val = exec_output.get(key, "")
                if isinstance(val, str) and len(val) > _MAX_OUTPUT_LEN:
                    exec_output[key] = val[:_MAX_OUTPUT_LEN] + f"\n... [truncated at {_MAX_OUTPUT_LEN} bytes]"

        return out

    def _hallucination_guard(self, data: dict, label: str) -> Optional[list]:
        """Reject obviously impossible values that LLMs might hallucinate."""
        errors = []

        # Negative durations
        for key in ("timeout_ms", "duration_ms", "cpu_limit_ms", "check_duration_ms",
                     "wall_time_ms", "cpu_time_ms", "queue_wait_ms", "drain_timeout_s"):
            val = data.get(key)
            if val is not None and isinstance(val, (int, float)) and val < 0:
                errors.append(f"{key} cannot be negative: {val}")

        # Negative memory
        for key in ("memory_limit_mb", "disk_limit_mb", "memory_peak_bytes",
                     "memory_total_mb", "disk_free_mb"):
            val = data.get(key)
            if val is not None and isinstance(val, (int, float)) and val < 0:
                errors.append(f"{key} cannot be negative: {val}")

        # Percentage range
        for key in ("cpu_usage_percent", "memory_usage_percent"):
            val = data.get(key)
            if val is not None and isinstance(val, (int, float)) and (val < 0 or val > 100):
                errors.append(f"{key} must be 0-100: {val}")

        # Nested checks for execution_output
        exec_output = data.get("execution_output")
        if isinstance(exec_output, dict):
            dur = exec_output.get("duration_ms")
            if dur is not None and isinstance(dur, (int, float)) and dur < 0:
                errors.append(f"execution_output.duration_ms cannot be negative: {dur}")

        # Nested checks for sandbox_config
        sandbox = data.get("sandbox_config")
        if isinstance(sandbox, dict):
            for key in ("memory_limit_mb", "cpu_limit_ms", "timeout_ms", "disk_limit_mb"):
                val = sandbox.get(key)
                if val is not None and isinstance(val, (int, float)) and val < 0:
                    errors.append(f"sandbox_config.{key} cannot be negative: {val}")

        return errors if errors else None

    # ── Result helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _fail(
        label: str,
        error_msg: str,
        raw_input: Any,
        details: Any = None,
    ) -> dict:
        logger.warning(f"ACL: {label} — {error_msg}")
        result: dict = {
            "success": False,
            "error": f"ACL validation failed: {error_msg}",
        }
        if details is not None:
            result["details"] = details
        if raw_input is not None:
            try:
                result["raw_input"] = raw_input if isinstance(raw_input, dict) else str(raw_input)
            except Exception:
                result["raw_input"] = "<unserializable>"
        return result


# ── Module-level singleton (constraint C1) ─────────────────────────────────
acl = AntiCorruptionLayer()
