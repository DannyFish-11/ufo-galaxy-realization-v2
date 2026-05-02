# OPERATOR SURFACE CLOSURE AUDIT 2026
## Galaxy V2 + Android Dual-Repo — Operator-Plane Truth and Gap Analysis

**Document authority:** Code-grounded audit only. All claims are traced to real class names,  
function names, file paths, constant names, and config key names sourced directly from  
repository code as of the audit date.

**Repos audited:**
- V2 (local): `core/`, `config/`, `config.json` — Galaxy Python/FastAPI center
- Android (remote): `DannyFish-11/ufo-galaxy-android` — Kotlin/Android client

**Audit date:** 2026  
**Auditor:** Copilot — automated source-read, zero hallucination policy

---

## Table of Contents

1. [Operator-Facing Inventory](#section-1-operator-facing-inventory)
2. [Authoritative Ownership Map](#section-2-authoritative-ownership-map)
3. [Read/Write Path Map](#section-3-readwrite-path-map)
4. [Current Surface Map](#section-4-current-surface-map)
5. [Missing Surface Map](#section-5-missing-surface-map)
6. [Docking / Integration Model](#section-6-dockingintegration-model)
7. [Warnings and Semantics](#section-7-warnings-and-semantics)
8. [Final Operator-Plane Truth Verdict](#section-8-final-operator-plane-truth-verdict)

---

## Section 1: Operator-Facing Inventory

Every item here is grounded in a real class, constant, field, config key, or file that was
read from source. Items are organized by category within each repo.

---

### 1.A — V2 Repository Items

#### 1.A.1 — Config Items (V2)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| C-V2-01 | `providers.openai.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable OpenAI provider |
| C-V2-02 | `providers.anthropic.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable Anthropic |
| C-V2-03 | `providers.gemini.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable Gemini |
| C-V2-04 | `providers.deepseek.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable DeepSeek |
| C-V2-05 | `providers.groq.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable Groq |
| C-V2-06 | `providers.openrouter.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable OpenRouter |
| C-V2-07 | `providers.oneapi.enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Enable/disable OneAPI aggregator |
| C-V2-08 | `providers.oneapi.base_url` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | OneAPI base URL (non-secret) |
| C-V2-09 | `routing.native_multimodal_policy` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Multimodal policy: `strict` / `prefer` / `allow_fallback` (see `VALID_NATIVE_MM_POLICIES`) |
| C-V2-10 | `routing.default_provider` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Default LLM provider name |
| C-V2-11 | `network.gateway_url` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | V2 gateway URL |
| C-V2-12 | `network.android_gateway_url` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | Android-facing gateway URL |
| C-V2-13 | `network.nats_url` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | NATS server URL |
| C-V2-14 | `network.ats_url` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | ATS endpoint URL |
| C-V2-15 | `network.webrtc_stun_url` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | WebRTC STUN server URL |
| C-V2-16 | `android.inference_mode` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | `center` / `local` / `hybrid` (see `VALID_ANDROID_INFERENCE_MODES`) |
| C-V2-17 | `android.vlm_service_enabled` | config | V2 | `core/config_schema.py` → `CONFIG_KEYS` | VLM service toggle on Android side |
| C-V2-18 | `OPENAI_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | OpenAI secret key (secrets.env only) |
| C-V2-19 | `ANTHROPIC_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | Anthropic secret |
| C-V2-20 | `GEMINI_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | Gemini secret |
| C-V2-21 | `DEEPSEEK_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | DeepSeek secret |
| C-V2-22 | `GROQ_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | Groq secret |
| C-V2-23 | `OPENROUTER_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | OpenRouter secret |
| C-V2-24 | `ONEAPI_API_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | OneAPI secret |
| C-V2-25 | `GALAXY_API_TOKEN` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | Galaxy gateway auth token |
| C-V2-26 | `SECRETVAULT_MASTER_KEY` | config | V2 | `core/config_schema.py` → `SECRET_KEYS` | Credential vault master key |
| C-V2-27 | `default_llm_model` | config | V2 | `config.json` | Default LLM model name (`"gpt-4o"`) |
| C-V2-28 | `web_ui_port` | config | V2 | `config.json` | Legacy web UI port fallback (9000) |
| C-V2-29 | `prefer_autonomous` | config | V2 | `config.json` | Autonomous execution preference flag |
| C-V2-30 | `parallel_execution_enabled` | config | V2 | `config.json` | Enable parallel task execution |
| C-V2-31 | `enable_continuum` | config | V2 | `config.json` | Toggle continuum cognitive engine |
| C-V2-32 | `enable_perception` | config | V2 | `config.json` | Toggle host perception module |
| C-V2-33 | `enable_human_field` | config | V2 | `config.json` | Toggle human field in continuum |
| C-V2-34 | `enable_liminal_field` | config | V2 | `config.json` | Toggle liminal field in continuum |
| C-V2-35 | `enable_decision_gate` | config | V2 | `config.json` | Toggle decision gate in continuum |
| C-V2-36 | `enable_desktop_presence_runtime` | config | V2 | `config.json` | Toggle `DesktopPresenceRuntime` shell |
| C-V2-37 | `enable_task_dag` | config | V2 | `config.json` | Toggle task DAG / retry subsystem |
| C-V2-38 | `task_dag_default_max_retries` | config | V2 | `config.json` | Default max retries for DAG tasks |
| C-V2-39 | `enable_webrtc_session_manager` | config | V2 | `config.json` | Toggle WebRTC session manager |
| C-V2-40 | `transport_prefer_webrtc` | config | V2 | `config.json` | Prefer WebRTC transport to Android |
| C-V2-41 | `transport_fallback_to_screenshot` | config | V2 | `config.json` | Allow screenshot fallback transport |
| C-V2-42 | `enable_cognitive_field_engine` | config | V2 | `config.json` | Toggle Block-3 cognitive field engine |
| C-V2-43 | `cognitive_manifest_threshold` | config | V2 | `config.json` | Manifest-state confidence threshold |
| C-V2-44 | `cognitive_passive_threshold` | config | V2 | `config.json` | Passive/silent threshold |
| C-V2-45 | `enable_cognitive_memory_split` | config | V2 | `config.json` | Toggle working vs long-term memory split |
| C-V2-46 | `working_memory_capacity` | config | V2 | `config.json` | Working memory entry capacity (20) |
| C-V2-47 | `long_term_memory_max_entries` | config | V2 | `config.json` | Long-term memory cap (500) |

#### 1.A.2 — Runtime State Items (V2)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| RS-V2-01 | `TriState` (SILENT / LIMINAL / MANIFEST) | runtime_state | V2 | `core/desktop_presence_runtime.py` → `TriState` enum | Canonical subject lifecycle tri-state |
| RS-V2-02 | `runtime_session_id` | runtime_state | V2 | `core/desktop_presence_runtime.py` → `handle_request()` | Per-request stable correlation ID propagated through all downstream layers |
| RS-V2-03 | NATS connection state (`is_connected()`, `get_stats()`) | runtime_state | V2 | `core/nats_bus.py` → `NATS_FABRIC_CARRIER_AUTHORITY` | Whether NATS carrier fabric is live; stats dict |
| RS-V2-04 | NATS heartbeat interval / worker version | runtime_state | V2 | `core/nats_heartbeat.py` → `NodeHeartbeatSender` | `GALAXY_HEARTBEAT_INTERVAL`, `GALAXY_WORKER_VERSION` env vars |
| RS-V2-05 | OpenClawd heartbeat state (`is_enabled()`, `_cycle_count`) | runtime_state | V2 | `core/openclawd_heartbeat.py` → `HeartbeatScheduler` | Heartbeat enabled, cycle count, tier1/tier2 model selection |
| RS-V2-06 | `OperatorSnapshot` (active tasks, devices, topology, capabilities) | runtime_state | V2 | `core/operator_surface.py` → `OperatorSnapshot` | Compact multi-dimensional runtime snapshot produced by `OperatorSurface.operator_snapshot()` |
| RS-V2-07 | `TaskInspection` fields (lifecycle, routing, result, failure_domain) | runtime_state | V2 | `core/operator_surface.py` → `TaskInspection` dataclass | Per-task canonical read-only projection |
| RS-V2-08 | `RouteInspection` fields (transport_strategy, effective_path, admissibility_verdict) | runtime_state | V2 | `core/operator_surface.py` → `RouteInspection` dataclass | Per-task routing decision projection |
| RS-V2-09 | `ExecutorInspection` fields (presence_state, last_heartbeat, is_online, fabric_reachable) | runtime_state | V2 | `core/operator_surface.py` → `ExecutorInspection` dataclass | Per-executor presence and capability projection |
| RS-V2-10 | `FailureDomainInspection` (failure_domain, retry_count, fallback_triggered) | runtime_state | V2 | `core/operator_surface.py` → `FailureDomainInspection` dataclass | Failure domain and retry history |
| RS-V2-11 | `LineageInspection` (ancestor_chain, children, retry_chain, timeline) | runtime_state | V2 | `core/operator_surface.py` → `LineageInspection` dataclass | Task graph lineage |
| RS-V2-12 | `RecoveryInspection` (is_recovered, recovery_disposition, current_owner) | runtime_state | V2 | `core/operator_surface.py` → `RecoveryInspection` dataclass | Recovery state after interruption |
| RS-V2-13 | `PartialResultInspection` (lifecycle_state, partial_result_disposition, resume_count) | runtime_state | V2 | `core/operator_surface.py` → `PartialResultInspection` dataclass | Hybrid execution partial-result state |
| RS-V2-14 | `AuditEvidenceInspection` (has_evidence, evidence_count, by_kind) | runtime_state | V2 | `core/operator_surface.py` → `AuditEvidenceInspection` dataclass | Durable audit evidence coverage |
| RS-V2-15 | `DevicePresenceSummary` (presence_state, is_ready, last_seen, capability_tags) | runtime_state | V2 | `core/operator_surface.py` → `DevicePresenceSummary` dataclass | Per-device presence and readiness |
| RS-V2-16 | `FlowOperatorProjection` (current_execution_phase, blocking_reason, recovery_status, truth_alignment_status) | runtime_state | V2 | `core/flow_level_operator_surface.py` → `FlowOperatorProjection` dataclass | Delegated flow operator view — Android execution phase, blocking, recovery, result convergence |
| RS-V2-17 | `AndroidExecutionPhase` enum values | runtime_state | V2 | `core/flow_level_operator_surface.py` → `AndroidExecutionPhase` | planning / grounding / execution / replan / stagnation / gate_decision / takeover / collaboration / completed / failed / unknown |
| RS-V2-18 | `AndroidCanonicalExecutionEvent` (phase, step_index, is_blocking, blocking_reason, policy_gate) | runtime_state | V2 | `core/flow_level_operator_surface.py` → `AndroidCanonicalExecutionEvent` dataclass | Per-event Android execution signal as absorbed by V2 |
| RS-V2-19 | `ReadinessMatrix` / `ReadinessDimension` (DimensionSeverity, DimensionStatus, MatrixVerdict) | runtime_state | V2 | `core/runtime_readiness_matrix.py` | Multi-dimensional automated release/runtime readiness verdict |
| RS-V2-20 | `ProviderStatus` (provider_id, enabled, has_key, ready) | runtime_state | V2 | `core/config_service.py` → `ProviderStatus` dataclass | Per-provider key+enable readiness |
| RS-V2-21 | `ConfigValidationResult` (ok, missing_secrets, invalid_values, oneapi_state, warnings) | runtime_state | V2 | `core/config_service.py` → `ConfigValidationResult` dataclass | Structured config validation result |
| RS-V2-22 | `ProviderConfig.status` (`ProviderStatus` enum: HEALTHY / DEGRADED / DOWN) | runtime_state | V2 | `core/multi_llm_router.py` → `ProviderConfig` dataclass | Per-provider live health state including latency_avg_ms, error_count, last_error |
| RS-V2-23 | `RoutingDecision` (provider, model, reason, alternatives) | runtime_state | V2 | `core/multi_llm_router.py` → `RoutingDecision` dataclass | LLM routing decision record |

#### 1.A.3 — Capability State Items (V2)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| CAP-V2-01 | Device capability tags (screen, camera, microphone, bluetooth, nfc, gps, etc.) | capability_state | V2 | `core/device_registry.py` → `DeviceRegistry.capability_index` | Per-device capability index maintained by compatibility layer |
| CAP-V2-02 | Device groups / tag index | capability_state | V2 | `core/device_registry.py` → `DeviceRegistry.groups`, `tag_index` | Device group membership and tag indexes |
| CAP-V2-03 | `VALID_PROVIDERS` frozenset | capability_state | V2 | `core/config_schema.py` | Seven recognized provider IDs: openai, anthropic, gemini, deepseek, groq, openrouter, oneapi |
| CAP-V2-04 | `VALID_ANDROID_INFERENCE_MODES` frozenset | capability_state | V2 | `core/config_schema.py` | `center` / `local` / `hybrid` — Android inference routing capability |
| CAP-V2-05 | `VALID_NATIVE_MM_POLICIES` frozenset | capability_state | V2 | `core/config_schema.py` | `strict` / `prefer` / `allow_fallback` — multimodal policy capability |
| CAP-V2-06 | `TaskType` enum (REASONING / FAST_RESPONSE / CODING / CREATIVE / ANALYSIS / PLANNING / AGENT_CONTROL / GENERAL) | capability_state | V2 | `core/multi_llm_router.py` → `TaskType` | LLM task-type routing capability matrix |
| CAP-V2-07 | `ProviderConfig.multimodal` flag | capability_state | V2 | `core/multi_llm_router.py` → `ProviderConfig.multimodal` | Whether a provider natively supports multimodal input |
| CAP-V2-08 | `ProviderConfig.supports_tools` flag | capability_state | V2 | `core/multi_llm_router.py` → `ProviderConfig.supports_tools` | Whether a provider supports function calling |
| CAP-V2-09 | `PortConfig._node_ports` / `_service_ports` | capability_state | V2 | `core/port_config.py` → `PortConfig` singleton | Runtime port map from `config/unified_ports.yaml` (130 nodes) |
| CAP-V2-10 | Node port registry (Node_00_StateMachine:8000, Node_01_OneAPI:7995, gateway:8765, openclawd:8099, etc.) | capability_state | V2 | `config/unified_ports.yaml` | Canonical port allocation for all 130 nodes and infrastructure services |
| CAP-V2-11 | MessageType enum (COMMAND / RESPONSE / ACK / HEARTBEAT / STATUS / EVENT / ERROR / STREAM_* / WAKE_EVENT / SESSION_MIGRATE / SESSION_RESTORE) | capability_state | V2 | `core/device_communication.py` → `MessageType` | Transport protocol message type capability |

#### 1.A.4 — Observability Items (V2)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| OBS-V2-01 | NATS subject `galaxy.workers.register` | observability | V2 | `core/nats_heartbeat.py` → `NodeHeartbeatSender` | Worker registration event subject |
| OBS-V2-02 | NATS subject `galaxy.workers.heartbeat` | observability | V2 | `core/nats_heartbeat.py` → `NodeHeartbeatSender` | Worker heartbeat event subject |
| OBS-V2-03 | StateEvent bus (NATS_CONNECTED / DISCONNECTED / RECONNECTING) | observability | V2 | `core/nats_bus.py` → C2 constraint comment | Connection lifecycle events emitted to EventBus |
| OBS-V2-04 | `EndToEndReviewSummary` (task + route + recovery + partial_result + audit_evidence + lineage) | observability | V2 | `core/operator_surface.py` → `EndToEndReviewSummary` | Unified postmortem review summary per task |
| OBS-V2-05 | `HeartbeatScheduler._cycle_count` and tier routing | observability | V2 | `core/openclawd_heartbeat.py` → `HeartbeatScheduler` | Autonomous heartbeat cycle counter, model tier escalation |
| OBS-V2-06 | `DimensionStatus` (PASS / FAIL / UNKNOWN / BLOCKED) and `MatrixVerdict` | observability | V2 | `core/runtime_readiness_matrix.py` | Machine-readable release readiness verdict |
| OBS-V2-07 | `ProviderConfig.latency_avg_ms`, `error_count`, `success_count`, `last_error`, `last_used` | observability | V2 | `core/multi_llm_router.py` → `ProviderConfig` | Per-provider live latency and error metrics |
| OBS-V2-08 | API Compatibility Surface Registry (`APICompatibilitySurface` records) | observability | V2 | `core/api_routes.py` → `get_api_compatibility_surface_registry()` | Explicit catalogue of compatibility-only routes |
| OBS-V2-09 | `control_plane/audit_ledger.py` | observability | V2 | `core/control_plane/audit_ledger.py` | Audit ledger in control plane |
| OBS-V2-10 | `control_plane/device_health_registry.py` | observability | V2 | `core/control_plane/device_health_registry.py` | Device health state registry in control plane |

---

### 1.B — Android Repository Items

#### 1.B.1 — Config Items (Android)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| C-AN-01 | `AppSettings.plannerMaxTokens` | config | Android | `com.ufo.galaxy.data.AppSettings` → `LocalLoopConfig.from(settings)` | MobileVLM planner max tokens (default 512, from `AppSettings`) |
| C-AN-02 | `AppSettings.plannerTemperature` | config | Android | `com.ufo.galaxy.data.AppSettings` → `LocalLoopConfig.from(settings)` | Planner sampling temperature (default 0.1) |
| C-AN-03 | `AppSettings.plannerTimeoutMs` | config | Android | `com.ufo.galaxy.data.AppSettings` → `LocalLoopConfig.from(settings)` | Planner HTTP timeout in ms (default 30000) |
| C-AN-04 | `AppSettings.groundingTimeoutMs` | config | Android | `com.ufo.galaxy.data.AppSettings` → `LocalLoopConfig.from(settings)` | SeeClick grounding timeout ms (default 15000) |
| C-AN-05 | `AppSettings.scaledMaxEdge` | config | Android | `com.ufo.galaxy.data.AppSettings` → `LocalLoopConfig.from(settings)` | Screenshot downscale max edge px (default 720) |
| C-AN-06 | `LocalLoopConfig.maxSteps` | config | Android | `com.ufo.galaxy.config.LocalLoopConfig` | Hard cap on loop steps (default 10) |
| C-AN-07 | `LocalLoopConfig.maxRetriesPerStep` | config | Android | `com.ufo.galaxy.config.LocalLoopConfig` | Max retries per failing step (default 2) |
| C-AN-08 | `LocalLoopConfig.stepTimeoutMs` | config | Android | `com.ufo.galaxy.config.LocalLoopConfig` | Per-step wall-clock timeout (0 = disabled) |
| C-AN-09 | `LocalLoopConfig.goalTimeoutMs` | config | Android | `com.ufo.galaxy.config.LocalLoopConfig` | Total session wall-clock timeout (0 = disabled) |
| C-AN-10 | `FallbackConfig.enablePlannerFallback` | config | Android | `com.ufo.galaxy.config.FallbackConfig` | Whether planner fallback ladder is active (default true) |
| C-AN-11 | `FallbackConfig.enableGroundingFallback` | config | Android | `com.ufo.galaxy.config.FallbackConfig` | Whether grounding fallback ladder is active (default true) |
| C-AN-12 | `FallbackConfig.enableRemoteHandoff` | config | Android | `com.ufo.galaxy.config.FallbackConfig` | Whether failed local exec may escalate to V2 (default false) |
| C-AN-13 | `FallbackConfig.maxFallbackAttempts` | config | Android | `com.ufo.galaxy.config.FallbackConfig` | Max fallback tier attempts (default 3) |
| C-AN-14 | `GALAXY_SERVER_URL` (BuildConfig) | config | Android | `app/build.gradle` → `buildConfigField` | Last-resort gateway WS URL fallback: `ws://192.168.1.100:8765` (debug) / `wss://galaxy.ufo.ai:8765` (release) |
| C-AN-15 | `API_VERSION` (BuildConfig) | config | Android | `app/build.gradle` → `buildConfigField` | `"v2.0"` |
| C-AN-16 | `CROSS_DEVICE_ENABLED` (BuildConfig) | config | Android | `app/build.gradle` → `buildConfigField` | Boolean cross-device feature flag (default false) |
| C-AN-17 | `PLANNER_MAX_TOKENS` / `PLANNER_TEMPERATURE` / `PLANNER_TIMEOUT_MS` (BuildConfig) | config | Android | `app/build.gradle` → `buildConfigField` | Compile-time fallback constants; superseded by AppSettings at runtime |
| C-AN-18 | `GROUNDING_TIMEOUT_MS` / `SCALED_MAX_EDGE` (BuildConfig) | config | Android | `app/build.gradle` → `buildConfigField` | Compile-time grounding fallback constants; superseded by AppSettings |
| C-AN-19 | `RemoteConfigFetcher.CONFIG_V1_PATH` (`/api/v1/config`) | config | Android | `com.ufo.galaxy.config.RemoteConfigFetcher` | V1 remote config fetch path |
| C-AN-20 | `RemoteConfigFetcher.CONFIG_LEGACY_PATH` (`/api/config`) | config | Android | `com.ufo.galaxy.config.RemoteConfigFetcher` | Legacy fallback config fetch path |

#### 1.B.2 — Runtime State Items (Android)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| RS-AN-01 | `ReadinessState` (modelReady, accessibilityReady, overlayReady) | runtime_state | Android | `com.ufo.galaxy.service.ReadinessState` → `UFOGalaxyApplication.readinessState` | Live tri-flag readiness snapshot; updated by `ReadinessChecker.checkAll()` |
| RS-AN-02 | `NativeInferenceLoader.loadAll()` result (`llamaCppAvailable`, `ncnnAvailable`) | runtime_state | Android | `com.ufo.galaxy.runtime.NativeInferenceLoader` | Whether `libllama.so` and `libncnn.so` were loaded successfully at startup |
| RS-AN-03 | `LocalInferenceRuntimeManager` lifecycle state | runtime_state | Android | `com.ufo.galaxy.runtime.LocalInferenceRuntimeManager` | Lifecycle authority for the on-device planner+grounding pair |
| RS-AN-04 | `RuntimeController` cross-device ON/OFF state | runtime_state | Android | `com.ufo.galaxy.runtime.RuntimeController` | Manages cross-device lifecycle, registration, and fallback |
| RS-AN-05 | `RuntimeHostDescriptor` (stable per-launch descriptor) | runtime_state | Android | `com.ufo.galaxy.runtime.RuntimeHostDescriptor` → `UFOGalaxyApplication.runtimeHostDescriptor` | Canonical runtime-host descriptor for this Android instance |
| RS-AN-06 | `runtimeSessionId` (stable per-app-launch UUID) | runtime_state | Android | `UFOGalaxyApplication.runtimeSessionId` | Generated once on process start; propagated as `AipMessage.runtime_session_id` |
| RS-AN-07 | `localLoopConfig` (active `LocalLoopConfig` snapshot) | runtime_state | Android | `UFOGalaxyApplication.localLoopConfig` | Current active loop config; null before init |
| RS-AN-08 | `GalaxyWebSocketClient` connection state | runtime_state | Android | `com.ufo.galaxy.network.GalaxyWebSocketClient` | WebSocket connection lifecycle to V2 gateway |
| RS-AN-09 | `OfflineTaskQueue` state | runtime_state | Android | `com.ufo.galaxy.network.OfflineTaskQueue` | Tasks queued for replay when connection returns |
| RS-AN-10 | `TailscaleAdapter` network state | runtime_state | Android | `com.ufo.galaxy.network.TailscaleAdapter` | Tailscale mesh network detection and discovery |
| RS-AN-11 | `NetworkDiagnostics` state | runtime_state | Android | `com.ufo.galaxy.network.NetworkDiagnostics` | Network diagnostics state |

#### 1.B.3 — Capability State Items (Android)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| CAP-AN-01 | `ModelManifest.RuntimeType` (LLAMA_CPP / MLC_LLM / NCNN / MNN / UNKNOWN) | capability_state | Android | `com.ufo.galaxy.model.ModelManifest` | Which inference backend is required for each model |
| CAP-AN-02 | `ModelManifest` for `MODEL_ID_MOBILEVLM` | capability_state | Android | `com.ufo.galaxy.model.ModelManifest.forKnownModel()` | MobileVLM V2-1.7B-Q4_K via llama.cpp; SHA256 in `ModelAssetManager.MOBILEVLM_SHA256`; `minDiskSpaceBytes=950_000_000` |
| CAP-AN-03 | `ModelManifest` for `MODEL_ID_SEECLICK` (param file) | capability_state | Android | `com.ufo.galaxy.model.ModelManifest.forKnownModel()` | SeeClick NCNN param; SHA256 in `ModelAssetManager.SEECLICK_SHA256`; `minDiskSpaceBytes=50_000_000` |
| CAP-AN-04 | `ModelManifest` for `MODEL_ID_SEECLICK_BIN` (bin weights) | capability_state | Android | `com.ufo.galaxy.model.ModelManifest.forKnownModel()` | SeeClick NCNN weights; SHA256 in `ModelAssetManager.SEECLICK_BIN_SHA256`; `minDiskSpaceBytes=400_000_000` |
| CAP-AN-05 | `CompatibilityResult` (Compatible / Incompatible / Unknown) | capability_state | Android | `com.ufo.galaxy.model.ModelManifest.checkCompatibility()` | Model-runtime version compatibility verdict |
| CAP-AN-06 | `LocalLoopReadiness` (from `LocalLoopReadinessProvider`) | capability_state | Android | `com.ufo.galaxy.local.LocalLoopReadiness` → `UFOGalaxyApplication.localLoopReadinessProvider` | Single source of truth for local-loop subsystem readiness |
| CAP-AN-07 | `WarmupResult` | capability_state | Android | `com.ufo.galaxy.inference.WarmupResult` | Warmup result for local inference services |
| CAP-AN-08 | `GroundingFallbackLadder` / `PlannerFallbackLadder` states | capability_state | Android | `com.ufo.galaxy.local.GroundingFallbackLadder`, `PlannerFallbackLadder` | Multi-tier fallback capability for grounding/planning |
| CAP-AN-09 | `HybridParticipantCapability` / `HybridParticipantCapabilityBoundary` | capability_state | Android | `com.ufo.galaxy.runtime.HybridParticipantCapability` | Hybrid local/remote participant capability |
| CAP-AN-10 | `CanonicalCapabilityProviderModel` | capability_state | Android | `com.ufo.galaxy.runtime.CanonicalCapabilityProviderModel` | Canonical capability provider model for Android runtime |

#### 1.B.4 — Observability Items (Android)

| # | Item Name | Category | Repo | Module / File | Description |
|---|-----------|----------|------|---------------|-------------|
| OBS-AN-01 | `GalaxyLogger` (structured observability logger) | observability | Android | `com.ufo.galaxy.observability.GalaxyLogger` | Structured logging; initialized before all other modules in `UFOGalaxyApplication.onCreate()` |
| OBS-AN-02 | `MetricsRecorder` | observability | Android | `com.ufo.galaxy.observability.MetricsRecorder` | Metrics collection for network, inference, and task execution |
| OBS-AN-03 | `SamplingConfig` | observability | Android | `com.ufo.galaxy.observability.SamplingConfig` | Telemetry sampling configuration |
| OBS-AN-04 | `TelemetryExporter` | observability | Android | `com.ufo.galaxy.observability.TelemetryExporter` | Exports telemetry to remote collector |
| OBS-AN-05 | `TraceContext` | observability | Android | `com.ufo.galaxy.observability.TraceContext` | Distributed trace context propagation |
| OBS-AN-06 | `LocalLoopTraceStore` | observability | Android | `com.ufo.galaxy.trace.LocalLoopTraceStore` → `UFOGalaxyApplication.localLoopTraceStore` | In-memory store of recent local-loop execution traces |
| OBS-AN-07 | `SessionHistoryStore` | observability | Android | `com.ufo.galaxy.history.SessionHistoryStore` → `UFOGalaxyApplication.sessionHistoryStore` | Persistent store of completed local-loop session summaries across restarts |
| OBS-AN-08 | `StagnationDetector` state | observability | Android | `com.ufo.galaxy.local.StagnationDetector` | Detects repeated state without progress in local loop |
| OBS-AN-09 | `PostActionObserver` | observability | Android | `com.ufo.galaxy.local.PostActionObserver` | Observes loop step outcomes post-action |
| OBS-AN-10 | `StepObservation` | observability | Android | `com.ufo.galaxy.local.StepObservation` | Per-step observation record in local loop |
| OBS-AN-11 | `DelegatedRuntimeReadinessSnapshot` / `DelegatedRuntimeGovernanceSnapshot` / `DelegatedRuntimeStrategySnapshot` | observability | Android | `com.ufo.galaxy.runtime.DelegatedRuntimeReadinessSnapshot` etc. | Multi-dimension delegated runtime audit snapshots |
| OBS-AN-12 | `RuntimeHealthSnapshot` | observability | Android | `com.ufo.galaxy.runtime.RuntimeHealthSnapshot` | Runtime health snapshot |
| OBS-AN-13 | `ParticipantLifecycleTruthReport` / `ParticipantHealthState` | observability | Android | `com.ufo.galaxy.runtime.ParticipantLifecycleTruthReport` | Participant lifecycle truth state |
| OBS-AN-14 | `SubtaskProgressReport` / `ParticipantProgressCheckpoint` | observability | Android | `com.ufo.galaxy.runtime.SubtaskProgressReport` | Subtask progress reporting |

---

## Section 2: Authoritative Ownership Map

For each item category, this section states the canonical truth location and the owning module.

### 2.1 — Config Authority

| Domain | Ground Truth Location | Owning Module | Notes |
|--------|-----------------------|---------------|-------|
| LLM provider keys (secrets) | `runtime/secrets.env` or OS env vars | `core/config_store.py` → `ConfigStore` | `SecretInConfigError` enforces that secrets never appear in `config.json` |
| LLM provider enable/disable, routing policy | `runtime/config.json` | `core/config_store.py` → `ConfigStore` | `NonSecretInSecretsError` enforces separation |
| Config defaults | `core/config_schema.py` → `ConfigDefaults` | `core/config_schema.py` | Immutable namespace; no I/O |
| Config validation | `core/config_service.py` → `ConfigService.validate()` | `core/config_service.py` | Delegates to `core/config_preflight.run_preflight` |
| Port allocation | `config/unified_ports.yaml` | `core/port_config.py` → `PortConfig` singleton | 130 nodes; override via `GALAXY_PORT_<NODE>` env vars |
| config.json runtime flags | `config.json` (repo root) | Direct JSON read at startup | Legacy fallback: `web_ui_port` defers to unified_ports.yaml `unified_launcher` key |
| Android loop config | `SharedPreferences` (runtime) → `assets/config.properties` → `BuildConfig` compile-time | `com.ufo.galaxy.data.AppSettings` → `LocalLoopConfig.from(settings)` | Config precedence: SharedPrefs > properties > BuildConfig |
| Android gateway URL | `SharedPreferences` → `RemoteConfigFetcher` (`/api/v1/config`) → `BuildConfig.GALAXY_SERVER_URL` | `com.ufo.galaxy.config.RemoteConfigFetcher` | V1-first, 404-fallback to `/api/config`; called from `UFOGalaxyApplication.initRemoteGatewayConfig()` |
| Android model manifests | Hardcoded in `ModelManifest.forKnownModel()` | `com.ufo.galaxy.model.ModelManifest` | SHA256 checksums in `ModelAssetManager`; HuggingFace sources |

### 2.2 — Runtime State Authority

| Domain | Ground Truth Location | Owning Module | Notes |
|--------|-----------------------|---------------|-------|
| Subject tri-state (SILENT/LIMINAL/MANIFEST) | In-process state in `DesktopPresenceRuntime` | `core/desktop_presence_runtime.py` | Canonical lifecycle; distinct from continuum posture and UI shell states |
| Task lifecycle | `CanonicalTaskRuntime` (queried by `OperatorSurface.inspect_task()`) | `core/canonical_task.py` → `get_canonical_task_runtime()` | Layer 9; `OperatorSurface` reads projections only |
| Routing decisions | `admissibility_policy_convergence` (sourced in `RouteInspection._source`) | `core/admissibility_policy_convergence.py` | Read via `OperatorSurface.inspect_route()` |
| Device truth (mutable state) | `UnifiedDeviceManager` (UDM) | `core/unified/device_manager.py` → `get_unified_device_manager()` | `DeviceRegistry` is a compatibility/indexing layer only, not a truth source |
| Device presence / topology | `NetworkTopologyRuntime` | Sourced in `DevicePresenceSummary._source = "network_topology_runtime"` | Assimilated from NATS state via `absorb_nats_state()` |
| NATS fabric state | `NATSBus` (module-level singleton `nats_bus`) | `core/nats_bus.py` | Absorbed into `NetworkTopologyRuntime` on connect/disconnect |
| Delegated flow phase (Android-side) | `FlowLevelOperatorSurface` projections | `core/flow_level_operator_surface.py` → `FlowLevelOperatorSurface` | Consumes from `DelegatedFlowEntityRuntime`, `FlowTruthAlignmentRuntime`, `FlowAwareConvergence`, `DelegatedFlowRecovery` |
| Android native runtime loading | `NativeInferenceLoader.loadAll()` result | `com.ufo.galaxy.runtime.NativeInferenceLoader` | Best-effort; failures degrade to remote V2 routing |
| Android readiness | `UFOGalaxyApplication.readinessState` (`ReadinessState`) | `com.ufo.galaxy.service.ReadinessChecker` | Updated at startup and by `GalaxyConnectionService` after models load |
| Android local-loop readiness | `DefaultLocalLoopReadinessProvider` / `LocalLoopReadinessProvider` | `com.ufo.galaxy.local.LocalLoopReadinessProvider` | Single source of truth for local-loop subsystem readiness |
| LLM provider health | In-process `ProviderConfig.status` / `latency_avg_ms` / `error_count` | `core/multi_llm_router.py` → `MultiLLMRouter._discover_providers()` | Updated on each call; not persisted between restarts |
| Heartbeat state | `HeartbeatScheduler` singleton | `core/openclawd_heartbeat.py` → `get_heartbeat_scheduler()` | Config from `config/agent.yaml` |

### 2.3 — Capability Authority

| Domain | Ground Truth Location | Owning Module |
|--------|-----------------------|---------------|
| Provider set | `VALID_PROVIDERS` frozenset | `core/config_schema.py` |
| Android inference modes | `VALID_ANDROID_INFERENCE_MODES` frozenset | `core/config_schema.py` |
| Node port map | `config/unified_ports.yaml` | `core/port_config.py` → `PortConfig` |
| Model file manifests (SHA256, size, source) | `ModelManifest.forKnownModel()` | `com.ufo.galaxy.model.ModelManifest` / `ModelAssetManager` |
| Fallback capability ladder | `GroundingFallbackLadder` / `PlannerFallbackLadder` | `com.ufo.galaxy.local.*` |

### 2.4 — Observability Authority

| Domain | Ground Truth Location | Owning Module |
|--------|-----------------------|---------------|
| Task/flow/route postmortem | `OperatorSurface.inspect_*()` methods + `EndToEndReviewSummary` | `core/operator_surface.py` |
| Flow-level Android execution phase | `FlowLevelOperatorSurface.inspect_flow()` → `FlowOperatorProjection` | `core/flow_level_operator_surface.py` |
| Release readiness verdict | `evaluate_readiness_matrix()` → `ReadinessMatrix` | `core/runtime_readiness_matrix.py` |
| Android metrics | `MetricsRecorder` | `com.ufo.galaxy.observability.MetricsRecorder` |
| Android structured logs | `GalaxyLogger` | `com.ufo.galaxy.observability.GalaxyLogger` |
| Android trace propagation | `TraceContext` / `runtimeSessionId` | `com.ufo.galaxy.observability.TraceContext` / `UFOGalaxyApplication` |
| Android session history | `SessionHistoryStore` | `com.ufo.galaxy.history.SessionHistoryStore` |
| Android loop trace | `LocalLoopTraceStore` | `com.ufo.galaxy.trace.LocalLoopTraceStore` |

---

## Section 3: Read/Write Path Map

### 3.1 — V2 Config Read/Write Paths

| Item | Read Path | Write Path | Restart Required? |
|------|-----------|------------|-------------------|
| `providers.*.enabled` | `ConfigService.get()` / `ConfigStore.read_config()` from `runtime/config.json` | `ConfigService.set_provider_enabled(provider, enabled)` → `ConfigStore.write_config()` | No (hot-reload if `config_hot_reload.py` is active) |
| `providers.oneapi.base_url` | `ConfigService.get("providers.oneapi.base_url")` | `ConfigService.set()` → `ConfigStore.write_config()` | No |
| `routing.native_multimodal_policy` | `ConfigService.get("routing.native_multimodal_policy")` | `ConfigService.set()` → `ConfigStore.write_config()` | No |
| `routing.default_provider` | `ConfigService.get("routing.default_provider")` | `ConfigService.set()` → `ConfigStore.write_config()` | No |
| `network.*` URLs | `ConfigService.get("network.*")` | `ConfigService.set()` → `ConfigStore.write_config()` | Requires reconnect |
| `android.inference_mode` | `ConfigService.get("android.inference_mode")` | `ConfigService.set()` → `ConfigStore.write_config()` | Requires reconnect to Android |
| `OPENAI_API_KEY` (and other secrets) | OS env var → `runtime/secrets.env` (priority: env > secrets.env > config.json) | `ConfigService.set_secret(key, value)` → `ConfigStore.write_secret()` | No (reloaded on next API call) |
| `config.json` runtime flags (enable_continuum, etc.) | Direct JSON read at startup | Manual file edit or `ConfigService.set()` | Restart required for most flags |
| Port allocations | `PortConfig.get_node_port(name)` / `get_service_port(name)` | YAML edit + process restart, or `GALAXY_PORT_<NODE>` env var override | Env var: no restart; YAML: restart |

### 3.2 — V2 Runtime State Read/Write Paths

| Item | Read Path | Write Path | Notes |
|------|-----------|------------|-------|
| `TriState` | `DesktopPresenceRuntime._state` (internal); projected via runtime result dict | `DesktopPresenceRuntime.handle_request()` drives transitions automatically | No direct operator write; driven by request flow |
| `OperatorSnapshot` | `GET /api/v1/operator` → `OperatorSurface.operator_snapshot()` | Read-only projection | — |
| `TaskInspection` | `GET /api/v1/operator` or `OperatorSurface.inspect_task(task_id)` | Created by canonical task runtime; operator cannot write | Read-only |
| `FlowOperatorProjection` | `FlowLevelOperatorSurface.inspect_flow(flow_id)` | Events absorbed from Android via truth ingress path | Read-only for operator |
| `AndroidExecutionPhase` | `FlowOperatorProjection.current_execution_phase` | Set by `AndroidCanonicalExecutionEvent` absorption | Operator cannot set directly |
| `ReadinessMatrix` | `get_readiness_matrix()` → `ReadinessMatrix.to_dict()` | `evaluate_readiness_matrix()` run at startup/CI | Read-only report |
| `ProviderStatus.ready` | `ConfigService.validate()` → `ConfigValidationResult.provider_statuses` | Set key via `ConfigService.set_secret()`, toggle via `set_provider_enabled()` | Composite derived field |
| NATS `is_connected()` | `nats_bus.is_connected()` | `nats_bus.connect()` / `nats_bus.disconnect()` | Connection driven by startup; not direct operator action |
| Heartbeat state | `get_heartbeat_scheduler().is_enabled()`, `_cycle_count` | `heartbeat.enabled` in `config/agent.yaml`; restart required to change | Config file write |

### 3.3 — Android Config Read/Write Paths

| Item | Read Path | Write Path | Notes |
|------|-----------|------------|-------|
| `AppSettings` (plannerMaxTokens etc.) | `SharedPrefsAppSettings` reads SharedPreferences at startup | Android Settings UI writes SharedPreferences | Runtime-editable via Settings UI |
| `LocalLoopConfig` | `LocalLoopConfig.from(settings)` called at init, stored as `UFOGalaxyApplication.localLoopConfig` | Settings UI → SharedPreferences → `LocalLoopConfig.from(settings)` on restart | Effective on next session |
| `BuildConfig.GALAXY_SERVER_URL` | `AppConfig.serverUrl` last-resort fallback | Build-time only (app/build.gradle) | Requires rebuild |
| Remote gateway URL | `RemoteConfigFetcher.fetchConfig()` → `AppSettings.applyGatewayConfig()` | Fetched from `GET /api/v1/config` at startup; failures fall back to local | Startup-time only |
| `CROSS_DEVICE_ENABLED` | `AppSettings.crossDeviceEnabled` (via BuildConfig as fallback) | Build-time or SharedPreferences override | Requires rebuild to change default |

### 3.4 — Android Runtime State Read/Write Paths

| Item | Read Path | Write Path | Notes |
|------|-----------|------------|-------|
| `ReadinessState` | `UFOGalaxyApplication.readinessState` | `ReadinessChecker.checkAll()` at startup and from `GalaxyConnectionService` | Updated async; operator reads snapshot |
| `NativeInferenceLoader` result | `UFOGalaxyApplication.onCreate()` log / debug panel | Startup only; `NativeInferenceLoader.loadAll()` | Cannot be re-triggered without restart |
| `LocalInferenceRuntimeManager` state | `localInferenceRuntimeManager` lifecycle methods | `LocalInferenceRuntimeManager.cancel()` at shutdown | Lifecycle managed by Application |
| `RuntimeController` cross-device state | `runtimeController` state | `RuntimeController.cancel()` / lifecycle events | Driven by WS connection events |
| `RuntimeHostDescriptor` | `UFOGalaxyApplication.runtimeHostDescriptor` | Set by `initRuntimeHostDescriptor()` post-WS-init | Immutable after init |
| `runtimeSessionId` | `UFOGalaxyApplication.runtimeSessionId` | Generated once at process start via `UUID.randomUUID()` | Immutable for process lifetime |
| `GalaxyWebSocketClient` connection | Client state methods | `connect()` / `disconnect()` lifecycle | Driven by WS lifecycle events |
| `OfflineTaskQueue` | Queue inspection | Tasks enqueued when offline; replayed on reconnect | Driven by connection events |
| `LocalLoopTraceStore` | `UFOGalaxyApplication.localLoopTraceStore` | Written by local loop execution | In-memory; not persisted across restarts |
| `SessionHistoryStore` | `UFOGalaxyApplication.sessionHistoryStore` | Completed sessions append to SharedPreferences | Persisted across restarts |

---

## Section 4: Current Surface Map

Which items already have CLI / API / status-board exposure and how.

### 4.1 — V2 REST API Endpoints (from `core/api_routes.py` domain map)

The following API domains are defined and wired via `core/api_routes.py` and `core/routes/` sub-modules:

| Endpoint Domain | Path Pattern | Exposed Items |
|-----------------|-------------|---------------|
| System status | `GET /api/v1/system` | System state and management |
| Devices | `GET/POST /api/v1/devices` | Device registration, listing, discovery, deregistration |
| Nodes | `GET /api/v1/nodes` | Node query and invocation |
| Agent dispatch | `POST /api/v1/agent` | Agent scheduling |
| Command routing | `POST /api/v1/command` | Command routing engine |
| AI intent | `POST /api/v1/ai` | AI intent understanding |
| Vision | `POST /api/v1/vision` | Visual understanding |
| Tasks | `GET /api/v1/tasks` | Task management |
| Chat | `POST /api/v1/chat` | Conversation interface |
| Health | `GET /api/v1/health` | Unified health check (Batch PR-4) |
| Monitoring | `GET /api/v1/monitoring` | Monitoring dashboard and alerts |
| Concurrency | `GET /api/v1/concurrency` | Concurrency state (Batch PR-4) |
| Errors | `GET /api/v1/errors` | Error tracking (Batch PR-4) |
| Discovery | `GET /api/v1/discovery` | Node discovery (Batch PR-4) |
| Security | `GET /api/v1/security` | Security audit (Batch PR-4) |
| Config | `GET/POST /api/v1/config` | Configuration management (Batch PR-4) |
| Relay | `/api/v1/relay` | Proxy forwarding |
| RAG | `GET /api/v1/rag` | RAG retrieval |
| Mesh | `/api/v1/mesh` | Mesh P2P |
| Vault | `/api/v1/vault` | Credential management |
| Cost | `GET /api/v1/cost` | Cost tracking |
| Channels | `/api/v1/channels` | Channel plugins |
| Federation | `/api/v1/federation` | Multi-instance federation |
| Projection | `GET /api/v1/projection` | Runtime state projection |
| **Operator** | `GET /api/v1/operator` | **Operator inspection surface (PR-510)** — `OperatorSurface.operator_snapshot()`, `inspect_task()`, `inspect_route()`, `inspect_executor()` |
| Stream | `/api/v1/stream` | SSE streaming |
| Device WebSocket (compat) | `/ws/device/{device_id}` | Compatibility WS path for legacy core-direct clients |
| Status WebSocket | `/ws/status` | Status push WebSocket |

**Key exposure reality:**
- `GET /api/v1/operator` (PR-510) is the only endpoint explicitly wired to `OperatorSurface`  
- The `CANONICAL_API_ROUTES_AUTHORITY = "core.api_routes"` sentinel declares ownership  
- `get_api_compatibility_surface_registry()` provides an explicit catalogue of two compat routes

### 4.2 — V2 Config API

- `GET /api/v1/config` — reads `ConfigService` / `ConfigStore` for config values  
- `POST /api/v1/config` — writes via `ConfigStore.write_config()` (validated by `ConfigService.validate()`)
- Config store enforces `SecretInConfigError` / `NonSecretInSecretsError` separation

### 4.3 — V2 Health and Monitoring

- `GET /api/v1/health` — unified health (Batch PR-4) — covers system-level health  
- `GET /api/v1/monitoring` — monitoring dashboard and alerts  
- `evaluate_readiness_matrix()` produces `ReadinessMatrix` — consumed by CI but not yet exposed at a dedicated REST endpoint; accessible programmatically via `get_readiness_matrix()`

### 4.4 — NATS Bus Observability

- `nats_bus.is_connected()` and `nats_bus.get_stats()` — programmatic access only  
- NATS_CONNECTED / DISCONNECTED / RECONNECTING events emitted to EventBus (C2 constraint in `core/nats_bus.py`)  
- `galaxy.workers.register` and `galaxy.workers.heartbeat` NATS subjects — observable by any NATS subscriber  
- No dedicated REST endpoint exposes NATS state to an operator console

### 4.5 — Android Status Exposure

- `readinessState` (modelReady / accessibilityReady / overlayReady) — accessible via Android debug panel and `UFOGalaxyApplication.readinessState`  
- `NativeInferenceLoader` result logged at startup: `"Native inference runtimes: llama.cpp=X ncnn=Y"`  
- `MetricsRecorder` and `GalaxyLogger` write structured logs — accessible via Android logcat / debug panel  
- `LocalLoopTraceStore` and `SessionHistoryStore` — in-app inspection only  
- No API endpoint on the Android side exposes runtime state to V2 or external operator console

---

## Section 5: Missing Surface Map

Items with no proper operator-plane exposure, listed with evidence from code.

### 5.1 — V2 Items with No Operator-Plane Exposure

| # | Item | Evidence (code location) | Gap Description |
|---|------|--------------------------|-----------------|
| M-V2-01 | `TriState` (SILENT/LIMINAL/MANIFEST) live value | `core/desktop_presence_runtime.py` → `TriState` enum; not in any REST response | No endpoint reports the current subject lifecycle state; `GET /api/v1/operator` snapshot does not include `TriState` |
| M-V2-02 | NATS `is_connected()` / `get_stats()` | `core/nats_bus.py` → `is_connected()`, `get_stats()` | No dedicated REST endpoint; no inclusion in health endpoint or operator snapshot |
| M-V2-03 | Per-provider `ProviderConfig.status` (HEALTHY/DEGRADED/DOWN), `latency_avg_ms`, `error_count`, `last_error` | `core/multi_llm_router.py` → `ProviderConfig` | Live LLM provider health metrics not surfaced at `/api/v1/operator`; `ConfigValidationResult.provider_statuses` shows config readiness only (enabled + has_key), not live runtime health |
| M-V2-04 | `ReadinessMatrix` as a live REST endpoint | `core/runtime_readiness_matrix.py` → `get_readiness_matrix()` | Programmatic only; no `/api/v1/readiness` or `/api/v1/operator/readiness` endpoint defined |
| M-V2-05 | `HeartbeatScheduler._cycle_count`, tier escalation history, last cycle result | `core/openclawd_heartbeat.py` → `HeartbeatScheduler` | Not surfaced at any endpoint; operator cannot see if heartbeat is stalled, how many cycles ran, or whether tier2 escalated |
| M-V2-06 | `FlowOperatorProjection` for active delegated flows (via `FlowLevelOperatorSurface`) | `core/flow_level_operator_surface.py` → `FlowLevelOperatorSurface.inspect_flow()` | `FlowLevelOperatorSurface` exists as a projection API but no route is defined at `/api/v1/operator/flows` or similar |
| M-V2-07 | `AndroidCanonicalExecutionEvent` history for a flow | `core/flow_level_operator_surface.py` → `FlowOperatorProjection.last_android_execution_event` | Events are absorbed but not queryable by flow_id from an operator endpoint |
| M-V2-08 | `PortConfig` live port map | `core/port_config.py` → `PortConfig.list_node_ports()`, `list_service_ports()` | Not exposed at any REST endpoint; no operator-accessible port registry API |
| M-V2-09 | `APICompatibilitySurface` registry as operator documentation | `core/api_routes.py` → `get_api_compatibility_surface_registry()` | The registry exists and is machine-readable but is not served at a REST endpoint for operator inspection |
| M-V2-10 | `RoutingDecision` per-task (provider, model, reason, alternatives) | `core/multi_llm_router.py` → `RoutingDecision` | LLM routing decisions are not included in `TaskInspection` or operator snapshot |
| M-V2-11 | Device `MessageType` / `AIPv3MessageType` protocol capability | `core/device_communication.py` → `MessageType` | Protocol version and message type capability matrix not surfaced in operator snapshot or device inspection |
| M-V2-12 | `control_plane/device_health_registry.py` state | `core/control_plane/device_health_registry.py` | Control plane device health registry not exposed via operator surface |
| M-V2-13 | `control_plane/swarm_scaler.py` / `smart_scheduler.py` state | `core/control_plane/swarm_scaler.py`, `smart_scheduler.py` | Swarm scaling and scheduling state not exposed |

### 5.2 — Android Items with No Operator-Plane Exposure to V2

| # | Item | Evidence (code location) | Gap Description |
|---|------|--------------------------|-----------------|
| M-AN-01 | `NativeInferenceLoader.loadAll()` result (`llamaCppAvailable`, `ncnnAvailable`) | `UFOGalaxyApplication.onCreate()` → logged only | V2 has no way to query whether libllama.so and libncnn.so loaded successfully on the Android device; this is critical for deciding whether `android.inference_mode = local` is viable |
| M-AN-02 | `ReadinessState` (modelReady, accessibilityReady, overlayReady) | `UFOGalaxyApplication.readinessState` | V2 cannot query this state; it is stored Android-side only |
| M-AN-03 | `LocalLoopReadiness` (from `LocalLoopReadinessProvider`) | `UFOGalaxyApplication.localLoopReadinessProvider` | V2 cannot determine if the local loop is ready without receiving an explicit capability advertisement from Android |
| M-AN-04 | `CompatibilityResult` of model manifest checks | `com.ufo.galaxy.model.ModelManifest.checkCompatibility()` | V2 cannot determine if a model is compatible with the Android runtime version |
| M-AN-05 | `ModelManifest` for active models (modelId, modelVersion, checksum, quantization, parameterCountM) | `com.ufo.galaxy.model.ModelManifest.forKnownModel()` | V2 does not receive model identity details; cannot display "Android is running MobileVLM v2-1.7B-Q4_K" |
| M-AN-06 | `LocalLoopConfig` active values (maxSteps, stepTimeoutMs, goalTimeoutMs, fallback flags) | `UFOGalaxyApplication.localLoopConfig` | V2 cannot inspect what config the Android device is running the local loop with |
| M-AN-07 | `AndroidExecutionPhase` (planning/grounding/execution/stagnation/gate_decision/...) as a V2-readable live signal | `com.ufo.galaxy.runtime.AndroidFlowExecutionPhase` | The `FlowLevelOperatorSurface` exists on V2 to consume these signals, but the Android side must emit them as canonical execution events; the full pipeline depends on `AndroidCanonicalExecutionEventOwner.kt` wiring to WS messages |
| M-AN-08 | `StagnationDetector` event | `com.ufo.galaxy.local.StagnationDetector` | Stagnation detection on Android is not emitted as a canonical event to V2 |
| M-AN-09 | `GroundingFallbackLadder` / `PlannerFallbackLadder` tier currently active | `com.ufo.galaxy.local.*` | V2 cannot tell which fallback tier Android is on |
| M-AN-10 | `SessionHistoryStore` sessions | `com.ufo.galaxy.history.SessionHistoryStore` | Completed session history is persisted on Android but not surfaced to V2 or operator console |
| M-AN-11 | `MetricsRecorder` per-inference latency data | `com.ufo.galaxy.observability.MetricsRecorder` | Inference latency metrics are collected on Android but not exported to V2 |
| M-AN-12 | `TailscaleAdapter` network discovery result | `com.ufo.galaxy.network.TailscaleAdapter` | Tailscale mesh network state is not reported to V2 |
| M-AN-13 | `OfflineTaskQueue` queue depth / task IDs | `com.ufo.galaxy.network.OfflineTaskQueue` | V2 cannot inspect how many tasks are queued on Android for replay |
| M-AN-14 | `DelegatedRuntimeReadinessSnapshot` / `DelegatedRuntimeGovernanceSnapshot` | `com.ufo.galaxy.runtime.*` | Multi-dimension delegated runtime audit snapshots are not returned to V2 |
| M-AN-15 | `RuntimeHealthSnapshot` | `com.ufo.galaxy.runtime.RuntimeHealthSnapshot` | Android runtime health snapshot not emitted to V2 |

---

## Section 6: Docking / Integration Model

### 6.1 — Grouping Recommendations (by operator plane function)

The operator console should group items into four functional panels. Each panel references the
real module/API that serves it.

#### Panel A: Setup / Configuration

**Source of truth: V2** (config.json + runtime/config.json + runtime/secrets.env)  
**Android contribution:** Android-side config is pulled from V2 at startup via `RemoteConfigFetcher.fetchConfig()` hitting `/api/v1/config`

Items to group here:
- All `CONFIG_KEYS` from `core/config_schema.py` — provider toggles, routing policy, network URLs, android integration mode
- `VALID_PROVIDERS` — provider identity (enum of 7)
- `VALID_ANDROID_INFERENCE_MODES` — `center` / `local` / `hybrid`
- `VALID_NATIVE_MM_POLICIES` — `strict` / `prefer` / `allow_fallback`
- Secret presence (has_key, not value) from `ConfigValidationResult.provider_statuses`
- `config.json` feature flags (enable_continuum, enable_desktop_presence_runtime, enable_task_dag, enable_webrtc_session_manager, etc.)
- Android BuildConfig overrides (PLANNER_MAX_TOKENS, GROUNDING_TIMEOUT_MS, etc.) — treated as compile-time overrides, shown alongside runtime AppSettings

**API gateway:** `GET/POST /api/v1/config`, `ConfigService.validate()` → `ConfigValidationResult`

#### Panel B: Runtime Monitoring (live status)

**Source of truth: V2** for center-side runtime; **Android** for device-side runtime (must be reported via WS messages)

Items to group here:
- `TriState` current value (SILENT/LIMINAL/MANIFEST) — from `DesktopPresenceRuntime`
- `OperatorSnapshot` — active tasks, online devices, topology node count, capability providers
- Per-task `TaskInspection` — lifecycle, routing, tool, result
- Per-device `DevicePresenceSummary` — presence_state, is_ready, last_seen, capability_tags
- `ProviderConfig.status` (HEALTHY/DEGRADED/DOWN) + `latency_avg_ms` + `error_count` — from `MultiLLMRouter`
- NATS `is_connected()` + `get_stats()`
- Heartbeat state (`is_enabled()`, `_cycle_count`, last cycle result)
- **Android-side (must be projected from WS):** `ReadinessState`, `NativeInferenceLoader` result, `LocalLoopReadiness`

**API gateway:** `GET /api/v1/operator` (primary), `GET /api/v1/health`, `GET /api/v1/monitoring`

#### Panel C: Execution Control (flow inspection)

**Source of truth: V2** for task-level; **jointly V2+Android** for delegated flows

Items to group here:
- Per-flow `FlowOperatorProjection` — current_execution_phase, blocking_reason, recovery_status, truth_alignment_status, canonical_result_status
- `AndroidExecutionPhase` live value — planning/grounding/execution/replan/stagnation/gate_decision/...
- `AndroidCanonicalExecutionEvent` history per flow
- `RouteInspection` — transport_strategy, effective_path, admissibility_verdict
- `FailureDomainInspection` — failure domain, retry count, fallback chain
- `RecoveryInspection` — is_recovered, recovery_disposition, current_owner
- `PartialResultInspection` — lifecycle_state, partial_result_disposition, resume_count
- `LineageInspection` — ancestor_chain, children, retry_chain, timeline
- **Android-side (must be projected):** `GroundingFallbackLadder` / `PlannerFallbackLadder` tier, `StagnationDetector` events, `OfflineTaskQueue` depth

**API gateway:** `GET /api/v1/operator` (uses `OperatorSurface.inspect_task()`, `inspect_route()`, `FlowLevelOperatorSurface.inspect_flow()`), new `GET /api/v1/operator/flows/{flow_id}` needed

#### Panel D: Model / Runtime Readiness

**Source of truth: Android** for model presence and native runtime; **V2** for readiness matrix

Items to group here:
- `ReadinessMatrix` / `ReadinessDimension` — transport, canonical execution path, capability enforcement, protocol regression, continuity/recovery
- `ProviderStatus.ready` per provider (enabled + has_key)
- `NativeInferenceLoader` result per device (`llamaCppAvailable`, `ncnnAvailable`)
- `ReadinessState` per device (modelReady, accessibilityReady, overlayReady)
- `ModelManifest` identity per device — modelId, modelVersion, runtimeType, quantization, parameterCountM, checksum match
- `CompatibilityResult` — Compatible / Incompatible / Unknown per model
- `LocalLoopReadiness` — whether local loop can accept tasks
- `WarmupResult` — whether inference services warmed up

**API gateway:** No dedicated endpoint today; `GET /api/v1/readiness` needed; Android must report via WS capability advertisement message

### 6.2 — Source of Truth vs Synchronized Concepts

| Concept | V2 Source of Truth | Android Source of Truth | Must Synchronize |
|---------|-------------------|-------------------------|------------------|
| `android.inference_mode` | `core/config_schema.py` / `runtime/config.json` | `AppSettings` (pulled from V2 via `RemoteConfigFetcher`) | V2 → Android at Android startup; Android must re-fetch if changed at runtime |
| Gateway URL | `network.gateway_url` in `runtime/config.json` | `AppSettings.galaxyGatewayUrl` (from RemoteConfigFetcher at startup) | V2 → Android; Android must reconnect if changed |
| Provider readiness | `ConfigService.validate()` → `ProviderStatus.ready` | Not mirrored | V2 only; Android does not need to know API keys |
| Model presence | `ModelManifest.forKnownModel()` (static in Android) | `ModelAssetManager` + `ModelDownloader` (dynamic) | Android is truth; V2 needs Android's model state projected via WS |
| Native runtime availability | Not tracked on V2 | `NativeInferenceLoader.loadAll()` | Android is truth; V2 needs to receive capability advertisement |
| Device readiness (modelReady, accessibilityReady, overlayReady) | Not tracked on V2 | `ReadinessState` | Android is truth; must be reported via `device_heartbeat` WS message or dedicated capability update |
| Task lifecycle | `CanonicalTaskRuntime` (V2) | `DelegatedExecutionTracker` / `CanonicalExecutionEvent` (Android) | V2 is truth for task lifecycle; Android reports progress events |
| Execution phase | `FlowOperatorProjection.current_execution_phase` (V2 inferred) | `AndroidFlowExecutionPhase` / `AndroidCanonicalExecutionEventOwner` (Android) | Android emits events → V2 absorbs → projects | 
| Session correlation | `runtime_session_id` in `DesktopPresenceRuntime` | `runtimeSessionId` in `UFOGalaxyApplication` | Must be propagated in all WS messages; `AipMessage.runtime_session_id` carries Android's value |
| LLM routing decisions | `RoutingDecision` from `MultiLLMRouter` | Not relevant (center-only) | V2 only |

### 6.3 — Duplicated or Mirrored Concepts

| Concept | V2 | Android | Conflict/Mirror Description |
|---------|----|---------|-----------------------------|
| Planner max tokens | `PLANNER_MAX_TOKENS = 512` in `config.json` → `ConfigDefaults` / `AppSettings` pushed from V2 | `BuildConfig.PLANNER_MAX_TOKENS = 512` as last-resort fallback → `AppSettings.plannerMaxTokens` | Both default to 512 but via different paths; `BuildConfig` constant is last-resort; `AppSettings` is runtime truth; mirrored in `LocalLoopConfig.planner.maxTokens` |
| Gateway URL | `network.gateway_url` / `network.android_gateway_url` in V2 config | `BuildConfig.GALAXY_SERVER_URL` debug/release variants + `RemoteConfigFetcher` | Three sources; `RemoteConfigFetcher` wins at runtime; `BuildConfig` is last-resort fallback |
| `android.inference_mode` | `VALID_ANDROID_INFERENCE_MODES` frozenset in `core/config_schema.py` | Not a named enum; implicitly controlled by `AppSettings.crossDeviceEnabled` + `BuildConfig.CROSS_DEVICE_ENABLED` | Concept exists in V2 schema but Android doesn't have a matching typed enum; cross-device enable/disable maps to `hybrid` ↔ `center` |
| Heartbeat | NATS `galaxy.workers.heartbeat` (worker-to-NATS) + `HeartbeatScheduler` (OpenClawd self-check) | WS connection heartbeat in `GalaxyWebSocketClient` | Three distinct heartbeat mechanisms; none project through the same operator-visible surface |
| Session ID | `runtime_session_id` from `DesktopPresenceRuntime` | `runtimeSessionId` from `UFOGalaxyApplication` (per-process UUID) | Both exist; Android's is per-launch stable; V2's is per-request; they must be correlated via `AipMessage.runtime_session_id` |
| Fallback | V2: `FailureDomainInspection.fallback_triggered`, `fallback_target` | Android: `GroundingFallbackLadder`, `PlannerFallbackLadder`, `FallbackConfig.enableRemoteHandoff` | Two-level fallback system; V2 sees task-level fallback; Android has service-level fallback ladders with `FallbackConfig.enableRemoteHandoff = false` by default |

---

## Section 7: Warnings and Semantics

The following items have specific display semantics that an operator console MUST enforce.
Evidence for each warning is cited from code.

### 7.1 — `degraded`

Show as **degraded** when:

| Condition | Code Evidence |
|-----------|---------------|
| `ProviderConfig.status == ProviderStatus.DEGRADED` | `core/multi_llm_router.py` → `ProviderStatus.DEGRADED` |
| `ProviderStatus.ready == False` (enabled but no API key) | `core/config_service.py` → `ProviderStatus.ready` property: `enabled and has_key` |
| `DimensionStatus.FAIL` on a CRITICAL `ReadinessDimension` | `core/runtime_readiness_matrix.py` → `DimensionSeverity.CRITICAL` + `DimensionStatus.FAIL` |
| `NativeInferenceLoader` result: `llamaCppAvailable=false` AND `android.inference_mode = "local"` | `UFOGalaxyApplication.onCreate()` + `core/config_schema.py` → `VALID_ANDROID_INFERENCE_MODES` |
| `AndroidExecutionPhase.stagnation` on a live flow | `core/flow_level_operator_surface.py` → `AndroidExecutionPhase.stagnation.is_blocking()` → True |
| `ExecutorInspection.is_online == False` for a device that has been dispatched to | `core/operator_surface.py` → `ExecutorInspection.is_online` |

### 7.2 — `blocked`

Show as **blocked** when:

| Condition | Code Evidence |
|-----------|---------------|
| `AndroidExecutionPhase.gate_decision` on a live flow | `core/flow_level_operator_surface.py` → `AndroidExecutionPhase.gate_decision.is_blocking()` → True |
| `FlowOperatorProjection.blocking_reason != ""` | `core/flow_level_operator_surface.py` → `FlowOperatorProjection.blocking_reason` |
| `AndroidCanonicalExecutionEvent.is_blocking == True` | `core/flow_level_operator_surface.py` → `AndroidCanonicalExecutionEvent.is_blocking` |
| `MatrixVerdict.BLOCKED` from `ReadinessMatrix` | `core/runtime_readiness_matrix.py` → `MatrixVerdict` |
| `ReadinessState.accessibilityReady == False` on Android while a task is being dispatched | `UFOGalaxyApplication.readinessState.accessibilityReady` |

### 7.3 — `pending-first-download`

Show as **pending-first-download** when:

| Condition | Code Evidence |
|-----------|---------------|
| `NativeInferenceLoader.ncnnAvailable == False` AND `MODEL_ID_SEECLICK` not downloaded | `ModelManifest.forKnownModel(MODEL_ID_SEECLICK)` + `ModelDownloader` |
| `NativeInferenceLoader.llamaCppAvailable == False` AND `MODEL_ID_MOBILEVLM` not downloaded | `ModelManifest.forKnownModel(MODEL_ID_MOBILEVLM)` + `ModelDownloader` |
| `ReadinessState.modelReady == False` at startup before first `ensureModelsAtStartup()` completion | `UFOGalaxyApplication.ensureModelsAtStartup()` — runs in `Dispatchers.IO + SupervisorJob` at startup |
| `CompatibilityResult.Unknown` for any model when runtime version is not yet determined | `ModelManifest.checkCompatibility(null)` → `CompatibilityResult.Unknown` |

**Special semantics:** `minDiskSpaceBytes` must be checked before download:
- MobileVLM: `950_000_000` bytes (~900 MB) — `ModelManifest.forKnownModel(MODEL_ID_MOBILEVLM).minDiskSpaceBytes`  
- SeeClick param: `50_000_000` bytes — `ModelManifest.forKnownModel(MODEL_ID_SEECLICK).minDiskSpaceBytes`  
- SeeClick weights: `400_000_000` bytes — `ModelManifest.forKnownModel(MODEL_ID_SEECLICK_BIN).minDiskSpaceBytes`

### 7.4 — `requires-restart`

Show as **requires-restart** (process restart of V2) when:

| Condition | Code Evidence |
|-----------|---------------|
| `enable_continuum` changed | `config.json` flag read at startup; no hot-reload defined for it |
| `enable_desktop_presence_runtime` changed | `config.json` flag |
| `enable_task_dag` changed | `config.json` flag |
| `enable_cognitive_field_engine` changed | `config.json` flag |
| `heartbeat.enabled` changed | `core/openclawd_heartbeat.py` → `_load_yaml_config("config/agent.yaml")` at `HeartbeatScheduler.__init__()` |
| `PortConfig` YAML changes | `core/port_config.py` → loaded once at singleton init; `PortConfig.reset()` is test-only |
| New Python node port assignment | `config/unified_ports.yaml` — read once at startup by `PortConfig._load()` |

### 7.5 — `requires-reconnect`

Show as **requires-reconnect** (re-establishment of WS/NATS connection) when:

| Condition | Code Evidence |
|-----------|---------------|
| `network.gateway_url` changed | `core/config_schema.py` → `CONFIG_KEYS`; gateway client uses this at connect time |
| `network.android_gateway_url` changed | Same; Android `RemoteConfigFetcher` re-fetches only at startup |
| `network.nats_url` changed | `core/nats_bus.py` → configured via `GALAXY_NATS_URL` env var read at `connect()` call |
| Android `AppSettings.galaxyGatewayUrl` changed | Android re-reads at startup only; WS must be closed and reconnected |
| `android.inference_mode` changed from `center` to `local` or `hybrid` | Routing must re-evaluate capability; Android side must re-initialize `LocalInferenceRuntimeManager` |

### 7.6 — `requires-android-restart`

Show as **requires-android-restart** (Android app restart) when:

| Condition | Code Evidence |
|-----------|---------------|
| `BuildConfig.GALAXY_SERVER_URL` is the active URL (no runtime override) | `app/build.gradle` → `buildConfigField`; only changeable via rebuild |
| `CROSS_DEVICE_ENABLED = false` in BuildConfig and runtime override not set | `app/build.gradle` → `CROSS_DEVICE_ENABLED` |
| `NativeInferenceLoader` failed and inference_mode is `local` | `NativeInferenceLoader.loadAll()` runs only in `onCreate()` |

### 7.7 — `unknown`

Show as **unknown** when:

| Condition | Code Evidence |
|-----------|---------------|
| `DimensionStatus.UNKNOWN` for a readiness dimension | `core/runtime_readiness_matrix.py` → `DimensionStatus.UNKNOWN` — "fail-safe default when dimension cannot be evaluated" |
| `AndroidExecutionPhase.unknown` on a delegated flow | `core/flow_level_operator_surface.py` → `AndroidExecutionPhase.unknown` — "current Android execution phase cannot be determined from the information available to V2" |
| `CompatibilityResult.Unknown` for a model | `com.ufo.galaxy.model.ModelManifest` → `CompatibilityResult.Unknown` — "proceed with a warning rather than blocking execution" |
| `ExecutorInspection.last_heartbeat == None` | `core/operator_surface.py` → `ExecutorInspection.last_heartbeat` — no heartbeat received yet |
| `FlowOperatorProjection.truth_alignment_status == ""` | `core/flow_level_operator_surface.py` → `FlowOperatorProjection.truth_alignment_status` — no alignment decision recorded |

---

## Section 8: Final Operator-Plane Truth Verdict

### 8.1 — What Actually Exists as an Operator Plane Today

Based on reading actual source code, the following is the real current operator/control plane:

**V2 Center-side:**
- `core/operator_surface.py` (`OperatorSurface` class, `OperatorSnapshot` dataclass, all `inspect_*` methods) — **fully implemented**, layer 10 architecture position declared, authority sentinels in place
- `core/flow_level_operator_surface.py` (`FlowLevelOperatorSurface`, `FlowOperatorProjection`, `AndroidExecutionPhase`) — **fully implemented**, projection-only, all Android execution phase semantics defined
- `GET /api/v1/operator` endpoint (PR-510) — **exists**, wired to `OperatorSurface`
- `GET /api/v1/config` / `POST /api/v1/config` — **exists**, wired to `ConfigService` / `ConfigStore`
- `GET /api/v1/health` — **exists** (Batch PR-4)
- `core/config_service.py` with `ConfigValidationResult` and `ProviderStatus` — **fully implemented**, provides per-provider readiness (enabled + has_key)
- `core/runtime_readiness_matrix.py` with `ReadinessMatrix` and blocking verdict — **fully implemented**, but no REST endpoint serving it
- `core/multi_llm_router.py` with per-provider `ProviderConfig.status` / latency / errors — **fully implemented**, but not surfaced in operator API responses
- Port map in `core/port_config.py` + `config/unified_ports.yaml` (130 nodes) — **fully implemented**, not exposed via REST

**Android-side:**
- `com.ufo.galaxy.runtime.NativeInferenceLoader` — **exists**, loads llama.cpp + NCNN at startup, logs result
- `com.ufo.galaxy.service.ReadinessChecker` → `ReadinessState` — **exists**, tri-flag readiness snapshot
- `com.ufo.galaxy.model.ModelManifest` + `ModelAssetManager` + `ModelDownloader` — **fully implemented**, SHA256 verification, disk space pre-check, HuggingFace sources
- `com.ufo.galaxy.local.LocalLoopReadinessProvider` — **exists**, single source of truth for local-loop readiness
- `com.ufo.galaxy.observability.GalaxyLogger` / `MetricsRecorder` / `TraceContext` — **fully implemented**
- `com.ufo.galaxy.config.RemoteConfigFetcher` — **exists**, fetches V2 config at startup

### 8.2 — What Remains to Be Surfaced and Unified

The following gaps are specifically grounded in code evidence:

#### Gap 1: V2 Runtime State Not in Operator API
- **`TriState`** (SILENT/LIMINAL/MANIFEST) is never serialized into any REST response. `DesktopPresenceRuntime._state` exists but is inaccessible to an operator console.
- **NATS connectivity** (`is_connected()`, `get_stats()`) is not in any operator endpoint.
- **Per-provider live health** (`ProviderConfig.status`, `latency_avg_ms`, `error_count`, `last_error`) is tracked in `MultiLLMRouter` but `GET /api/v1/operator` does not include it; `ConfigValidationResult.provider_statuses` shows config-readiness only.
- **`ReadinessMatrix`** is machine-readable but has no REST endpoint; operator cannot poll it.
- **`HeartbeatScheduler`** cycle count and tier escalation history are not observable.
- **Active flow projections** via `FlowLevelOperatorSurface.inspect_flow()` are not served at a REST path.

#### Gap 2: Android State Not Projected to V2
- **`NativeInferenceLoader` result** (`llamaCppAvailable`, `ncnnAvailable`) is logged at Android startup but V2 never receives it as a structured message.
- **`ReadinessState`** (modelReady, accessibilityReady, overlayReady) is stored in `UFOGalaxyApplication.readinessState` but not reported to V2 via WS.
- **`LocalLoopReadiness`** is the single source of truth for local-loop capability but V2 cannot query it.
- **`ModelManifest` identity** (which model is present, what SHA256, what quantization) is never sent to V2.
- **`AndroidExecutionPhase` as a live V2 signal:** The `FlowLevelOperatorSurface` projection layer exists on V2 and `AndroidCanonicalExecutionEventOwner.kt` exists on Android, but the pipeline from Android loop execution phase changes to V2-absorbed `AndroidCanonicalExecutionEvent` records requires WS message wiring that is not confirmed complete.
- **`GroundingFallbackLadder` / `PlannerFallbackLadder` tier** — V2 cannot see which fallback tier Android is on.
- **`OfflineTaskQueue` depth** — V2 cannot see how many tasks are queued for replay.

#### Gap 3: Configuration Synchronization
- `android.inference_mode` exists in V2's `CONFIG_KEYS` but Android does not have a matching typed enum; the `CROSS_DEVICE_ENABLED` BuildConfig flag partially maps to it but there is no structured config sync protocol.
- The three-level gateway URL resolution (BuildConfig → RemoteConfigFetcher → SharedPreferences) is functional but V2 cannot verify which URL Android is actually using at runtime.

#### Gap 4: Missing Dedicated Endpoints
The following endpoints are architecturally implied by existing modules but not yet defined in `core/api_routes.py`:
- `GET /api/v1/readiness` → `ReadinessMatrix.to_dict()` from `core/runtime_readiness_matrix.py`
- `GET /api/v1/operator/flows` → list of `FlowOperatorProjection` from `FlowLevelOperatorSurface`
- `GET /api/v1/operator/flows/{flow_id}` → single `FlowOperatorProjection`
- `GET /api/v1/operator/llm` → `ProviderConfig` health list from `MultiLLMRouter`
- `GET /api/v1/operator/nats` → `nats_bus.is_connected()` + `nats_bus.get_stats()`
- `GET /api/v1/operator/heartbeat` → `HeartbeatScheduler` cycle state
- `GET /api/v1/ports` → `PortConfig.list_node_ports()` + `list_service_ports()`

#### Gap 5: Android Capability Advertisement Protocol
V2's `FlowLevelOperatorSurface` is designed to absorb Android execution events, and `AndroidCanonicalExecutionEventOwner.kt` exists in `com.ufo.galaxy.runtime`. However, there is no confirmed REST or WS message type in `core/device_communication.py` → `MessageType` that carries:
- `ReadinessState` from Android to V2
- Model manifest / native runtime availability
- Local loop readiness
- Fallback tier state
- `RuntimeHealthSnapshot`

The `MessageType.WAKE_EVENT` exists in V2's protocol as `"wake_event"`, and `MessageType.HEARTBEAT` carries keepalive. A structured **capability advertisement** message type (distinct from heartbeat) for the above state is absent from `MessageType` enum in `core/device_communication.py`.

### 8.3 — Summary Verdict Table

| Dimension | Status | Evidence |
|-----------|--------|----------|
| V2 task-level operator surface | **EXISTS — not fully exposed** | `OperatorSurface`, `GET /api/v1/operator`; TriState, NATS, LLM health, flow projections missing from API |
| V2 flow-level Android execution surface | **EXISTS — not plumbed to REST** | `FlowLevelOperatorSurface.inspect_flow()` exists; no REST path; depends on Android event emission pipeline |
| V2 config service | **COMPLETE** | `ConfigService`, `ConfigStore`, `ConfigSchema`; `GET/POST /api/v1/config` wired |
| V2 provider readiness (config-plane) | **COMPLETE** | `ConfigValidationResult.provider_statuses` from `ConfigService.validate()` |
| V2 provider health (runtime-plane) | **NOT SURFACED** | `ProviderConfig.status/latency/errors` in `MultiLLMRouter` — not in operator API |
| V2 release readiness matrix | **EXISTS — not in REST** | `ReadinessMatrix`; no `/api/v1/readiness` endpoint |
| V2 port map | **EXISTS — not in REST** | `PortConfig` + `unified_ports.yaml` (130 nodes); no REST endpoint |
| Android native runtime state | **NOT REPORTED TO V2** | `NativeInferenceLoader`, `ReadinessState`, `LocalLoopReadiness` — Android-local only |
| Android model identity / manifests | **NOT REPORTED TO V2** | `ModelManifest.forKnownModel()` — Android-local; V2 has no model presence information |
| Android execution phase projection | **ARCHITECTURE EXISTS — WIRING INCOMPLETE** | `AndroidExecutionPhase`, `FlowLevelOperatorSurface`, `AndroidCanonicalExecutionEventOwner.kt`; WS message pipeline not confirmed complete |
| Config sync V2 → Android | **PARTIAL** | `RemoteConfigFetcher` pulls `android.inference_mode` at startup; no runtime sync protocol |
| Android capability advertisement to V2 | **MISSING** | No `MessageType` for structured capability/readiness advertisement in `core/device_communication.py` |
| Operator console UI | **NOT EXISTS** | No console UI file found; `OPERATOR_CONSOLE_ROLE`, `STATUS_BOARD_ROLE`, `TOPOLOGY_VIEWER_ROLE` sentinels exist in `core/operator_surface.py` — role boundaries are defined but no implementation |

---

*End of OPERATOR SURFACE CLOSURE AUDIT 2026.*  
*All claims above are grounded exclusively in source code read from the two repositories.*  
*No design documents, PRDs, or prior audit markdown files were used as evidence.*
