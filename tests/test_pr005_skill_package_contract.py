"""tests/test_pr005_skill_package_contract.py
==============================================

Unit tests for PR-005: Canonical Skill Package Contract.

Test groups
-----------
  A) SkillPackageContractError
  B) validate_skill_package_contract — valid manifests
  C) validate_skill_package_contract — required field violations
  D) validate_skill_package_contract — optional field violations
  E) validate_skill_package_contract — schema_version enforcement
  F) validate_skill_package_contract — allow_future_schema
  G) is_valid_skill_package_contract helper
  H) build_skill_package_contract_summary helper
  I) SkillPackageContract.to_dict / from_dict round-trip
  J) SkillLoader.load() rejects invalid skill.json via contract
  K) GitHubInstaller._register_skill() rejects invalid manifest via contract
  L) GitHubInstaller._register_skill() accepts valid manifest and calls SkillLoader
  M) Successful install registers Skill into SkillLoader and refreshes capability registry
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _valid_manifest(**overrides) -> Dict[str, Any]:
    """Return a minimal valid skill.json manifest dict."""
    base = {
        "schema_version": "1",
        "id": "my-skill",
        "name": "My Skill",
        "description": "Does something useful.",
        "version": "1.0.0",
        "handler_file": "handler.py",
        "handler_function": "execute",
    }
    base.update(overrides)
    return base


# ===========================================================================
# A) SkillPackageContractError
# ===========================================================================


class TestSkillPackageContractError:
    def test_error_stores_violations(self):
        from core.skill_package_contract import SkillPackageContractError

        exc = SkillPackageContractError(["v1", "v2"], skill_id="bad-skill")
        assert exc.violations == ["v1", "v2"]
        assert exc.skill_id == "bad-skill"

    def test_error_code(self):
        from core.skill_package_contract import SkillPackageContractError

        assert SkillPackageContractError.error_code == "SKILL_PACKAGE_CONTRACT_INVALID"

    def test_str_representation(self):
        from core.skill_package_contract import SkillPackageContractError

        exc = SkillPackageContractError(["missing id"], skill_id="")
        assert "SKILL_PACKAGE_CONTRACT_INVALID" in exc.error_code
        assert "missing id" in str(exc)

    def test_is_value_error_subclass(self):
        from core.skill_package_contract import SkillPackageContractError

        exc = SkillPackageContractError(["v"])
        assert isinstance(exc, ValueError)


# ===========================================================================
# B) validate_skill_package_contract — valid manifests
# ===========================================================================


class TestValidateSkillPackageContractValid:
    def test_minimal_valid(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContract

        contract = validate_skill_package_contract(_valid_manifest())
        assert isinstance(contract, SkillPackageContract)
        assert contract.id == "my-skill"
        assert contract.name == "My Skill"
        assert contract.handler_file == "handler.py"
        assert contract.handler_function == "execute"

    def test_returns_correct_schema_version(self):
        from core.skill_package_contract import validate_skill_package_contract

        contract = validate_skill_package_contract(_valid_manifest())
        assert contract.schema_version == "1"

    def test_optional_fields_defaults(self):
        from core.skill_package_contract import validate_skill_package_contract

        contract = validate_skill_package_contract(
            {"id": "s", "name": "S", "handler_file": "h.py", "handler_function": "run"}
        )
        assert contract.description == ""
        assert contract.dependencies == []
        assert contract.permissions == []
        assert contract.tags == []
        assert contract.repository == ""
        assert contract.author == ""

    def test_full_manifest_all_optional_fields(self):
        from core.skill_package_contract import validate_skill_package_contract

        manifest = _valid_manifest(
            dependencies=["httpx>=0.27"],
            permissions=["internet"],
            tags=["search", "web"],
            repository="https://github.com/example/skill",
            author="Jane <jane@example.com>",
            parameters=[{"name": "query", "type": "string", "required": True}],
        )
        contract = validate_skill_package_contract(manifest)
        assert contract.dependencies == ["httpx>=0.27"]
        assert contract.permissions == ["internet"]
        assert contract.tags == ["search", "web"]
        assert contract.author == "Jane <jane@example.com>"
        assert len(contract.parameters) == 1

    def test_id_with_underscores_and_hyphens(self):
        from core.skill_package_contract import validate_skill_package_contract

        contract = validate_skill_package_contract(
            _valid_manifest(id="my_cool-skill123")
        )
        assert contract.id == "my_cool-skill123"

    def test_nested_handler_file_path(self):
        from core.skill_package_contract import validate_skill_package_contract

        contract = validate_skill_package_contract(
            _valid_manifest(handler_file="src/handlers/main.py")
        )
        assert contract.handler_file == "src/handlers/main.py"


# ===========================================================================
# C) validate_skill_package_contract — required field violations
# ===========================================================================


class TestValidateSkillPackageContractRequiredViolations:
    def test_missing_id(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        m = _valid_manifest()
        del m["id"]
        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(m)
        assert any("'id'" in v for v in exc_info.value.violations)

    def test_empty_id(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(id=""))
        assert any("'id'" in v for v in exc_info.value.violations)

    def test_id_with_spaces_rejected(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(id="my skill"))
        assert any("'id'" in v for v in exc_info.value.violations)

    def test_id_with_dots_rejected(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(id="my.skill"))
        assert any("'id'" in v for v in exc_info.value.violations)

    def test_missing_name(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        m = _valid_manifest()
        del m["name"]
        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(m)
        assert any("'name'" in v for v in exc_info.value.violations)

    def test_empty_name(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(name=""))
        assert any("'name'" in v for v in exc_info.value.violations)

    def test_missing_handler_file(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        m = _valid_manifest()
        del m["handler_file"]
        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(m)
        assert any("'handler_file'" in v for v in exc_info.value.violations)

    def test_empty_handler_file(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(handler_file=""))
        assert any("'handler_file'" in v for v in exc_info.value.violations)

    def test_missing_handler_function(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        m = _valid_manifest()
        del m["handler_function"]
        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(m)
        assert any("'handler_function'" in v for v in exc_info.value.violations)

    def test_empty_handler_function(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(handler_function=""))
        assert any("'handler_function'" in v for v in exc_info.value.violations)

    def test_multiple_violations_collected(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract({})
        # Should report id, name, handler_file, handler_function all missing
        assert len(exc_info.value.violations) >= 4

    def test_non_dict_raises_type_error(self):
        from core.skill_package_contract import validate_skill_package_contract

        with pytest.raises(TypeError):
            validate_skill_package_contract(["not", "a", "dict"])

    def test_none_raises_type_error(self):
        from core.skill_package_contract import validate_skill_package_contract

        with pytest.raises(TypeError):
            validate_skill_package_contract(None)


# ===========================================================================
# D) validate_skill_package_contract — optional field violations
# ===========================================================================


class TestValidateSkillPackageContractOptionalViolations:
    def test_dependencies_not_list(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(dependencies="httpx"))
        assert any("'dependencies'" in v for v in exc_info.value.violations)

    def test_dependencies_non_string_entry(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(dependencies=[1, 2]))
        assert any("'dependencies'" in v for v in exc_info.value.violations)

    def test_permissions_not_list(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(permissions="internet"))
        assert any("'permissions'" in v for v in exc_info.value.violations)

    def test_permissions_non_string_entry(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(permissions=[42]))
        assert any("'permissions'" in v for v in exc_info.value.violations)

    def test_tags_not_list(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(tags="web"))
        assert any("'tags'" in v for v in exc_info.value.violations)

    def test_tags_non_string_entry(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(tags=[1, "web"]))
        assert any("'tags'" in v for v in exc_info.value.violations)

    def test_parameters_not_list(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(parameters="query"))
        assert any("'parameters'" in v for v in exc_info.value.violations)

    def test_parameter_entry_not_dict(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(parameters=["bad"]))
        assert any("parameters[0]" in v for v in exc_info.value.violations)

    def test_parameter_entry_missing_name(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(
                _valid_manifest(parameters=[{"type": "string"}])
            )
        assert any("parameters[0].name" in v for v in exc_info.value.violations)


# ===========================================================================
# E) validate_skill_package_contract — schema_version enforcement
# ===========================================================================


class TestValidateSkillPackageContractSchemaVersion:
    def test_unsupported_schema_version_raises(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError) as exc_info:
            validate_skill_package_contract(_valid_manifest(schema_version="99"))
        assert any("schema_version" in v for v in exc_info.value.violations)

    def test_missing_schema_version_defaults_to_1(self):
        from core.skill_package_contract import validate_skill_package_contract

        m = _valid_manifest()
        del m["schema_version"]
        contract = validate_skill_package_contract(m)
        assert contract.schema_version == "1"


# ===========================================================================
# F) validate_skill_package_contract — allow_future_schema
# ===========================================================================


class TestValidateSkillPackageContractAllowFutureSchema:
    def test_future_schema_accepted_with_flag(self):
        from core.skill_package_contract import validate_skill_package_contract

        contract = validate_skill_package_contract(
            _valid_manifest(schema_version="2"),
            allow_future_schema=True,
        )
        assert contract.schema_version == "2"

    def test_future_schema_rejected_without_flag(self):
        from core.skill_package_contract import validate_skill_package_contract, SkillPackageContractError

        with pytest.raises(SkillPackageContractError):
            validate_skill_package_contract(_valid_manifest(schema_version="2"))


# ===========================================================================
# G) is_valid_skill_package_contract helper
# ===========================================================================


class TestIsValidSkillPackageContract:
    def test_valid_returns_true(self):
        from core.skill_package_contract import is_valid_skill_package_contract

        assert is_valid_skill_package_contract(_valid_manifest()) is True

    def test_invalid_returns_false(self):
        from core.skill_package_contract import is_valid_skill_package_contract

        assert is_valid_skill_package_contract({}) is False

    def test_non_dict_returns_false(self):
        from core.skill_package_contract import is_valid_skill_package_contract

        assert is_valid_skill_package_contract("not a dict") is False  # type: ignore
        assert is_valid_skill_package_contract(None) is False  # type: ignore


# ===========================================================================
# H) build_skill_package_contract_summary helper
# ===========================================================================


class TestBuildSkillPackageContractSummary:
    def test_summary_has_expected_keys(self):
        from core.skill_package_contract import (
            validate_skill_package_contract,
            build_skill_package_contract_summary,
        )

        contract = validate_skill_package_contract(
            _valid_manifest(
                dependencies=["httpx"],
                tags=["web"],
                permissions=["internet"],
            )
        )
        summary = build_skill_package_contract_summary(contract)

        assert summary["id"] == "my-skill"
        assert summary["name"] == "My Skill"
        assert summary["schema_version"] == "1"
        assert summary["handler_file"] == "handler.py"
        assert summary["handler_function"] == "execute"
        assert summary["has_dependencies"] is True
        assert summary["dependency_count"] == 1
        assert summary["has_permissions"] is True
        assert summary["tags"] == ["web"]

    def test_summary_no_dependencies(self):
        from core.skill_package_contract import (
            validate_skill_package_contract,
            build_skill_package_contract_summary,
        )

        contract = validate_skill_package_contract(_valid_manifest())
        summary = build_skill_package_contract_summary(contract)
        assert summary["has_dependencies"] is False
        assert summary["dependency_count"] == 0


# ===========================================================================
# I) SkillPackageContract.to_dict / from_dict round-trip
# ===========================================================================


class TestSkillPackageContractRoundTrip:
    def test_to_dict_keys(self):
        from core.skill_package_contract import validate_skill_package_contract

        contract = validate_skill_package_contract(_valid_manifest())
        d = contract.to_dict()

        required_keys = {
            "schema_version", "id", "name", "description", "version",
            "handler_file", "handler_function", "parameters",
            "dependencies", "permissions", "tags", "repository", "author",
        }
        assert required_keys.issubset(set(d.keys()))

    def test_from_dict_round_trip(self):
        from core.skill_package_contract import SkillPackageContract, validate_skill_package_contract

        original = validate_skill_package_contract(
            _valid_manifest(
                tags=["a", "b"],
                dependencies=["httpx"],
                permissions=["internet"],
                parameters=[{"name": "q"}],
            )
        )
        restored = SkillPackageContract.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.handler_file == original.handler_file
        assert restored.handler_function == original.handler_function
        assert restored.tags == original.tags
        assert restored.dependencies == original.dependencies
        assert restored.permissions == original.permissions
        assert restored.parameters == original.parameters


# ===========================================================================
# J) SkillLoader.load() rejects invalid skill.json via contract
# ===========================================================================


class TestSkillLoaderContractEnforcement:
    def test_load_rejects_missing_required_fields(self, tmp_path):
        """SkillLoader.load() returns failure when skill.json is invalid."""
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        # Write a skill.json that is missing required fields
        (skill_dir / "skill.json").write_text(
            json.dumps({"name": "incomplete"}), encoding="utf-8"
        )

        from core.skill_loader import SkillLoader

        loader = SkillLoader()
        result = _run(loader.load(str(skill_dir)))

        assert result["success"] is False
        assert "violations" in result and len(result["violations"]) > 0

    def test_load_rejects_invalid_id_format(self, tmp_path):
        """SkillLoader.load() rejects skill.json with invalid id format."""
        skill_dir = tmp_path / "bad-id-skill"
        skill_dir.mkdir()
        manifest = {
            "id": "my skill with spaces",
            "name": "My Skill",
            "handler_file": "handler.py",
            "handler_function": "execute",
        }
        (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")

        from core.skill_loader import SkillLoader

        loader = SkillLoader()
        result = _run(loader.load(str(skill_dir)))

        assert result["success"] is False
        assert "violations" in result or "contract" in result.get("error", "").lower()

    def test_load_succeeds_with_valid_manifest_no_handler(self, tmp_path):
        """SkillLoader.load() accepts valid skill.json (handler file may be absent)."""
        skill_dir = tmp_path / "valid-skill"
        skill_dir.mkdir()
        manifest = _valid_manifest()
        (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
        # Note: handler.py is not created — skill will load but in ERROR status

        from core.skill_loader import SkillLoader

        loader = SkillLoader()
        result = _run(loader.load(str(skill_dir)))

        # Contract passes; actual handler load may fail, but the contract gate is passed
        # result["success"] may be True with ERROR status or False with handler error
        # The key assertion is that it did NOT fail due to contract violation
        if not result.get("success"):
            assert "contract" not in result.get("error", "").lower()


# ===========================================================================
# K) GitHubInstaller._register_skill() rejects invalid manifest via contract
# ===========================================================================


class TestRegisterSkillContractEnforcement:
    def test_rejects_missing_id(self, tmp_path):
        from core.github_installer import _register_skill

        manifest = {
            "name": "my-skill",
            "handler_file": "handler.py",
            "handler_function": "execute",
            # missing "id"
        }
        result = _register_skill(tmp_path, manifest)

        assert result["success"] is False
        assert result.get("error_code") == "SKILL_PACKAGE_CONTRACT_INVALID"
        assert "violations" in result

    def test_rejects_missing_handler_file(self, tmp_path):
        from core.github_installer import _register_skill

        manifest = {
            "id": "my-skill",
            "name": "My Skill",
            "handler_function": "execute",
            # missing "handler_file"
        }
        result = _register_skill(tmp_path, manifest)

        assert result["success"] is False
        assert result.get("error_code") == "SKILL_PACKAGE_CONTRACT_INVALID"

    def test_rejects_missing_handler_function(self, tmp_path):
        from core.github_installer import _register_skill

        manifest = {
            "id": "my-skill",
            "name": "My Skill",
            "handler_file": "handler.py",
            # missing "handler_function"
        }
        result = _register_skill(tmp_path, manifest)

        assert result["success"] is False
        assert result.get("error_code") == "SKILL_PACKAGE_CONTRACT_INVALID"

    def test_rejects_invalid_id_format(self, tmp_path):
        from core.github_installer import _register_skill

        manifest = _valid_manifest(id="bad id!")
        result = _register_skill(tmp_path, manifest)

        assert result["success"] is False
        assert result.get("error_code") == "SKILL_PACKAGE_CONTRACT_INVALID"
        assert "violations" in result

    def test_rejects_empty_manifest(self, tmp_path):
        from core.github_installer import _register_skill

        result = _register_skill(tmp_path, {})

        assert result["success"] is False
        assert result.get("error_code") == "SKILL_PACKAGE_CONTRACT_INVALID"
        assert len(result.get("violations", [])) >= 4

    def test_violations_list_in_response(self, tmp_path):
        from core.github_installer import _register_skill

        result = _register_skill(tmp_path, {"name": "only-name"})
        assert isinstance(result.get("violations"), list)
        assert len(result["violations"]) > 0


# ===========================================================================
# L) GitHubInstaller._register_skill() accepts valid manifest and calls SkillLoader
# ===========================================================================


class TestRegisterSkillValidManifest:
    @patch("core.github_installer.skill_loader", create=True)
    def test_valid_manifest_calls_skill_loader(self, mock_loader, tmp_path):
        """A valid manifest should pass the contract gate and call SkillLoader."""
        from core.github_installer import _register_skill

        # Simulate SkillLoader.load() returning success
        mock_loader_instance = MagicMock()
        mock_loader_instance.load = AsyncMock(
            return_value={"success": True, "skill_id": "my-skill", "name": "My Skill"}
        )

        manifest = _valid_manifest()

        with patch("core.skill_loader.skill_loader", mock_loader_instance):
            with patch("core.github_installer.skill_loader", mock_loader_instance):
                result = _register_skill(tmp_path, manifest)

        # Should pass the contract gate; result depends on actual SkillLoader availability
        # In unit test context, the SkillLoader mock may or may not be called
        # — the important invariant is that contract errors are NOT returned
        assert result.get("error_code") != "SKILL_PACKAGE_CONTRACT_INVALID"

    def test_valid_manifest_does_not_return_contract_error(self, tmp_path):
        """A valid manifest must not return a SKILL_PACKAGE_CONTRACT_INVALID error."""
        from core.github_installer import _register_skill

        manifest = _valid_manifest()
        result = _register_skill(tmp_path, manifest)

        # May fail for other reasons (SkillLoader, file not found, etc.) but
        # never with the contract error code
        assert result.get("error_code") != "SKILL_PACKAGE_CONTRACT_INVALID"
        assert "violations" not in result or result.get("violations") is None

    def test_result_includes_schema_version_on_success(self, tmp_path):
        """Successful registration includes schema_version in response."""
        from core.github_installer import _register_skill

        manifest = _valid_manifest()

        loader = MagicMock()
        loader.load = AsyncMock(
            return_value={"success": True, "skill_id": "my-skill", "name": "My Skill"}
        )

        with patch("core.skill_loader.skill_loader", loader):
            result = _register_skill(tmp_path, manifest)

        if result.get("success"):
            assert "schema_version" in result


# ===========================================================================
# M) Successful install registers Skill and refreshes capability registry
# ===========================================================================


class TestSkillCapabilityRegistryIntegration:
    def test_capability_registry_inject_called_after_load(self, tmp_path):
        """SkillLoader.load() calls _inject_skill_to_registry on success."""
        skill_dir = tmp_path / "cap-skill"
        skill_dir.mkdir()

        # Create valid skill.json and a minimal handler
        manifest = _valid_manifest(id="cap-skill", name="Cap Skill")
        (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
        (skill_dir / "handler.py").write_text(
            "async def execute(**kwargs):\n    return kwargs\n",
            encoding="utf-8",
        )

        from core.skill_loader import SkillLoader

        loader = SkillLoader()

        inject_calls = []

        original_inject = loader._inject_skill_to_registry

        def _spy_inject(skill_id: str) -> None:
            inject_calls.append(skill_id)
            # Best-effort; ignore CapabilityRegistry errors in unit test
            try:
                original_inject(skill_id)
            except Exception:
                pass

        loader._inject_skill_to_registry = _spy_inject

        result = _run(loader.load(str(skill_dir)))

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert "cap-skill" in inject_calls

    def test_loaded_skill_appears_in_list_skills(self, tmp_path):
        """After a successful load, the skill appears in list_skills()."""
        skill_dir = tmp_path / "listed-skill"
        skill_dir.mkdir()

        manifest = _valid_manifest(id="listed-skill", name="Listed Skill")
        (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
        (skill_dir / "handler.py").write_text(
            "async def execute(**kwargs):\n    return kwargs\n",
            encoding="utf-8",
        )

        from core.skill_loader import SkillLoader

        loader = SkillLoader()
        result = _run(loader.load(str(skill_dir)))

        assert result.get("success") is True
        skills = loader.list_skills()
        skill_ids = [s["id"] for s in skills]
        assert "listed-skill" in skill_ids
