"""tests/test_llm_router_provider_wiring.py
==============================================
Provider-wiring regression guards for the "honest cloud fallback" change
(2026-07-15).

Covers four properties that were silently broken/incomplete before:

  1. OpenRouter (OpenAI-compatible aggregator) is a real, fully-wired provider:
     present in the env-key map, the adapter map, and the declarative
     PROVIDER_REGISTRY (with an openrouter.ai base_url).
  2. agnes / moonshot / openrouter are actually reachable by auto-routing —
     i.e. each appears in at least one TASK_ROUTING_PREFERENCES list (they were
     registered but absent from every preference list, so never auto-selected).
  3. "hf_local" no longer pollutes the preference lists — its internal adapter
     was never implemented, so it could never register, yet it sat 2nd in every
     list. It must appear in NO TASK_ROUTING_PREFERENCES list.
  4. The YAML routing policy is local-first: every task_routing priority list
     starts with "ollama".
"""

from __future__ import annotations

import pathlib

import yaml

from core.multi_llm_router import (
    _PROVIDER_ENV_KEY_MAP,
    ADAPTER_MAP,
    PROVIDER_REGISTRY,
    TASK_ROUTING_PREFERENCES,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_POLICY_PATH = _REPO_ROOT / "config" / "llm_routing_policy.yaml"


# ── 1. OpenRouter is a real, fully-wired provider ────────────────────────────
def test_openrouter_in_env_key_map():
    assert _PROVIDER_ENV_KEY_MAP.get("openrouter") == "OPENROUTER_API_KEY"


def test_openrouter_in_adapter_map():
    assert "openrouter" in ADAPTER_MAP


def test_openrouter_registered_with_base_url():
    entries = [e for e in PROVIDER_REGISTRY if e.get("name") == "openrouter"]
    assert len(entries) == 1, "openrouter must have exactly one registry entry"
    assert "openrouter.ai" in entries[0]["base_url"]


# ── 2. agnes / moonshot / openrouter are reachable by auto-routing ───────────
def test_new_providers_appear_in_some_preference_list():
    all_prefs = {p for prefs in TASK_ROUTING_PREFERENCES.values() for p in prefs}
    for provider in ("agnes", "moonshot", "openrouter"):
        assert provider in all_prefs, f"{provider} unreachable by auto-routing"


# ── 3. hf_local removed from all preference lists ────────────────────────────
def test_hf_local_absent_from_all_preference_lists():
    for task_type, prefs in TASK_ROUTING_PREFERENCES.items():
        assert "hf_local" not in prefs, f"hf_local still in {task_type} preferences"


# ── 4. YAML routing policy is local-first ────────────────────────────────────
def test_yaml_task_routing_is_local_first():
    with _POLICY_PATH.open("r", encoding="utf-8") as fh:
        policy = yaml.safe_load(fh)

    task_routing = policy["task_routing"]
    assert task_routing, "task_routing section must not be empty"

    for task_name, spec in task_routing.items():
        priorities = spec["priorities"]
        assert priorities, f"{task_name} priorities must not be empty"
        assert priorities[0] == "ollama", f"{task_name} must be local-first (ollama at index 0)"
