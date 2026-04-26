#!/usr/bin/env python3
"""scripts/check_mainline_routing_enforcement.py
==================================================

Blocking CI guardrail: verify that mainline routing enforcement is present
and that the explicit-device-id capability bypass gap is closed.

Checks
------
1. ``core.mainline_routing_enforcement`` is importable and exposes the
   canonical enforcement sentinels.
2. ``core.capability_routing_gate`` is importable (dependency of the
   enforcement module).
3. The enforcement function ``audit_explicit_device_capabilities`` is present
   and returns a non-None result for a minimal smoke call.
4. ``core.android_runtime_host`` exposes the
   ``ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT`` sentinel (truthful status
   expression for Android local AI).
5. ``core.openclawd`` source contains the enforcement call site
   ``enforce_explicit_route_capability_gate`` so that the bypass gap cannot
   be quietly re-opened by removing the function call.

Exit codes
----------
0 — all checks pass
1 — one or more checks fail (printed to stdout)

Usage
-----
    python scripts/check_mainline_routing_enforcement.py
    python scripts/check_mainline_routing_enforcement.py --warn-only
"""
from __future__ import annotations

import argparse
import importlib
import pathlib
import sys
from typing import List, Tuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CHECKS: List[Tuple[str, bool, str]] = []  # (description, passed, detail)


def _record(description: str, passed: bool, detail: str = "") -> None:
    _CHECKS.append((description, passed, detail))
    status = "✅" if passed else "❌"
    print(f"  {status} {description}")
    if not passed and detail:
        print(f"       Detail: {detail}")


# ---------------------------------------------------------------------------
# Check 1 — mainline_routing_enforcement importable + sentinels present
# ---------------------------------------------------------------------------
def check_enforcement_module() -> None:
    try:
        _repo_root_str = str(_REPO_ROOT)
        if _repo_root_str not in sys.path:
            sys.path.insert(0, _repo_root_str)
        mod = importlib.import_module("core.mainline_routing_enforcement")
    except Exception as exc:
        _record(
            "core.mainline_routing_enforcement is importable",
            False,
            str(exc),
        )
        return

    _record("core.mainline_routing_enforcement is importable", True)

    for sentinel in (
        "MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY",
        "MAINLINE_ROUTING_ENFORCEMENT_PR_SENTINEL",
        "CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY",
        "NO_SILENT_CAPABILITY_BYPASS_POLICY",
        "EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_POLICY",
    ):
        present = hasattr(mod, sentinel)
        _record(
            f"  sentinel {sentinel!r} present",
            present,
            "" if present else f"Attribute missing from core.mainline_routing_enforcement",
        )

    for fn_name in ("audit_explicit_device_capabilities", "enforce_explicit_route_capability_gate"):
        present = callable(getattr(mod, fn_name, None))
        _record(
            f"  function {fn_name!r} callable",
            present,
            "" if present else f"Function not found or not callable",
        )


# ---------------------------------------------------------------------------
# Check 2 — capability routing gate importable
# ---------------------------------------------------------------------------
def check_capability_routing_gate() -> None:
    try:
        importlib.import_module("core.capability_routing_gate")
        _record("core.capability_routing_gate is importable", True)
    except Exception as exc:
        _record("core.capability_routing_gate is importable", False, str(exc))


# ---------------------------------------------------------------------------
# Check 3 — smoke call to audit_explicit_device_capabilities
# ---------------------------------------------------------------------------
def check_audit_smoke_call() -> None:
    try:
        mod = importlib.import_module("core.mainline_routing_enforcement")
        audit_fn = getattr(mod, "audit_explicit_device_capabilities", None)
        ExplicitRouteVerdict = getattr(mod, "ExplicitRouteVerdict", None)
        if audit_fn is None or ExplicitRouteVerdict is None:
            _record(
                "audit_explicit_device_capabilities smoke call",
                False,
                "Function or ExplicitRouteVerdict not found.",
            )
            return

        # Smoke: empty required_capabilities → NO_REQUIREMENTS verdict
        result = audit_fn("device_test", [])
        ok = result is not None and result.verdict == ExplicitRouteVerdict.NO_REQUIREMENTS
        _record(
            "audit_explicit_device_capabilities smoke call (no-op path)",
            ok,
            "" if ok else f"Unexpected result: {result}",
        )

        # Smoke: required_capabilities with no runtime → INSUFFICIENT_DATA or CONFIRMED
        result2 = audit_fn("device_test", ["screen"], device_capabilities=["screen", "touch"])
        ok2 = result2 is not None and result2.verdict in (
            ExplicitRouteVerdict.CONFIRMED,
            ExplicitRouteVerdict.NO_REQUIREMENTS,
        )
        _record(
            "audit_explicit_device_capabilities smoke call (confirmed path)",
            ok2,
            "" if ok2 else f"Unexpected verdict: {getattr(result2, 'verdict', None)}",
        )

        # Smoke: required_capabilities with missing cap → MISMATCH
        result3 = audit_fn("device_test", ["screen", "local_ai"], device_capabilities=["screen"])
        ok3 = result3 is not None and result3.verdict == ExplicitRouteVerdict.MISMATCH
        _record(
            "audit_explicit_device_capabilities smoke call (mismatch path)",
            ok3,
            "" if ok3 else f"Unexpected verdict: {getattr(result3, 'verdict', None)}",
        )
    except Exception as exc:
        _record("audit_explicit_device_capabilities smoke call", False, str(exc))


# ---------------------------------------------------------------------------
# Check 4 — Android local AI sentinel present
# ---------------------------------------------------------------------------
def check_android_local_ai_sentinel() -> None:
    try:
        mod = importlib.import_module("core.android_runtime_host")
    except Exception as exc:
        _record("core.android_runtime_host is importable", False, str(exc))
        return

    _record("core.android_runtime_host is importable", True)

    sentinel = "ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT"
    present = hasattr(mod, sentinel)
    _record(
        f"  sentinel {sentinel!r} present",
        present,
        "" if present else "Missing truthful Android local AI status sentinel",
    )

    flag = "ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG"
    flag_val = getattr(mod, flag, None)
    flag_ok = flag_val is False
    _record(
        f"  {flag} is False (local AI off by default)",
        flag_ok,
        "" if flag_ok else f"Expected False, got {flag_val!r}",
    )


# ---------------------------------------------------------------------------
# Check 5 — openclawd.py contains the enforcement call site
# ---------------------------------------------------------------------------
def check_openclawd_call_site() -> None:
    openclawd_path = _REPO_ROOT / "core" / "openclawd.py"
    if not openclawd_path.exists():
        _record("core/openclawd.py contains enforcement call site", False, "File not found")
        return

    source = openclawd_path.read_text(encoding="utf-8")
    marker = "enforce_explicit_route_capability_gate"
    present = marker in source
    _record(
        "core/openclawd.py references enforce_explicit_route_capability_gate",
        present,
        "" if present else (
            "The enforcement call site is missing from openclawd.py.  "
            "The explicit-device-id capability bypass gap may be re-opened."
        ),
    )

    # Also check that the required_capabilities forwarding fix is present in _dispatch_device
    forward_marker = "required_capabilities=required_caps"
    forward_present = forward_marker in source
    _record(
        "core/openclawd.py _dispatch_device forwards required_capabilities",
        forward_present,
        "" if forward_present else (
            "_dispatch_device does not forward required_capabilities to send_gateway_command.  "
            "The TaskEnvelope capability gate will not be reached on explicit device routes."
        ),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify mainline routing enforcement is present and active."
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Exit 0 even on failures (warning mode for advisory runs).",
    )
    args = parser.parse_args()

    print("Mainline Routing Enforcement Guardrail")
    print("=" * 50)

    check_enforcement_module()
    check_capability_routing_gate()
    check_audit_smoke_call()
    check_android_local_ai_sentinel()
    check_openclawd_call_site()

    failed = [d for d, ok, _ in _CHECKS if not ok]
    passed = [d for d, ok, _ in _CHECKS if ok]

    print()
    print(f"Results: {len(passed)} passed, {len(failed)} failed")

    if failed:
        print()
        print("FAILED checks:")
        for desc in failed:
            print(f"  ❌ {desc}")
        if args.warn_only:
            print()
            print("⚠️  warn-only mode: exiting 0 despite failures.")
            return 0
        return 1

    print("✅ All mainline routing enforcement checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
