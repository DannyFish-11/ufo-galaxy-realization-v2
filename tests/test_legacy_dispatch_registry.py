#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_legacy_dispatch_registry.py
========================================

PR-A: Canonical Task & Execution Spine — legacy dispatch registry tests.

Validates:
  A)  Authority sentinels importable and correct.
  B)  LegacyDispatchClassification enum values.
  C)  LegacyDispatchEntry construction and to_dict().
  D)  LegacyRegistrySnapshot construction and to_dict().
  E)  LegacyDispatchRegistry.register() basic case.
  F)  LegacyDispatchRegistry.register() idempotent upsert.
  G)  LegacyDispatchRegistry.register() empty module raises ValueError.
  H)  LegacyDispatchRegistry.get() found and not-found.
  I)  LegacyDispatchRegistry.is_registered() true/false.
  J)  LegacyDispatchRegistry.get_by_classification() filtering.
  K)  LegacyDispatchRegistry.all_entries() returns list.
  L)  LegacyDispatchRegistry.snapshot() structure and counts.
  M)  get_legacy_dispatch_registry() returns singleton.
  N)  reset_registry() changes singleton.
  O)  Bootstrap: fusion.unified_orchestrator is pre-registered as FACADE_ONLY.
  P)  Bootstrap: galaxy_gateway.orchestrator.galaxy_orchestrator is FACADE_ONLY.
  Q)  Bootstrap: core.e2e_orchestrator is pre-registered as FACADE_ONLY.
  R)  Bootstrap: core.device_orchestrator is pre-registered as FACADE_ONLY.
  S)  Bootstrap: galaxy_gateway.task_router is DEPRECATED.
  T)  Bootstrap: core.cross_device_execution_chain is COMPAT_ONLY.
  U)  Bootstrap: core.local_execution_chain is COMPAT_ONLY.
  V)  Bootstrap: core.hybrid_executor is COMPAT_ONLY.
  W)  Bootstrap: core.remote_execution_mode_resolver is COMPAT_ONLY.
  X)  Bootstrap: galaxy_gateway.agent_bridge is COMPAT_ONLY.
  Y)  Bootstrap: galaxy_gateway.cross_device_coordinator is COMPAT_ONLY.
  Z)  Bootstrap: core.execution_spine is COMPAT_ONLY.
  AA) register_legacy_dispatch() convenience function works.
  AB) snapshot_registry() returns LegacyRegistrySnapshot.
  AC) snapshot contains at least all bootstrapped entries.
  AD) All public names appear in __all__.
"""

from __future__ import annotations

import pytest

from core.legacy_dispatch_registry import (
    LEGACY_DISPATCH_REGISTRY_AUTHORITY,
    LEGACY_DISPATCH_REGISTRY_POLICY,
    LegacyDispatchClassification,
    LegacyDispatchEntry,
    LegacyDispatchRegistry,
    LegacyRegistrySnapshot,
    get_legacy_dispatch_registry,
    register_legacy_dispatch,
    reset_registry,
    snapshot_registry,
)
import core.legacy_dispatch_registry as _mod


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def fresh_registry():
    reset_registry()
    yield
    reset_registry()


# ===========================================================================
# A) Authority sentinels
# ===========================================================================

def test_A1_authority_importable():
    assert LEGACY_DISPATCH_REGISTRY_AUTHORITY is not None


def test_A2_authority_value_contains_keyword():
    assert "LEGACY_DISPATCH_REGISTRY" in LEGACY_DISPATCH_REGISTRY_AUTHORITY


def test_A3_policy_non_empty():
    assert isinstance(LEGACY_DISPATCH_REGISTRY_POLICY, str)
    assert len(LEGACY_DISPATCH_REGISTRY_POLICY) > 0


def test_A4_policy_mentions_command_router():
    assert "CommandRouter" in LEGACY_DISPATCH_REGISTRY_POLICY


# ===========================================================================
# B) LegacyDispatchClassification enum
# ===========================================================================

def test_B1_compat_only():
    assert LegacyDispatchClassification.COMPAT_ONLY.value == "compat-only"


def test_B2_deprecated():
    assert LegacyDispatchClassification.DEPRECATED.value == "deprecated"


def test_B3_facade_only():
    assert LegacyDispatchClassification.FACADE_ONLY.value == "facade-only"


# ===========================================================================
# C) LegacyDispatchEntry
# ===========================================================================

def test_C1_entry_defaults():
    entry = LegacyDispatchEntry()
    assert entry.module == ""
    assert entry.classification == LegacyDispatchClassification.DEPRECATED
    assert entry.reason == ""
    assert entry.pr_origin == ""


def test_C2_entry_custom():
    entry = LegacyDispatchEntry(
        module="my.module",
        classification=LegacyDispatchClassification.FACADE_ONLY,
        reason="test",
        pr_origin="PR-A",
    )
    assert entry.module == "my.module"
    assert entry.classification == LegacyDispatchClassification.FACADE_ONLY


def test_C3_entry_to_dict_keys():
    entry = LegacyDispatchEntry(module="test.mod")
    d = entry.to_dict()
    for k in ("entry_id", "module", "classification", "reason", "registered_at", "pr_origin"):
        assert k in d


def test_C4_entry_to_dict_classification_is_str():
    entry = LegacyDispatchEntry(
        module="test.mod",
        classification=LegacyDispatchClassification.COMPAT_ONLY,
    )
    d = entry.to_dict()
    assert d["classification"] == "compat-only"


# ===========================================================================
# D) LegacyRegistrySnapshot
# ===========================================================================

def test_D1_snapshot_defaults():
    snap = LegacyRegistrySnapshot()
    assert snap.total_entries == 0
    assert isinstance(snap.entries_by_classification, dict)
    assert isinstance(snap.entries, list)


def test_D2_snapshot_to_dict_keys():
    snap = LegacyRegistrySnapshot()
    d = snap.to_dict()
    for k in ("total_entries", "entries_by_classification", "entries", "snapshot_ts"):
        assert k in d


# ===========================================================================
# E) LegacyDispatchRegistry.register()
# ===========================================================================

def test_E1_register_basic():
    reg = LegacyDispatchRegistry()
    entry = reg.register(
        module="test.module",
        classification=LegacyDispatchClassification.DEPRECATED,
        reason="test reason",
    )
    assert isinstance(entry, LegacyDispatchEntry)
    assert entry.module == "test.module"


def test_E2_register_returns_entry():
    reg = LegacyDispatchRegistry()
    entry = reg.register("mod.x", LegacyDispatchClassification.COMPAT_ONLY)
    assert entry is not None


# ===========================================================================
# F) LegacyDispatchRegistry.register() idempotent
# ===========================================================================

def test_F1_register_idempotent_upsert():
    reg = LegacyDispatchRegistry()
    reg.register("mod.y", LegacyDispatchClassification.DEPRECATED)
    reg.register("mod.y", LegacyDispatchClassification.FACADE_ONLY, reason="updated")
    entry = reg.get("mod.y")
    assert entry is not None
    assert entry.classification == LegacyDispatchClassification.FACADE_ONLY


# ===========================================================================
# G) Empty module raises ValueError
# ===========================================================================

def test_G1_empty_module_raises():
    reg = LegacyDispatchRegistry()
    with pytest.raises(ValueError):
        reg.register("", LegacyDispatchClassification.DEPRECATED)


# ===========================================================================
# H) LegacyDispatchRegistry.get()
# ===========================================================================

def test_H1_get_found():
    reg = LegacyDispatchRegistry()
    reg.register("mod.found", LegacyDispatchClassification.DEPRECATED)
    assert reg.get("mod.found") is not None


def test_H2_get_not_found():
    reg = LegacyDispatchRegistry()
    assert reg.get("mod.notfound") is None


# ===========================================================================
# I) is_registered()
# ===========================================================================

def test_I1_is_registered_true():
    reg = LegacyDispatchRegistry()
    reg.register("mod.z", LegacyDispatchClassification.COMPAT_ONLY)
    assert reg.is_registered("mod.z") is True


def test_I2_is_registered_false():
    reg = LegacyDispatchRegistry()
    assert reg.is_registered("mod.ghost") is False


# ===========================================================================
# J) get_by_classification()
# ===========================================================================

def test_J1_get_by_classification_facade():
    reg = LegacyDispatchRegistry()
    reg.register("mod.a", LegacyDispatchClassification.FACADE_ONLY)
    reg.register("mod.b", LegacyDispatchClassification.DEPRECATED)
    facades = reg.get_by_classification(LegacyDispatchClassification.FACADE_ONLY)
    assert any(e.module == "mod.a" for e in facades)
    assert not any(e.module == "mod.b" for e in facades)


# ===========================================================================
# K) all_entries()
# ===========================================================================

def test_K1_all_entries_returns_list():
    reg = LegacyDispatchRegistry()
    reg.register("mod.1", LegacyDispatchClassification.DEPRECATED)
    reg.register("mod.2", LegacyDispatchClassification.COMPAT_ONLY)
    entries = reg.all_entries()
    assert isinstance(entries, list)
    assert len(entries) == 2


# ===========================================================================
# L) snapshot()
# ===========================================================================

def test_L1_snapshot_total_entries():
    reg = LegacyDispatchRegistry()
    reg.register("mod.x", LegacyDispatchClassification.DEPRECATED)
    snap = reg.snapshot()
    assert snap.total_entries == 1


def test_L2_snapshot_entries_by_classification():
    reg = LegacyDispatchRegistry()
    reg.register("mod.p", LegacyDispatchClassification.FACADE_ONLY)
    reg.register("mod.q", LegacyDispatchClassification.FACADE_ONLY)
    reg.register("mod.r", LegacyDispatchClassification.DEPRECATED)
    snap = reg.snapshot()
    assert snap.entries_by_classification.get("facade-only") == 2
    assert snap.entries_by_classification.get("deprecated") == 1


# ===========================================================================
# M) Singleton
# ===========================================================================

def test_M1_singleton():
    r1 = get_legacy_dispatch_registry()
    r2 = get_legacy_dispatch_registry()
    assert r1 is r2


# ===========================================================================
# N) reset_registry()
# ===========================================================================

def test_N1_reset_changes_singleton():
    r1 = get_legacy_dispatch_registry()
    reset_registry()
    r2 = get_legacy_dispatch_registry()
    assert r1 is not r2


# ===========================================================================
# O–Z) Bootstrap entries
# ===========================================================================

def test_O1_unified_orchestrator_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("fusion.unified_orchestrator")


def test_O2_unified_orchestrator_is_facade_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("fusion.unified_orchestrator")
    assert entry.classification == LegacyDispatchClassification.FACADE_ONLY


def test_P1_galaxy_orchestrator_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("galaxy_gateway.orchestrator.galaxy_orchestrator")


def test_P2_galaxy_orchestrator_is_facade_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("galaxy_gateway.orchestrator.galaxy_orchestrator")
    assert entry.classification == LegacyDispatchClassification.FACADE_ONLY


def test_Q1_e2e_orchestrator_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.e2e_orchestrator")


def test_Q2_e2e_orchestrator_is_facade_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.e2e_orchestrator")
    assert entry.classification == LegacyDispatchClassification.FACADE_ONLY


def test_R1_device_orchestrator_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.device_orchestrator")


def test_R2_device_orchestrator_is_facade_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.device_orchestrator")
    assert entry.classification == LegacyDispatchClassification.FACADE_ONLY


def test_S1_task_router_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("galaxy_gateway.task_router")


def test_S2_task_router_is_deprecated():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("galaxy_gateway.task_router")
    assert entry.classification == LegacyDispatchClassification.DEPRECATED


def test_T1_cross_device_execution_chain_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.cross_device_execution_chain")


def test_T2_cross_device_execution_chain_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.cross_device_execution_chain")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


def test_U1_local_execution_chain_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.local_execution_chain")


def test_U2_local_execution_chain_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.local_execution_chain")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


def test_V1_hybrid_executor_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.hybrid_executor")


def test_V2_hybrid_executor_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.hybrid_executor")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


def test_W1_remote_execution_mode_resolver_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.remote_execution_mode_resolver")


def test_W2_remote_execution_mode_resolver_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.remote_execution_mode_resolver")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


def test_X1_agent_bridge_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("galaxy_gateway.agent_bridge")


def test_X2_agent_bridge_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("galaxy_gateway.agent_bridge")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


def test_Y1_cross_device_coordinator_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("galaxy_gateway.cross_device_coordinator")


def test_Y2_cross_device_coordinator_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("galaxy_gateway.cross_device_coordinator")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


def test_Z1_execution_spine_pre_registered():
    reg = get_legacy_dispatch_registry()
    assert reg.is_registered("core.execution_spine")


def test_Z2_execution_spine_is_compat_only():
    reg = get_legacy_dispatch_registry()
    entry = reg.get("core.execution_spine")
    assert entry.classification == LegacyDispatchClassification.COMPAT_ONLY


# ===========================================================================
# AA) register_legacy_dispatch convenience function
# ===========================================================================

def test_AA1_register_legacy_dispatch_works():
    reset_registry()
    entry = register_legacy_dispatch(
        "my.legacy.module",
        LegacyDispatchClassification.DEPRECATED,
        reason="test convenience",
        pr_origin="PR-TEST",
    )
    assert entry.module == "my.legacy.module"
    assert entry.pr_origin == "PR-TEST"


# ===========================================================================
# AB) snapshot_registry()
# ===========================================================================

def test_AB1_snapshot_registry_returns_snapshot():
    snap = snapshot_registry()
    assert isinstance(snap, LegacyRegistrySnapshot)


# ===========================================================================
# AC) At least 10 bootstrapped entries
# ===========================================================================

def test_AC1_snapshot_has_minimum_bootstrapped_entries():
    snap = snapshot_registry()
    assert snap.total_entries >= 10, \
        f"Expected at least 10 bootstrapped entries, got {snap.total_entries}"


# ===========================================================================
# AD) __all__ completeness
# ===========================================================================

def test_AD1_all_exports_importable():
    for name in _mod.__all__:
        assert hasattr(_mod, name), f"{name} missing from module"
