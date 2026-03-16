"""
tests/fixtures/legacy_payloads.py
===================================

Canonical legacy-payload fixtures used by the PR-S6 regression and
compatibility-guardrail test suite.

Each fixture represents a realistic "wire" message as it would arrive from
an AIP v1.0 or AIP v2.0 client *before* any compat normalisation.  The
expected normalised v3 fields are recorded alongside each fixture so that
tests can assert correctness without re-implementing the mapping logic.

Usage::

    from tests.fixtures.legacy_payloads import LEGACY_V1, LEGACY_V2, NATIVE_V3

    raw = LEGACY_V1["device_register"]
    # Pass through compat then assert on the returned AIPMessage.
"""

# ---------------------------------------------------------------------------
# AIP / 1.0 fixtures  (no ``version`` field; legacy ``type`` aliases)
# ---------------------------------------------------------------------------

LEGACY_V1 = {
    # --- device registration --------------------------------------------------
    "device_register": {
        "type": "register",
        "device_id": "v1-dev-001",
        "payload": {
            "model": "Pixel 7",
            "os_version": "Android 13",
        },
    },
    # Alias variants that must also be accepted
    "device_register_alias_agent_register": {
        "type": "agent_register",
        "device_id": "v1-dev-002",
    },
    "device_register_alias_registration": {
        "type": "registration",
        "device_id": "v1-dev-003",
    },

    # --- heartbeat ------------------------------------------------------------
    "heartbeat": {
        "type": "heartbeat",
        "device_id": "v1-dev-010",
    },
    "heartbeat_alias_device_heartbeat": {
        "type": "device_heartbeat",
        "device_id": "v1-dev-011",
    },

    # --- capability_report ----------------------------------------------------
    # In AIP/1.0, capability data was sent inside a generic "register" message
    # or as a custom type.  We test both the promoted type *and* normalisation
    # of the fields.
    "capability_report_via_register": {
        "type": "register",
        "device_id": "v1-dev-020",
        "payload": {
            "platform": "android",
            "supported_actions": ["click", "swipe", "screenshot"],
            "version": "1.0",
        },
    },

    # --- task_assign ----------------------------------------------------------
    "task_assign_via_task_execute": {
        "type": "task_execute",
        "device_id": "v1-dev-030",
        "payload": {
            "task_id": "t-v1-001",
            "commands": [{"tool_name": "click", "parameters": {"x": 50, "y": 100}}],
        },
    },

    # --- command_result -------------------------------------------------------
    "command_result": {
        "type": "command_result",
        "device_id": "v1-dev-040",
        "payload": {
            "command_id": "cmd-v1-001",
            "status": "success",
            "output": "done",
        },
    },
    "command_result_alias_response": {
        "type": "response",
        "device_id": "v1-dev-041",
        "payload": {"status": "success"},
    },
}

# ---------------------------------------------------------------------------
# AIP / 2.0 fixtures  (``version == "2.0"``; same field names as v3)
# ---------------------------------------------------------------------------

LEGACY_V2 = {
    # --- device_register ------------------------------------------------------
    "device_register": {
        "version": "2.0",
        "type": "device_register",
        "device_id": "v2-dev-001",
        "payload": {"model": "Galaxy S23", "os_version": "Android 14"},
    },

    # --- heartbeat ------------------------------------------------------------
    "heartbeat": {
        "version": "2.0",
        "type": "heartbeat",
        "device_id": "v2-dev-010",
    },

    # --- capability_report ----------------------------------------------------
    "capability_report": {
        "version": "2.0",
        "type": "capability_report",
        "device_id": "v2-dev-020",
        "payload": {
            "platform": "android",
            "supported_actions": ["click", "swipe", "input_text", "screenshot"],
            "version": "2.0",
        },
    },

    # --- task_assign ----------------------------------------------------------
    "task_assign": {
        "version": "2.0",
        "type": "task_assign",
        "device_id": "v2-dev-030",
        "task_id": "t-v2-001",
        "payload": {"action": "screenshot"},
    },

    # --- command_result -------------------------------------------------------
    "command_result": {
        "version": "2.0",
        "type": "command_result",
        "device_id": "v2-dev-040",
        "payload": {"success": True, "output": "captured"},
    },
}

# ---------------------------------------------------------------------------
# Native AIP / 3.0 fixtures  (``version == "3.0"``; canonical v3 fields)
# ---------------------------------------------------------------------------

NATIVE_V3 = {
    # --- device_register ------------------------------------------------------
    "device_register": {
        "version": "3.0",
        "type": "device_register",
        "device_id": "v3-dev-001",
        "payload": {
            "model": "Pixel 8 Pro",
            "os_version": "Android 14",
            "platform": "android",
        },
    },

    # --- heartbeat ------------------------------------------------------------
    "heartbeat": {
        "version": "3.0",
        "type": "heartbeat",
        "device_id": "v3-dev-010",
    },

    # --- capability_report ----------------------------------------------------
    "capability_report": {
        "version": "3.0",
        "type": "capability_report",
        "device_id": "v3-dev-020",
        "payload": {
            "platform": "android",
            "supported_actions": ["click", "swipe", "input_text", "screenshot", "scroll"],
            "version": "3.0",
        },
    },

    # --- task_assign ----------------------------------------------------------
    "task_assign": {
        "version": "3.0",
        "type": "task_assign",
        "device_id": "v3-dev-030",
        "task_id": "t-v3-001",
        "payload": {"action": "click", "params": {"x": 100, "y": 200}},
    },

    # --- command_result -------------------------------------------------------
    "command_result": {
        "version": "3.0",
        "type": "command_result",
        "device_id": "v3-dev-040",
        "payload": {"success": True, "output": "ok"},
    },
}

# ---------------------------------------------------------------------------
# Negative-test fixtures: raw v2-type strings that must NOT be accepted by
# strict v3 endpoints (parse_message_strict) without compat normalisation.
# ---------------------------------------------------------------------------

NEGATIVE_CASES = {
    # A plain v2 versioned message delivered directly to a strict v3 endpoint
    "v2_device_register_strict": {
        "version": "2.0",
        "type": "device_register",
        "device_id": "neg-dev-001",
    },
    # No version field at all (legacy v1 behaviour) – strict should reject
    "v1_no_version_strict": {
        "type": "register",
        "device_id": "neg-dev-002",
    },
    # v1 with version "1.0" explicit
    "v1_explicit_version_strict": {
        "version": "1.0",
        "type": "heartbeat",
        "device_id": "neg-dev-003",
    },
    # v2-only field names that have no meaning in v3 (message_type instead of type)
    "v2_only_field_message_type": {
        "version": "2.0",
        "message_type": "device_register",
        "device_id": "neg-dev-004",
    },
}
