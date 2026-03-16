"""
tests/test_v3_schemas.py
========================

Validates the AIP v3.0 JSON Schema files stored in
``galaxy_gateway/protocol/schemas/``.

For each schema the tests verify:

1. The file is valid JSON and loads without error.
2. Every example embedded in the schema ``"examples"`` array is accepted by
   the schema validator (positive test).
3. Payloads that are missing required fields are rejected (negative test).
"""

import json
import os
import pathlib

import pytest
import jsonschema
from jsonschema import Draft202012Validator, ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHEMAS_DIR = pathlib.Path(__file__).parent.parent / "galaxy_gateway" / "protocol" / "schemas"

SCHEMA_FILES = {
    "aip_envelope": "aip_envelope.schema.json",
    "device_register": "device_register.schema.json",
    "heartbeat": "heartbeat.schema.json",
    "capability_report": "capability_report.schema.json",
    "task_assign": "task_assign.schema.json",
    "command_result": "command_result.schema.json",
}


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / SCHEMA_FILES[name]
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validate(schema: dict, instance: dict):
    """Validate *instance* against *schema* using Draft 2020-12."""
    validator = Draft202012Validator(schema)
    validator.validate(instance)


def assert_invalid(schema: dict, instance: dict):
    """Assert that *instance* does NOT conform to *schema*."""
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(instance))
    assert errors, (
        f"Expected validation failure but schema accepted the instance:\n{json.dumps(instance, indent=2)}"
    )


# ---------------------------------------------------------------------------
# 1. Schema files load without error
# ---------------------------------------------------------------------------

class TestSchemaFilesLoad:
    @pytest.mark.parametrize("name", list(SCHEMA_FILES))
    def test_file_exists_and_parses(self, name):
        schema = load_schema(name)
        assert isinstance(schema, dict), f"Expected dict for schema '{name}'"
        assert "$schema" in schema, f"Missing '$schema' key in '{name}'"
        assert "title" in schema, f"Missing 'title' key in '{name}'"

    @pytest.mark.parametrize("name", list(SCHEMA_FILES))
    def test_schema_is_valid_json_schema(self, name):
        schema = load_schema(name)
        # jsonschema can validate the meta-schema itself
        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as exc:
            pytest.fail(f"Schema '{name}' is not a valid JSON Schema: {exc}")


# ---------------------------------------------------------------------------
# 2. Embedded examples are accepted (positive tests)
# ---------------------------------------------------------------------------

class TestEmbeddedExamplesValid:
    @pytest.mark.parametrize("name", list(SCHEMA_FILES))
    def test_examples_pass_validation(self, name):
        schema = load_schema(name)
        examples = schema.get("examples", [])
        if not examples:
            pytest.skip(f"Schema '{name}' has no embedded examples")
        for i, example in enumerate(examples):
            try:
                validate(schema, example)
            except ValidationError as exc:
                pytest.fail(
                    f"Schema '{name}' example[{i}] failed validation:\n{exc.message}"
                )


# ---------------------------------------------------------------------------
# 3. Positive tests – well-formed v3 payloads
# ---------------------------------------------------------------------------

class TestDeviceRegisterValid:
    def setup_method(self):
        self.schema = load_schema("device_register")

    def test_minimal_v3(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "device_register",
            "device_id": "dev-001",
        })

    def test_full_v3(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "device_register",
            "device_id": "android-abc123",
            "device_type": "android_phone",
            "platform": "android",
            "name": "My Phone",
            "model": "Pixel 7",
            "os_version": "Android 14",
            "sdk_version": 34,
            "capabilities": 1023,
        })

    def test_v3_1_version_accepted(self):
        validate(self.schema, {
            "version": "3.1",
            "type": "device_register",
            "device_id": "dev-002",
        })


class TestHeartbeatValid:
    def setup_method(self):
        self.schema = load_schema("heartbeat")

    def test_minimal_v3(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev-001",
        })

    def test_with_trace_metadata(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev-001",
            "trace_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "route_mode": "cross_device",
        })


class TestCapabilityReportValid:
    def setup_method(self):
        self.schema = load_schema("capability_report")

    def test_minimal_v3(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "capability_report",
            "device_id": "android-abc123",
            "platform": "android",
            "supported_actions": ["tap", "swipe", "screenshot"],
        })

    def test_with_capability_schemas(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "capability_report",
            "device_id": "android-abc123",
            "platform": "android",
            "supported_actions": ["tap"],
            "capability_version": "1.0",
            "capability_schemas": [
                {
                    "action": "tap",
                    "params": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}},
                    "exec_mode": "remote",
                    "tags": ["ui", "touch"],
                }
            ],
        })


class TestTaskAssignValid:
    def setup_method(self):
        self.schema = load_schema("task_assign")

    def test_minimal_v3(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "task_assign",
            "device_id": "android-abc123",
            "task_id": "task-001",
            "task_type": "ui_automation",
            "payload": {"action": "tap", "x": 100, "y": 200},
        })

    def test_with_commands(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "task_assign",
            "device_id": "android-abc123",
            "task_id": "task-002",
            "task_type": "screenshot",
            "payload": {},
            "priority": 8,
            "timeout": 10,
            "commands": [
                {"command_id": "cmd-1", "tool_name": "screenshot", "parameters": {}}
            ],
        })


class TestCommandResultValid:
    def setup_method(self):
        self.schema = load_schema("command_result")

    def test_minimal_v3(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "command_result",
            "device_id": "android-abc123",
        })

    def test_with_results(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "command_result",
            "device_id": "android-abc123",
            "task_id": "task-001",
            "task_status": "completed",
            "results": [
                {
                    "command_id": "cmd-1",
                    "status": "success",
                    "result": {"screenshot_path": "/sdcard/shot.png"},
                    "execution_time": 0.5,
                }
            ],
        })

    def test_failure_result(self):
        validate(self.schema, {
            "version": "3.0",
            "type": "command_result",
            "device_id": "android-abc123",
            "task_id": "task-002",
            "task_status": "failed",
            "results": [
                {
                    "command_id": "cmd-2",
                    "status": "failure",
                    "error": "Element not found",
                    "execution_time": 1.2,
                }
            ],
            "error": "Task failed: element not found",
        })


# ---------------------------------------------------------------------------
# 4. Negative tests – missing required fields are rejected
# ---------------------------------------------------------------------------

class TestMissingVersionRejected:
    @pytest.mark.parametrize("name", [
        "device_register", "heartbeat", "capability_report",
        "task_assign", "command_result",
    ])
    def test_missing_version_rejected(self, name):
        schema = load_schema(name)
        base = {
            "type": name,
            "device_id": "dev-001",
            "platform": "android",
            "supported_actions": ["tap"],
            "task_id": "t1",
            "task_type": "ui",
            "payload": {},
        }
        del_key = "version"
        instance = {k: v for k, v in base.items() if k != del_key}
        assert_invalid(schema, instance)

    @pytest.mark.parametrize("name", [
        "device_register", "heartbeat", "capability_report",
        "task_assign", "command_result",
    ])
    def test_legacy_version_rejected(self, name):
        """Version '2.0' must fail the pattern ^3[.] check (version field must start with '3.')."""
        schema = load_schema(name)
        base = {
            "version": "2.0",
            "type": name,
            "device_id": "dev-001",
            "platform": "android",
            "supported_actions": ["tap"],
            "task_id": "t1",
            "task_type": "ui",
            "payload": {},
        }
        assert_invalid(schema, base)


class TestCapabilityReportMissingFields:
    def setup_method(self):
        self.schema = load_schema("capability_report")
        self.valid = {
            "version": "3.0",
            "type": "capability_report",
            "device_id": "android-abc123",
            "platform": "android",
            "supported_actions": ["tap"],
        }

    def test_missing_platform_rejected(self):
        instance = {k: v for k, v in self.valid.items() if k != "platform"}
        assert_invalid(self.schema, instance)

    def test_missing_supported_actions_rejected(self):
        instance = {k: v for k, v in self.valid.items() if k != "supported_actions"}
        assert_invalid(self.schema, instance)

    def test_empty_supported_actions_rejected(self):
        instance = {**self.valid, "supported_actions": []}
        assert_invalid(self.schema, instance)

    def test_missing_device_id_rejected(self):
        instance = {k: v for k, v in self.valid.items() if k != "device_id"}
        assert_invalid(self.schema, instance)


class TestTaskAssignMissingFields:
    def setup_method(self):
        self.schema = load_schema("task_assign")
        self.valid = {
            "version": "3.0",
            "type": "task_assign",
            "device_id": "dev-001",
            "task_id": "task-001",
            "task_type": "ui_automation",
            "payload": {},
        }

    @pytest.mark.parametrize("field", ["task_id", "task_type", "payload", "device_id"])
    def test_missing_required_field(self, field):
        instance = {k: v for k, v in self.valid.items() if k != field}
        assert_invalid(self.schema, instance)


class TestAIPEnvelopeMissingFields:
    def setup_method(self):
        self.schema = load_schema("aip_envelope")

    def test_missing_version_rejected(self):
        assert_invalid(self.schema, {"type": "heartbeat", "device_id": "dev-1"})

    def test_missing_type_rejected(self):
        assert_invalid(self.schema, {"version": "3.0", "device_id": "dev-1"})

    def test_missing_device_id_rejected(self):
        assert_invalid(self.schema, {"version": "3.0", "type": "heartbeat"})
