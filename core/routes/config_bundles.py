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

## ``members`` —— 并进这个按钮的子开关

``owns`` 说「这一档管哪些键」,``members`` 是其中**不配单独成为开关**的那几个:
它们和主键是同一件事的两个侧面,拆成两处各存一份,迟早出现「主键关了、子键还开着」
(启动日志里真出现过 ``cross_device=False`` 与 ``nats_enabled=True`` 并排)。

**判据只有一条:(主键关、这个键开) 这个组合有没有意义。** 没有 → 成员;有 → 不是。
下面这些**看着像、其实不是**成员,每一个都有代码里写明的理由:

* ``GALAXY_SYSTEM_AUDIO_TO_PERCEPTION`` —— 「只要回声消除、不想让模型听见自己在放什么」是
  ``system_audio_capture_service.feed_perception_enabled`` 的文档里**特意**拆开的隐私选择;
* ``GALAXY_VOICE`` / ``GALAXY_SPEAK`` / ``GALAXY_LOCAL_AUDIO`` —— 听、朗读、本机外放是三个
  方向,「只要听写不要朗读」「朗读给别的设备、电脑不外放」都是有意义的组合;
* 默认关的 opt-in(主脑、联邦、WebRTC、Funnel、主动感知……)—— 按钮「开」不能替用户
  把一个有花费或对外暴露面的选项打开,所以它们留在「全部设置」里。

写入语义(``bundle_writes``):主键写成 ``false`` → 全部成员写成 ``false``;主键写成
``true`` → 成员**回到登记表的默认值**(不是一律 ``true``:不替用户打开 opt-in)。
只有布尔主键可以有成员 —— 三档的 GALAXY_AUTONOMY 没有「关」。
"""

from __future__ import annotations

import fnmatch
from typing import Any, Dict, Iterable, List, Tuple

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
        # 主动开口续在哪条对话上:环境在场关着的时候没有「主动开口」可续。
        "members": ("GALAXY_AMBIENT_SHARE_SESSION",),
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
            "GALAXY_ONBOARDING_ENABLED",
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
        # 发现附近设备 / 向手机手表宣告自己 / 设备接入平面 / 消息总线:
        # 只用本机时,这四样要么没有对象可发现,要么白占一个常驻进程。
        # 主脑、联邦、WebRTC、Funnel、远程桌面是默认关的 opt-in —— 不在此列(见模块说明)。
        "members": (
            "GALAXY_ONBOARDING_ENABLED",
            "GALAXY_LAN_DISCOVERY",
            "GALAXY_MDNS",
            "GALAXY_NATS_ENABLED",
        ),
    },
    {
        "key": "voice",
        # 名字直接说清楚这一档管什么:念出来的和写在屏上的是同一份文字,一句一句
        # 对齐着走(以及做不到时怎么如实降级)。原本是「声音」+ 副标题「声字同文」——
        # 一行说得完的事不必占两行,而且「声音」这两个字太宽,什么都可能是它。
        "name": "声字同文",
        "note": "",
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
        # 不给副标题:右边那枚牌子已经把当前档写出来了(safe / guided / autonomous),
        # 再写一句「问过再做」是同一件事说两遍,而且只对得上三档里的一档。
        "note": "",
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


def owned_keys(bundle: Dict[str, Any], schema_keys: Iterable[str]) -> List[str]:
    """把一档的 ``owns``(带 glob)展开成**它真正管的那些键**。唯一展开处。

    为什么要有这个函数
    ==================
    ``owns`` 原本**只有测试读**,运行时的 ``key_count`` / ``overrides`` 全是按
    ``category`` 数的。两者差得很远 —— 实测「自主」这一档 ``owns`` 展开只有 5 个键,
    而 ``category == "agent"`` 有 59 个。于是:

    * 面板上「自主」那一行显示「有 1 项手改过」,那一项其实是 ``GALAXY_MODEL_TIER``
      —— 它是**第五行 ABCD 那个控件**写进去的,跟"要不要问过再做"毫无关系;
    * 而这个文件里那段"这里**没有** GALAXY_HITL_*……留在 owns 之外不是含糊过去,
      是把「这一档不管它」这句话写下来"的说明,在运行时**根本不成立** ——
      那些键的 category 也是 agent,照样被数进来。文档说的和现实相反。

    现在运行时改成读这里,``owns`` 才真的是"这一档管哪些键"的唯一定义处。
    """
    keys = set(schema_keys)
    out: set = set()
    for pattern in bundle.get("owns", ()):
        out.update(fnmatch.filter(keys, pattern))
    return sorted(out)


def member_keys(bundle: Dict[str, Any]) -> Tuple[str, ...]:
    """这一档并进来的子开关(没有则为空)。"""
    return tuple(bundle.get("members", ()))


def expected_member_value(bundle_value: str, schema_default: str) -> str:
    """主键处于 ``bundle_value`` 时,一个成员**应当**是什么值。唯一定义处。

    关 → ``false``;开 → 登记表默认值(opt-in 的成员默认就是 ``false``,按钮不替人打开)。
    ``bundle_writes`` 写的和 ``_bundle_state`` 拿来比「有没有偏离」的是同一个答案。
    """
    return "false" if bundle_value == "false" else schema_default


def bundle_writes(bundle: Dict[str, Any], value: str, schema: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """翻这一档要写哪些键:主键 + 全部成员,**一次写完**(同一次落盘)。

    成员只对布尔主键有意义;非布尔主键(三档的自主)直接只写主键。
    """
    writes: Dict[str, str] = {bundle["primary"]: value}
    if schema.get(bundle["primary"], {}).get("type") != "boolean":
        return writes
    for key in member_keys(bundle):
        writes[key] = expected_member_value(value, str(schema[key]["default"]))
    return writes
