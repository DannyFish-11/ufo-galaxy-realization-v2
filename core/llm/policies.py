"""
core/llm/policies.py — LLM Routing Policy
==========================================

**Batch PR-5: Multi-LLM routing decomposition**

This module extracts the provider selection policy from
``core.multi_llm_router`` into an explicit, testable submodule.

Authority sentinel
------------------
``LLM_POLICIES_AUTHORITY = "core.llm.policies"``

Responsibilities
----------------
* ``TASK_ROUTING_PREFERENCES`` — mapping of ``TaskType`` → ordered provider
  preference list.
* ``PROVIDER_MODEL_MAP`` — mapping of provider name → per-task-type model.
* ``PolicyBasedSelector`` — class that selects the best available provider
  for a given task type by applying the routing preference table.

The actual provider health state lives in ``core.multi_llm_router`` and is
consumed here read-only via a provider status query interface.

Design
------
``PolicyBasedSelector.select()`` returns the provider name and model string
for the highest-priority healthy provider, falling back down the preference
list if earlier providers are unavailable or degraded.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.multi_llm_router import (
    ProviderConfig,
    ProviderStatus,
    TaskType,
    TASK_ROUTING_PREFERENCES,
    PROVIDER_MODEL_MAP,
)

logger = logging.getLogger("Galaxy.LLM.Policies")

# ── module authority sentinel ─────────────────────────────────────────────
LLM_POLICIES_AUTHORITY: str = "core.llm.policies"
"""Sentinel: core.llm.policies is the canonical LLM routing policy module.

Import this symbol to assert that a call site is using the decomposed
provider selection policy module.
"""

# Re-export routing tables so callers can import from here instead
__all__ = [
    "LLM_POLICIES_AUTHORITY",
    "TASK_ROUTING_PREFERENCES",
    "PROVIDER_MODEL_MAP",
    "PolicyBasedSelector",
    "ProviderSelectionResult",
]


class ProviderSelectionResult:
    """Result of a provider selection decision.

    Attributes
    ----------
    provider:
        Selected provider name (e.g. ``"anthropic"``).
    model:
        Selected model string (e.g. ``"claude-sonnet-4.6"``).
    task_type:
        The task type used for selection.
    reason:
        Human-readable explanation of why this provider was selected.
    alternatives:
        Ordered list of other providers that were considered.
    skipped:
        Providers that were skipped and the reason (e.g. ``"DOWN"``).
    """

    def __init__(
        self,
        provider: str,
        model: str,
        task_type: TaskType,
        reason: str = "",
        alternatives: Optional[List[str]] = None,
        skipped: Optional[Dict[str, str]] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.task_type = task_type
        self.reason = reason
        self.alternatives = list(alternatives or [])
        self.skipped = dict(skipped or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "task_type": self.task_type.value,
            "reason": self.reason,
            "alternatives": self.alternatives,
            "skipped": self.skipped,
        }

    def __repr__(self) -> str:
        return (
            f"ProviderSelectionResult(provider={self.provider!r}, "
            f"model={self.model!r}, task_type={self.task_type.value!r})"
        )


class PolicyBasedSelector:
    """Select the best available provider for a task type using the policy table.

    Parameters
    ----------
    providers:
        Dict of provider name → ``ProviderConfig``.  This is passed at
        construction time and should reflect the current provider registry.
    allow_degraded:
        If ``True`` (default), degraded providers are used as a fallback
        when no healthy providers are available.
    """

    def __init__(
        self,
        providers: Dict[str, ProviderConfig],
        allow_degraded: bool = True,
    ) -> None:
        self._providers = providers
        self._allow_degraded = allow_degraded

    def select(
        self,
        task_type: TaskType,
        exclude: Optional[List[str]] = None,
    ) -> Optional[ProviderSelectionResult]:
        """Return the best available provider for *task_type*.

        Parameters
        ----------
        task_type:
            The type of task (determines preference ordering).
        exclude:
            Provider names to exclude from selection (e.g. recently failed).

        Returns
        -------
        ProviderSelectionResult or None:
            ``None`` only if no providers are available at all.
        """
        exclusion_set = set(exclude or [])
        preference_list = TASK_ROUTING_PREFERENCES.get(
            task_type, TASK_ROUTING_PREFERENCES.get(TaskType.GENERAL, [])
        )

        healthy_result: Optional[ProviderSelectionResult] = None
        degraded_result: Optional[ProviderSelectionResult] = None
        skipped: Dict[str, str] = {}
        alternatives: List[str] = []

        for provider_name in preference_list:
            if provider_name in exclusion_set:
                skipped[provider_name] = "excluded"
                continue
            cfg = self._providers.get(provider_name)
            if cfg is None:
                skipped[provider_name] = "not_configured"
                continue
            if not cfg.api_key:
                skipped[provider_name] = "no_api_key"
                continue

            model = self._pick_model(provider_name, task_type, cfg)
            result = ProviderSelectionResult(
                provider=provider_name,
                model=model,
                task_type=task_type,
                reason=f"policy preference for {task_type.value}",
                alternatives=[],
                skipped={},
            )

            if cfg.status == ProviderStatus.HEALTHY:
                if healthy_result is None:
                    healthy_result = result
                else:
                    alternatives.append(provider_name)
            elif cfg.status == ProviderStatus.DEGRADED and self._allow_degraded:
                if degraded_result is None:
                    degraded_result = result
                else:
                    alternatives.append(provider_name)
            else:
                skipped[provider_name] = cfg.status.value

        chosen = healthy_result or degraded_result
        if chosen is not None:
            chosen.alternatives = alternatives
            chosen.skipped = skipped
            if chosen is degraded_result:
                chosen.reason = f"fallback to degraded provider for {task_type.value}"
        return chosen

    def _pick_model(
        self,
        provider_name: str,
        task_type: TaskType,
        cfg: ProviderConfig,
    ) -> str:
        """Return the preferred model string for *provider_name* and *task_type*."""
        per_provider = PROVIDER_MODEL_MAP.get(provider_name, {})
        model = per_provider.get(task_type) or per_provider.get(TaskType.GENERAL)
        if model is None:
            model = cfg.default_model
        return model
