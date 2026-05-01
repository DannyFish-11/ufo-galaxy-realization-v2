"""
core/operational_enablement_audit.py
=====================================
Deep Dual-Repository Operational Enablement Audit — 2026

**METHODOLOGY DECLARATION**
----------------------------
Every fact in this module is derived exclusively from direct inspection of
real source files in both repositories:

  V2  : DannyFish-11/ufo-galaxy-realization-v2  (this repo)
  APK : DannyFish-11/ufo-galaxy-android

No prior audit documents, verdict files, or narrative markdown summaries are
used as evidence.  Each constant below names the exact source file and symbol
that substantiates the claim.

**SCOPE**
---------
1. V2-side operator configuration reality
2. Android-side operator configuration reality
3. Desktop state board / desktop control surface reality
4. Agent runtime mode / "three states" reality
5. Android on-device model provisioning reality
6. Clone → build → configure → run reality
7. Final operability verdict

Authority sentinel
------------------
``OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY = "core.operational_enablement_audit"``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY: str = "core.operational_enablement_audit"

AUDIT_SCOPE: str = (
    "V2=DannyFish-11/ufo-galaxy-realization-v2 "
    "APK=DannyFish-11/ufo-galaxy-android "
    "evidence=real-source-code-only"
)

# ===========================================================================
# SECTION 1 — V2-SIDE OPERATOR CONFIGURATION REALITY
# ===========================================================================
#
# Source files examined:
#   core/config_schema.py          — canonical key classification, SECRET_KEYS, VALID_PROVIDERS
#   core/config_store.py           — low-level I/O; runtime/config.json + runtime/secrets.env
#   core/config_service.py         — high-level API; provider enable/disable, routing policy
#   core/config_preflight.py       — pre-flight validation; reads runtime/secrets.env at startup
#   core/unified_config.py         — compatibility facade; merges all sources
#   core/config_hot_reload.py      — HotReloadConfigManager; file-watch based live reload
#   setup_wizard.py                — interactive CLI wizard (python main.py --setup)
#   config.json                    — static root defaults (project root)
#   config/unified_ports.yaml      — port assignments (referenced in unified_config.py docstring)
#   core/routes/vault.py           — API vault: POST /api/v1/vault/credentials writes secrets
# ---------------------------------------------------------------------------

class V2ConfigSource(str, Enum):
    """
    Canonical config source layers, ordered lowest → highest precedence.
    Source: core/unified_config.py docstring "Config source precedence" section.
    """
    STATIC_CONFIG_JSON        = "config.json (root)"          # lowest; read-only static defaults
    RUNTIME_CONFIG_JSON       = "runtime/config.json"         # written by ConfigService/ConfigStore
    RUNTIME_SECRETS_ENV       = "runtime/secrets.env"         # written by ConfigService/ConfigStore
    LEGACY_DOT_ENV            = ".env"                        # user-managed legacy secrets file
    PROCESS_ENVIRONMENT       = "os.environ"                  # highest; CLI / Docker / CI overrides


V2_CONFIG_SOURCE_PRECEDENCE: List[V2ConfigSource] = [
    V2ConfigSource.STATIC_CONFIG_JSON,     # lowest
    V2ConfigSource.RUNTIME_CONFIG_JSON,
    V2ConfigSource.RUNTIME_SECRETS_ENV,
    V2ConfigSource.LEGACY_DOT_ENV,
    V2ConfigSource.PROCESS_ENVIRONMENT,    # highest
]
"""
Config source precedence list (low → high).
Source: core/unified_config.py _load_config / _load_from_config_store / _load_env call order.
"""

V2_REQUIRED_API_KEY_ENV_VARS: List[str] = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "ONEAPI_API_KEY",
    "GALAXY_API_TOKEN",
    "SECRETVAULT_MASTER_KEY",
]
"""
All recognised secret keys.
Source: core/config_schema.py SECRET_KEYS frozenset.
At least one of the LLM provider API keys (OPENAI, ANTHROPIC, GEMINI, DEEPSEEK, GROQ, etc.)
is required for the AI inference chain to function.
GALAXY_API_TOKEN is required only when the auth middleware is active.
"""

V2_VALID_PROVIDERS: List[str] = [
    "openai", "anthropic", "gemini", "deepseek",
    "groq", "openrouter", "oneapi",
]
"""
Recognised LLM provider IDs.
Source: core/config_schema.py VALID_PROVIDERS frozenset.
"""

V2_NON_SECRET_CONFIG_KEYS: List[str] = [
    "providers.openai.enabled",
    "providers.anthropic.enabled",
    "providers.gemini.enabled",
    "providers.deepseek.enabled",
    "providers.groq.enabled",
    "providers.openrouter.enabled",
    "providers.oneapi.enabled",
    "providers.oneapi.base_url",
    "routing.native_mm_policy",
    "routing.primary_provider",
]
"""
Non-secret runtime config keys stored in runtime/config.json.
Source: core/config_schema.py CONFIG_KEYS frozenset.
"""

# Runtime-editable vs startup-only classification
V2_STARTUP_ONLY_CONFIG: List[str] = [
    "GALAXY_SYSTEM_MODE",
    "GALAXY_NATS_URL",
    "GALAXY_NATS_ENABLED",
    "GALAXY_FABRIC_STRICT",
    "GALAXY_NETWORK_MODE",
    "GALAXY_CROSS_DEVICE_ENABLED",
    "GALAXY_TAILSCALE_ENABLED",
    "GALAXY_TAILSCALE_HOST",
    "GALAXY_TRANSPORT_PRIORITY",
]
"""
System-mode and fabric config env vars read once at import time by core/system_mode.py.
FABRIC_CONFIG is a frozen dataclass resolved at import; changing these env vars at
runtime does NOT affect the running process without a restart.
Source: core/system_mode.py resolve_fabric_config() and FABRIC_CONFIG singleton.
"""

V2_RUNTIME_HOT_RELOADABLE_CONFIG: List[str] = [
    "providers.<name>.enabled",
    "routing.native_mm_policy",
    "routing.primary_provider",
]
"""
Config keys that can be changed without restarting the V2 process.
After a ConfigService write, HotReloadConfigManager propagates the change to subscribers.
Source: windows_client/status_board_v2/config_control.py ConfigControlSurface._apply_change()
        → core/config_service.py ConfigService.set_provider_enabled() / set_routing_policy()
        → core/config_hot_reload.py HotReloadConfigManager (file watcher + subscriber notify).
"""

V2_CONFIG_SETUP_PATHS: List[str] = [
    "python main.py --setup  → setup_wizard.py (interactive CLI wizard)",
    "POST /api/v1/vault/credentials  → core/routes/vault.py (API; auth-gated)",
    "edit .env or runtime/secrets.env directly  (manual)",
    "status_board_v2 config_control surface  → provider toggle / routing policy only",
]
"""
All paths by which an operator can configure the V2 system.
Sources: main.py --setup shortcut; core/routes/vault.py; core/unified_config.py;
         windows_client/status_board_v2/config_control.py.
"""


# ===========================================================================
# SECTION 2 — ANDROID-SIDE OPERATOR CONFIGURATION REALITY
# ===========================================================================
#
# Source files examined:
#   app/build.gradle                           — BuildConfig fields (compile-time defaults)
#   app/src/main/assets/config.properties      — packaged asset defaults (override BuildConfig)
#   app/src/main/java/.../data/AppSettings.kt  — SharedPreferences runtime settings authority
#   app/src/main/java/.../ui/NetworkSettingsScreen.kt — full settings UI (Compose)
#   app/src/main/java/.../UFOGalaxyApplication.kt     — initConfig(), initRemoteGatewayConfig()
#   app/src/main/java/.../config/RemoteConfigFetcher.kt — M3: GET /api/v1/config auto-fill
# ---------------------------------------------------------------------------

class AndroidConfigLayer(str, Enum):
    """
    Android configuration hierarchy, ordered lowest → highest precedence.
    Source: app/src/main/assets/config.properties header comment
            and app/build.gradle comment on GALAXY_SERVER_URL.
    """
    BUILD_CONFIG     = "BuildConfig (app/build.gradle)"
    ASSET_DEFAULTS   = "assets/config.properties"
    SHARED_PREFS     = "SharedPreferences (AppSettings)"


ANDROID_CONFIG_PRECEDENCE: List[AndroidConfigLayer] = [
    AndroidConfigLayer.BUILD_CONFIG,    # lowest: last-resort fallback
    AndroidConfigLayer.ASSET_DEFAULTS,  # middle: packaged defaults
    AndroidConfigLayer.SHARED_PREFS,    # highest: user-saved settings
]
"""
Source: UFOGalaxyApplication.kt initConfig() commentary and AppSettings.kt seeding logic.
"""

ANDROID_SERVER_URL_DEFAULT_DEBUG: str = "ws://192.168.1.100:8765"
"""
Build-time default for debug APK.
Source: app/build.gradle buildConfigField "String", "GALAXY_SERVER_URL",
        '"ws://192.168.1.100:8765"'
"""

ANDROID_SERVER_URL_DEFAULT_RELEASE: str = "wss://galaxy.ufo.ai:8765"
"""
Build-time default for release APK.
Source: app/build.gradle buildTypes.release buildConfigField "String", "GALAXY_SERVER_URL",
        '"wss://galaxy.ufo.ai:8765"'
"""

ANDROID_ASSET_GATEWAY_URL_PLACEHOLDER: str = "ws://100.x.x.x:8765"
"""
Packaged asset default — intentionally a placeholder requiring operator substitution.
Source: app/src/main/assets/config.properties, key galaxy_gateway_url.
The comment explicitly says: 'Replace 100.x.x.x with the actual Tailscale IP of the gateway host.'
"""

ANDROID_CROSS_DEVICE_DEFAULT: bool = False
"""
Default value for cross_device_enabled.
Source: app/src/main/assets/config.properties cross_device_enabled=false
        AND app/build.gradle buildConfigField "boolean", "CROSS_DEVICE_ENABLED", "false"
"""

ANDROID_SERVER_URL_RUNTIME_EDITABLE: bool = True
"""
The serverUrl (galaxyGatewayUrl) CAN be changed at runtime without rebuilding the APK.
The NetworkSettingsScreen.kt UI writes the new host/port to AppSettings (SharedPreferences),
and 'Save and Reconnect' immediately triggers a WebSocket reconnect.
Source: ui/NetworkSettingsScreen.kt onSaveAndReconnect callback.
"""

ANDROID_CROSS_DEVICE_RUNTIME_EDITABLE: bool = True
"""
cross_device_enabled CAN be toggled at runtime without rebuilding the APK.
Source: config.properties comment: 'the runtime value can be toggled via
        UFOGalaxyApplication.setCrossDeviceEnabled(Boolean) or the developer settings menu.'
Changes persist because AppSettings writes to SharedPreferences.
"""

ANDROID_SETTINGS_UI_EXISTS: bool = True
"""
A full settings UI exists in the installed app.
Source: app/src/main/java/com/ufo/galaxy/ui/NetworkSettingsScreen.kt
Composable NetworkSettingsScreen provides:
  - Gateway host/IP text field
  - Port text field
  - TLS toggle switch
  - Allow self-signed cert toggle (debug only)
  - Device ID text field
  - REST base URL text field
  - Metrics endpoint text field
  - Save button (writes to SharedPreferences)
  - Save and Reconnect button (writes + triggers WS reconnect)
  - Auto-discover button (calls TailscaleAdapter.autoDiscoverNode50)
  - Fill Tailscale IP button
  - Run Diagnostics button
"""

ANDROID_REMOTE_CONFIG_FETCH: bool = True
"""
M3 feature: on startup, UFOGalaxyApplication calls initRemoteGatewayConfig(),
which uses RemoteConfigFetcher to GET /api/v1/config from the current gateway URL.
If successful, the returned JSON is passed to AppSettings.applyGatewayConfig() so
that galaxyGatewayUrl / gatewayHost / gatewayPort are updated automatically before
the WebSocket connection is established.
Source: UFOGalaxyApplication.kt initRemoteGatewayConfig() docstring.
Failures are logged and local config is preserved unchanged.
"""


# ===========================================================================
# SECTION 3 — DESKTOP STATE BOARD / CONTROL SURFACE REALITY
# ===========================================================================
#
# Source files examined:
#   windows_client/status_board_v2/__init__.py      — package doc: lists all surface layers
#   windows_client/status_board_v2/config_control.py — ConfigControlSurface (writable control)
#   core/operator_surface.py                        — OperatorSurface (read-only projection)
#   core/desktop_consumption_adapter.py             — flat view-model adapter
#   core/desktop_presence_runtime.py               — tri-state lifecycle
#   core/routes/projection.py                       — GET /api/v1/projection/* endpoints
# ---------------------------------------------------------------------------

class DesktopBoardCapability(str, Enum):
    """What the status_board_v2 package is capable of."""
    STATUS_READ_ONLY           = "read_only_status_projection"
    CONFIG_WRITE_PROVIDER      = "config_write_provider_enable_disable"
    CONFIG_WRITE_ROUTING       = "config_write_routing_policy"
    TOPOLOGY_INSPECT           = "topology_inspect_nodes_and_relations"
    DIAGNOSTIC_INSPECT         = "diagnostic_inspect_single_task"
    TASK_ROUTE_INSPECT         = "task_route_and_executor_inspect"


DESKTOP_BOARD_IS_CONTROL_SURFACE: bool = True
"""
The status_board_v2 is NOT a read-only status panel.
It includes ConfigControlSurface which can:
  - Toggle provider enabled/disabled (ControlOperation.TOGGLE_PROVIDER)
  - Set routing policy (ControlOperation.SET_ROUTING_POLICY: strict|prefer|allow_fallback)
All writes flow through: ConfigControlSurface → ConfigService → ConfigStore → runtime/config.json
Hot-reload is attempted after each successful write.
Source: windows_client/status_board_v2/config_control.py
        class ConfigControlSurface, class ControlOperation.
"""

DESKTOP_BOARD_WRITE_OPERATIONS: List[str] = [
    "toggle_provider: enable/disable any of the 7 recognized LLM providers",
    "set_routing_policy: strict | prefer | allow_fallback",
]
"""
The complete, bounded set of write operations the status board can perform.
Source: windows_client/status_board_v2/config_control.py ControlOperation enum.
"""

DESKTOP_BOARD_READ_SURFACES: List[str] = [
    "PhaseSurface       — tri-state phase (silent/liminal/manifest)",
    "DomainSurface      — runtime domain (local/cross_device/transition)",
    "TopologySurface    — model topology weights (top-N)",
    "DeviceSurface      — active devices and execution stage",
    "MetricsSurface     — presence/coherence/tendency metrics",
    "LiminalSurface     — liminal spatial projection dimensions",
    "ManifestSurface    — manifest stage execution surface",
    "ReturnSurface      — return intelligence summary",
    "AdapterSurface     — adapter-driven integrated PR-10 payload",
    "TopologyInspector  — node/relation/readiness/routing inspection (PR-13)",
    "TopologyHistory    — topology history (PR-14)",
]
"""
All read-only projection surfaces in the status board.
Source: windows_client/status_board_v2/__init__.py package docstring.
"""

DESKTOP_BOARD_WRITE_PERSISTENCE: bool = True
"""
Writes from the control surface DO persist across restarts.
ConfigStore writes to runtime/config.json (non-secrets) and runtime/secrets.env (secrets),
which are loaded at next startup by UnifiedConfig._load_from_config_store().
Source: core/config_store.py ConfigStore.write_config() / write_secret().
"""

DESKTOP_BOARD_AFFECTS_RUNTIME: bool = True
"""
Writes from the control surface DO affect runtime behavior immediately.
ConfigControlSurface._apply_change() calls HotReloadConfigManager after a successful write
so that runtime subscribers (e.g., multi_llm_router) receive the new config without restart.
Source: windows_client/status_board_v2/config_control.py ConfigControlSurface._apply_change()
        docstring: 'Hot-reload — after a successful write, the surface attempts to trigger
        the existing HotReloadConfigManager to immediately propagate the change to runtime subscribers.'
"""

DESKTOP_BOARD_VERDICT: str = (
    "STATUS_PLUS_BOUNDED_CONTROL — the status board is more than a read-only panel: "
    "it provides a real, write-through, hot-reload-enabled control surface for the "
    "provider and routing dimensions of the config. It is NOT a full operator console "
    "(cannot set API keys, cannot modify system-mode env vars, cannot dispatch tasks). "
    "For a mature operator, it fills the day-to-day config surface requirement."
)


# ===========================================================================
# SECTION 4 — AGENT RUNTIME MODE / "THREE STATES" REALITY
# ===========================================================================
#
# Source files examined:
#   core/desktop_presence_runtime.py           — TriState enum + DesktopPresenceRuntime
#   system_integration/hardware_trigger.py     — SystemState enum (UI shell expansion modes)
#   core/system_mode.py                        — SystemMode enum (fabric/deployment modes)
# ---------------------------------------------------------------------------

class TriStateMode(str, Enum):
    """
    Canonical subject lifecycle tri-state.
    Source: core/desktop_presence_runtime.py class TriState(str, Enum).
    This is the 'three states' the user referred to.
    """
    SILENT   = "silent"    # at rest; multimodal ingress continues
    LIMINAL  = "liminal"   # request received; OpenClawd cognition in progress
    MANIFEST = "manifest"  # actively producing output / controlling devices


TRI_STATE_IS_REAL_RUNTIME_MODE: bool = True
"""
The three states are NOT display labels. They are real runtime mode gates.
DesktopPresenceRuntime drives the lifecycle: no adapter can skip the progression.
In LIMINAL, OpenClawd.process() is actively running.
In MANIFEST, device control / output dispatch is active.
Source: core/desktop_presence_runtime.py DesktopPresenceRuntime._transition_to(),
        handle_request(), and the docstring 'Drive tri-state transitions; no adapter/launcher
        can skip the progression.'
"""

TRI_STATE_BEHAVIORAL_CONSEQUENCES: Dict[str, str] = {
    TriStateMode.SILENT: (
        "Subject at rest. Native multimodal ingress (PerceptionFrame) active in background. "
        "No active cognition request. Incoming requests trigger transition to LIMINAL."
    ),
    TriStateMode.LIMINAL: (
        "OpenClawd.process() is invoked with the runtime_session_id. "
        "Continuum orchestration, decision branching, and route selection are in progress. "
        "Both LOCAL_EXECUTION_CHAIN and CROSS_DEVICE_EXECUTION_CHAIN are candidates here."
    ),
    TriStateMode.MANIFEST: (
        "Subject actively producing output, controlling devices, or expanding into "
        "a cross-device loop. Transitions back to SILENT upon completion."
    ),
}
"""
Source: core/desktop_presence_runtime.py TriState enum docstring + handle_request() flow.
"""

TRI_STATE_UI_CONTROL_SURFACE: str = (
    "Status board V2 PhaseSurface reads the current tri-state phase from the canonical "
    "projection endpoint GET /api/v1/projection/runtime-truth. "
    "The status board DISPLAYS but does NOT directly set the tri-state — the lifecycle "
    "is driven by the runtime shell and subject core, not by operator commands."
)
"""
Source: windows_client/status_board_v2/phase_surface.py (display only)
        and core/desktop_presence_runtime.py (authoritative driver).
"""

class UIShellMode(str, Enum):
    """
    Desktop clothing expansion modes — NOT the subject lifecycle tri-state.
    These describe how the desktop UI shell is rendered, not what the subject is doing.
    Source: system_integration/hardware_trigger.py class SystemState(str, Enum).
    """
    DORMANT   = "dormant"    # clothing hidden / collapsed
    ISLAND    = "island"     # compact clothing mode (dynamic island style)
    SIDESHEET = "sidesheet"  # side panel clothing expansion
    FULLAGENT = "fullagent"  # full clothing expansion


class FabricMode(str, Enum):
    """
    Fabric / deployment modes — resolved once at startup from env vars.
    Source: core/system_mode.py class SystemMode(str, Enum).
    """
    DESKTOP_LOCAL         = "desktop-local"        # default; no cross-device fabric
    DESKTOP_CROSS_DEVICE  = "desktop-cross-device" # opt-in; NATS / control-plane active


THREE_STATE_DISAMBIGUATION: Dict[str, str] = {
    "user_referred_three_states": (
        "TriState: SILENT / LIMINAL / MANIFEST — the subject lifecycle. "
        "These are real runtime mode gates in core/desktop_presence_runtime.py."
    ),
    "ui_shell_four_states": (
        "UIShellMode: DORMANT / ISLAND / SIDESHEET / FULLAGENT — desktop rendering modes. "
        "These describe how the Windows desktop clothing is displayed, not what is executing."
    ),
    "fabric_two_modes": (
        "FabricMode: desktop-local / desktop-cross-device — deployment topology modes. "
        "Set via GALAXY_SYSTEM_MODE env var; resolved once at startup."
    ),
}


# ===========================================================================
# SECTION 5 — ANDROID ON-DEVICE MODEL PROVISIONING REALITY
# ===========================================================================
#
# Source files examined:
#   app/src/main/java/.../model/ModelAssetManager.kt      — model registry + verify + evict
#   app/src/main/java/.../model/ModelDownloader.kt        — download via HttpURLConnection
#   app/src/main/java/.../model/ModelManifest.kt          — HuggingFace source definitions
#   app/src/main/java/.../model/ModelProvisioningPipeline.kt — 8-stage formal pipeline
#   app/src/main/java/.../UFOGalaxyApplication.kt          — ensureModelsAtStartup()
#   app/build.gradle                                       — dependencies section
# ---------------------------------------------------------------------------

ANDROID_MODELS: List[Dict] = [
    {
        "model_id":         "mobilevlm",
        "role":             "MobileVLM V2-1.7B — UI planning / task planning",
        "runtime_type":     "llama.cpp GGUF",
        "file":             "mobilevlm-v2-1.7b.Q4_K_M.gguf",
        "size_bytes_approx": 1_200_000_000,
        "huggingface_repo": "ZiangWu/MobileVLM_V2-1.7B-GGUF",
        "huggingface_url":  "https://huggingface.co/ZiangWu/MobileVLM_V2-1.7B-GGUF/resolve/main/mobilevlm-v2-1.7b.Q4_K_M.gguf",
        "sha256":           None,  # Source: ModelAssetManager.MOBILEVLM_SHA256 = null (TODO comment)
        "sha256_note":      "EXPLICITLY null in code — verification bypassed in current build",
    },
    {
        "model_id":         "seeclick",
        "role":             "SeeClick NCNN param file — UI grounding / element coordinate",
        "runtime_type":     "NCNN",
        "file":             "seeclick.ncnn.param",
        "size_bytes_approx": 50_000_000,
        "huggingface_repo": "cckevinn/SeeClick",
        "huggingface_url":  "https://huggingface.co/cckevinn/SeeClick/resolve/main/ncnn/seeclick.ncnn.param",
        "sha256":           None,  # Source: ModelAssetManager.SEECLICK_SHA256 = null (TODO comment)
        "sha256_note":      "EXPLICITLY null in code — verification bypassed in current build",
    },
    {
        "model_id":         "seeclick_bin",
        "role":             "SeeClick NCNN bin weights — UI grounding / element coordinate",
        "runtime_type":     "NCNN",
        "file":             "seeclick.ncnn.bin",
        "size_bytes_approx": 400_000_000,
        "huggingface_repo": "cckevinn/SeeClick",
        "huggingface_url":  "https://huggingface.co/cckevinn/SeeClick/resolve/main/ncnn/seeclick.ncnn.bin",
        "sha256":           None,  # Source: ModelAssetManager.SEECLICK_BIN_SHA256 = null (TODO comment)
        "sha256_note":      "EXPLICITLY null in code — verification bypassed in current build",
    },
]
"""
Three model assets tracked by ModelAssetManager.
Sources: ModelAssetManager.kt companion object constants and ModelManifest.kt forKnownModel().
Total download size: ~1.65 GB.
"""

ANDROID_MODEL_DOWNLOAD_MECHANISM: str = (
    "Direct HTTP via java.net.HttpURLConnection (no OkHttp, no specialized HuggingFace SDK). "
    "Download URL is the canonical HuggingFace resolve URL from ModelManifest.HuggingFace.downloadUrl. "
    "Source: ModelDownloader.kt DefaultHttpFactory.open() and ModelManifest.kt HuggingFace.downloadUrl."
)

ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES: List[str] = [
    "1. Compatibility check — manifest.checkCompatibility(runtimeVersion)",
    "2. Low-storage check — modelsDir.usableSpace vs minDiskSpaceBytes; evict if needed",
    "3. Partial-asset cleanup — delete *.tmp leftover from prior interrupted download",
    "4. Download — HttpURLConnection streaming with progress events",
    "5. Checksum verify — SHA-256 inside ModelDownloader (skipped when expectedSha256=null)",
    "6. Atomic install — rename .tmp → final path",
    "7. Activation — ModelAssetManager.markLoaded(modelId)",
    "8. Rollback — on activation failure, revert status; caller can also delete file",
]
"""
Source: ModelProvisioningPipeline.kt class-level docstring listing all 8 stages.
"""

ANDROID_MODEL_PROVISIONING_AUTO_ON_STARTUP: bool = True
"""
At app launch, UFOGalaxyApplication.ensureModelsAtStartup() runs in a background
coroutine (CoroutineScope(Dispatchers.IO + SupervisorJob())).
It calls modelAssetManager.verifyAll(), then modelAssetManager.downloadSpecsForMissing(),
and then modelDownloader.downloadSync() for each missing spec.
Source: UFOGalaxyApplication.kt ensureModelsAtStartup() function.
"""

ANDROID_MODEL_PROVISIONING_LIMITATIONS: List[str] = [
    "SHA-256 checksums are null for all 3 models — integrity verification is BYPASSED. "
    "Source: ModelAssetManager.kt companion object MOBILEVLM_SHA256 / SEECLICK_SHA256 / SEECLICK_BIN_SHA256 = null "
    "with explicit TODO comment 'set before production deployment'.",

    "llama.cpp runtime for MobileVLM is NOT in build.gradle dependencies. "
    "ModelManifest specifies RuntimeType.LLAMA_CPP but no llama.cpp Android library "
    "(e.g., 'io.github.ggml-org:llama.cpp-android' or similar) appears in app/build.gradle. "
    "The local inference path requires llama.cpp to be present and runnable on-device. "
    "Source: app/build.gradle dependencies section (no llama.cpp dependency listed).",

    "NCNN runtime for SeeClick is NOT in build.gradle dependencies. "
    "ModelManifest specifies RuntimeType.NCNN but no NCNN Android AAR appears in app/build.gradle. "
    "Source: app/build.gradle dependencies section (no ncnn dependency listed).",

    "DegradedPlannerService and DegradedGroundingService exist as fallbacks but only "
    "provide stub/degraded behavior — they do NOT perform real MobileVLM or SeeClick inference. "
    "Source: inference/DegradedPlannerService.kt and inference/DegradedGroundingService.kt.",

    "Total model download size is ~1.65 GB (1.2 GB MobileVLM + ~0.45 GB SeeClick). "
    "A first-run on a device without Wi-Fi or with limited storage will likely fail. "
    "Source: ModelManifest.kt minDiskSpaceBytes values.",
]
"""
Critical gaps between the declared model provisioning architecture and a fully runnable state.
"""

ANDROID_MODEL_PROVISIONING_VERDICT: str = (
    "PIPELINE_COMPLETE_BUT_INFERENCE_RUNTIME_NOT_BUNDLED: "
    "The provisioning pipeline (download → verify → activate) is architecturally complete. "
    "Model files can be auto-downloaded from HuggingFace at first run. "
    "However, the actual inference server (llama.cpp for MobileVLM, NCNN for SeeClick) "
    "is not present in app/build.gradle. Without these native runtimes, the downloaded "
    "model files cannot be loaded and executed. The 'local AI loop' capability is "
    "structurally defined but cannot execute on a plain debug/release APK built from "
    "this source tree."
)


# ===========================================================================
# SECTION 6 — CLONE → BUILD → CONFIGURE → RUN REALITY
# ===========================================================================
# ---------------------------------------------------------------------------

@dataclass
class RunbookStep:
    """A single operator action in the clone-to-run sequence."""
    seq: int
    action: str
    required: bool
    rebuild_needed: bool
    notes: str


V2_RUNBOOK: List[RunbookStep] = [
    RunbookStep(
        seq=1,
        action="git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2",
        required=True,
        rebuild_needed=False,
        notes="Python 3.9+ required. Source: README.md.",
    ),
    RunbookStep(
        seq=2,
        action="pip install -r requirements.txt",
        required=True,
        rebuild_needed=False,
        notes="All Python dependencies. Source: requirements.txt.",
    ),
    RunbookStep(
        seq=3,
        action="python main.py --setup  (OR manually create .env / runtime/secrets.env)",
        required=True,
        rebuild_needed=False,
        notes=(
            "At least one LLM provider API key must be filled. "
            "GALAXY_SYSTEM_MODE and GALAXY_CROSS_DEVICE_ENABLED must be set if "
            "cross-device fabric is desired. "
            "Source: setup_wizard.py; core/config_preflight.py; core/system_mode.py."
        ),
    ),
    RunbookStep(
        seq=4,
        action="python main.py",
        required=True,
        rebuild_needed=False,
        notes=(
            "Starts all 7 orchestrator phases and then delegates to unified_launcher.py. "
            "Source: main.py _run_orchestrator_preflight() → unified_launcher.py."
        ),
    ),
    RunbookStep(
        seq=5,
        action="(Optional) Access status_board_v2 to toggle providers or routing policy",
        required=False,
        rebuild_needed=False,
        notes=(
            "Provider toggles and routing policy can be changed at runtime via the "
            "desktop status board without restarting. "
            "Source: windows_client/status_board_v2/config_control.py."
        ),
    ),
]
"""
Minimal V2 runbook derived from main.py, setup_wizard.py, requirements.txt, config_preflight.py.
"""

ANDROID_RUNBOOK: List[RunbookStep] = [
    RunbookStep(
        seq=1,
        action="git clone https://github.com/DannyFish-11/ufo-galaxy-android",
        required=True,
        rebuild_needed=False,
        notes="Kotlin/Android project. JDK 17 required. Source: app/build.gradle compileOptions.",
    ),
    RunbookStep(
        seq=2,
        action="(Optional) Edit app/src/main/assets/config.properties: set galaxy_gateway_url",
        required=False,
        rebuild_needed=True,
        notes=(
            "Changing assets/config.properties requires a rebuild. "
            "Alternatively, change the URL at runtime via NetworkSettingsScreen after install. "
            "Source: app/src/main/assets/config.properties."
        ),
    ),
    RunbookStep(
        seq=3,
        action="./gradlew assembleDebug",
        required=True,
        rebuild_needed=False,
        notes="Produces app/build/outputs/apk/debug/app-debug.apk.",
    ),
    RunbookStep(
        seq=4,
        action="adb install app/build/outputs/apk/debug/app-debug.apk",
        required=True,
        rebuild_needed=False,
        notes="Install on Android 8.0+ (minSdk 26). Source: app/build.gradle defaultConfig.",
    ),
    RunbookStep(
        seq=5,
        action="Grant: Accessibility Service + Overlay permission",
        required=True,
        rebuild_needed=False,
        notes=(
            "Required for UI automation execution. "
            "Source: ReadinessChecker in UFOGalaxyApplication."
        ),
    ),
    RunbookStep(
        seq=6,
        action="Open app → Network Settings → Enter V2 gateway IP/port → Save and Reconnect",
        required=True,
        rebuild_needed=False,
        notes=(
            "Enter the actual Tailscale IP (or LAN IP) of the V2 host. "
            "Enable cross_device_enabled switch. "
            "Source: ui/NetworkSettingsScreen.kt onSaveAndReconnect."
        ),
    ),
    RunbookStep(
        seq=7,
        action="App auto-downloads MobileVLM (~1.2 GB) + SeeClick (~450 MB) from HuggingFace",
        required=True,
        rebuild_needed=False,
        notes=(
            "Requires internet access and ~1.65 GB storage. "
            "Download runs automatically via ensureModelsAtStartup(). "
            "NOTE: even after download, llama.cpp and NCNN runtimes are not bundled — "
            "local AI inference may not work without additional native library setup. "
            "Source: UFOGalaxyApplication.kt ensureModelsAtStartup(); "
            "ModelAssetManager.kt ANDROID_MODEL_PROVISIONING_LIMITATIONS."
        ),
    ),
    RunbookStep(
        seq=8,
        action="Enable 'cross_device_enabled' in Network Settings if not done in step 6",
        required=True,
        rebuild_needed=False,
        notes=(
            "Default is false. Without enabling this, no WebSocket connection is made. "
            "Source: app/src/main/assets/config.properties cross_device_enabled=false."
        ),
    ),
]
"""
Minimal Android runbook derived from build.gradle, assets/config.properties,
UFOGalaxyApplication.kt, ui/NetworkSettingsScreen.kt, and model provisioning code.
"""


# ===========================================================================
# SECTION 7 — FINAL OPERABILITY VERDICT
# ===========================================================================
# ---------------------------------------------------------------------------

class OperabilityTier(str, Enum):
    """
    Operability tier for the integrated dual-repo system.
    """
    MATURE_CONFIGURABLE_APP       = "mature_configurable_application"
    IMPL_COMPLETE_DEVOPS_ORIENTED = "implementation_complete_developer_ops_oriented"
    PARTIALLY_COMPLETE            = "partially_complete"


FINAL_VERDICT: OperabilityTier = OperabilityTier.IMPL_COMPLETE_DEVOPS_ORIENTED
"""
The integrated system is NOT a partially-complete project — the V2 side has a complete
configuration stack, desktop control surface, hot-reload, API vault, and a staged startup.
The Android side has a complete network settings UI, runtime-editable config, and a formal
model provisioning pipeline.

However, it is NOT yet a mature operator-configurable consumer application because:
  1. Android local inference runtimes (llama.cpp, NCNN) are not bundled in build.gradle.
  2. Model SHA-256 checksums are null (integrity verification bypassed).
  3. Cross-device requires an external Tailscale/VPN network; no zero-config provisioning.
  4. GALAXY_SYSTEM_MODE and cross-device flags require manual env var setup on V2 side.

Verdict: IMPLEMENTATION_COMPLETE_DEVELOPER_OPS_ORIENTED — a developer or DevOps-skilled
operator can fully configure, build, and run the system with documented manual steps.
A non-technical end-user cannot do so without additional infrastructure and bundled runtimes.
"""

FINAL_VERDICT_QUALIFICATIONS: List[str] = [
    "V2 configuration stack is complete and runtime-editable (provider toggles, routing policy).",
    "Desktop status board is a real bounded control surface, not read-only.",
    "Android network settings are fully runtime-configurable via built-in UI — no rebuild needed.",
    "cross_device_enabled persists via SharedPreferences — survives app restarts.",
    "Android model provisioning pipeline is architecturally complete (8 formal stages).",
    "Models are auto-downloaded from HuggingFace at first run (~1.65 GB total).",
    "CRITICAL GAP: llama.cpp (for MobileVLM) and NCNN (for SeeClick) not in app/build.gradle.",
    "CRITICAL GAP: All 3 model SHA-256 checksums are null — integrity verification disabled.",
    "DEPLOYMENT GAP: Cross-device requires Tailscale or equivalent; no NAT traversal built-in.",
    "CONFIGURATION GAP: V2 system-mode env vars require manual setup or process restart.",
]

CHINESE_SUMMARY: str = """
【双仓联合实际可运行性审查 — 最终结论】

基于对两个仓库真实代码的直接审查（不参考任何旧的审查文档）：

■ V2 侧（ufo-galaxy-realization-v2）配置现实
  • 配置优先级（低→高）：config.json → runtime/config.json → runtime/secrets.env → .env → 环境变量
  • 7个LLM提供商API Key通过 setup_wizard.py 或手动编辑 .env 配置
  • Desktop Status Board V2 不是纯只读面板——它是一个真实的写通控制面：
    可以启用/禁用LLM Provider、设置路由策略，写入持久化，支持热更新
  • GALAXY_SYSTEM_MODE 等系统模式变量仅在启动时读取一次，修改后需重启
  • 三种 Agent 状态（用户所说的"三个状态"）：
    SILENT（静默）→ LIMINAL（边界中，认知处理中）→ MANIFEST（显现，输出/设备控制中）
    这三个状态是真实运行时门控，不是显示标签。
  • 另有4种UI壳展开模式（DORMANT/ISLAND/SIDESHEET/FULLAGENT），是桌面展示形态，不是认知状态。

■ Android 侧（ufo-galaxy-android）配置现实
  • serverUrl配置优先级（低→高）：BuildConfig → assets/config.properties → SharedPreferences
  • 安装后无需重新编译即可修改服务器地址——NetworkSettingsScreen提供完整UI：
    主机、端口、TLS开关、设备ID、REST地址、诊断、Tailscale自动探测、一键填入Tailscale IP
  • cross_device_enabled 默认 false，可在运行时通过设置界面切换，持久保存于SharedPreferences
  • 启动时自动通过 RemoteConfigFetcher 从网关 /api/v1/config 拉取配置（M3特性）

■ Android 端模型供给现实（最关键部分）
  • 三个模型：MobileVLM V2-1.7B（~1.2GB GGUF）、SeeClick NCNN param（~50MB）、SeeClick NCNN bin（~400MB）
  • 全部来源：Hugging Face（ZiangWu/MobileVLM_V2-1.7B-GGUF + cckevinn/SeeClick）
  • 下载机制：HttpURLConnection 直连 HuggingFace，自动在首次启动时下载
  • 供给流水线8阶段完整：兼容性检查→存储预检→清理临时文件→下载→校验→原子安装→激活→回滚
  • 【关键缺口】app/build.gradle 中没有 llama.cpp 和 NCNN 的 Android 依赖库
    → 模型文件下载后无法实际加载运行（没有推理引擎）
  • 【关键缺口】三个模型的SHA-256均为null（代码注释明确写"TODO: set before production"）
    → 完整性校验被绕过

■ 端到端可运行路径现实
  V2侧：clone → pip install → python main.py --setup（填入API Key）→ python main.py → 运行
  Android侧：clone → gradlew assembleDebug → 安装→ 授权无障碍+悬浮窗 →
            进入网络设置填入Tailscale IP → 启用cross_device → 等待模型下载（~1.65GB）→
            但本地AI推理因缺少推理引擎库而无法工作

■ 最终判断
  这套系统的定性是：
    【实现完整、偏开发/运维导向的系统】
    Implementation-Complete, Developer/Ops-Oriented System

  不是"半成品"——主架构完整，配置界面存在，模型供给流水线正式且完整。
  不是"零门槛消费级产品"——跨设备需要Tailscale，Android本地AI需要额外推理库。
  
  一个具备DevOps能力的操作员可以按照可文档化的步骤完整搭建和运行这套系统。
  一个普通最终用户在当前代码状态下无法开箱即用。
"""


# ===========================================================================
# Public API
# ===========================================================================

def get_audit_summary() -> Dict:
    """Return a JSON-serialisable audit summary dict."""
    return {
        "authority": OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY,
        "scope": AUDIT_SCOPE,
        "v2_config_sources_count": len(V2_CONFIG_SOURCE_PRECEDENCE),
        "v2_required_api_keys": V2_REQUIRED_API_KEY_ENV_VARS,
        "v2_valid_providers": V2_VALID_PROVIDERS,
        "v2_runtime_hot_reloadable": V2_RUNTIME_HOT_RELOADABLE_CONFIG,
        "android_server_url_runtime_editable": ANDROID_SERVER_URL_RUNTIME_EDITABLE,
        "android_cross_device_runtime_editable": ANDROID_CROSS_DEVICE_RUNTIME_EDITABLE,
        "android_cross_device_default": ANDROID_CROSS_DEVICE_DEFAULT,
        "android_settings_ui_exists": ANDROID_SETTINGS_UI_EXISTS,
        "android_remote_config_fetch": ANDROID_REMOTE_CONFIG_FETCH,
        "desktop_board_is_control_surface": DESKTOP_BOARD_IS_CONTROL_SURFACE,
        "desktop_board_write_operations": DESKTOP_BOARD_WRITE_OPERATIONS,
        "desktop_board_write_persistence": DESKTOP_BOARD_WRITE_PERSISTENCE,
        "desktop_board_affects_runtime": DESKTOP_BOARD_AFFECTS_RUNTIME,
        "desktop_board_verdict": DESKTOP_BOARD_VERDICT,
        "tri_state_is_real_runtime_mode": TRI_STATE_IS_REAL_RUNTIME_MODE,
        "tri_state_modes": [m.value for m in TriStateMode],
        "ui_shell_modes": [m.value for m in UIShellMode],
        "fabric_modes": [m.value for m in FabricMode],
        "android_models_count": len(ANDROID_MODELS),
        "android_model_provisioning_auto": ANDROID_MODEL_PROVISIONING_AUTO_ON_STARTUP,
        "android_model_provisioning_pipeline_stages": ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES,
        "android_model_provisioning_limitations": ANDROID_MODEL_PROVISIONING_LIMITATIONS,
        "android_model_provisioning_verdict": ANDROID_MODEL_PROVISIONING_VERDICT,
        "final_verdict": FINAL_VERDICT.value,
        "final_verdict_qualifications_count": len(FINAL_VERDICT_QUALIFICATIONS),
        "v2_runbook_steps": len(V2_RUNBOOK),
        "android_runbook_steps": len(ANDROID_RUNBOOK),
    }


__all__ = [
    "OPERATIONAL_ENABLEMENT_AUDIT_AUTHORITY",
    "AUDIT_SCOPE",
    "V2ConfigSource",
    "V2_CONFIG_SOURCE_PRECEDENCE",
    "V2_REQUIRED_API_KEY_ENV_VARS",
    "V2_VALID_PROVIDERS",
    "V2_NON_SECRET_CONFIG_KEYS",
    "V2_STARTUP_ONLY_CONFIG",
    "V2_RUNTIME_HOT_RELOADABLE_CONFIG",
    "V2_CONFIG_SETUP_PATHS",
    "AndroidConfigLayer",
    "ANDROID_CONFIG_PRECEDENCE",
    "ANDROID_SERVER_URL_DEFAULT_DEBUG",
    "ANDROID_SERVER_URL_DEFAULT_RELEASE",
    "ANDROID_ASSET_GATEWAY_URL_PLACEHOLDER",
    "ANDROID_CROSS_DEVICE_DEFAULT",
    "ANDROID_SERVER_URL_RUNTIME_EDITABLE",
    "ANDROID_CROSS_DEVICE_RUNTIME_EDITABLE",
    "ANDROID_SETTINGS_UI_EXISTS",
    "ANDROID_REMOTE_CONFIG_FETCH",
    "DesktopBoardCapability",
    "DESKTOP_BOARD_IS_CONTROL_SURFACE",
    "DESKTOP_BOARD_WRITE_OPERATIONS",
    "DESKTOP_BOARD_READ_SURFACES",
    "DESKTOP_BOARD_WRITE_PERSISTENCE",
    "DESKTOP_BOARD_AFFECTS_RUNTIME",
    "DESKTOP_BOARD_VERDICT",
    "TriStateMode",
    "TRI_STATE_IS_REAL_RUNTIME_MODE",
    "TRI_STATE_BEHAVIORAL_CONSEQUENCES",
    "TRI_STATE_UI_CONTROL_SURFACE",
    "UIShellMode",
    "FabricMode",
    "THREE_STATE_DISAMBIGUATION",
    "ANDROID_MODELS",
    "ANDROID_MODEL_DOWNLOAD_MECHANISM",
    "ANDROID_MODEL_PROVISIONING_PIPELINE_STAGES",
    "ANDROID_MODEL_PROVISIONING_AUTO_ON_STARTUP",
    "ANDROID_MODEL_PROVISIONING_LIMITATIONS",
    "ANDROID_MODEL_PROVISIONING_VERDICT",
    "RunbookStep",
    "V2_RUNBOOK",
    "ANDROID_RUNBOOK",
    "OperabilityTier",
    "FINAL_VERDICT",
    "FINAL_VERDICT_QUALIFICATIONS",
    "CHINESE_SUMMARY",
    "get_audit_summary",
]

