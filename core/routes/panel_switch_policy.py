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

* 最后一部分是**和某个整档按钮同一件事的另一面** —— 「跨设备」关掉了，局域网发现、mDNS 宣告、设备接入平面、
  消息总线再单独开着没有意义。它们并进那个按钮（``core/routes/config_bundles.py`` 的 ``members``），
  翻按钮时一起写，不再各占一行。

``panel`` / ``builtin`` / ``ops`` / ``member`` 就是这四种去处。后三种**不在面板上列出**，但仍在 ``CONFIG_SCHEMA`` 里：
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
#: 并进某个整档按钮：和那一档的主键是同一件事的另一面（判据与写入语义见 config_bundles 模块说明）。
#: 面板不列；清单里写「并进了哪一档」，并与 CONFIG_BUNDLES 的 ``members`` 互相核对。
MEMBER = "member"

DISPOSITIONS = (PANEL, BUILTIN, OPS, MEMBER)


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


def _m(group: str, reason: str) -> SwitchPolicy:
    return SwitchPolicy(MEMBER, group, reason)


SWITCH_POLICY: Dict[str, SwitchPolicy] = {
    # ── 声音 ────────────────────────────────────────────────────────────
    "GALAXY_VOICE": _p("声音", "语音总闸：关掉后启动时不起语音循环，麦克风也不占用"),
    "GALAXY_SPEAK": _b(
        "声音",
        "朗读回复：默认开，是系统的一项基本能力。想关用面板上「声字同文」那个整档按钮（它的主键就是这个键），不再单列一行",
    ),
    "GALAXY_LOCAL_AUDIO": _b(
        "声音", "本机外放：默认开，是系统的基本能力；「朗读给别的设备、电脑不外放」这种少见组合改 .env"
    ),
    "GALAXY_AEC": _b(
        "声音",
        "回声消除：把喇叭放出去的声音从麦克风里减掉；关掉 AI 会听见自己说话。没有回环设备的机器上它自己旁通，不需要人去管",
    ),
    "GALAXY_NATIVE_AUDIO": _o(
        "声音",
        "「服务现实」门控：本机有没有原生听/说的后端。由本机模型档位（B 档激活时 core/native_modal.py 自动开、"
        "离开时自动关）管着，不是用户的取舍；用户的取舍是选哪一档，以及 GALAXY_NATIVE_AUDIO_CHAT",
    ),
    "GALAXY_KOKORO_AUTOFETCH": _o(
        "声音", "替补引擎 Kokoro 的按需下载：用到它时才在后台拉模型（约 310MB），默认开；不是用户每天要碰的开关"
    ),
    "GALAXY_INDEXTTS_AUTOFETCH": _o(
        "声音", "替补引擎 IndexTTS 的按需下载：体积很大，默认关；要用时先选这个引擎，再改 .env 打开"
    ),
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
    "GALAXY_AMBIENT_SHARE_SESSION": _m(
        "感知与在场", "并进「全模态」：主动开口续在哪条对话上；自发在场关着时没有主动开口可续"
    ),
    "GALAXY_ACTIVE_PERCEPTION": _p("感知与在场", "主动感知（不等你开口自己找事做）：默认关，开了会多花算力与注意力"),
    "GALAXY_PROACTIVE_SCREEN": _p("感知与在场", "屏幕变化也触发主动开口：默认关，屏幕一直在变会话会很多"),
    "GALAXY_SYSTEM_AUDIO_CAPTURE": _b(
        "感知与在场",
        "回环采集的电源：回声消除的参考信号来源，只在进程内做减法、不出网、不进上下文；真正的隐私取舍是「播放声送不送进模型」（GALAXY_SYSTEM_AUDIO_TO_PERCEPTION）",
    ),
    "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION": _p("感知与在场", "播放声送不送进模型（关掉则只用于回声消除）：隐私"),
    "GALAXY_NATIVE_AUDIO_CHAT": _p("感知与在场", "把录音原样发给模型（默认走转文字）：隐私与 token 的取舍"),
    "GALAXY_NATIVE_MM_CHAT": _b("感知与在场", "图片按模型原生格式发：关掉只会退回文字摘要，看不见图"),
    "GALAXY_NATIVE_MODAL_AUTO": _b("感知与在场", "切到 B 档时自动激活原生后端：关掉只是多一步手动"),
    # ── 记忆 ────────────────────────────────────────────────────────────
    "GALAXY_MEMORY_MEDIA": _p("记忆与隐私", "把记忆里的截图/录音真的存盘：隐私。代码里默认关"),
    "GALAXY_MEMORY_REPLAY_MEDIA": _p("记忆与隐私", "召回时把过往截图/录音也发给模型：很费 token、也是隐私"),
    "GALAXY_EXPERIENCE_STRATEGY": _b(
        "记忆与隐私",
        "历史遗留的总闸：设计上的控制是 GALAXY_EXPERIENCE_GUIDANCE 的 off / shadow / on 三档，这个只是向后兼容的 kill switch；从自己做过的事里学，不出本机",
    ),
    "GALAXY_ACI_ENABLED": _b("记忆与隐私", "预取上下文：纯加速，没有理由关"),
    "GALAXY_FOCUS_STACK_ENABLED": _b("记忆与隐私", "注意力栈（记住刚才在聊什么）：关掉被打断后接不回去"),
    # ── 桌面操作与自治（面板「自主」整档管其中几项）──────────────────────
    "GALAXY_COMPUTER_USE": _b(
        "桌面操作与自治",
        "桌面操作闭环（AI 自己点鼠标敲键盘）：默认开，是系统的基本能力。要不要放手由「自主」那一档（safe / guided / autonomous）决定，不另设开关",
    ),
    "GALAXY_STOP_KEY": _b(
        "桌面操作与自治",
        "动手时按 Esc 叫停：是安全能力，关掉只会少一道刹车。唯一的例外是个别安全软件把键盘钩子当键盘记录器，那时改 .env 关掉，停止改走面板按钮",
    ),
    "GALAXY_DURABLE_EXEC": _b(
        "桌面操作与自治",
        "任务状态落盘、重启接着跑：默认开，是系统的基本能力（任务不该因为一次重启就丢）。落盘有保留上限，只留要续跑的和它们依赖的",
    ),
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
    "GALAXY_CROSS_DEVICE_ENABLED": _p(
        "多设备与网络", "跨设备模式：整档「跨设备」的主键。关=本地模式(只在本机跑)，开=跨设备模式"
    ),
    "GALAXY_MASTER_BRAIN_ENABLED": _p(
        "多设备与网络",
        "主脑编排 + worker/NATS 分布式：默认关=单机。与「跨设备」的关系见 docs/PANEL_SWITCHES.md 的合并建议",
    ),
    "GALAXY_NATS_ENABLED": _m("多设备与网络", "并进「跨设备」：NATS 消息总线；只用本机时白占一个常驻进程"),
    "GALAXY_ONBOARDING_ENABLED": _m("多设备与网络", "并进「跨设备」：设备接入平面（发现附近设备、候选/成员）的总闸"),
    "GALAXY_LAN_DISCOVERY": _m("多设备与网络", "并进「跨设备」：局域网自动发现设备；只用本机时没有对象可发现"),
    "GALAXY_MDNS": _m("多设备与网络", "并进「跨设备」：mDNS 广播网关，手机/手表免输 IP；只用本机时没有人需要它"),
    "GALAXY_HA_BRIDGE": _b(
        "多设备与网络",
        "接入 Home Assistant：URL 与令牌都配齐才会启动，没配时完全不动；配齐本身就是人的授权，不需要再有一个开关",
    ),
    "GALAXY_TAILSCALE_ENABLED": _o(
        "多设备与网络", "显式走 Tailscale 通道：跨设备模式的传输顺序里本来就把它排第一，这个键只是手动强指定，改 .env"
    ),
    "GALAXY_ENABLE_WEBRTC": _o(
        "多设备与网络",
        "把 WebRTC 直连当可选传输通道：需要的是下面「数据通道」那个真取舍的开关，这个是网关内部的通道登记",
    ),
    "GALAXY_ENABLE_SCRCPY": _o("多设备与网络", "把 scrcpy 投屏当可选传输通道：调试 / 特殊场景，改 .env"),
    "GALAXY_ENABLE_MQTT": _o("多设备与网络", "把 MQTT 当可选传输通道：只有接了 MQTT 设备的人需要，改 .env"),
    "GALAXY_USE_GATEWAY_FOR_WEBRTC": _b("多设备与网络", "WebRTC 信令走网关：关掉客户端要自己找信令地址，只会更麻烦"),
    "GALAXY_ENABLE_LEGACY_MULTIDEVICE": _o(
        "多设备与网络", "旧版多设备兼容层：规范实现在 galaxy_gateway，默认关，只有迁移期的老调用方需要"
    ),
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
    "GALAXY_AUTH_ENABLED": _b(
        "安全姿态", "鉴权：默认开（本机自动签令牌、其他设备走配对）。关掉等于谁都能调接口，不该有人在面板上一点就关"
    ),
    "GALAXY_REQUIRE_API_TOKEN": _o(
        "安全姿态",
        "部署加固：没带令牌的请求一律拒绝。本机桌面靠自签令牌，打开它要有共享口令，是对外暴露的部署才需要的决定",
    ),
    "GALAXY_REQUIRE_DEVICE_APPROVAL": _o(
        "安全姿态",
        "部署加固：未配对批准的设备只能连接、不作为派发目标。打开后手机要先被批准才接得到任务，是部署的人的决定",
    ),
    "GALAXY_PERM_STRICT": _o(
        "安全姿态", "部署加固：没显式授权的节点动作一律拒绝。白名单还没全量普及，打开会拒掉未声明的节点"
    ),
    "GALAXY_STRICT_AUTHORITY_CHECK": _o(
        "安全姿态", "部署加固：来源存疑的指令一律拒绝（启动时的权威边界校验失败即中止）。是部署的人的决定"
    ),
    "GALAXY_HITL_CONFIRM_GATE": _p(
        "安全姿态",
        "命令路由处的额外闸：高危命令（高危词表或零信任规则命中）要你批准才执行，超时按拒绝；是对 AI 行为的偏好，不是部署加固",
    ),
    "GALAXY_SSH_STRICT_HOST_KEYS": _o(
        "安全姿态",
        "部署加固：连第一次见的远程机器也拒（指纹要事先录进来）。默认是第一次连时记下指纹并告诉你、之后对不上就拒",
    ),
    "GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT": _o(
        "安全姿态",
        "危险逃生口：允许执行未经校验的远程安装脚本（供应链风险，装本地模型时才可能用到）。默认拦着，不该让人在面板上一点就放开",
    ),
    "GALAXY_WEIGHTS_ALLOW_PICKLE": _o(
        "安全姿态",
        "危险逃生口：允许加载 pickle 格式权重（反序列化即执行代码，历次模型投毒的载体）。默认拦着，不该让人在面板上一点就放开",
    ),
    "GALAXY_ALLOW_ENDPOINT_OVERRIDE": _b(
        "安全姿态",
        "允许覆盖 provider 的 base_url：中转 / relay 要用，关掉会让这些部署断掉；要「绝不走中转」的部署由运维改 .env",
    ),
    "GALAXY_EGRESS_ALLOW_PRIVATE": _b(
        "安全姿态", "允许连内网地址：跨设备编队走的就是内网，关掉会把多设备打死；要锁死的是部署的人，改 .env"
    ),
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
PANEL_HIDDEN_SWITCH_KEYS = keys_with(BUILTIN) | keys_with(OPS) | keys_with(MEMBER)

__all__ = [
    "BUILTIN",
    "DISPOSITIONS",
    "MEMBER",
    "OPS",
    "PANEL",
    "PANEL_HIDDEN_SWITCH_KEYS",
    "SWITCH_POLICY",
    "SwitchPolicy",
    "keys_with",
]
