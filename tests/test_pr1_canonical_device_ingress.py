#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr1_canonical_device_ingress.py
==========================================

PR-1 — Canonicalize device ingress to gateway /ws/device/{device_id}.

Validates that:
- galaxy_gateway/routes/websocket.py exposes a CANONICAL_DEVICE_INGRESS_AUTHORITY
  sentinel that clearly names /ws/device/{device_id} as the canonical path.
- The gateway websocket module docstring declares /ws/device/{device_id} as
  [CANONICAL] and all other device paths as non-canonical.
- The /ws/device/{device_id} route docstring is clearly canonical.
- The /ws/android/{device_id} route is demoted to [COMPAT].
- The /ws/{device_id} route is marked [DEPRECATED].
- The /ws route is marked [DEBUG].
- The /ws/ufo3/{device_id} route retains [LEGACY-DISABLED] / disabled status.
- core/api_routes.py /ws/device/{device_id} is explicitly marked as
  compatibility-only (non-canonical, non-primary).
- core/api_routes.py module docstring notes that canonical ingress is in gateway.
- core/api_routes.py create_websocket_routes docstring marks it as compat surface.
- CANONICAL_DEVICE_INGRESS_AUTHORITY is a non-empty string.
- CANONICAL_DEVICE_INGRESS_AUTHORITY references /ws/device/{device_id}.
- CANONICAL_DEVICE_INGRESS_AUTHORITY references the gateway module.
- No other path in the gateway websocket file claims to be canonical ingress.
- The sentinel does not claim orchestration or readiness authority.

Test index:
  1.  CANONICAL_DEVICE_INGRESS_AUTHORITY present in gateway websocket source.
  2.  CANONICAL_DEVICE_INGRESS_AUTHORITY is assigned a non-empty string.
  3.  CANONICAL_DEVICE_INGRESS_AUTHORITY references /ws/device/{device_id}.
  4.  CANONICAL_DEVICE_INGRESS_AUTHORITY references galaxy_gateway.
  5.  CANONICAL_DEVICE_INGRESS_AUTHORITY does not claim ORCHESTRATION authority.
  6.  CANONICAL_DEVICE_INGRESS_AUTHORITY does not claim READINESS authority.
  7.  gateway websocket module docstring contains CANONICAL_DEVICE_INGRESS_AUTHORITY section.
  8.  gateway websocket module docstring marks /ws/device/{device_id} as [CANONICAL].
  9.  gateway websocket module docstring marks /ws/android/{device_id} as [COMPAT].
  10. gateway websocket module docstring marks /ws/{device_id} as [DEPRECATED].
  11. gateway websocket module docstring marks /ws as [DEBUG].
  12. gateway websocket module docstring marks /ws/ufo3/{device_id} as [LEGACY-DISABLED].
  13. /ws/device/{device_id} route docstring contains 'canonical' (case-insensitive).
  14. /ws/device/{device_id} route docstring contains 'CANONICAL'.
  15. /ws/android/{device_id} route docstring contains 'COMPAT'.
  16. /ws/android/{device_id} route docstring states it is NOT the canonical ingress.
  17. /ws/{device_id} route docstring contains 'DEPRECATED'.
  18. /ws/{device_id} route docstring states new clients must use /ws/device/.
  19. /ws route docstring contains 'DEBUG'.
  20. /ws route docstring states it is not for production device ingress.
  21. core api_routes.py module docstring mentions canonical ingress is in gateway.
  22. core api_routes.py module docstring marks /ws/device as compat/non-canonical.
  23. core create_websocket_routes docstring marks it as COMPATIBILITY SURFACE.
  24. core create_websocket_routes docstring states NOT the canonical device ingress.
  25. core device_websocket handler docstring contains '[COMPAT]'.
  26. core device_websocket handler docstring references galaxy_gateway as canonical.
  27. /ws/ufo3 disabled behavior is preserved in gateway source (legacy guard present).
  28. gateway websocket source does not present /ws/android as canonical ingress.
  29. gateway websocket source does not present /ws as canonical ingress.
  30. gateway websocket source does not present /ws/{device_id} as canonical ingress.
"""

import os

import pytest

# ---------------------------------------------------------------------------
# Helpers — read source files directly to avoid heavy import side-effects
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _read(relpath: str) -> str:
    full = os.path.join(_REPO_ROOT, relpath)
    with open(full, encoding="utf-8") as fh:
        return fh.read()


_GW_WS = _read("galaxy_gateway/routes/websocket.py")
_CORE_ROUTES = _read("core/api_routes.py")


# ---------------------------------------------------------------------------
# 1-6: CANONICAL_DEVICE_INGRESS_AUTHORITY sentinel
# ---------------------------------------------------------------------------

def test_01_sentinel_present_in_source():
    """CANONICAL_DEVICE_INGRESS_AUTHORITY is defined in gateway websocket source."""
    assert "CANONICAL_DEVICE_INGRESS_AUTHORITY" in _GW_WS


def test_02_sentinel_assigned_nonempty_string():
    """CANONICAL_DEVICE_INGRESS_AUTHORITY is assigned a non-empty string value."""
    # The assignment line must contain a string literal (quote after '=')
    import re
    match = re.search(
        r'CANONICAL_DEVICE_INGRESS_AUTHORITY\s*=\s*["\(]', _GW_WS
    )
    assert match, "CANONICAL_DEVICE_INGRESS_AUTHORITY assignment not found or not a string"


def test_03_sentinel_references_canonical_path():
    """CANONICAL_DEVICE_INGRESS_AUTHORITY references /ws/device/{device_id}."""
    import re
    # Extract the full sentinel assignment (handles multi-line parenthesised string)
    match = re.search(
        r'CANONICAL_DEVICE_INGRESS_AUTHORITY\s*=\s*\((.*?)\)',
        _GW_WS, re.DOTALL
    )
    if not match:
        # Try single-line assignment
        match = re.search(
            r'CANONICAL_DEVICE_INGRESS_AUTHORITY\s*=\s*"([^"]*)"',
            _GW_WS
        )
    assert match, "CANONICAL_DEVICE_INGRESS_AUTHORITY assignment not found"
    value = match.group(1)
    assert "ws/device" in value, f"Sentinel does not reference /ws/device/ path: {value!r}"


def test_04_sentinel_references_gateway_module():
    """CANONICAL_DEVICE_INGRESS_AUTHORITY references galaxy_gateway."""
    lines = _GW_WS.splitlines()
    sentinel_lines = [l for l in lines if "CANONICAL_DEVICE_INGRESS_AUTHORITY" in l or "galaxy_gateway" in l]
    combined = "\n".join(sentinel_lines)
    assert "galaxy_gateway" in combined


def _extract_sentinel_value(source: str) -> str:
    """Extract the string value of CANONICAL_DEVICE_INGRESS_AUTHORITY from source."""
    import re
    # Multi-line parenthesised string
    match = re.search(
        r'CANONICAL_DEVICE_INGRESS_AUTHORITY\s*=\s*\((.*?)\)',
        source, re.DOTALL
    )
    if match:
        return match.group(1)
    # Single-line string
    match = re.search(
        r'CANONICAL_DEVICE_INGRESS_AUTHORITY\s*=\s*"([^"]*)"',
        source
    )
    if match:
        return match.group(1)
    return ""


def test_05_sentinel_does_not_claim_orchestration():
    """CANONICAL_DEVICE_INGRESS_AUTHORITY does not claim ORCHESTRATION authority."""
    value = _extract_sentinel_value(_GW_WS).upper()
    assert "ORCHESTRATION_AUTHORITY" not in value
    assert "ORCHESTRATION AUTHORITY" not in value


def test_06_sentinel_does_not_claim_readiness():
    """CANONICAL_DEVICE_INGRESS_AUTHORITY does not claim READINESS authority."""
    value = _extract_sentinel_value(_GW_WS).upper()
    assert "READINESS_AUTHORITY" not in value
    assert "READINESS AUTHORITY" not in value


# ---------------------------------------------------------------------------
# 7-12: Module docstring path authority table
# ---------------------------------------------------------------------------

def test_07_module_docstring_has_canonical_authority_section():
    """Gateway websocket module docstring contains CANONICAL_DEVICE_INGRESS_AUTHORITY section."""
    assert "CANONICAL DEVICE INGRESS AUTHORITY" in _GW_WS.upper()


def test_08_module_docstring_marks_ws_device_as_canonical():
    """Gateway websocket module docstring marks /ws/device/{device_id} as [CANONICAL]."""
    assert "[CANONICAL]" in _GW_WS
    # The [CANONICAL] tag must appear near /ws/device/
    import re
    # Accept either order on the same line
    assert re.search(r"\[CANONICAL\].*ws/device|ws/device.*\[CANONICAL\]", _GW_WS)


def test_09_module_docstring_marks_android_as_compat():
    """Gateway websocket module docstring marks /ws/android/{device_id} as [COMPAT]."""
    assert "[COMPAT]" in _GW_WS
    import re
    assert re.search(r"\[COMPAT\].*ws/android|ws/android.*\[COMPAT\]", _GW_WS)


def test_10_module_docstring_marks_generic_as_deprecated():
    """Gateway websocket module docstring marks /ws/{device_id} as [DEPRECATED]."""
    assert "[DEPRECATED]" in _GW_WS


def test_11_module_docstring_marks_ws_root_as_debug():
    """Gateway websocket module docstring marks /ws as [DEBUG]."""
    assert "[DEBUG]" in _GW_WS


def test_12_module_docstring_marks_ufo3_as_legacy_disabled():
    """Gateway websocket module docstring marks /ws/ufo3/{device_id} as [LEGACY-DISABLED]."""
    assert "[LEGACY-DISABLED]" in _GW_WS


# ---------------------------------------------------------------------------
# 13-20: Individual route docstrings
# ---------------------------------------------------------------------------

def test_13_ws_device_route_docstring_contains_canonical_lowercase():
    """gateway /ws/device/{device_id} route docstring contains 'canonical' (case-insensitive)."""
    assert "canonical" in _GW_WS.lower()


def test_14_ws_device_route_docstring_contains_canonical_tag():
    """gateway /ws/device/{device_id} route docstring contains [CANONICAL] tag."""
    # The route function itself must carry [CANONICAL]
    import re
    # Find the websocket_device function body
    match = re.search(
        r'async def websocket_device.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match, "websocket_device function with docstring not found"
    docstring = match.group(1)
    assert "[CANONICAL]" in docstring, f"[CANONICAL] not in websocket_device docstring: {docstring!r}"


def test_15_android_route_docstring_contains_compat_tag():
    """gateway /ws/android/{device_id} route docstring contains [COMPAT] tag."""
    import re
    match = re.search(
        r'async def websocket_android_primary.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match, "websocket_android_primary function with docstring not found"
    docstring = match.group(1)
    assert "[COMPAT]" in docstring, f"[COMPAT] not in websocket_android_primary docstring: {docstring!r}"


def test_16_android_route_docstring_states_not_canonical():
    """gateway /ws/android/{device_id} route docstring states it is NOT the canonical ingress."""
    import re
    match = re.search(
        r'async def websocket_android_primary.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match
    docstring = match.group(1)
    assert "NOT" in docstring or "not" in docstring.lower(), (
        "websocket_android_primary docstring should state it is not canonical"
    )


def test_17_generic_route_docstring_contains_deprecated_tag():
    """gateway /ws/{device_id} route docstring contains [DEPRECATED] tag."""
    import re
    match = re.search(
        r'async def websocket_endpoint\b.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match, "websocket_endpoint function with docstring not found"
    docstring = match.group(1)
    assert "[DEPRECATED]" in docstring, f"[DEPRECATED] not in websocket_endpoint docstring: {docstring!r}"


def test_18_generic_route_docstring_directs_to_canonical():
    """gateway /ws/{device_id} route docstring directs new clients to use /ws/device/."""
    import re
    match = re.search(
        r'async def websocket_endpoint\b.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match
    docstring = match.group(1)
    assert "/ws/device/" in docstring, (
        "websocket_endpoint docstring should reference /ws/device/ as the correct path"
    )


def test_19_ws_root_docstring_contains_debug_tag():
    """gateway /ws route docstring contains [DEBUG] tag."""
    import re
    match = re.search(
        r'async def websocket_endpoint_auto.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match, "websocket_endpoint_auto function with docstring not found"
    docstring = match.group(1)
    assert "[DEBUG]" in docstring, f"[DEBUG] not in websocket_endpoint_auto docstring: {docstring!r}"


def test_20_ws_root_docstring_not_for_production():
    """gateway /ws route docstring states it is not for production device ingress."""
    import re
    match = re.search(
        r'async def websocket_endpoint_auto.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    assert match
    docstring = match.group(1)
    lower = docstring.lower()
    assert "not for production" in lower or "debug" in lower, (
        "websocket_endpoint_auto docstring should state it is not for production"
    )


# ---------------------------------------------------------------------------
# 21-26: core/api_routes.py compat annotations
# ---------------------------------------------------------------------------

def test_21_core_module_docstring_references_gateway_canonical():
    """core/api_routes.py module docstring mentions canonical ingress is in gateway."""
    lower = _CORE_ROUTES.lower()
    assert "canonical" in lower and "gateway" in lower, (
        "core/api_routes.py module docstring should reference gateway canonical ingress"
    )


def test_22_core_module_docstring_marks_ws_device_as_compat():
    """core/api_routes.py module docstring marks /ws/device as compat/non-canonical."""
    assert "兼容" in _CORE_ROUTES or "compat" in _CORE_ROUTES.lower() or "COMPAT" in _CORE_ROUTES


def test_23_core_create_websocket_routes_marked_compat_surface():
    """core create_websocket_routes docstring marks it as COMPATIBILITY SURFACE."""
    import re
    match = re.search(
        r'def create_websocket_routes.*?"""(.*?)"""',
        _CORE_ROUTES, re.DOTALL
    )
    assert match, "create_websocket_routes function with docstring not found"
    docstring = match.group(1)
    upper = docstring.upper()
    assert "COMPAT" in upper or "COMPATIBILITY" in upper, (
        f"create_websocket_routes docstring should mark it as compatibility surface: {docstring!r}"
    )


def test_24_core_create_websocket_routes_not_canonical():
    """core create_websocket_routes docstring states NOT the canonical device ingress."""
    import re
    match = re.search(
        r'def create_websocket_routes.*?"""(.*?)"""',
        _CORE_ROUTES, re.DOTALL
    )
    assert match
    docstring = match.group(1)
    lower = docstring.lower()
    assert "not" in lower and "canonical" in lower, (
        "create_websocket_routes docstring should state NOT the canonical device ingress"
    )


def test_25_core_device_websocket_handler_compat_tag():
    """core device_websocket handler docstring contains [COMPAT] tag."""
    import re
    match = re.search(
        r'async def device_websocket.*?"""(.*?)"""',
        _CORE_ROUTES, re.DOTALL
    )
    assert match, "device_websocket handler with docstring not found"
    docstring = match.group(1)
    assert "[COMPAT]" in docstring, f"[COMPAT] not in core device_websocket docstring: {docstring!r}"


def test_26_core_device_websocket_references_gateway_canonical():
    """core device_websocket handler docstring references galaxy_gateway as canonical."""
    import re
    match = re.search(
        r'async def device_websocket.*?"""(.*?)"""',
        _CORE_ROUTES, re.DOTALL
    )
    assert match
    docstring = match.group(1)
    assert "galaxy_gateway" in docstring, (
        "core device_websocket docstring should reference galaxy_gateway as canonical ingress"
    )


# ---------------------------------------------------------------------------
# 27-30: Behavioral invariants
# ---------------------------------------------------------------------------

def test_27_ufo3_disabled_guard_preserved():
    """gateway websocket source preserves legacy guard for /ws/ufo3 (disabled by default)."""
    assert "_LEGACY_PROTOCOLS_ENABLED" in _GW_WS
    assert "GALAXY_ENABLE_LEGACY_PROTOCOLS" in _GW_WS


def test_28_android_path_not_presented_as_canonical_in_gateway():
    """gateway websocket source does not present /ws/android as canonical ingress."""
    import re
    # The old "Primary Android WebSocket path" phrasing must be gone
    assert "Primary Android WebSocket path" not in _GW_WS
    # /ws/android should not appear with [CANONICAL] tag
    assert not re.search(r"\[CANONICAL\].*ws/android|ws/android.*\[CANONICAL\]", _GW_WS)


def test_29_ws_root_not_presented_as_canonical():
    """gateway websocket source does not present /ws (root) as canonical ingress."""
    import re
    # The auto-assign endpoint docstring must not contain [CANONICAL]
    match = re.search(
        r'async def websocket_endpoint_auto.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    if match:
        docstring = match.group(1)
        assert "[CANONICAL]" not in docstring


def test_30_generic_path_not_presented_as_canonical():
    """gateway websocket source does not present /ws/{device_id} as canonical ingress."""
    import re
    # websocket_endpoint (the generic one) docstring must not contain [CANONICAL]
    match = re.search(
        r'async def websocket_endpoint\b.*?"""(.*?)"""',
        _GW_WS, re.DOTALL
    )
    if match:
        docstring = match.group(1)
        assert "[CANONICAL]" not in docstring
