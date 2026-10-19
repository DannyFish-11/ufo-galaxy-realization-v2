"""面板上不再列出的设置 —— 机器自己定的，和只在跨设备模式下才有意义的。

面板「全部设置」曾经列到 186 行。逐行对过之后，其中 **95 行不该由人来填**，**15 行只在跨设备模式下才有意义**：

* **内置**（``BUILTIN_GROUPS``）：路径、内部服务的地址、模型型号与规格、固定的严格默认、开发 / 运维逃生口。
  它们有一个对的默认（路径跟着数据总目录走、地址是启动器自己分配的本机回环、型号按本机自己挑……），
  人填错了只会把系统弄坏，人填对了也和默认一样。列在面板上只是让人去背一份不该背的清单。
* **只在跨设备模式下才有意义**（``CROSS_DEVICE_ONLY_KEYS``）：消息总线地址、联邦对端、打洞 / 中继服务器、设备名、网格口令……
  本地模式（默认）下它们是纯噪音；切到跨设备模式，面板刷新后就出现（判模式只认
  ``core.system_mode.cross_device_requested()``，不在这里另推导）。

藏起来不等于没接上：这些键仍在 ``CONFIG_SCHEMA`` 里 —— ``POST /api/config`` 照收、``.env`` 照写、环境变量照读，
智能体与脚本照用；只是 ``GET /api/config/all`` 不列、「保存设置」不再把它们的默认值钉进 ``.env``
（钉了，以后代码里的默认修正就永远盖不住它，见 ``core.routes.config._write_env_file_with``）。

**登记表的默认值必须等于代码里的默认值** —— 否则「保存一次设置」就悄悄改变了行为。这一条由
``tests/test_panel_builtin_keys.py`` 逐个核对；核对时揪出过两处真漂移：
``CORS_ALLOWED_ORIGINS`` / ``CORS_ALLOWED_HEADERS`` 登记成 ``*``（代码的安全默认是本机端口与显式请求头，
点一次保存就被钉成「任何来源」），``CHROMA_PERSIST_DIR`` 登记成 ``./chroma``（代码读的是 ``./chroma_db``）。

听写模型大小（``GALAXY_WHISPER_MODEL`` / ``GALAXY_AMBIENT_ASR_SIZE``）与音色、「开源优先」等偏好型的 5+2 个键不在这里：
它们改由对话里让智能体调（``core/tuning.py``），也不上面板。

注意与 ``core/routes/config.py::PANEL_HIDDEN_KEYS`` 的区别：那份是「元层 / 多机内部调参」，并要求隐藏的开关默认在「开」的一侧；
本模块是更宽的一档，不要求。两份互不重叠（测试核对）。
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

#: 分组 → (一句话理由, 键…)。理由写给读这份清单的人，也进 ``docs/SYSTEM_STATUS.md``。
BUILTIN_GROUPS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "paths": (
        "路径：全部落在数据总目录（GALAXY_DATA_DIR）下，由它派生；只留「数据总目录」一个给人指",
        (
            "GALAXY_FEATURE_FLAGS_PATH",
            "GALAXY_MASTER_BRAIN_STATE_PATH",
            "ANDROID_DEVICE_STATE_STORE_PATH",
            "GALAXY_ONBOARDING_STATE_DIR",
            "GALAXY_TASK_LEDGER_PATH",
            "GALAXY_TASK_ALLOCATION_STATE_PATH",
            "GALAXY_TASK_GRAPH_STATE_PATH",
            "GALAXY_LAST_OPERATOR_ACTION_STATE_PATH",
            "GALAXY_PEER_TRUST_PATH",
            "GALAXY_TAILNET_MEMBERSHIP_PATH",
            "GALAXY_LOG_DIR",
            "CHROMA_PERSIST_DIR",
            "GALAXY_MEMORY_MEDIA_DIR",
            "GALAXY_OMNIMEM_DIR",
            "GALAXY_CLIP_DIR",
            "GALAXY_CLAP_DIR",
            "GALAXY_KOKORO_DIR",
            "GALAXY_INDEXTTS_DIR",
            "GITHUB_INSTALL_DIR",
        ),
    ),
    "internal_endpoints": (
        "内部服务的地址与端口：启动器自己分配、本机回环；只有拆机部署才改，那是运维",
        (
            "NODE_92_URL",
            "NODE_45_URL",
            "NODE_33_URL",
            "NODE_71_URL",
            "NODE_71_HOST",
            "NODE_95_URL",
            "NODE_97_URL",
            "NODE09_SANDBOX_URL",
            "GALAXY_API_HOST",
            "MQTT_PORT",
            "GALAXY_VNC_CMD",
            "GALAXY_VNC_PORT",
        ),
    ),
    "auto_pick": (
        "型号 / 规格 / 引擎细节：按本机硬件与已装的东西自动挑；下载源由 core.hf_endpoint 探测择优（连带的开关 GALAXY_HF_MIRROR"
        "按开关清单登记为内置，见 panel_switch_policy），pip 源有候选链",
        (
            "DEEPSEEK_OCR2_MODEL",
            "GEMINI_AUDIO_MODEL",
            "OPENAI_AUDIO_MODEL",
            "GALAXY_RESPONSES_PROVIDERS",
            "GALAXY_REALTIME_MODEL",
            "GALAXY_REALTIME_URL",
            "GALAXY_REALTIME_VOICE",
            "GALAXY_LOCAL_OPENAI_MODEL",
            "GALAXY_LOCAL_OPENAI_SERVES",
            "GALAXY_REASONING_OPENAI_MODEL",
            "GALAXY_REASONING_OPENAI_SERVES",
            "GALAXY_LOCAL_GUI_VLM_MODEL",
            "GALAXY_LLAMA_SERVER_BIN",
            "GALAXY_MODEL_TIER",
            "GALAXY_PERCEPTION_MODEL",
            "GALAXY_EMBED_MODEL",
            "GALAXY_CLIP_MODEL",
            "GALAXY_CLAP_MODEL",
            "GALAXY_SIMPLEMEM_MODEL",
            "GALAXY_SENSEVOICE_MODEL",
            "GALAXY_PIPER_MODEL",
            "GALAXY_KOKORO_MODEL",
            "GALAXY_KOKORO_LANG",
            "GALAXY_MELO_LANG",
            "GALAXY_MELO_SPEAKER",
            "GALAXY_MELO_DEVICE",
            "GALAXY_DEVICE_TYPE",
            "GALAXY_DESKTOP_SHELL",
            "GALAXY_AUTO_DOCKER",
            "GALAXY_CONTAINER_RUNTIME",
            "GALAXY_HF_ENDPOINT",
            "GALAXY_PIP_INDEX",
        ),
    ),
    "strict_defaults": (
        "固定的严格默认 / 上限：没人该改；真要改走 .env",
        (
            "GALAXY_NATS_EXECUTOR_FALLBACK",
            "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE",
            "GALAXY_RESULT_INGRESS_CONTINUITY_MODE",
            "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE",
            "GALAXY_HITL_CONFIRM_TIMEOUT_S",
            "GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S",
            "GALAXY_MAX_MESSAGE_SIZE",
            "GALAXY_OPS_FAILURE_REASONS_MAX",
            "GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX",
            "GALAXY_OPS_REJECTION_REASONS_MAX",
            "GALAXY_OPS_FALLBACK_KINDS_MAX",
            "GALAXY_VISION_BACKEND_ORDER",
            "GALAXY_NATIVE_REALTIME_PATH",
            "GALAXY_ASR_INITIAL_PROMPT",
            "GALAXY_LAN_DISCOVERY_TYPES",
        ),
    ),
    "ops_escape": (
        "开发 / 运维逃生口：给排障的人，不是给用户的",
        (
            "GALAXY_PREFLIGHT_MODE",
            "GALAXY_GATEWAY_MODE",
            "GALAXY_OTEL_EXPORTER",
            "GALAXY_OTEL_SERVICE_NAME",
            "GALAXY_GW_ADAPTER_DLQ_SUBJECT",
            "GALAXY_BLUEZ_DBUS_ADDRESS",
            "GALAXY_PS_ALLOWED_CMDLETS",
            "GALAXY_FORCE_COLLAB_MODE",
            "GALAXY_TOOLS_CORE",
            "CORS_ALLOWED_ORIGINS",
            "CORS_ALLOWED_METHODS",
            "CORS_ALLOWED_HEADERS",
        ),
    ),
}

#: 内置键的并集：``GET /api/config/all`` 不列、「保存设置」不钉默认值。
PANEL_BUILTIN_KEYS: FrozenSet[str] = frozenset(k for _reason, keys in BUILTIN_GROUPS.values() for k in keys)

#: 只在跨设备模式下才列 —— 只有「这台电脑作为设备加入网络」时才有意义的键(总线地址、联邦、
#: 本机作为设备的名字、mesh 口令、本机传输顺序)。判模式的唯一出处是 ``core.system_mode.cross_device_requested()``。
#:
#: **不在这里的**:自建内网(``GALAXY_HEADSCALE_*``、``GALAXY_TAILSCALE_HOST`` / ``_TAG``)与 TURN / STUN。
#: 它们管的是手表、手机怎么找到并连上智能体(出门直连、WebRTC 打洞),电脑在本地模式时一样要配 ——
#: 以前藏在跨设备模式后面,本地模式下手表出门直连连配置的地方都没有。
CROSS_DEVICE_ONLY_KEYS: FrozenSet[str] = frozenset(
    {
        "GALAXY_NATS_URL",
        "FEDERATION_LOCAL_HOST",
        "FEDERATION_PEERS",
        "GALAXY_TRANSPORT_PRIORITY",
        "GALAXY_DEVICE_NAME",
        "GALAXY_MESH_SECRET",
    }
)

#: 以前的登记表把这些**错误的默认值**钉进过 ``.env``（点一次「保存设置」就写一遍）。现在登记表的默认已改对，
#: 这些旧钉的值在下一次保存时一并清掉 —— 面板上已经没有这一行，人不可能是在面板上有意填的它。
#:
#: ``CORS_ALLOWED_ORIGINS=*`` / ``CORS_ALLOWED_HEADERS=*`` 是最要紧的一对：网关带着 ``allow_credentials=True``
#: 挂这两个值，``*`` 等于任何网页都能带着凭据跨站调本机的接口。
#: 没有把 ``CHROMA_PERSIST_DIR=./chroma`` 列进来：那个旧钉的目录里可能已经写了新数据，清掉它就把数据甩在后面。
LEGACY_PINNED_DEFAULTS: Dict[str, Tuple[str, ...]] = {
    "CORS_ALLOWED_ORIGINS": ("*",),
    "CORS_ALLOWED_HEADERS": ("*",),
}


def unlisted_at_default(key: str, value: object, default: object, explicit: bool) -> bool:
    """不在面板上列的键，且没人动过 —— 它在 ``.env`` 里只是噪音（或者是旧版本钉进去的错误默认）。

    ``explicit``：这次请求里明确写了它。明确写的不算噪音，原样保留。
    """
    if key not in PANEL_BUILTIN_KEYS and key not in CROSS_DEVICE_ONLY_KEYS:
        return False
    if explicit:
        return False
    text = str(value)
    return text == str(default) or text in LEGACY_PINNED_DEFAULTS.get(key, ())


__all__ = [
    "BUILTIN_GROUPS",
    "CROSS_DEVICE_ONLY_KEYS",
    "LEGACY_PINNED_DEFAULTS",
    "PANEL_BUILTIN_KEYS",
    "unlisted_at_default",
]
