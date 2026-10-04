"""面板上的每一个开关该不该是开关 —— 唯一的清单。

背景
----
设置页「全部设置」按 ``CONFIG_SCHEMA`` 列出来：390 个键里有 96 个布尔开关。逐个对着生产代码核过之后，
它们不是一类东西：

* 一部分是**真有取舍**的 —— 隐私（录音存不存）、花费（多模型协作）、硬件与网络（要不要下 310MB 模型、
  走不走国内镜像）、安全姿态（要不要强制令牌）。这些必须在面板上，让人选。
* 一部分是**不该有人去关**的内部机制 —— 熔断器、派发幂等、回声消除的两个子参数、自回声闸门……
  默认开，关掉只会让系统变差或出事，列在面板上只是多一排看不懂的控件。
* 一部分是**开发 / 运维 / 打包 / 测试**用的逃生口 —— ``GALAXY_DEV_MODE``、Tauri 自动构建、
  「本机回环也封禁」（打开它，桌面应用会把自己锁在自己的后端门外，这件事真发生过）。

``panel`` / ``builtin`` / ``ops`` 就是这三种去处。后两种**不在面板上列出**，但仍在 ``CONFIG_SCHEMA`` 里：
``POST /api/config`` 照收、``.env`` 照写、环境变量照读 —— 藏起来不等于没接上
（见 ``tests/test_panel_hidden_config_keys.py``）。

规矩
----
**新增一个布尔开关，必须先在这里说它是哪一种、为什么**（``tests/test_every_switch_has_a_disposition.py``
盯着）—— 仓库所有者的要求是「不要乱加开关」，这是它的可执行形式。

数据只在这里；``docs/PANEL_SWITCHES.md`` 由 ``scripts/gen_panel_switches_doc.py`` 从这里生成，不手写。
"""

from __future__ import annotations

from typing import Dict, NamedTuple

#: 留在面板上：用户真有取舍。
PANEL = "panel"
#: 内置：不该有人去关的内部机制。默认必须在「开」的一侧，且与代码里的默认值一致。面板不列。
BUILTIN = "builtin"
#: 开发 / 运维 / 打包 / 测试用的逃生口。面板不列；默认值照实写，不要求在「开」的一侧。
OPS = "ops"

DISPOSITIONS = (PANEL, BUILTIN, OPS)


class SwitchPolicy(NamedTuple):
    disposition: str
    group: str  # 用户语言里的分组（panel）/ 它属于哪一块（builtin、ops）
    reason: str


def _p(group: str, reason: str) -> SwitchPolicy:
    return SwitchPolicy(PANEL, group, reason)


def _b(group: str, reason: str) -> SwitchPolicy:
    return SwitchPolicy(BUILTIN, group, reason)


def _o(group: str, reason: str) -> SwitchPolicy:
    return SwitchPolicy(OPS, group, reason)


SWITCH_POLICY: Dict[str, SwitchPolicy] = {
    # ── 声音 ────────────────────────────────────────────────────────────
    "GALAXY_VOICE": _p("声音", "语音总闸：关掉后启动时不起语音循环，麦克风也不占用"),
    "GALAXY_SPEAK": _p("声音", "朗读回复：有人想只要文字"),
    "GALAXY_LOCAL_AUDIO": _p("声音", "本机出不出声：可以朗读给别的设备、但不想电脑外放"),
    "GALAXY_AEC": _p("声音", "回声消除：没有回环设备的机器上等于旁通，有人想整个关掉"),
    "GALAXY_NATIVE_AUDIO": _p("声音", "让模型直接听音频（需全模态服务）还是先转文字：花费与能力的取舍"),
    "GALAXY_KOKORO_AUTOFETCH": _p("声音", "首次使用时后台下载约 310MB 模型：流量与磁盘的取舍"),
    "GALAXY_INDEXTTS_AUTOFETCH": _p("声音", "首次使用时后台下载 IndexTTS 模型（体积很大）：流量与磁盘的取舍"),
    "GALAXY_AEC_COMFORT_NOISE": _b("声音", "回声消除的子参数：把压掉的部分填回极低底噪，消除呼吸感；没有理由单独关"),
    "GALAXY_AEC_RES": _b("声音", "回声消除的子参数：线性对消后再压一层非线性残余；没有理由单独关"),
    "GALAXY_TTS_STREAMING": _b("声音", "分句流式朗读（边生成边说）：关掉只会更慢"),
    "GALAXY_VOICE_BACKCHANNEL": _b("声音", "后台干活时的短应答（嗯，还在处理）：对话节奏的内部细节"),
    "GALAXY_VOICE_BACKCHANNEL_TOLERANCE": _b("声音", "用户只是嗯/对/好时不打断：关掉则一出词就打断，是退步"),
    "GALAXY_VOICE_DELEGATE": _b("声音", "重活先口头致谢、后台跑：关掉对话会被堵死"),
    "GALAXY_VOICE_DUCKING": _b("声音", "用户开口先压低音量再判断是不是真打断：关掉只会更突兀"),
    "GALAXY_VOICE_ECHO_GUARD": _b(
        "声音", "自回声文字闸门：识别结果与刚念过的话高度重合就不当用户输入；关掉 AI 会对自己说话起反应"
    ),
    "GALAXY_INDEXTTS_FP16": _o("声音", "IndexTTS 的 fp16 推理：只对显存紧张的特定 GPU 有意义，改 .env 即可"),
    "GALAXY_INDEXTTS_USE_EMO_TEXT": _o("声音", "IndexTTS 由台词推断情绪：引擎专属调参"),
    # ── 感知与在场（面板「全模态」整档管其中几项）─────────────────────────
    "GALAXY_AMBIENT_LOOP": _p("感知与在场", "自发在场（持续看/听、自己判断何时开口）：整档「全模态」的主键"),
    "GALAXY_AMBIENT_SHARE_SESSION": _p("感知与在场", "主动开口续在当前对话上，还是另起一条不打断你的会话：偏好"),
    "GALAXY_ACTIVE_PERCEPTION": _p("感知与在场", "主动感知（不等你开口自己找事做）：默认关，开了会多花算力与注意力"),
    "GALAXY_PROACTIVE_SCREEN": _p("感知与在场", "屏幕变化也触发主动开口：默认关，屏幕一直在变会话会很多"),
    "GALAXY_SYSTEM_AUDIO_CAPTURE": _p("感知与在场", "采集本机播放声：隐私 —— AI 能听见电脑在放什么"),
    "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION": _p("感知与在场", "播放声送不送进模型（关掉则只用于回声消除）：隐私"),
    "GALAXY_NATIVE_AUDIO_CHAT": _p("感知与在场", "把录音原样发给模型（默认走转文字）：隐私与 token 的取舍"),
    "GALAXY_NATIVE_MM_CHAT": _b("感知与在场", "图片按模型原生格式发：关掉只会退回文字摘要，看不见图"),
    "GALAXY_NATIVE_MODAL_AUTO": _b("感知与在场", "切到 B 档时自动激活原生后端：关掉只是多一步手动"),
    # ── 记忆 ────────────────────────────────────────────────────────────
    "GALAXY_MEMORY_MEDIA": _p("记忆与隐私", "把记忆里的截图/录音真的存盘：隐私。代码里默认关"),
    "GALAXY_MEMORY_REPLAY_MEDIA": _p("记忆与隐私", "召回时把过往截图/录音也发给模型：很费 token、也是隐私"),
    "GALAXY_EXPERIENCE_STRATEGY": _p(
        "记忆与隐私", "用历史经验调整策略：面板上这是它唯一的开关（模式档 GALAXY_EXPERIENCE_GUIDANCE 没登记进面板）"
    ),
    "GALAXY_ACI_ENABLED": _b("记忆与隐私", "预取上下文：纯加速，没有理由关"),
    "GALAXY_FOCUS_STACK_ENABLED": _b("记忆与隐私", "注意力栈（记住刚才在聊什么）：关掉被打断后接不回去"),
    # ── 桌面操作与自治（面板「自主」整档管其中几项）──────────────────────
    "GALAXY_COMPUTER_USE": _p("桌面操作与自治", "桌面操作闭环（AI 自己点鼠标敲键盘）：整档「自主」管的键，安全相关"),
    "GALAXY_STOP_KEY": _p("桌面操作与自治", "动手时按 Esc 叫停：个别人的 Esc 另有用途"),
    "GALAXY_DURABLE_EXEC": _p("桌面操作与自治", "任务状态落盘、重启接着跑：默认关，开了有写盘开销"),
    "GALAXY_CU_MEMORY": _b("桌面操作与自治", "桌面操作记住失败经验：纯正向，没有理由关"),
    "GALAXY_COMPUTER_USE_NATIVE_TOOL": _o(
        "桌面操作与自治", "声明厂商原生 computer 工具：实验特性，要求路由落到特定型号"
    ),
    "GALAXY_UNIFIED_WORKFLOW": _o("桌面操作与自治", "统一工作流引擎：实验特性，默认关"),
    # ── 模型与花费 ──────────────────────────────────────────────────────
    "GALAXY_OPENSOURCE_FIRST": _p("模型与花费", "同等能力下先用本地/开源：省钱、不出网"),
    "GALAXY_MOA_ENABLED": _p("模型与花费", "难题让几个模型各出方案再汇总：质量与花费的取舍"),
    "GALAXY_BANDIT_ROUTING": _b("模型与花费", "按实测表现挑模型：路由的内部学习，关掉退回固定顺序"),
    "GALAXY_ROUTER_ADAPTIVE_CONCURRENCY": _b("模型与花费", "按实测延迟自动调并发：内部调节"),
    "GALAXY_ROUTER_CB_ENABLED": _b("模型与花费", "熔断器：后端连续出错就暂停用它。关掉会一直撞墙"),
    "GALAXY_DISPATCH_IDEMPOTENCY": _b(
        "模型与花费", "派发幂等（同一任务重复下发只执行一次）：关掉会重复执行副作用，不该有人去关"
    ),
    "GALAXY_FAST_LOOP": _b("模型与花费", "简单请求走短路径：关掉只会更慢"),
    "GALAXY_HF_OLLAMA_FALLBACK": _b("模型与花费", "HuggingFace 拉不到时回落 Ollama：只在兜底时起作用"),
    "GALAXY_IGNORE_CONTEXT_MEASUREMENTS": _o("模型与花费", "忽略本机实测的 KV 单价：排障用"),
    # ── 多设备与网络 ────────────────────────────────────────────────────
    "GALAXY_CROSS_DEVICE_ENABLED": _p("多设备与网络", "跨设备编排：整档「跨设备」的主键。关掉则只在本机跑"),
    "GALAXY_MASTER_BRAIN_ENABLED": _p(
        "多设备与网络",
        "主脑编排 + worker/NATS 分布式：默认关=单机。与「跨设备」的关系见 docs/PANEL_SWITCHES.md 的合并建议",
    ),
    "GALAXY_NATS_ENABLED": _p("多设备与网络", "NATS 消息总线：单机自用可以关，省一个常驻进程"),
    "GALAXY_ONBOARDING_ENABLED": _p("多设备与网络", "设备接入平面（发现附近设备、候选/成员）：总闸"),
    "GALAXY_LAN_DISCOVERY": _p("多设备与网络", "局域网自动发现设备：会在局域网里探测，有人不想"),
    "GALAXY_MDNS": _p("多设备与网络", "mDNS 广播网关，手机/手表免输 IP：会在局域网里宣告自己"),
    "GALAXY_HA_BRIDGE": _p("多设备与网络", "接入 Home Assistant：有 HA 的人可能不想让 AI 去控智能家居"),
    "GALAXY_REMOTE_DESKTOP": _p("多设备与网络", "远程桌面接入：默认关，打开就是对外开一个口"),
    "FEDERATION_ENABLED": _p("多设备与网络", "联邦（把多套 Galaxy 连成一片）：默认关的 opt-in"),
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL": _p(
        "多设备与网络", "WebRTC 数据通道（浏览器/手机把摄像头麦克风直接推给感知层）：opt-in"
    ),
    "GALAXY_TS_FUNNEL": _p("多设备与网络", "把网关经 Tailscale Funnel 暴露到公网：必须让人看见"),
    "GALAXY_HF_MIRROR": _p("多设备与网络", "模型下载走国内镜像：按所在网络选"),
    "GALAXY_ONBOARDING_BLUETOOTH": _b("多设备与网络", "接入平面的蓝牙扫描：受「设备接入平面」总闸管，没有理由单独关"),
    "GALAXY_ONBOARDING_CAN": _b("多设备与网络", "接入平面的 CAN 总线扫描：同上"),
    "GALAXY_ONBOARDING_SERIAL": _b("多设备与网络", "接入平面的串口扫描：同上"),
    "GALAXY_ONBOARDING_SSDP": _b("多设备与网络", "接入平面的 SSDP/UPnP 扫描：同上"),
    "GALAXY_TS_ADVERTISE_RELAY": _b("多设备与网络", "把本机登记为 Tailscale 中继：Tailscale 的内部细节"),
    "GALAXY_HEADSCALE_AUTOJOIN": _b("多设备与网络", "配好 Headscale 后自动加入：没配时什么都不做"),
    "GALAXY_TRANSPORT_ADAPTIVE": _b("多设备与网络", "传输方式自适应：内部调节"),
    "GALAXY_CONSENSUS_ROUND": _b(
        "多设备与网络", "多候选设备时派发前先收敛一轮：内部机制，关掉与加入这一轮之前逐字相同"
    ),
    "GALAXY_ANDROID_WS_ENABLED": _o(
        "多设备与网络", "安卓 WS 接入面：鉴权默认开，开鉴权时它会连带打开 —— 实际上没有可选的"
    ),
    "GALAXY_FABRIC_STRICT": _o("多设备与网络", "NATS 不可达即视为致命：严格部署用，桌面用不到"),
    # ── 安全姿态（都是「更严」的选项，默认放行；要不要更严是用户的事）──────────
    "GALAXY_AUTH_ENABLED": _p("安全姿态", "鉴权：默认开（本机自动签令牌）。关掉等于谁都能调接口"),
    "GALAXY_REQUIRE_API_TOKEN": _p("安全姿态", "强制要求令牌：没带令牌的请求一律拒绝"),
    "GALAXY_REQUIRE_DEVICE_APPROVAL": _p("安全姿态", "未配对批准的设备只能连接、不作为派发目标"),
    "GALAXY_PERM_STRICT": _p("安全姿态", "节点权限从严：没显式授权的动作一律拒绝"),
    "GALAXY_STRICT_AUTHORITY_CHECK": _p("安全姿态", "权威校验从严：来源存疑的指令一律拒绝"),
    "GALAXY_HITL_CONFIRM_GATE": _p("安全姿态", "执行前都要你点确认：最稳但最慢"),
    "GALAXY_SSH_STRICT_HOST_KEYS": _p("安全姿态", "严格核对远程机器指纹：第一次见的机器也拒"),
    "GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT": _p("安全姿态", "允许执行远程安装脚本：有供应链风险"),
    "GALAXY_WEIGHTS_ALLOW_PICKLE": _p("安全姿态", "允许加载 pickle 格式权重：反序列化即执行代码"),
    "GALAXY_ALLOW_ENDPOINT_OVERRIDE": _p(
        "安全姿态", "允许覆盖 provider 的 base_url：中转/relay 要用，也是一个可被滥用的口"
    ),
    "GALAXY_EGRESS_ALLOW_PRIVATE": _p("安全姿态", "允许连内网地址：跨设备编队走的就是内网"),
    "GALAXY_MANIFEST_ON_FIRST_TOKEN": _b(
        "安全姿态", "首个字一出就显形：界面时序，不是安全选项（登记在 security 类是历史遗留）"
    ),
    "GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK": _o("安全姿态", "回落旧调度器：迁移期兜底，默认关"),
    "GALAXY_INPUT_VALIDATION_LOOPBACK": _o("安全姿态", "本机回环也做输入校验：测试用；本机来的请求本来就是桌面自己"),
    "GALAXY_IP_BLOCK_LOOPBACK": _o(
        "安全姿态", "本机回环也会因连续失败被封：打开它，桌面会把自己锁在自己的后端门外（真发生过）"
    ),
    "GALAXY_RATE_LIMIT_LOOPBACK": _o("安全姿态", "本机回环也限流：测试用"),
    # ── 启动、诊断与打包（没有人会因为性格不同而选不同的值）─────────────────
    "GALAXY_OTEL_ENABLED": _b("启动与诊断", "链路追踪：没配导出地址时只在进程内产生、不外发"),
    "GALAXY_PHASE_TIMING": _b("启动与诊断", "记录启动各阶段耗时：廉价，排查启动慢时要用"),
    "GALAXY_URL_SENTINEL": _b("启动与诊断", "Ollama 地址自检：启动时探一次，不对就纠正"),
    "GALAXY_TAURI_AUTOBUILD": _b("启动与诊断", "Tauri 外壳缺产物时自动构建：打包细节"),
    "GALAXY_TAURI_AUTO_INSTALL_MSVC": _b("启动与诊断", "Windows 缺 MSVC 时自动装：打包细节"),
    "GALAXY_DEV_MODE": _o("启动与诊断", "开发者模式：放宽部分校验。不该出现在用户面板上"),
    "GALAXY_VERBOSE": _o("启动与诊断", "启动输出展开每一步：等价于命令行 -v"),
    "GALAXY_STRICT_PREFLIGHT": _o("启动与诊断", "启动前检查从严：运维用，面板打开它只会让下次起不来"),
    "GALAXY_PREFLIGHT_FAIL_FAST": _o("启动与诊断", "只影响预检命令行的退出码，不影响正常启动"),
    "GALAXY_SKIP_ELECTRON": _o("启动与诊断", "跳过桌面外壳（无头部署）：在面板上打开它，下次启动就没有面板了"),
    "GALAXY_SKIP_DESKTOP_SURFACE": _o("启动与诊断", "同上，是 GALAXY_SKIP_ELECTRON 的第二个写法"),
    "GALAXY_ENTRYMODE_USE_READINESS": _o("启动与诊断", "入口按就绪度判定的实验路径：代码里默认关"),
}


def keys_with(disposition: str) -> frozenset:
    return frozenset(k for k, p in SWITCH_POLICY.items() if p.disposition == disposition)


#: 登记在 CONFIG_SCHEMA 里、但面板不列的开关（内置 + 运维）。
PANEL_HIDDEN_SWITCH_KEYS = keys_with(BUILTIN) | keys_with(OPS)

__all__ = [
    "BUILTIN",
    "DISPOSITIONS",
    "OPS",
    "PANEL",
    "PANEL_HIDDEN_SWITCH_KEYS",
    "SWITCH_POLICY",
    "SwitchPolicy",
    "keys_with",
]
