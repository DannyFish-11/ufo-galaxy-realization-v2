# Model Routing Authority

> **Status:** Canonical — formalised in this PR; strengthened in PR-1 (architecture freeze);
> confirmed unchanged in PR-0 (unified native-multimodal-first architecture freeze).
> **Scope:** Routing authority for projection-facing model/provider selection semantics.
>
> **PR-0 confirmation:** `TopologyRouter` remains the **sole** canonical routing
> authority.  `TopologyRoutePlan` remains the **sole** canonical routing output
> contract.  This is unchanged.  The addition of a configuration entry surface
> inside `status_board_v2` (Phase D) does **not** alter this invariant —
> configuration entry modifies routing inputs (provider inventory, preferences);
> it never bypasses or replaces `TopologyRouter` as the decision-making authority.
>
> **PR-4 update:** The provider inventory consumed by `TopologyRouter` is now
> driven by the unified config authority.  `ProviderInventory` entries carry
> `config_enabled` / `config_has_key` / `is_candidate_eligible` flags set by
> `core.model_topology.inventory_from_config`.  The routing candidate pool
> (`ProviderInventory.candidate_pool_entries()`) excludes disabled providers
> and providers missing required secrets.  Unconfigured OneAPI is treated as
> **absent** from the candidate pool (not merely disabled).  See
> [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) §2B.
>
> Related: [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) ·
> [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md) ·
> [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md)

---

## 1. Overview

This document defines **the single canonical model-routing authority** for the Galaxy
system. It clarifies which components own routing truth, how downstream surfaces consume
that truth, and which legacy structures are retained only as compatibility bridges.

---

## 2. Canonical Routing Authority Path

```
ProviderInventory  ──┐
                     ├──▶  TopologyRouter  ──▶  TopologyRoutePlan  ──▶  Projection consumers
AggregatorRouterHint ┘          │
                                └─ builds ModelSupplyGraph
                                   applies ModelWeightField per node
                                   runs routing_policy selection
```

### 2.1 Canonical authority module

```
core/model_topology/topology_router.py
```

- **`TopologyRouter`** is the **sole** canonical routing decision-maker.  No other
  component has routing-truth authority.
- **`TopologyRoutePlan`** is the **sole** canonical routing output contract.  Any
  routing summary produced outside of a `TopologyRoutePlan` is a legacy
  compatibility artefact, not an authority source.
- `TopologyRouter.route(phase, domain)` produces a deterministic, stable plan.
- All routing-related projection fields (`selected_model`, `selected_provider`,
  `is_native_multimodal`, `support_models`, `route_reason`) must be sourced from a
  `TopologyRoutePlan` whenever one is available.
- **The desktop status board topology display must consume canonical route truth
  from `TopologyRoutePlan` via the projection layer.**  The topology surface
  must never derive its own routing conclusions.
- **The dashboard is not a routing-truth authority surface.**  Dashboard endpoints
  and frontend state may display routing information, but they do not own it and
  must not be treated as the source of truth.
- **Any routing path that does not originate from `TopologyRouter` is a degraded
  compatibility path**, not a canonical alternative.  These paths are registered
  in `core/orchestration_authority/legacy_paths.py` with
  `LegacyPathStatus.LEGACY_COMPATIBILITY`.

The authority is identified by the sentinel:

```python
# core/model_topology/topology_router.py
CANONICAL_ROUTING_AUTHORITY = "core.model_topology.topology_router.TopologyRouter"
```

---

## 3. What `TopologyRoutePlan` Is Responsible For

`TopologyRoutePlan` is the **stable output contract** produced by `TopologyRouter`.  
It carries:

| Field | Description |
|---|---|
| `primary_model` | Top-ranked `ModelNode`; the canonical primary supply |
| `support_models` | Ordered list of supporting `ModelNode` objects |
| `active_weights` | `node_id → ModelWeightField` for every node considered |
| `route_reason` | Human-readable routing explanation |
| `phase` | `TriStatePhase` used for this plan |
| `domain` | `RuntimeDomain` used for this plan |
| `graph` | `ModelSupplyGraph` built for this plan |

`TopologyRoutePlan.to_dict()` is the stable serialisation format consumed by
downstream projection builders.

---

## 4. How Projection Consumers Read Routing Truth

### 4.1 `RuntimeProjection` (`core/projection/runtime_projection.py`)

`RuntimeProjection` is populated by `build_runtime_projection()` in
`core/projection/projection_compiler.py`.

When a `TopologyRoutePlan` is provided:

- `primary_model_id` ← `route_plan.primary_model.node_id`
- `support_model_ids` ← `[n.node_id for n in route_plan.support_models]`
- `active_weights` ← `{node_id: wf.combined_weight ...}`
- `route_reason` ← `route_plan.route_reason`
- `routing_authority` is set to `CANONICAL_ROUTING_AUTHORITY`

When no `TopologyRoutePlan` is provided, routing fields default to `None` /
empty collections.  `routing_authority` is set to `"none"`.

### 4.2 `DesktopStatusProjection` (`contracts/desktop_status_projection.py`)

`DesktopStatusProjection.model_routing` is a `ModelRoutingProjection` built by
`_build_model_routing_projection(ucp)`.

**Source priority (highest to lowest):**

1. **CANONICAL** — `ucp["topology_route_plan"]` block (`TopologyRoutePlan.to_dict()` output).
   When present, all routing fields are read from this block.  
   `routing_authority_source` is set to `"topology_router"`.

2. **LEGACY COMPAT** — top-level UCP keys (`chosen_model`, `chosen_provider`,
   `is_native_multimodal`, `support_model_ids`, `route_reason`) and the
   `multimodal_route` block (PR-20).  
   `routing_authority_source` is set to `"legacy_ucp_keys"`.

The `routing_authority_source` field on `ModelRoutingProjection` tells consumers
which path was taken.  Any consumer that receives `routing_authority_source != "topology_router"`
should treat the routing data as a **degraded compatibility result from a non-canonical
authority path**.  It must not be presented as authoritative topology state.

---

## 5. Legacy Compatibility Routing Semantics

The following structures are retained **for backward compatibility only**.  They are
**not** routing authority sources and must never be treated as canonical.  All are
classified as degraded compatibility paths:

| Structure | Role | Canonical replacement |
|---|---|---|
| `core.multi_llm_router.MultiLLMRouter` | Legacy multi-provider LLM selector | `TopologyRouter` |
| `dashboard.backend.main` (provider routing endpoints) | Legacy dashboard provider list — **not a routing-truth authority** | `TopologyRouter` via `ProviderInventory` |
| `ucp["chosen_model"]` / `ucp["chosen_provider"]` top-level keys | Legacy UCP compat keys | `ucp["topology_route_plan"]` |
| `ucp["multimodal_route"]` block | PR-20 multimodal route compat | `ucp["topology_route_plan"]` (preferred) |

These paths are registered in `core/orchestration_authority/legacy_paths.py` with
`LegacyPathStatus.LEGACY_COMPATIBILITY`.

### 5.1 What must no longer claim routing authority

- **`dashboard/` endpoints must not define the active model/provider selection.**
  The dashboard is not a routing-truth authority surface; it is in retirement per
  [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md).
- `MultiLLMRouter` must not be used as the primary routing decision-maker for new code.
- Top-level scattered `chosen_model` / `chosen_provider` keys in the UCP must not be
  used directly when a `topology_route_plan` block is present.
- **Any summary of routing state that does not originate from `TopologyRoutePlan` is a
  degraded compatibility result**, not an authoritative routing view.  Such summaries
  must be labelled as `routing_authority_source: "legacy_ucp_keys"` or similar so that
  consumers can detect the degraded state.

---

## 6. Data Flow Diagram (Canonical Path)

```
ProviderInventory (inventory of providers/models)
    │
    ▼
TopologyRouter.route(phase, domain)          ← CANONICAL AUTHORITY
    │
    ▼
TopologyRoutePlan {                          ← CANONICAL OUTPUT CONTRACT
    primary_model,
    support_models,
    active_weights,
    route_reason,
    phase,
    domain,
    graph
}
    │
    ├──▶ RuntimeProjection                   ← STATUS BOARD V2 / PROJECTION ENDPOINT
    │       (via build_runtime_projection)
    │       routing_authority = "core.model_topology.topology_router.TopologyRouter"
    │
    └──▶ DesktopStatusProjection             ← SHELL-FACING STATUS CONTRACT
            (via _build_model_routing_projection reading ucp["topology_route_plan"])
            routing_authority_source = "topology_router"
```

---

## 7. Guardrails and Tests

Guardrails are implemented in `tests/test_pr53_model_routing_authority.py`:

- `TopologyRouter` output is correctly reflected in `RuntimeProjection` routing fields.
- `DesktopStatusProjection` prefers `topology_route_plan` over legacy UCP keys.
- Legacy bridge inputs do not override `topology_route_plan` when present.
- `CANONICAL_ROUTING_AUTHORITY` sentinel is importable from `topology_router`.
- `routing_authority_source` on `ModelRoutingProjection` correctly reflects the source used.

Legacy routing paths are registered in `core/orchestration_authority/legacy_paths.py`
(PR-routing-authority entries).

---

## 9. L1 — LLM Cognitive Routing Authority Closure

> **Status:** Implemented in PR-L1.

### 9.1 The L1 Problem

Before L1, LLM routing decisions were scattered across the codebase.
Provider-specific code, feature routes, and fallback paths each imported
`core.multi_llm_router.get_llm_router()` directly and made implicit routing
decisions without going through any single canonical gate.  The result was:

- Provider code acting as a de-facto route authority.
- Feature-specific branches silently acquiring their own model-selection
  semantics.
- Fallback paths redefining routing intent without any visibility.

### 9.2 L1 Canonical LLM Routing Authority

```
core/llm/route_authority.py
```

- **`LLMRouteAuthority`** is the **single canonical gate** for all LLM
  model-selection decisions.  All cognitive / LLM routing requests must pass
  through `LLMRouteAuthority.resolve()` before reaching provider supply.
- **`LLMRouteRequest`** is the explicit input contract for a routing decision.
- **`LLMRouteDecision`** is the output contract carrying the decision, routing
  reason, and the `LLM_ROUTE_AUTHORITY` sentinel.
- **`get_llm_route_authority()`** is the canonical factory function.  Callers
  that previously used `core.multi_llm_router.get_llm_router()` for routing
  decisions must switch to `get_llm_route_authority()`.

The authority sentinel:

```python
# core/llm/route_authority.py
LLM_ROUTE_AUTHORITY = "core.llm.route_authority.LLMRouteAuthority"
```

### 9.3 L1 Authority / Supply Separation

| Layer | Module | Role |
|---|---|---|
| **Routing authority** | `core.llm.route_authority.LLMRouteAuthority` | Decides which model/provider handles a cognitive task |
| **Provider supply** | `core.multi_llm_router.MultiLLMRouter` | Supplies provider instances, executes LLM calls, manages failover |

Provider supply code must not override routing decisions made by
`LLMRouteAuthority`.  Feature-specific code must not make routing decisions
outside the canonical authority.

### 9.4 Canonical LLM Routing Data Flow (L1)

```
LLMRouteRequest {task_type, complexity, preferred_provider, feature_context}
    │
    ▼
LLMRouteAuthority.resolve()               ← L1 CANONICAL ROUTING AUTHORITY
    │  (consults MultiLLMRouter.route() for provider policy)
    ▼
LLMRouteDecision {provider, model, reason, authority=LLM_ROUTE_AUTHORITY}
    │
    ▼
MultiLLMRouter (provider supply / execution)  ← supply layer only
    │
    ▼
LLMResponse
```

### 9.5 Legacy Paths Updated in L1

The following scattered routing paths were updated to route through
`LLMRouteAuthority`:

- `core/routes/ai.py` (twin + swarm agent creation)
- `core/routes/nodes.py` (node execution router)
- `core/routes/system.py` (LLM router status + hot-reload)
- `core/routes/observability.py` (diagnostic model-route endpoint)
- `core/system_integration.py` (built-in chat capability)

The following paths were registered as `LEGACY_COMPATIBILITY` in
`core/orchestration_authority/legacy_paths.py` (PR-L1 entries) and are
scheduled for migration in a future L1-continuation PR:

- `core.openclawd.OpenClawd`
- `core.agent.kernel.AgentKernel`
- `core.ai_intent.IntentParser`
- `galaxy_gateway.orchestrator.galaxy_orchestrator`
- `dashboard.backend.main`

### 9.6 L1 Tests

Guardrails for L1 routing authority closure are implemented in
`tests/test_l1_llm_routing_authority.py`.

---

## 10. L2 — Canonical Model Supply Truth, Provider Ordering, and Fallback Legality

> **Status:** Implemented in PR-L2.

### 10.1 The L2 Problem

After L1, routing authority (deciding *where* to route) was centralised in
`LLMRouteAuthority`.  However, supply authority (deciding *whether* a route
can be satisfied and *how* to degrade legally) was still scattered:

- Provider ordering was implicit in scattered `route()` calls rather than
  defined in one explicit canonical place.
- Unavailable providers could trigger ad-hoc provider-specific substitution
  without any declared legality basis.
- Fallback paths could silently redefine the practical model served without
  surfacing the reason.
- Emergency / "best-effort" provider shortcuts could short-circuit canonical
  ordering.

### 10.2 L2 Canonical Supply Authority

```
core/llm/supply_authority.py
```

- **`LLMSupplyAuthority`** is the **single canonical gate** for supply
  resolution.  It sits between `LLMRouteDecision` (L1 output) and provider
  execution.
- **`FallbackLegality`** is the explicit vocabulary of legal fallback bases.
  Any fallback that cannot be classified is rejected.
- **`ProviderOrderingPolicy`** makes provider ordering explicit and consistent
  in one place rather than scattered across integrations.
- **`SupplyResolutionResult`** is the canonical output contract: it always
  states which provider/model was *requested*, which was *supplied*, and the
  exact *legal basis* for any fallback taken.
- **`get_llm_supply_authority()`** is the canonical factory function.

The authority sentinel:

```python
# core/llm/supply_authority.py
LLM_SUPPLY_AUTHORITY = "core.llm.supply_authority.LLMSupplyAuthority"
```

### 10.3 L2 Authority / Supply / Execution Separation

| Layer | Module | Role |
|---|---|---|
| **Routing authority (L1)** | `core.llm.route_authority.LLMRouteAuthority` | Decides *intent*: which provider/model to use |
| **Supply authority (L2)** | `core.llm.supply_authority.LLMSupplyAuthority` | Decides *satisfaction*: can intent be met legally? |
| **Execution** | `core.multi_llm_router.MultiLLMRouter` | Performs the actual LLM API call |

Provider-specific code must not perform supply resolution independently.
Emergency / shortcut paths inside providers are not permitted to override the
canonical supply decision produced by `LLMSupplyAuthority`.

### 10.4 Fallback Legality Contract

Fallback is ONLY permitted under one of these explicit bases:

| `FallbackLegality` | Meaning |
|---|---|
| `NONE` | No fallback; primary was satisfied directly |
| `PRIMARY_UNAVAILABLE` | Primary provider is DOWN or missing API key |
| `PRIMARY_DEGRADED` | Primary provider is DEGRADED; policy allows degraded fallback |
| `CAPABILITY_MISMATCH` | Primary lacks a required capability (tool-use, multimodal, etc.) |
| `EXPLICIT_CALLER_PREFERENCE` | Caller's `preferred_provider` was unavailable; L1 consented to fall through |
| `NO_SUPPLY_AVAILABLE` | No provider could be supplied under any legal basis |

Any fallback that cannot be classified under one of the first four bases is
rejected; `SupplyResolutionResult.is_satisfied` is `False`.

### 10.5 Canonical L2 Data Flow

```
LLMRouteDecision {provider, model, reason, authority=LLM_ROUTE_AUTHORITY}
    │  (L1 canonical route intent)
    ▼
LLMSupplyAuthority.resolve_supply(decision, supply_state)   ← L2 CANONICAL SUPPLY GATE
    │  1. Build canonical ordered provider list from supply_state
    │     (route_intent → fallback_candidates → available_ids)
    │  2. Walk ordered list; check health + capabilities
    │  3. Classify any fallback under FallbackLegality
    │  4. Stop at first legally satisfiable provider
    ▼
SupplyResolutionResult {
    requested_provider, requested_model,   ← what L1 asked for
    supplied_provider, supplied_model,     ← what supply gives
    fallback_legality,                     ← explicit legal basis
    ordering_basis,                        ← how ordering was derived
    is_satisfied,                          ← can we proceed?
    resolution_trace,                      ← full audit trail
    authority = LLM_SUPPLY_AUTHORITY,
}
    │
    ▼
MultiLLMRouter (execution layer — supply truth is now canonical)
```

### 10.6 Provider Ordering Contract

Provider ordering is derived from the canonical supply snapshot passed to
`LLMSupplyAuthority.resolve_supply()`.  The algorithm is defined once here
and is never inferred ad-hoc inside a provider-specific integration.

Ordering priority (highest first):

1. Provider explicitly named in the `LLMRouteDecision` (canonical route intent).
2. Available providers in the canonical `fallback_candidates` list of the
   supply snapshot (when `prefer_canonical_fallback_list=True`).
3. Remaining available providers from `available_provider_ids`.
4. Any providers in the supply records that are not DOWN (safety net).

Providers with health status DOWN are always excluded.

### 10.7 L2 Tests

Guardrails for L2 supply authority closure are implemented in
`tests/test_l2_model_supply_authority.py`.

---


For new code producing routing decisions:

1. Build a `ProviderInventory` from your provider/model list.
2. Instantiate `TopologyRouter(inventory)`.
3. Call `router.route(phase, domain)` to get a `TopologyRoutePlan`.
4. Embed `plan.to_dict()` as `ucp["topology_route_plan"]` in the `UnifiedControlPlan`.
5. Pass the `UnifiedControlPlan` to `build_desktop_status_projection()`.

For existing code still populating `chosen_model` / `chosen_provider` top-level keys:  
— Continue doing so for backward compatibility, but add `topology_route_plan` when possible.
— These keys are now explicitly classified as legacy compat fallbacks.

---

## 11. L3 — Canonical Cognitive Input Assembly Authority

### 11.1 The L3 Problem

After L1 (routing authority) and L2 (supply / fallback legality) were unified,
context assembly remained scattered.  Different features attach prompt prefixes,
memory blocks, tool manifests, runtime state, user metadata, continuity context,
or execution hints in slightly different ways:

- `AgentKernel._fallback_chat` assembles system prompt + user policy + history
  + user message locally.
- `OpenCodeEngine.generate_code_async` assembles its own system prompt + user
  content + context dict independently.
- `AgentFactory._build_agent_generation_prompt` constructs a prompt string with
  soul policy + task description + schema in yet another private path.
- Feature-specific helpers in `enhancements/` define their own prompt builders.

The result was that the system had no single authoritative answer to: *"What
cognitive context did the model actually receive, and under whose rules was it
assembled?"*

### 11.2 L3 Canonical Cognitive Input Assembly Authority

The L3 closure is implemented in `core/llm/context_authority.py`.

**`CognitiveContextAuthority`** is the **single canonical cognitive input
assembly authority**.  All cognitive context (prompt, memory, tools, runtime
state, policy constraints, continuity data, execution metadata) must be
assembled through `CognitiveContextAuthority.assemble()` before being passed
to provider formatting and model invocation.

The authority sentinel:

```python
# core/llm/context_authority.py
LLM_CONTEXT_AUTHORITY = "core.llm.context_authority.CognitiveContextAuthority"
```

- **`get_cognitive_context_authority()`** is the canonical factory function.
- **`CognitiveContextRequest`** is the input contract — all cognitive inputs
  are expressed as fields of this dataclass before assembly.
- **`CognitiveContextAssembly`** is the canonical output — carries the
  assembled `messages` list, `tool_manifest`, `assembly_trace`, and the
  `LLM_CONTEXT_AUTHORITY` sentinel.

### 11.3 L3 Authority / Supply / Context Separation

| Layer | Module | Role |
|---|---|---|
| **Routing authority (L1)** | `core.llm.route_authority.LLMRouteAuthority` | Decides *intent*: which provider/model to use |
| **Supply authority (L2)** | `core.llm.supply_authority.LLMSupplyAuthority` | Decides *satisfaction*: can intent be met legally? |
| **Context authority (L3)** | `core.llm.context_authority.CognitiveContextAuthority` | Assembles *cognitive world*: what the model actually receives |
| **Execution** | `core.multi_llm_router.MultiLLMRouter` | Performs the actual LLM API call |

Provider-specific code must not assemble cognitive context independently.
Feature-specific prompt builders must terminate in `CognitiveContextAuthority`.
Retry, fallback, replay, and recovery paths must use the same `assemble()` call
and the same `CognitiveContextRequest`.

### 11.4 Canonical Assembly Order Contract

The canonical cognitive context is **always** assembled in the following order:

1. **System message** — constructed from, in order:
   a. `system_prefix` — base identity / role (default: "You are Galaxy, an intelligent AI assistant.")
   b. `soul_policy` — SOUL constraints (task_execute / hybrid paths only)
   c. `agents_policy` — AGENTS policy
   d. `user_policy` — USER preferences
   e. `policy_constraints` — additional free-form policy constraints
   f. `memory_context` — long-term / retrieved memory
   g. `continuity_context` — session continuity / replay context
   h. `execution_metadata` — operational hints (retry count, recovery flag, etc.)

2. **Conversation history** — the most recent `max_history_turns` turns from
   `conversation_history`, in chronological order.

3. **Current user message** — appended as the final `{"role": "user", ...}` entry.

Feature-specific code must not redefine this order.

### 11.5 Canonical L3 Data Flow

```
CognitiveContextRequest {
    task_type, system_prefix,
    soul_policy, agents_policy, user_policy, policy_constraints,
    memory_context, continuity_context,
    conversation_history, tool_manifest,
    user_message, session_id, feature_context,
    execution_mode, execution_metadata,
    max_history_turns,
}
    │
    ▼
CognitiveContextAuthority.assemble(request)   ← L3 CANONICAL CONTEXT GATE
    │  1. Build system message (prefix → soul → agents → user → constraints
    │                           → memory → continuity → metadata)
    │  2. Append conversation history (bounded by max_history_turns)
    │  3. Append user message
    │  4. Record full assembly trace
    ▼
CognitiveContextAssembly {
    messages,           ← canonical OpenAI-compatible message list
    tool_manifest,      ← normalised tool declarations (may be None)
    assembly_trace,     ← ordered audit list of assembled inputs
    authority,          ← LLM_CONTEXT_AUTHORITY sentinel
    is_canonical,       ← True for canonical path
    source_request,     ← originating CognitiveContextRequest
}
    │
    ▼
LLMRouteAuthority (L1) → LLMSupplyAuthority (L2) → MultiLLMRouter (execution)
```

### 11.6 Retry / Fallback / Recovery Contract

Retry, fallback, replay, and recovery paths **must** assemble context by
calling `CognitiveContextAuthority.assemble()` with the same
`CognitiveContextRequest` as the original path.  They must not rebuild the
message list independently.

Any retry-specific operational metadata (e.g. `retry_count`, `recovery_reason`)
may be passed via `execution_metadata`.  The assembly order and cognitive
meaning remain unchanged.

### 11.7 L3 Tests

Guardrails for L3 context authority closure are implemented in
`tests/test_l3_cognitive_context_authority.py`.

---

## 12. L4 — Cognitive Execution Authority Boundary Closure

### 12.1 Summary

L4 closes the final layer of the cognitive authority stack.  It establishes
`CognitiveExecutionAuthority` as the **single canonical gate** through which all
LLM invocations must pass after L3 context assembly and L2 supply resolution.
With L4 in place, `ufo-galaxy-realization-v2` unambiguously owns:

| Authority | Layer | Module |
|---|---|---|
| Routing truth | L1 | `core.llm.route_authority.LLMRouteAuthority` |
| Supply legality truth | L2 | `core.llm.supply_authority.LLMSupplyAuthority` |
| Context assembly truth | L3 | `core.llm.context_authority.CognitiveContextAuthority` |
| **Cognitive execution semantics** | **L4** | **`core.llm.execution_authority.CognitiveExecutionAuthority`** |

Providers, adapters, transports, and compatibility shims are explicitly
subordinate to this boundary.  They contribute:

- **Execution capability** — making the actual API call.
- **Transport formatting** — converting the canonical message list to the wire
  format the provider accepts.
- **Raw output** — returning the provider's raw API response.

They must NOT:

- Decide which model or provider to use (L1 authority).
- Reinterpret cognitive context (L3 authority).
- Define fallback semantics (L2 authority).
- Normalize or interpret the response content as final cognitive truth (L4 authority).

### 12.2 L4 Canonical Cognitive Execution Authority

```
core/llm/execution_authority.py
```

**`CognitiveExecutionAuthority`** is the **single canonical gate** through which
all LLM invocations must pass.  It:

1. Verifies the context assembly carries the `LLM_CONTEXT_AUTHORITY` sentinel
   (confirming L3 was used).
2. Verifies the supply result carries the `LLM_SUPPLY_AUTHORITY` sentinel
   (confirming L2 was used) and that supply is satisfied.
3. Delegates raw execution to the provider adapter (capability only).
4. Normalizes the raw provider output under center-owned semantics.
5. Embeds `LLM_EXECUTION_AUTHORITY` in the canonical result.

The authority sentinel:

```python
# core/llm/execution_authority.py
LLM_EXECUTION_AUTHORITY = "core.llm.execution_authority.CognitiveExecutionAuthority"
```

- **`get_cognitive_execution_authority()`** is the canonical factory function.
- **`CognitiveExecutionRequest`** is the input contract — carries the L3
  context assembly, L2 supply resolution, and execution parameters.
- **`CognitiveExecutionResult`** is the canonical output — carries normalized
  content, tool calls, execution trace, and the `LLM_EXECUTION_AUTHORITY`
  sentinel.

### 12.3 Complete L1–L4 Authority Stack

```
CognitiveContextRequest  ──▶  CognitiveContextAuthority.assemble()  (L3)
                                    │
                                    ▼
                              CognitiveContextAssembly { authority=LLM_CONTEXT_AUTHORITY }
                                    │
LLMRouteDecision (L1)  ─────────────┤
SupplyResolutionResult (L2) ─────────┤
                                    ▼
                              CognitiveExecutionAuthority.execute()  (L4)
                                    │  1. Verify LLM_CONTEXT_AUTHORITY sentinel
                                    │  2. Verify LLM_SUPPLY_AUTHORITY sentinel + is_satisfied
                                    │  3. Dispatch to provider (capability only)
                                    │  4. Normalize output (center-owned semantics)
                                    ▼
                              CognitiveExecutionResult {
                                  content,        ← center-owned normalized text
                                  tool_calls,     ← canonical OpenAI-compatible format
                                  provider,       ← from supply resolution (not provider-local)
                                  model,          ← from supply resolution (not provider-local)
                                  authority,      ← LLM_EXECUTION_AUTHORITY sentinel
                                  execution_trace,← ordered audit list
                                  source_context, ← CognitiveContextAssembly (L3)
                                  source_supply,  ← SupplyResolutionResult (L2)
                                  raw_response,   ← raw provider output (not authoritative)
                              }
```

### 12.4 Center/Provider Cognitive Authority Boundary

The boundary is explicit and enforced at the `execute()` gate:

| Responsibility | Owner |
|---|---|
| Which provider/model to use | L1 `LLMRouteAuthority` |
| Whether supply is legal | L2 `LLMSupplyAuthority` |
| What context the model receives | L3 `CognitiveContextAuthority` |
| How execution is performed | L4 `CognitiveExecutionAuthority` |
| How output is normalized/interpreted | L4 `CognitiveExecutionAuthority` |
| Raw API call mechanics | Provider adapter (capability only) |
| Wire format translation | Provider adapter (formatting only) |
| Raw API response | Provider adapter (raw output only) |

Provider-specific code that attempts to re-interpret cognitive context, override
the model selection, or define private normalization semantics violates this
boundary.

### 12.5 Response Normalization Contract

Final output interpretation and normalization are performed once, here, under
center-owned semantics:

- `content` is always a `str` (empty string when the provider returns no text).
- `tool_calls` is always `None` or a list of dicts in canonical OpenAI-compatible
  tool-call format (provider-specific formats are translated).
- `raw_response` is preserved for diagnostics but is **not** used as the
  authoritative interpretation of cognitive output.

### 12.6 Retry / Fallback / Compatibility Contract

Retry, fallback, replay, and recovery paths MUST:

1. Use the same `CognitiveContextAssembly` (from L3) — do not rebuild context
   independently.
2. Use a fresh `SupplyResolutionResult` from L2 if the supply path changes
   (primary failed, fallback taken).
3. Call `CognitiveExecutionAuthority.execute()` for every attempt — never bypass
   the execution gate.
4. Pass retry/fallback metadata via `CognitiveExecutionRequest.execution_metadata`
   so the trace records the attempt context.

Compatibility shims and legacy paths must not define parallel cognitive truth.
They must either be updated to flow through `CognitiveExecutionAuthority` or be
registered as `LegacyPathStatus.LEGACY_COMPATIBILITY` paths in
`core/orchestration_authority/legacy_paths.py`.

### 12.7 L4 Tests

Guardrails for L4 cognitive execution authority boundary closure are implemented
in `tests/test_l4_cognitive_execution_authority.py`.
