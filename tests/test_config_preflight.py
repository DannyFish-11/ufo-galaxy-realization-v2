"""
tests/test_config_preflight.py — PR-G3 Config Governance
==========================================================

Unit and functional tests for ``core/config_preflight.py`` and the
``GALAXY_SECRET_BACKEND`` extension in ``core/credential_vault.py``.

Test groups
-----------
1.  EnvCheck / _is_set                — placeholder detection, empty values.
2.  run_preflight — all present       — report.ok True, no criticals.
3.  run_preflight — CRITICAL missing  — fail_fast raises ConfigPreflightError.
4.  run_preflight — dry_run           — never raises even with criticals.
5.  run_preflight — WARNING missing   — report.ok True (only criticals block).
6.  run_preflight — mode filtering    — only relevant group checks run.
7.  PreflightReport.format()          — contains CRITICAL var name and hint.
8.  require_env                       — raises on missing/placeholder.
9.  require_env                       — returns value when set.
10. CLI exit codes                    — sys.exit(0) ok, sys.exit(1) critical.
11. CredentialVault — default backend — backend_name == "env".
12. CredentialVault — vault backend   — backend_name == "vault", get/set routed.
13. CredentialVault — kms backend     — falls back to env, logs warning.
14. _SecretVaultBackend.health        — returns False when unreachable.
15. migrate_env_to_vault dry_run      — records True without writing.
16. migrate_env_to_vault live         — stores credential in vault.
17. migrate_env_to_vault skips placeholders.
18. reset_vault                       — clears singleton.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_checks(severity="CRITICAL", var="TEST_VAR", groups=None):
    """Build a minimal single-check list for isolation."""
    from core.config_preflight import EnvCheck, Severity
    return [
        EnvCheck(
            var=var,
            severity=getattr(Severity, severity),
            description="Test variable",
            hint="Set TEST_VAR=something",
            groups=groups or ["all"],
        )
    ]


# ===========================================================================
# 1. _is_set — placeholder detection
# ===========================================================================

class TestIsSet(unittest.TestCase):
    def _call(self, var, value, allow_placeholder=True):
        from core.config_preflight import _is_set
        with patch.dict(os.environ, {var: value}, clear=False):
            return _is_set(var, allow_placeholder)

    def test_empty_string(self):
        present, _ = self._call("_T", "")
        self.assertFalse(present)

    def test_unset(self):
        from core.config_preflight import _is_set
        os.environ.pop("__GALAXY_TEST_UNSET__", None)
        present, _ = _is_set("__GALAXY_TEST_UNSET__")
        self.assertFalse(present)

    def test_real_value(self):
        present, hint = self._call("_T", "sk-real-key")
        self.assertTrue(present)
        self.assertEqual(hint, "(set)")

    def test_placeholder_your_(self):
        present, hint = self._call("_T", "your_api_key_here")
        self.assertFalse(present)
        self.assertIn("placeholder", hint)

    def test_placeholder_your_dash(self):
        present, _ = self._call("_T", "your-secret")
        self.assertFalse(present)

    def test_placeholder_allowed_false(self):
        # When allow_placeholder=False, placeholder is treated as present
        present, _ = self._call("_T", "your_api_key_here", allow_placeholder=False)
        self.assertTrue(present)


# ===========================================================================
# 2. run_preflight — all checks present
# ===========================================================================

class TestRunPreflightAllPresent(unittest.TestCase):
    def test_ok_when_all_set(self):
        from core.config_preflight import run_preflight
        checks = _fresh_checks(severity="CRITICAL", var="__GALAXY_PREF_VAR__")
        with patch.dict(os.environ, {"__GALAXY_PREF_VAR__": "real-value"}, clear=False):
            report = run_preflight(dry_run=True, checks=checks, mode="all", verbose=False)
        self.assertTrue(report.ok)
        self.assertEqual(len(report.criticals), 0)
        self.assertEqual(len(report.passed), 1)


# ===========================================================================
# 3. run_preflight — CRITICAL missing, fail_fast raises
# ===========================================================================

class TestRunPreflightCriticalMissing(unittest.TestCase):
    def test_raises_when_critical_missing(self):
        from core.config_preflight import run_preflight, ConfigPreflightError
        checks = _fresh_checks(severity="CRITICAL", var="__GALAXY_PREF_MISSING__")
        os.environ.pop("__GALAXY_PREF_MISSING__", None)
        with self.assertRaises(ConfigPreflightError) as ctx:
            run_preflight(dry_run=False, fail_fast=True, checks=checks, mode="all", verbose=False)
        self.assertIn("__GALAXY_PREF_MISSING__", str(ctx.exception))

    def test_report_contains_critical_finding(self):
        from core.config_preflight import run_preflight, ConfigPreflightError
        checks = _fresh_checks(severity="CRITICAL", var="__GALAXY_PREF_MISSING__")
        os.environ.pop("__GALAXY_PREF_MISSING__", None)
        try:
            run_preflight(dry_run=False, fail_fast=True, checks=checks, mode="all", verbose=False)
        except ConfigPreflightError as exc:
            self.assertEqual(len(exc.report.criticals), 1)
            self.assertEqual(exc.report.criticals[0].check.var, "__GALAXY_PREF_MISSING__")


# ===========================================================================
# 4. run_preflight — dry_run never raises
# ===========================================================================

class TestRunPreflightDryRun(unittest.TestCase):
    def test_dry_run_no_raise(self):
        from core.config_preflight import run_preflight
        checks = _fresh_checks(severity="CRITICAL", var="__GALAXY_PREF_DRY__")
        os.environ.pop("__GALAXY_PREF_DRY__", None)
        # Should NOT raise
        report = run_preflight(dry_run=True, fail_fast=True, checks=checks, mode="all", verbose=False)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.criticals), 1)


# ===========================================================================
# 5. run_preflight — WARNING missing does NOT block
# ===========================================================================

class TestRunPreflightWarningMissing(unittest.TestCase):
    def test_warning_missing_still_ok(self):
        from core.config_preflight import run_preflight
        checks = _fresh_checks(severity="WARNING", var="__GALAXY_PREF_WARN__")
        os.environ.pop("__GALAXY_PREF_WARN__", None)
        report = run_preflight(dry_run=False, fail_fast=True, checks=checks, mode="all", verbose=False)
        self.assertTrue(report.ok)
        self.assertEqual(len(report.warnings), 1)
        self.assertEqual(len(report.criticals), 0)


# ===========================================================================
# 6. run_preflight — mode filtering
# ===========================================================================

class TestRunPreflightModeFiltering(unittest.TestCase):
    def test_gateway_group_not_run_in_core_mode(self):
        from core.config_preflight import run_preflight, EnvCheck, Severity
        gateway_check = EnvCheck(
            var="__GALAXY_GATEWAY_ONLY__",
            severity=Severity.CRITICAL,
            description="Gateway only",
            hint="set it",
            groups=["gateway"],
        )
        os.environ.pop("__GALAXY_GATEWAY_ONLY__", None)
        # mode=core: gateway checks should NOT run → no findings at all
        report = run_preflight(
            dry_run=True,
            checks=[gateway_check],
            mode="core",
            verbose=False,
        )
        self.assertEqual(len(report.findings), 0)

    def test_all_mode_includes_gateway(self):
        from core.config_preflight import run_preflight, EnvCheck, Severity
        gateway_check = EnvCheck(
            var="__GALAXY_GATEWAY_ONLY_ALL__",
            severity=Severity.CRITICAL,
            description="Gateway only",
            hint="set it",
            groups=["gateway"],
        )
        os.environ.pop("__GALAXY_GATEWAY_ONLY_ALL__", None)
        report = run_preflight(
            dry_run=True,
            checks=[gateway_check],
            mode="all",
            verbose=False,
        )
        self.assertEqual(len(report.findings), 1)


# ===========================================================================
# 7. PreflightReport.format()
# ===========================================================================

class TestPreflightReportFormat(unittest.TestCase):
    def test_format_contains_var_and_hint(self):
        from core.config_preflight import run_preflight
        checks = _fresh_checks(severity="CRITICAL", var="__GALAXY_FORMAT_VAR__")
        checks[0] = checks[0].__class__(
            var="__GALAXY_FORMAT_VAR__",
            severity=checks[0].severity,
            description="Test description",
            hint="Run export __GALAXY_FORMAT_VAR__=value",
            groups=["all"],
        )
        os.environ.pop("__GALAXY_FORMAT_VAR__", None)
        report = run_preflight(dry_run=True, checks=checks, mode="all", verbose=True)
        text = report.format(verbose=True)
        self.assertIn("__GALAXY_FORMAT_VAR__", text)
        self.assertIn("Run export", text)

    def test_format_ok_message_when_all_pass(self):
        from core.config_preflight import run_preflight
        checks = _fresh_checks(severity="CRITICAL", var="__GALAXY_FORMAT_OK__")
        with patch.dict(os.environ, {"__GALAXY_FORMAT_OK__": "real-value"}, clear=False):
            report = run_preflight(dry_run=True, checks=checks, mode="all", verbose=False)
        text = report.format(verbose=False)
        self.assertIn("✅", text)


# ===========================================================================
# 8–9. require_env
# ===========================================================================

class TestRequireEnv(unittest.TestCase):
    def test_raises_on_missing(self):
        from core.config_preflight import require_env
        os.environ.pop("__REQ_MISSING__", None)
        with self.assertRaises(RuntimeError) as ctx:
            require_env("__REQ_MISSING__")
        self.assertIn("__REQ_MISSING__", str(ctx.exception))

    def test_raises_on_placeholder(self):
        from core.config_preflight import require_env
        with patch.dict(os.environ, {"__REQ_PH__": "your_key_here"}, clear=False):
            with self.assertRaises(RuntimeError):
                require_env("__REQ_PH__")

    def test_hint_in_error(self):
        from core.config_preflight import require_env
        os.environ.pop("__REQ_HINT__", None)
        with self.assertRaises(RuntimeError) as ctx:
            require_env("__REQ_HINT__", hint="generate with openssl")
        self.assertIn("generate with openssl", str(ctx.exception))

    def test_returns_value_when_set(self):
        from core.config_preflight import require_env
        with patch.dict(os.environ, {"__REQ_OK__": "real-value"}, clear=False):
            self.assertEqual(require_env("__REQ_OK__"), "real-value")


# ===========================================================================
# 10. CLI exit codes
# ===========================================================================

class TestCliExitCodes(unittest.TestCase):
    def _run_cli(self, env_overrides, extra_args=None):
        """Run _main() and capture SystemExit code."""
        from core.config_preflight import _main
        args = ["prog", "--mode", "all"] + (extra_args or [])
        with patch.object(sys, "argv", args):
            with patch.dict(os.environ, env_overrides, clear=False):
                try:
                    _main()
                    return 0
                except SystemExit as exc:
                    return exc.code

    def test_exit_0_when_all_critical_set(self):
        # Patch _CHECKS with only checks whose vars we can control
        from core import config_preflight
        original = config_preflight._CHECKS
        try:
            config_preflight._CHECKS = _fresh_checks(
                severity="CRITICAL", var="__CLI_OK__"
            )
            code = self._run_cli({"__CLI_OK__": "real-value"})
            self.assertEqual(code, 0)
        finally:
            config_preflight._CHECKS = original

    def test_exit_1_when_critical_missing(self):
        from core import config_preflight
        original = config_preflight._CHECKS
        try:
            config_preflight._CHECKS = _fresh_checks(
                severity="CRITICAL", var="__CLI_MISS__"
            )
            env = dict(os.environ)
            env.pop("__CLI_MISS__", None)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("__CLI_MISS__", None)
                code = self._run_cli({})
            self.assertEqual(code, 1)
        finally:
            config_preflight._CHECKS = original

    def test_dry_run_exit_0_even_on_critical(self):
        from core import config_preflight
        original = config_preflight._CHECKS
        try:
            config_preflight._CHECKS = _fresh_checks(
                severity="CRITICAL", var="__CLI_DRY__"
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("__CLI_DRY__", None)
                code = self._run_cli({}, extra_args=["--dry-run"])
            self.assertEqual(code, 0)
        finally:
            config_preflight._CHECKS = original


# ===========================================================================
# 11. CredentialVault — default backend is "env"
# ===========================================================================

class TestCredentialVaultDefaultBackend(unittest.TestCase):
    def setUp(self):
        from core.credential_vault import reset_vault
        reset_vault()

    def tearDown(self):
        from core.credential_vault import reset_vault
        reset_vault()
        os.environ.pop("GALAXY_SECRET_BACKEND", None)

    def test_default_backend_name_is_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GALAXY_SECRET_BACKEND", None)
            from core.credential_vault import get_vault
            vault = get_vault()
            self.assertEqual(vault.backend_name, "env")

    def test_get_credential_reads_env(self):
        from core.credential_vault import get_vault
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-123"}, clear=False):
            vault = get_vault()
            result = vault.get_credential("openai")
            self.assertEqual(result, "sk-test-123")

    def test_set_then_get_in_memory(self):
        from core.credential_vault import get_vault
        vault = get_vault()
        vault.set_credential("test_key", "test_value")
        self.assertEqual(vault.get_credential("test_key"), "test_value")


# ===========================================================================
# 12. CredentialVault — vault backend routes get/set to _SecretVaultBackend
# ===========================================================================

class TestCredentialVaultVaultBackend(unittest.TestCase):
    def setUp(self):
        from core.credential_vault import reset_vault
        reset_vault()

    def tearDown(self):
        from core.credential_vault import reset_vault
        reset_vault()
        os.environ.pop("GALAXY_SECRET_BACKEND", None)

    def _make_vault_with_mock_backend(self):
        from core.credential_vault import CredentialVault, _SecretVaultBackend
        mock_backend = MagicMock(spec=_SecretVaultBackend)
        mock_backend.get.return_value = None
        mock_backend.set.return_value = True
        vault = CredentialVault(backend=mock_backend)
        return vault, mock_backend

    def test_backend_name_is_vault(self):
        vault, _ = self._make_vault_with_mock_backend()
        self.assertEqual(vault.backend_name, "vault")

    def test_set_credential_calls_backend(self):
        vault, mock_backend = self._make_vault_with_mock_backend()
        vault.set_credential("openai", "sk-from-vault")
        mock_backend.set.assert_called_once_with("openai", "sk-from-vault")

    def test_get_credential_falls_back_to_backend(self):
        vault, mock_backend = self._make_vault_with_mock_backend()
        mock_backend.get.return_value = "sk-vault-value"
        result = vault.get_credential("openai")
        self.assertEqual(result, "sk-vault-value")
        mock_backend.get.assert_called_once_with("openai")

    def test_get_credential_cached_after_backend_fetch(self):
        vault, mock_backend = self._make_vault_with_mock_backend()
        mock_backend.get.return_value = "sk-cached"
        vault.get_credential("openai")
        vault.get_credential("openai")  # second call should use cache
        # Backend should only be called once
        self.assertEqual(mock_backend.get.call_count, 1)

    def test_memory_takes_priority_over_backend(self):
        vault, mock_backend = self._make_vault_with_mock_backend()
        vault._credentials["openai"] = "sk-in-memory"
        result = vault.get_credential("openai")
        self.assertEqual(result, "sk-in-memory")
        mock_backend.get.assert_not_called()

    def test_backend_failure_falls_back_to_env(self):
        from core.credential_vault import CredentialVault, _SecretVaultBackend
        mock_backend = MagicMock(spec=_SecretVaultBackend)
        mock_backend.get.return_value = None  # backend unavailable
        mock_backend.set.return_value = False
        vault = CredentialVault(backend=mock_backend)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-fallback"}, clear=False):
            result = vault.get_credential("openai")
        self.assertEqual(result, "sk-env-fallback")

    def test_set_logs_warning_on_backend_failure(self):
        from core.credential_vault import CredentialVault, _SecretVaultBackend
        mock_backend = MagicMock(spec=_SecretVaultBackend)
        mock_backend.set.return_value = False
        vault = CredentialVault(backend=mock_backend)
        import logging
        with self.assertLogs("Galaxy.CredentialVault", level=logging.WARNING):
            vault.set_credential("some_key", "some_value")


# ===========================================================================
# 13. CredentialVault — kms backend falls back to env
# ===========================================================================

class TestCredentialVaultKmsBackend(unittest.TestCase):
    def setUp(self):
        from core.credential_vault import reset_vault
        reset_vault()

    def tearDown(self):
        from core.credential_vault import reset_vault
        reset_vault()
        os.environ.pop("GALAXY_SECRET_BACKEND", None)

    def test_kms_falls_back_to_env_with_warning(self):
        import logging
        from core import credential_vault
        with patch.dict(os.environ, {"GALAXY_SECRET_BACKEND": "kms"}, clear=False):
            with self.assertLogs("Galaxy.CredentialVault", level=logging.WARNING):
                backend = credential_vault._build_backend()
        self.assertIsNone(backend)

    def test_kms_vault_backend_name_is_kms(self):
        from core.credential_vault import CredentialVault
        vault = CredentialVault(backend=None)
        with patch.dict(os.environ, {"GALAXY_SECRET_BACKEND": "kms"}, clear=False):
            # When there's no backend instance but env says kms, report kms
            self.assertEqual(vault.backend_name, "kms")

    def test_kms_falls_back_to_env_for_get_credential(self):
        """When KMS backend is selected (but not implemented), credentials come from ENV."""
        from core.credential_vault import CredentialVault
        # KMS backend returns None from _build_backend, so vault has no backend
        vault = CredentialVault(backend=None)
        with patch.dict(os.environ, {
            "GALAXY_SECRET_BACKEND": "kms",
            "OPENAI_API_KEY": "sk-kms-fallback",
        }, clear=False):
            result = vault.get_credential("openai")
        self.assertEqual(result, "sk-kms-fallback")


# ===========================================================================
# 14. _SecretVaultBackend.health — returns False when unreachable
# ===========================================================================

class TestSecretVaultBackendHealth(unittest.TestCase):
    def test_health_false_when_unreachable(self):
        from core.credential_vault import _SecretVaultBackend
        backend = _SecretVaultBackend(base_url="http://127.0.0.1:19999")
        self.assertFalse(backend.health())

    def test_get_none_when_unreachable(self):
        from core.credential_vault import _SecretVaultBackend
        backend = _SecretVaultBackend(base_url="http://127.0.0.1:19999")
        self.assertIsNone(backend.get("some_key"))

    def test_set_false_when_unreachable(self):
        from core.credential_vault import _SecretVaultBackend
        backend = _SecretVaultBackend(base_url="http://127.0.0.1:19999")
        self.assertFalse(backend.set("some_key", "some_value"))


# ===========================================================================
# 15–17. migrate_env_to_vault
# ===========================================================================

class TestMigrateEnvToVault(unittest.TestCase):
    def setUp(self):
        from core.credential_vault import reset_vault
        reset_vault()

    def tearDown(self):
        from core.credential_vault import reset_vault
        reset_vault()
        os.environ.pop("GALAXY_SECRET_BACKEND", None)

    def test_dry_run_returns_true_without_writing(self):
        from core.credential_vault import migrate_env_to_vault, get_vault
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real"}, clear=False):
            results = migrate_env_to_vault(dry_run=True)
        vault = get_vault()
        # In dry_run mode credentials should NOT be in vault memory
        self.assertNotIn("openai", vault._credentials)
        self.assertTrue(results.get("openai", False))

    def test_live_migration_stores_credential(self):
        from core.credential_vault import migrate_env_to_vault, get_vault
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-migrate"}, clear=False):
            results = migrate_env_to_vault(dry_run=False)
        vault = get_vault()
        self.assertEqual(vault._credentials.get("openai"), "sk-real-migrate")
        self.assertTrue(results.get("openai", False))

    def test_skips_placeholder_values(self):
        from core.credential_vault import migrate_env_to_vault
        with patch.dict(os.environ, {"OPENAI_API_KEY": "your_openai_api_key_here"}, clear=False):
            results = migrate_env_to_vault(dry_run=False)
        self.assertFalse(results.get("openai", True))

    def test_skips_empty_values(self):
        from core.credential_vault import migrate_env_to_vault
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            results = migrate_env_to_vault(dry_run=False)
        self.assertFalse(results.get("openai", True))


# ===========================================================================
# 18. reset_vault — clears singleton
# ===========================================================================

class TestResetVault(unittest.TestCase):
    def test_reset_clears_singleton(self):
        from core import credential_vault
        v1 = credential_vault.get_vault()
        credential_vault.reset_vault()
        v2 = credential_vault.get_vault()
        self.assertIsNot(v1, v2)

    def test_reset_allows_new_backend_selection(self):
        from core import credential_vault
        # First create with env backend
        v1 = credential_vault.get_vault()
        self.assertEqual(v1.backend_name, "env")
        credential_vault.reset_vault()
        # Inject a mock backend directly to test vault backend selection
        mock_backend = MagicMock(spec=credential_vault._SecretVaultBackend)
        with patch.object(credential_vault, "_build_backend", return_value=mock_backend):
            with patch.dict(os.environ, {"GALAXY_SECRET_BACKEND": "vault"}, clear=False):
                v2 = credential_vault.get_vault()
                self.assertEqual(v2.backend_name, "vault")
                self.assertIs(v2._backend, mock_backend)
        credential_vault.reset_vault()
        os.environ.pop("GALAXY_SECRET_BACKEND", None)


if __name__ == "__main__":
    unittest.main()
