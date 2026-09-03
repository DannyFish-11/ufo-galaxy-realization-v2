"""整档开关 —— 一个开关管一整片键。**这份表是那件事的唯一定义处。**

## 为什么它自己一个文件

它和 ``config_schema_registry.py`` 里那 333 条是两个层级的东西:那边一行 = 一个
配置键,这里一行 = 一**档**,一档对应一个 ``category``、管着几十个键。塞在同一个
文件里读起来像是「又一批键」,而它恰恰不是。

(直接的由头是 ``scripts/check_file_complexity.py`` 那道门:registry 涨过了基线。
拆哪一块不是随便挑的 —— 挑的是本来就该分开的那一块。)

## 一档的开合由**主键**说了算

不是「这一档里的键是不是都开着」:一档里几十个键各有各的默认值,拿它们投票投不出
一个人能预期的结果。主键就是那个「这项能力到底开不开」的键,其余是它的细调。

## 面板不许自己再存一份

那样同一个事实两处各存,迟早一处说开、另一处说关,而且没人看得见。面板只渲染
``GET /api/config/bundles`` 现算出来的结果。这四行之前确实在面板里写死过(连
keyCount 都是手抄的数字),点一下只翻一个本地变量、不发任何请求 —— 开关看着能动,
后端什么都不知道。

## ``primary`` 的类型决定这一档画成什么控件

**不是所有档都是两态的**:GALAXY_AUTONOMY 是 safe / guided / autonomous 三档,
渲染成推拉开关会把中间那档吞掉 —— 这个仓库为「三态开关被当成布尔」栽过一次,见
tests/test_voice_switches_reach_the_panel.py 里那条。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

CONFIG_BUNDLES: Tuple[Dict[str, Any], ...] = (
    {
        "key": "omnimodal",
        "name": "全模态",
        "note": "屏 摄 系统声 · 自发在场",
        "category": "perception",
        "primary": "GALAXY_AMBIENT_LOOP",
        # note 里**没有**「麦」。听得见这件事的机件(ASR 引擎、Whisper 规格、
        # 环境聆听的转写模型)都在「声音」那一档 —— 这一档管的是「什么时候去看、
        # 去听、要不要开口」,不是「用什么去听」。把 GALAXY_AMBIENT_ASR_SIZE 也
        # 算进来的话,两档就都声称管着同一个键了。
        "owns": (
            "GALAXY_AMBIENT_LOOP",
            "GALAXY_AMBIENT_INTERVAL_S",
            "GALAXY_AMBIENT_COOLDOWN_S",
            "GALAXY_AMBIENT_SHARE_SESSION",
            "GALAXY_ACTIVE_PERCEPTION",
            "GALAXY_PROACTIVE_SCREEN",
            "GALAXY_PERCEPTION_PRIVACY_DEFAULT",
            "GALAXY_DESKTOP_PERCEPTION_TTL",
            "GALAXY_VIDEO_FPS_*",
            "GALAXY_SYSTEM_AUDIO_*",
            "GALAXY_PERCEPTION_KEYFRAMES",
        ),
    },
    {
        "key": "cross_device",
        "name": "跨设备",
        "note": "发现 配对 主脑 NATS 手机 手表",
        "category": "devices",
        "primary": "GALAXY_CROSS_DEVICE_ENABLED",
        # 2026-09-03 归口:NATS 四键原在 network、主脑那两个旋钮原在 advanced、
        # WebRTC 数据通道连同 TURN/信令超时原在 network。
        #
        # 判据是**关掉它失去的是哪项能力,而不是它用什么技术实现**:
        #   · 关掉 NATS,失去的是主脑/worker 分布式 —— 而 GALAXY_MASTER_BRAIN_ENABLED
        #     的描述里就写着「启用主脑编排 + worker/NATS 分布式」。开关在 devices、
        #     它的总线在 network,是同一个事实两处各存。
        #   · 关掉 WebRTC 数据通道,失去的是**手机/浏览器那端**的摄像头与麦克风,
        #     本机的不受影响 —— 那是「手机」,不是「网络」。TURN 与信令超时是它的
        #     配套机件,一起走;开关一处、旋钮另一处正是这次要治的病。
        #   · GALAXY_TS_FUNNEL 本来就在这儿,GALAXY_TS_ADVERTISE_RELAY 却在 network,
        #     而它俩讲的是同一件事(手表/手机怎么连回来)。
        "owns": (
            "GALAXY_CROSS_DEVICE_ENABLED",
            "GALAXY_MASTER_BRAIN_*",
            "GALAXY_NATS_*",
            "GALAXY_FABRIC_STRICT",
            "GALAXY_MESH_*",
            "GALAXY_LAN_DISCOVERY*",
            "GALAXY_MDNS",
            "GALAXY_HEARTBEAT_INTERVAL",
            "GALAXY_TS_*",
            "GALAXY_TURN_URLS",
            "GALAXY_SIGNALING_TIMEOUT_S",
            "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL",
            "GALAXY_DEVICE_*",
            "GALAXY_ANDROID_WS_ENABLED",
            "ANDROID_DEVICE_*",
            "FEDERATION_*",
            "NODE_*_URL",
        ),
    },
    {
        "key": "voice",
        "name": "声音",
        "note": "跟文字锁步",
        "category": "voice",
        "primary": "GALAXY_SPEAK",
        "owns": (
            "GALAXY_SPEAK*",
            "GALAXY_VOICE_*",
            "GALAXY_TTS_*",
            "GALAXY_ASR_*",
            "GALAXY_AEC*",
            "GALAXY_LOCKSTEP_*",
            "GALAXY_TEXT_VOICE_LOCKSTEP",
            "GALAXY_AMBIENT_ASR_SIZE",
            "GALAXY_WHISPER_MODEL",
        ),
    },
    {
        "key": "autonomy",
        "name": "自主",
        "note": "问过再做",
        "category": "agent",
        # 三档,不是开关。见模块开头那段说明。
        "primary": "GALAXY_AUTONOMY",
        # 这里**没有** GALAXY_HITL_* / GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S /
        # GALAXY_TOOL_GUARDIAN。头一版把它们写进来了,下面那道门当场红 —— 它们在
        # 「安全与权限」那一类里。
        #
        # 想过要不要把它们搬过来:「执行前都要你点确认」读起来确实像第四档自治。
        # 但它是一道**与档位无关、可以叠加**的闸:三档里的任何一档都能同时开着它。
        # 搬过来等于宣称它是 GALAXY_AUTONOMY 的旋钮,而它不是 —— 而且一个找
        # 「什么时候会拦我一下」的人,会去「安全与权限」那一格找它。
        #
        # 留在 owns 之外不是含糊过去:是把「这一档不管它」这句话写下来。
        "owns": (
            "GALAXY_AUTONOMY",
            "GALAXY_COMPUTER_USE",
            "GALAXY_CU_*",
        ),
    },
)
