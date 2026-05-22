"""
core/config_preflight.py — Galaxy Pre-flight Configuration Check  (PR-G3)
==========================================================================

Validates that all **critical** environment variables are present before the
Galaxy runtime starts.  When a required variable is absent the checker emits
an actionable hint and, in *fail_fast* mode, raises ``ConfigPreflightError``
so the process exits with a non-zero status instead of crashing later with a
less descriptive error.

Public API
----------
run_preflight(dry_run=False, fail_fast=True, mode="auto") -> PreflightReport
    Run all configured checks and return a report.  When *fail_fast* is True
    and at least one CRITICAL finding is present, raises ConfigPreflightError
    after printing the report.

    *mode* selects which check groups to run:
      "auto"        — infer from environment (gateway/android/ws/core/all)
      "gateway"     — galaxy_gateway process
      "android"     — Android-client-facing WS bridge
      "ws"          — WebSocket / signaling config
      "core"        — core runtime (LLM keys, auth)
      "all"         — every group

ConfigPreflightError
    Raised on critical failure when fail_fast=True.

Local configuration authority integration  (PR-3)
-------------------------------------------------
Preflight automatically loads ``runtime/secrets.env`` into the process
environment (without overwriting already-set env vars) before running checks.
This means secrets configured via the local unified authority are visible to
the preflight check exactly as if they had been exported in the shell.

The canonical local persistence targets are:
  - ``runtime/config.json``  — non-secret system configuration
  - ``runtime/secrets.env``  — secret values (API keys, tokens)

Environment variables that influence this module
------------------------------------------------
GALAXY_PREFLIGHT_MODE      Override the mode when running as __main__.
GALAXY_PREFLIGHT_FAIL_FAST Set to "0"/"false" to disable fail-fast.
GALAXY_SECRET_BACKEND      "env" (default) | "vault" | "kms" — selects the
                            credentials back-end used by CredentialVault.
"""

from __future__ import annotations

import os
import sys
import textwrap
import logging
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.ConfigPreflight")


# ---------------------------------------------------------------------------
# Local configuration authority loader  (PR-3)
# ---------------------------------------------------------------------------

def _load_runtime_secrets_into_env() -> List[str]:
    """
    Load ``runtime/secrets.env`` into ``os.environ`` (without overwriting).

    Returns the list of key names that were loaded from the file so that the
    preflight report can indicate their source.

    This function is called once at the start of ``run_preflight``.  It is
    idempotent and never raises — errors are logged/printed but do not block
    startup.
    """
    _secrets_path = Path(__file__).parent.parent / "runtime" / "secrets.env"
    loaded: List[str] = []
    if not _secrets_path.exists():
        return loaded
    try:
        with open(_secrets_path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                if key and val and key not in os.environ:
                    os.environ[key] = val
                    loaded.append(key)
    except OSError:
        pass  # non-fatal; the env-check below will report missing vars
    return loaded


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # Must be set; startup should be blocked
    WARNING  = "WARNING"    # Strongly recommended; feature will be degraded
    INFO     = "INFO"       # Informational; defaults exist


# ---------------------------------------------------------------------------
# Check descriptor
# ---------------------------------------------------------------------------

@dataclass
class EnvCheck:
    """Describes a single environment-variable requirement."""
    var: str
    severity: Severity
    description: str
    hint: str
    groups: List[str]             # which preflight groups this belongs to
    allow_placeholder: bool = True  # treat "your_*_here" as missing


# ---------------------------------------------------------------------------
# Registry of checks
# ---------------------------------------------------------------------------
#
# Groups:
#   core     — LLM keys, auth, token — needed by the main Galaxy server
#   gateway  — galaxy_gateway process
#   android  — Android WS / device bridge
#   ws       — WebSocket / WebRTC / signaling
#   vault    — Secret-vault back-end

_CHECKS: List[EnvCheck] = [
    # ── Core: LLM (at least one required; all WARNING) ───────────────────
    EnvCheck(
        var="OPENAI_API_KEY",
        severity=Severity.WARNING,
        description="OpenAI API key for LLM inference.",
        hint=(
            "Set OPENAI_API_KEY in .env or export it in the shell.\n"
            "  Example: OPENAI_API_KEY=sk-...\n"
            "  At least one LLM provider key is required to run agents."
        ),
        groups=["core", "all"],
    ),
    EnvCheck(
        var="ANTHROPIC_API_KEY",
        severity=Severity.WARNING,
        description="Anthropic Claude API key (optional if OpenAI is set).",
        hint=(
            "Set ANTHROPIC_API_KEY=sk-ant-... in .env if you want to use Claude.\n"
            "  Required when GALAXY_LLM_PROVIDER=anthropic."
        ),
        groups=["core", "all"],
    ),
    # ── Core: auth / security ────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_API_TOKEN",
        severity=Severity.CRITICAL,
        description="Bearer token used to authenticate REST + WebSocket endpoints.",
        hint=(
            "Generate a random token and set it in .env:\n"
            "  GALAXY_API_TOKEN=$(python3 -c \"import secrets; print(secrets.token_urlsafe(32))\")\n"
            "  Also set GALAXY_AUTH_ENABLED=true to enforce it.\n"
            "  Or set GALAXY_REQUIRE_API_TOKEN=true to treat a missing token as CRITICAL "
            "even when Bearer auth is disabled (staging hardening).\n"
            "  Without this token any client can send commands to the API when auth is off."
        ),
        groups=["core", "gateway", "all"],
    ),
    # ── Core: secret back-end ────────────────────────────────────────────
    EnvCheck(
        var="SECRETVAULT_MASTER_KEY",
        severity=Severity.WARNING,
        description="Master encryption key for Node_03 SecretVault.",
        hint=(
            "Generate and set SECRETVAULT_MASTER_KEY in .env:\n"
            "  SECRETVAULT_MASTER_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')\n"
            "  Required when GALAXY_SECRET_BACKEND=vault."
        ),
        groups=["vault", "all"],
    ),
    # ── Gateway ──────────────────────────────────────────────────────────
    # ── System mode / fabric baseline (canonical config contract) ────────
    EnvCheck(
        var="GALAXY_SYSTEM_MODE",
        severity=Severity.INFO,
        description="System startup/fabric mode (default: desktop-local).",
        hint=(
            "Set GALAXY_SYSTEM_MODE=desktop-local for first-start / single-machine use.\n"
            "  Set to desktop-cross-device when the cross-device fabric should be active.\n"
            "  See docs/SYSTEM_MODE_CONFIG.md for details."
        ),
        groups=["core", "gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_NATS_ENABLED",
        severity=Severity.INFO,
        description="Enable the NATS bus (default: derived from GALAXY_SYSTEM_MODE).",
        hint=(
            "Set GALAXY_NATS_ENABLED=true to activate NATS regardless of mode.\n"
            "  Defaults to false in desktop-local mode, true in desktop-cross-device mode."
        ),
        groups=["gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_FABRIC_STRICT",
        severity=Severity.INFO,
        description="Treat missing fabric dependencies as hard startup failures (default: false).",
        hint=(
            "Set GALAXY_FABRIC_STRICT=true only in desktop-cross-device mode when NATS\n"
            "  must be available for the system to function.  Leave false (default) for\n"
            "  graceful degradation."
        ),
        groups=["gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_NETWORK_MODE",
        severity=Severity.INFO,
        description="Network topology mode: local | lan | tailscale | relay (default: local).",
        hint=(
            "Set GALAXY_NETWORK_MODE=lan for LAN-only deployments.\n"
            "  Set to tailscale when Tailscale is the primary network fabric.\n"
            "  Set to relay when using a public relay server."
        ),
        groups=["gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_CROSS_DEVICE_ENABLED",
        severity=Severity.INFO,
        description="Enable/disable cross-device routing (default: derived from GALAXY_SYSTEM_MODE).",
        hint=(
            "Set GALAXY_CROSS_DEVICE_ENABLED=true to enable cross-device routing.\n"
            "  Set to false to disable (safe default for single-device deployments).\n"
            "  When GALAXY_SYSTEM_MODE is set, this value is derived automatically."
        ),
        groups=["gateway", "all"],
    ),
    # ── WebSocket / signaling ────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_SIGNALING_TIMEOUT_S",
        severity=Severity.INFO,
        description="WebRTC signaling timeout in seconds (default: 30).",
        hint=(
            "Set GALAXY_SIGNALING_TIMEOUT_S=30 (or another positive integer).\n"
            "  Increase to 60 on high-latency networks."
        ),
        groups=["ws", "all"],
    ),
    # ── Android bridge ───────────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_AUTH_ENABLED",
        severity=Severity.WARNING,
        description="Enforce Bearer-token auth on all endpoints (default: false).",
        hint=(
            "Set GALAXY_AUTH_ENABLED=true in production.\n"
            "  Requires GALAXY_API_TOKEN to also be set.\n"
            "  Without this, Android clients can connect without authentication."
        ),
        groups=["android", "gateway", "all"],
    ),
    # ── TLS ─────────────────────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_TLS_CERT",
        severity=Severity.INFO,
        description="Path to TLS certificate file (enables HTTPS when set with GALAXY_TLS_KEY).",
        hint=(
            "Set GALAXY_TLS_CERT=/path/to/cert.pem and GALAXY_TLS_KEY=/path/to/key.pem\n"
            "  to enable HTTPS.  Leave blank for plain HTTP (development only)."
        ),
        groups=["gateway", "ws", "all"],
    ),
    # ── NATS (optional) ──────────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_NATS_URL",
        severity=Severity.INFO,
        description="NATS control-plane URL (default: nats://localhost:4222).",
        hint=(
            "Set GALAXY_NATS_URL=nats://localhost:4222 if using the NATS control plane.\n"
            "  Leave unset to disable NATS (all NATS paths become no-ops)."
        ),
        groups=["gateway", "all"],
    ),
    # ── Runtime bridge (optional) ────────────────────────────────────────
    EnvCheck(
        var="GALAXY_RUNTIME_URL",
        severity=Severity.INFO,
        description="URL of the Galaxy Agent Runtime (for AgentBridge).",
        hint=(
            "Set GALAXY_RUNTIME_URL=http://localhost:8200 if running the agent runtime.\n"
            "  Leave unset to disable the agent bridge (GALAXY_RUNTIME_ENABLED=0)."
        ),
        groups=["gateway", "all"],
    ),
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    check: EnvCheck
    present: bool
    value_hint: str = ""   # safe summary of the value (never the actual secret)


@dataclass
class PreflightReport:
    findings: List[Finding] = field(default_factory=list)
    mode: str = "all"

    # ── helpers ──────────────────────────────────────────────────────────

    @property
    def criticals(self) -> List[Finding]:
        return [f for f in self.findings
                if not f.present and f.check.severity == Severity.CRITICAL]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings
                if not f.present and f.check.severity == Severity.WARNING]

    @property
    def passed(self) -> List[Finding]:
        return [f for f in self.findings if f.present]

    @property
    def ok(self) -> bool:
        """True only when there are no CRITICAL findings."""
        return len(self.criticals) == 0

    # ── display ──────────────────────────────────────────────────────────

    def format(self, verbose: bool = True) -> str:
        lines: List[str] = [
            "",
            "╔══════════════════════════════════════════════════════════╗",
            "║         Galaxy Pre-flight Configuration Check           ║",
            "╚══════════════════════════════════════════════════════════╝",
            f"  Mode  : {self.mode}",
            f"  Checks: {len(self.findings)}  "
            f"passed={len(self.passed)}  "
            f"warnings={len(self.warnings)}  "
            f"criticals={len(self.criticals)}",
            "",
        ]

        if self.criticals:
            lines.append("  ❌  CRITICAL — startup blocked")
            lines.append("  " + "─" * 56)
            for f in self.criticals:
                lines.append(f"  • {f.check.var}")
                lines.append(f"    {f.check.description}")
                for hint_line in f.check.hint.splitlines():
                    lines.append(f"    💡 {hint_line}")
                lines.append("")

        if self.warnings and verbose:
            lines.append("  ⚠️   WARNING — degraded functionality")
            lines.append("  " + "─" * 56)
            for f in self.warnings:
                lines.append(f"  • {f.check.var}")
                lines.append(f"    {f.check.description}")
                for hint_line in f.check.hint.splitlines():
                    lines.append(f"    💡 {hint_line}")
                lines.append("")

        if self.ok:
            lines.append("  ✅  All CRITICAL checks passed.")

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class ConfigPreflightError(RuntimeError):
    """Raised when CRITICAL env vars are missing and fail_fast=True."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        missing = ", ".join(f.check.var for f in report.criticals)
        super().__init__(
            f"Pre-flight check failed — missing critical env vars: {missing}\n"
            f"Run 'python -m core.config_preflight' or set the variables and retry."
        )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

_FALSY = {"0", "false", "no", "off", "none", ""}
# Import placeholder prefixes from credential_vault to share the single source of truth.
# Fall back to a local copy if the import fails (e.g. during isolated testing).
try:
    from core.credential_vault import PLACEHOLDER_PREFIXES as _PLACEHOLDER_PREFIXES
except Exception:  # pragma: no cover
    _PLACEHOLDER_PREFIXES = ("your_", "your-", "change_me", "todo", "<", "example", "xxx")


def _is_set(var: str, allow_placeholder: bool = True) -> tuple[bool, str]:
    """Return (is_set, value_hint) for an env var."""
    raw = os.environ.get(var, "")
    if not raw:
        return False, ""
    if allow_placeholder and raw.lower().startswith(_PLACEHOLDER_PREFIXES):
        return False, f"(looks like a placeholder: {raw[:20]}…)"
    return True, "(set)"


def _groups_for_mode(mode: str) -> List[str]:
    """Resolve the list of group names for a given mode string."""
    if mode == "all":
        return ["all", "core", "gateway", "android", "ws", "vault"]
    if mode == "auto":
        # Infer from process/env context
        groups = set(["core"])
        if os.environ.get("GALAXY_GATEWAY_MODE") or os.environ.get("GALAXY_TLS_CERT"):
            groups.add("gateway")
        if os.environ.get("GALAXY_ANDROID_WS_ENABLED") or os.environ.get("GALAXY_AUTH_ENABLED"):
            groups.add("android")
        if os.environ.get("GALAXY_SIGNALING_TIMEOUT_S") or os.environ.get("GALAXY_TURN_URLS"):
            groups.add("ws")
        if os.environ.get("GALAXY_SECRET_BACKEND", "env").lower() in ("vault", "kms"):
            groups.add("vault")
        return list(groups)
    return [mode, "core"]


def _api_token_missing_is_critical() -> bool:
    """CRITICAL only when Bearer auth is enforced or explicitly required."""
    auth = os.environ.get("GALAXY_AUTH_ENABLED", "").lower() in ("true", "1", "yes")
    require = os.environ.get("GALAXY_REQUIRE_API_TOKEN", "").lower() in ("true", "1", "yes")
    return auth or require


def _adjust_findings_for_token_policy(findings: List[Finding]) -> List[Finding]:
    """Downgrade missing GALAXY_API_TOKEN from CRITICAL to WARNING when auth is off."""
    out: List[Finding] = []
    for f in findings:
        if (
            f.check.var == "GALAXY_API_TOKEN"
            and not f.present
            and f.check.severity == Severity.CRITICAL
            and not _api_token_missing_is_critical()
        ):
            out.append(
                Finding(
                    check=replace(f.check, severity=Severity.WARNING),
                    present=f.present,
                    value_hint=f.value_hint,
                )
            )
        else:
            out.append(f)
    return out


def _build_protected_compat_ws_policy_finding() -> Optional[Finding]:
    """Return a CRITICAL finding when protected mode requests compat WS ingress."""
    try:
        from core.api_routes import (
            PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV,
            get_core_compat_device_ingress_policy,
        )
    except ImportError:
        return None

    try:
        policy = get_core_compat_device_ingress_policy()
    except Exception as exc:
        logger.warning("Compat WS policy preflight probe failed: %s", exc)
        return None
    if not policy.get("blocked_by_protected_mode"):
        return None

    return Finding(
        check=EnvCheck(
            var="GALAXY_ENABLE_CORE_COMPAT_WS",
            severity=Severity.CRITICAL,
            description=(
                "Core compatibility websocket ingress cannot be activated in protected "
                "cross-device mode without an explicit override."
            ),
            hint=(
                "Unset GALAXY_ENABLE_CORE_COMPAT_WS and use the canonical gateway ingress "
                "/ws/device/{device_id} for production/cross-device operation.\n"
                f"Only set {PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV}=true for explicitly "
                "controlled migration/debug fallback sessions."
            ),
            groups=["gateway", "android", "all"],
            allow_placeholder=False,
        ),
        present=False,
    )


def _augment_findings_with_compat_ws_policy(
    findings: List[Finding],
    groups: Sequence[str],
) -> List[Finding]:
    """Append protected-mode compat WS policy violations as CRITICAL findings."""
    if not any(group in {"gateway", "android", "all"} for group in groups):
        return findings

    policy_finding = _build_protected_compat_ws_policy_finding()
    if policy_finding is None:
        return findings
    return [*findings, policy_finding]


def run_preflight(
    dry_run: bool = False,
    fail_fast: bool = True,
    mode: str = "auto",
    checks: Optional[Sequence[EnvCheck]] = None,
    verbose: bool = True,
) -> PreflightReport:
    """
    Run the pre-flight configuration check.

    Parameters
    ----------
    dry_run:
        When True, print the report but never raise ConfigPreflightError.
        Useful for CI validation without blocking startup.
    fail_fast:
        When True (default) and there are CRITICAL findings, raise
        ConfigPreflightError after printing the report.
    mode:
        Which group of checks to run (see module docstring).
    checks:
        Override the default check registry (mainly for testing).
    verbose:
        Include WARNING details in the report output.

    Returns
    -------
    PreflightReport
    """
    _checks = list(checks) if checks is not None else _CHECKS
    groups = _groups_for_mode(mode)

    # Load runtime/secrets.env into env before checking (PR-3: local config authority)
    _load_runtime_secrets_into_env()

    findings: List[Finding] = []
    for check in _checks:
        if not any(g in groups for g in check.groups):
            continue
        present, hint = _is_set(check.var, check.allow_placeholder)
        findings.append(Finding(check=check, present=present, value_hint=hint))

    findings = _adjust_findings_for_token_policy(findings)
    findings = _augment_findings_with_compat_ws_policy(findings, groups)

    report = PreflightReport(findings=findings, mode=mode)

    if verbose or not report.ok:
        print(report.format(verbose=verbose), file=sys.stderr)

    if not dry_run and fail_fast and not report.ok:
        raise ConfigPreflightError(report)

    return report


# ---------------------------------------------------------------------------
# Convenience: check a single variable
# ---------------------------------------------------------------------------

def require_env(var: str, hint: str = "") -> str:
    """
    Return the value of *var* or raise a descriptive RuntimeError.

    Intended for inline use inside module-level code that needs a specific
    env var and wants a clear error message:

        secret = require_env("SECRETVAULT_MASTER_KEY",
                             "Generate with: python3 -c \\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\\"")
    """
    value = os.environ.get(var, "")
    if not value or value.lower().startswith(_PLACEHOLDER_PREFIXES):
        msg = f"Required environment variable '{var}' is not set."
        if hint:
            msg += f"\n  💡 {hint}"
        raise RuntimeError(msg)
    return value


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Galaxy pre-flight configuration check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python -m core.config_preflight --mode all --dry-run
              python -m core.config_preflight --mode gateway
              python -m core.config_preflight --mode core --no-fail-fast
        """),
    )
    parser.add_argument(
        "--mode",
        default=os.environ.get("GALAXY_PREFLIGHT_MODE", "all"),
        choices=["auto", "all", "core", "gateway", "android", "ws", "vault"],
        help="Check group to validate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("GALAXY_PREFLIGHT_FAIL_FAST", "1").lower() in _FALSY,
        help="Print report but exit 0 even on CRITICAL failures",
    )
    parser.add_argument(
        "--no-fail-fast",
        dest="fail_fast",
        action="store_false",
        default=True,
        help="Return non-zero exit code but do not raise exception",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress WARNING details; only show CRITICAL issues",
    )

    args = parser.parse_args()

    try:
        report = run_preflight(
            dry_run=args.dry_run,
            fail_fast=False,   # we handle exit ourselves below
            mode=args.mode,
            verbose=not args.quiet,
        )
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error during preflight: {exc}", file=sys.stderr)
        sys.exit(2)

    if not report.ok and not args.dry_run:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    _main()
