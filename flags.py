"""
flags.py
========
Feature Flag Registry for Device Resolution & Activation Plane.

Purpose:
    Central, version-controlled registry of all feature flags used by the
    Unified Node Contract and launcher_adapter subsystems.  Each flag has
    an owner, a rollout plan, and a cleanup condition so flags do not
    become permanent technical debt.

Definition of Done for flag removal:
    - Flag has been in "stable" mode for 2+ releases with no incidents.
    - All environments (dev/staging/prod) report zero usage of the guarded path.
    - Owner signs off in a PR that removes the flag.

See: https://docs.google.com/document/d/1(**TODO**)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Flag definition
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeatureFlag:
    name: str
    env_var: str
    default: str
    owner: str          # GitHub handle or team
    purpose: str        # One-line why this flag exists
    rollout_plan: str   # How to migrate from default to final
    cleanup_condition: str  # When can this flag be removed
    since: str          # Version when introduced
    status: str         # experimental / beta / stable / deprecated


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
REGISTERED_FLAGS = {
    # --- Launcher Adapter ---
    "launcher_adapter_mode": FeatureFlag(
        name="launcher_adapter_mode",
        env_var="LAUNCHER_ADAPTER_MODE",
        default="observe_only",
        owner="@DannyFish-11",
        purpose="Controls how LauncherAdapter reacts to device resolution decisions",
        rollout_plan=(
            "observe_only (v3.5+) → dry_run (validate logging) → "
            "allowlist (pilot nodes) → full (general availability)"
        ),
        cleanup_condition=(
            "When 'full' mode has run in production for 2 releases "
            "without rollback to observe_only"
        ),
        since="v3.5.0",
        status="experimental",
    ),

    "launcher_adapter_allowlist": FeatureFlag(
        name="launcher_adapter_allowlist",
        env_var="LAUNCHER_ADAPTER_ALLOWLIST",
        default="",
        owner="@DannyFish-11",
        purpose="Comma-separated list of nodes allowed to auto-start in allowlist mode",
        rollout_plan="Empty (no restriction) → pilot list → removed when mode goes full",
        cleanup_condition="Removed together with launcher_adapter_mode when mode flag is deleted",
        since="v3.5.0",
        status="experimental",
    ),

    # --- NATS Bus ---
    "nats_mode": FeatureFlag(
        name="nats_mode",
        env_var="NATS_MODE",
        default="embedded",
        owner="@DannyFish-11",
        purpose="How NATS message bus is provided: embedded server, external, or no-op",
        rollout_plan="no-op (legacy) → embedded (current) → external (future scale)",
        cleanup_condition="When all environments run embedded or external; no-op path removed",
        since="v3.4.0",
        status="stable",
    ),

    # --- Desktop Presence / Three-State GUI ---
    "galaxy_skip_electron": FeatureFlag(
        name="galaxy_skip_electron",
        env_var="GALAXY_SKIP_ELECTRON",
        default="",
        owner="@DannyFish-11",
        purpose="If set to '1', skip starting the Electron three-state GUI",
        rollout_plan="Always present as escape hatch; likely permanent",
        cleanup_condition="Likely never — serves as headless mode toggle",
        since="v3.3.0",
        status="stable",
    ),

    # --- WebRTC ---
    "webrtc_task_lifecycle": FeatureFlag(
        name="webrtc_task_lifecycle",
        env_var="WEBRTC_TASK_LIFECYCLE",
        default="enabled",
        owner="@DannyFish-11",
        purpose="Enable WebRTC handshake gate in CommandRouter for tasks with requires_webrtc=True",
        rollout_plan="enabled (opt-in per task) → enabled by default → always-on",
        cleanup_condition="When all multimodal tasks use WebRTC and no opt-out needed",
        since="v3.5.0",
        status="beta",
    ),
}


def get_flag(name: str) -> Optional[FeatureFlag]:
    """Return a registered flag by name."""
    return REGISTERED_FLAGS.get(name)


def list_flags(status: Optional[str] = None) -> list[FeatureFlag]:
    """List all flags, optionally filtered by status."""
    flags = list(REGISTERED_FLAGS.values())
    if status:
        flags = [f for f in flags if f.status == status]
    return flags


if __name__ == "__main__":
    print("Registered Feature Flags")
    print("=" * 60)
    for flag in REGISTERED_FLAGS.values():
        print(f"\n{flag.name}")
        print(f"  env_var : {flag.env_var}")
        print(f"  default : {flag.default}")
        print(f"  owner   : {flag.owner}")
        print(f"  status  : {flag.status}")
        print(f"  purpose : {flag.purpose}")
        print(f"  since   : {flag.since}")
        print(f"  cleanup : {flag.cleanup_condition}")
