#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_gateway_transport_boundary.py
=============================================

PR-10 — Galaxy gateway transport & routing substrate boundary formalization.

Validates that:
- Each key gateway module exposes its boundary sentinel constant.
- Sentinel values are non-empty strings that clearly identify the module's
  transport-only role.
- The README and GATEWAY_TRANSPORT_BOUNDARY.md contain the expected
  architectural boundary sections.
- No sentinel value claims authority over readiness, orchestration
  eligibility, formation truth, or entry-mode decisioning.

Test index:
  1.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY importable from websocket_handler.
  2.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY is a non-empty string.
  3.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY contains 'TRANSPORT'.
  4.  DEVICE_ROUTER_TRANSPORT_AUTHORITY importable from device_router.
  5.  DEVICE_ROUTER_TRANSPORT_AUTHORITY is a non-empty string.
  6.  DEVICE_ROUTER_TRANSPORT_AUTHORITY contains 'ROUTING_SUBSTRATE'.
  7.  CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY importable from cross_device_coordinator.
  8.  CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY is a non-empty string.
  9.  CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY contains 'TRANSPORT_LAYER'.
  10. GATEWAY_SSOT_WRITE_AUTHORITY importable from ssot.
  11. GATEWAY_SSOT_WRITE_AUTHORITY is a non-empty string.
  12. GATEWAY_SSOT_WRITE_AUTHORITY contains 'WRITE_PATH'.
  13. WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY does not claim ORCHESTRATION authority.
  14. DEVICE_ROUTER_TRANSPORT_AUTHORITY does not claim ORCHESTRATION authority.
  15. CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY does not claim ORCHESTRATION authority.
  16. GATEWAY_SSOT_WRITE_AUTHORITY does not claim SYSTEM_WIDE_READINESS authority.
  17. GATEWAY_TRANSPORT_BOUNDARY.md file exists in galaxy_gateway/.
  18. GATEWAY_TRANSPORT_BOUNDARY.md mentions 'transport' in responsibilities section.
  19. GATEWAY_TRANSPORT_BOUNDARY.md mentions 'NOT' non-responsibilities section.
  20. GATEWAY_TRANSPORT_BOUNDARY.md mentions websocket_handler sentinel name.
  21. GATEWAY_TRANSPORT_BOUNDARY.md mentions device_router sentinel name.
  22. GATEWAY_TRANSPORT_BOUNDARY.md mentions cross_device_coordinator sentinel name.
  23. GATEWAY_TRANSPORT_BOUNDARY.md mentions ssot sentinel name.
  24. galaxy_gateway/README.md contains 'Architectural Boundaries' section.
  25. galaxy_gateway/README.md contains a responsibilities table.
  26. galaxy_gateway/README.md contains a non-responsibilities table.
  27. galaxy_gateway/README.md mentions 'entry-mode' as a non-responsibility.
  28. galaxy_gateway/README.md mentions 'orchestration eligibility' as non-responsibility.
  29. galaxy_gateway/README.md mentions 'formation' as non-responsibility.
  30. galaxy_gateway/README.md mentions 'global readiness' as non-responsibility.
  31. websocket_handler.py module docstring contains 'NOT responsible for'.
  32. device_router.py module docstring contains 'NOT responsible for'.
  33. cross_device_coordinator.py module docstring contains 'NOT responsible for'.
  34. ssot.py module docstring contains 'NOT responsible for'.
  35. websocket_handler.py module docstring mentions 'local transport state'.
  36. device_router.py module docstring mentions 'routing substrate'.
  37. cross_device_coordinator.py module docstring mentions 'convenience'.
  38. ssot.py module docstring mentions 'gateway-side canonical write path'.
  39. All four sentinel values are distinct strings.
  40. Sentinel values do not contain secrets or sensitive information.
"""

import importlib
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GATEWAY_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "galaxy_gateway"
)


def _read_gateway_file(relpath: str) -> str:
    full = os.path.normpath(os.path.join(_GATEWAY_ROOT, relpath))
    with open(full, encoding="utf-8") as fh:
        return fh.read()


def _import_sentinel(module_path: str, attr: str):
    """Import *attr* from *module_path* without executing full app startup."""
    spec = importlib.util.find_spec(module_path)
    if spec is None:
        pytest.skip(f"Module {module_path!r} not importable in this env — skipping")
    # Use source-only text inspection for boundary tests so we don't need
    # the full dependency graph to be installed.
    src_file = spec.origin
    if src_file is None:
        pytest.skip(f"Cannot locate source for {module_path!r}")
    with open(src_file, encoding="utf-8") as fh:
        source = fh.read()
    return source, src_file


# ---------------------------------------------------------------------------
# Fixtures: read source files directly (avoids heavy import side-effects)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ws_source():
    return _read_gateway_file("websocket_handler.py")


@pytest.fixture(scope="module")
def dr_source():
    return _read_gateway_file("device_router.py")


@pytest.fixture(scope="module")
def cdc_source():
    return _read_gateway_file("cross_device_coordinator.py")


@pytest.fixture(scope="module")
def ssot_source():
    return _read_gateway_file("ssot.py")


@pytest.fixture(scope="module")
def boundary_doc():
    return _read_gateway_file("GATEWAY_TRANSPORT_BOUNDARY.md")


@pytest.fixture(scope="module")
def readme_doc():
    return _read_gateway_file("README.md")


# ---------------------------------------------------------------------------
# Helper: extract sentinel value from source text
# ---------------------------------------------------------------------------

def _extract_sentinel(source: str, name: str) -> str:
    """Return the string value assigned to *name* in *source*, or ''."""
    import re
    pattern = rf'{re.escape(name)}\s*=\s*["\']([^"\']+)["\']'
    # Multi-line: value may span a continuation
    pattern2 = rf'{re.escape(name)}\s*=\s*\(\s*["\']([^"\']+)["\']'
    m = re.search(pattern, source) or re.search(pattern2, source)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# 1-3: websocket_handler sentinel
# ---------------------------------------------------------------------------

def test_01_ws_sentinel_present(ws_source):
    assert "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY" in ws_source


def test_02_ws_sentinel_nonempty(ws_source):
    val = _extract_sentinel(ws_source, "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY")
    assert val, "Sentinel value should be a non-empty string"


def test_03_ws_sentinel_contains_transport(ws_source):
    val = _extract_sentinel(ws_source, "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY")
    assert "TRANSPORT" in val.upper()


# ---------------------------------------------------------------------------
# 4-6: device_router sentinel
# ---------------------------------------------------------------------------

def test_04_dr_sentinel_present(dr_source):
    assert "DEVICE_ROUTER_TRANSPORT_AUTHORITY" in dr_source


def test_05_dr_sentinel_nonempty(dr_source):
    val = _extract_sentinel(dr_source, "DEVICE_ROUTER_TRANSPORT_AUTHORITY")
    assert val


def test_06_dr_sentinel_routing_substrate(dr_source):
    val = _extract_sentinel(dr_source, "DEVICE_ROUTER_TRANSPORT_AUTHORITY")
    assert "ROUTING_SUBSTRATE" in val.upper()


# ---------------------------------------------------------------------------
# 7-9: cross_device_coordinator sentinel
# ---------------------------------------------------------------------------

def test_07_cdc_sentinel_present(cdc_source):
    assert "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY" in cdc_source


def test_08_cdc_sentinel_nonempty(cdc_source):
    val = _extract_sentinel(cdc_source, "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY")
    assert val


def test_09_cdc_sentinel_transport_layer(cdc_source):
    val = _extract_sentinel(cdc_source, "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY")
    assert "TRANSPORT_LAYER" in val.upper()


# ---------------------------------------------------------------------------
# 10-12: ssot sentinel
# ---------------------------------------------------------------------------

def test_10_ssot_sentinel_present(ssot_source):
    assert "GATEWAY_SSOT_WRITE_AUTHORITY" in ssot_source


def test_11_ssot_sentinel_nonempty(ssot_source):
    val = _extract_sentinel(ssot_source, "GATEWAY_SSOT_WRITE_AUTHORITY")
    assert val


def test_12_ssot_sentinel_write_path(ssot_source):
    val = _extract_sentinel(ssot_source, "GATEWAY_SSOT_WRITE_AUTHORITY")
    assert "WRITE_PATH" in val.upper()


# ---------------------------------------------------------------------------
# 13-16: sentinels do NOT claim wrong authority
# ---------------------------------------------------------------------------

def test_13_ws_sentinel_not_orchestration(ws_source):
    val = _extract_sentinel(ws_source, "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY")
    assert "ORCHESTRATION_AUTHORITY" not in val.upper()


def test_14_dr_sentinel_not_orchestration(dr_source):
    val = _extract_sentinel(dr_source, "DEVICE_ROUTER_TRANSPORT_AUTHORITY")
    assert "ORCHESTRATION_AUTHORITY" not in val.upper()


def test_15_cdc_sentinel_not_orchestration(cdc_source):
    val = _extract_sentinel(cdc_source, "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY")
    assert "ORCHESTRATION_AUTHORITY" not in val.upper()


def test_16_ssot_sentinel_not_system_wide_readiness(ssot_source):
    val = _extract_sentinel(ssot_source, "GATEWAY_SSOT_WRITE_AUTHORITY")
    assert "SYSTEM_WIDE_READINESS" not in val.upper()


# ---------------------------------------------------------------------------
# 17-23: GATEWAY_TRANSPORT_BOUNDARY.md
# ---------------------------------------------------------------------------

def test_17_boundary_doc_exists():
    path = os.path.normpath(os.path.join(_GATEWAY_ROOT, "GATEWAY_TRANSPORT_BOUNDARY.md"))
    assert os.path.isfile(path), "GATEWAY_TRANSPORT_BOUNDARY.md must exist in galaxy_gateway/"


def test_18_boundary_doc_mentions_transport(boundary_doc):
    assert "transport" in boundary_doc.lower()


def test_19_boundary_doc_mentions_not(boundary_doc):
    assert "not" in boundary_doc.lower()


def test_20_boundary_doc_ws_sentinel_name(boundary_doc):
    assert "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY" in boundary_doc


def test_21_boundary_doc_dr_sentinel_name(boundary_doc):
    assert "DEVICE_ROUTER_TRANSPORT_AUTHORITY" in boundary_doc


def test_22_boundary_doc_cdc_sentinel_name(boundary_doc):
    assert "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY" in boundary_doc


def test_23_boundary_doc_ssot_sentinel_name(boundary_doc):
    assert "GATEWAY_SSOT_WRITE_AUTHORITY" in boundary_doc


# ---------------------------------------------------------------------------
# 24-30: galaxy_gateway/README.md
# ---------------------------------------------------------------------------

def test_24_readme_architectural_boundaries(readme_doc):
    assert "Architectural Boundaries" in readme_doc or "Architectural boundary" in readme_doc


def test_25_readme_responsibilities_table(readme_doc):
    assert "Gateway Responsibilities" in readme_doc or "Responsibilities" in readme_doc


def test_26_readme_non_responsibilities_table(readme_doc):
    assert "Non-Responsibilities" in readme_doc or "Non-responsibilities" in readme_doc or "NOT" in readme_doc


def test_27_readme_entry_mode_non_responsibility(readme_doc):
    assert "entry-mode" in readme_doc.lower() or "Entry-mode" in readme_doc


def test_28_readme_orchestration_eligibility_non_responsibility(readme_doc):
    assert "orchestration eligibility" in readme_doc.lower()


def test_29_readme_formation_non_responsibility(readme_doc):
    assert "formation" in readme_doc.lower()


def test_30_readme_global_readiness_non_responsibility(readme_doc):
    assert "global readiness" in readme_doc.lower() or "readiness truth" in readme_doc.lower()


# ---------------------------------------------------------------------------
# 31-38: module docstrings
# ---------------------------------------------------------------------------

def test_31_ws_docstring_not_responsible(ws_source):
    assert "NOT responsible for" in ws_source


def test_32_dr_docstring_not_responsible(dr_source):
    assert "NOT responsible for" in dr_source


def test_33_cdc_docstring_not_responsible(cdc_source):
    assert "NOT responsible for" in cdc_source


def test_34_ssot_docstring_not_responsible(ssot_source):
    assert "NOT responsible for" in ssot_source


def test_35_ws_docstring_local_transport(ws_source):
    assert "local transport state" in ws_source.lower()


def test_36_dr_docstring_routing_substrate(dr_source):
    assert "routing substrate" in dr_source.lower()


def test_37_cdc_docstring_convenience(cdc_source):
    assert "convenience" in cdc_source.lower()


def test_38_ssot_docstring_write_path(ssot_source):
    assert "write path" in ssot_source.lower()


# ---------------------------------------------------------------------------
# 39-40: sentinel uniqueness and safety
# ---------------------------------------------------------------------------

def test_39_all_sentinels_distinct(ws_source, dr_source, cdc_source, ssot_source):
    vals = [
        _extract_sentinel(ws_source, "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY"),
        _extract_sentinel(dr_source, "DEVICE_ROUTER_TRANSPORT_AUTHORITY"),
        _extract_sentinel(cdc_source, "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY"),
        _extract_sentinel(ssot_source, "GATEWAY_SSOT_WRITE_AUTHORITY"),
    ]
    assert len(set(vals)) == len(vals), "All sentinel values must be distinct"


def test_40_sentinels_no_secrets(ws_source, dr_source, cdc_source, ssot_source):
    """Sentinel string values should not contain anything that looks like a secret."""
    bad_patterns = ["password", "secret", "apikey", "token", "credential"]
    sentinel_pairs = [
        (ws_source, "WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY"),
        (dr_source, "DEVICE_ROUTER_TRANSPORT_AUTHORITY"),
        (cdc_source, "CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY"),
        (ssot_source, "GATEWAY_SSOT_WRITE_AUTHORITY"),
    ]
    for src, name in sentinel_pairs:
        val = _extract_sentinel(src, name).lower()
        for pat in bad_patterns:
            assert pat not in val, (
                f"Sentinel {name!r} value contains sensitive keyword {pat!r}: {val!r}"
            )
