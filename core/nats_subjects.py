"""
core/nats_subjects.py — NATS 主题与 JetStream 流的唯一定义处
============================================================

从 ``core/nats_bus.py`` 拆出来的**命名 SSOT**。拆的理由不是文件太长,是这一层
反复出问题,而每次的形态都一样:**同一个主题被定义了两次**。

已经踩过的两次
--------------
1. **单复数分裂**。``NATSTopics.TASK_*`` 用单数 ``galaxy.task.*``,而 JetStream
   流、两个订阅器、``command_router`` / ``scheduler`` / 网关适配器全用复数
   ``galaxy.tasks.*``。NATS 逐 token 精确匹配,``task`` 与 ``tasks`` 之间没有
   任何通配符能搭桥 —— 实测经单数常量发出的任务结果 **0 条**到得了主脑,而
   ``publish_task_result`` 有四个生产调用方,它们各自都以为自己闭环了。
2. **网关的第二处定义**。``GatewayNATSAdapter._publish_result`` 自己拼
   ``NATSTopics.task_result(task_id)`` 再调私有的 ``nats_bus._publish``,绕过了
   ``publish_task_result_envelope``。收敛到单数那次,这处就是差点被漏掉的那处。

所以这个模块只放**名字**,不放行为:主题常量、拼接用的 classmethod、流定义。
谁要发/要订,从这里取名字,不要在调用点重新拼一个。

单复数并存的现状(有意为之)
--------------------------
``NATSTopics.TASK_*`` 是规范面(单数),复数是既有运转面。两个前缀都在
``GALAXY_TASKS`` 流的 subjects 里,订阅侧用 ``NATSBus._subscribe_both`` 两个
都订(各带自己的 durable 名),所以两边发的都收得到、且每条只收一次。
新代码一律走单数常量。
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# JetStream stream definitions
# ═══════════════════════════════════════════════════════════════════════════════

_STREAMS = {
    "GALAXY_TASKS": {
        # 两个前缀并存。``galaxy.task.>``(单数)是 NATSTopics 定下的新规范,
        # ``galaxy.tasks.>``(复数)是既有运转面(command_router / scheduler /
        # gateway_nats_adapter / 各 legacy 发布器)还在用的。NATS 逐 token 精确
        # 匹配,``task`` 与 ``tasks`` 永不相通 —— 两者都必须在流里,否则落在流外
        # 的那一半连持久化都没有。两个前缀不重叠,不会触发 JetStream 的
        # "subject overlaps" 冲突。
        "subjects": ["galaxy.tasks.>", "galaxy.task.>"],
        "max_msgs": 100_000,
        "max_bytes": 1_073_741_824,  # 1 GB
    },
    "GALAXY_MCP": {
        "subjects": ["galaxy.mcp.>"],
        "max_msgs": 50_000,
        "max_bytes": 536_870_912,  # 512 MB
    },
    "GALAXY_EVENTS": {
        "subjects": ["galaxy.events.>", "galaxy.workers.>"],
        "max_msgs": 200_000,
        "max_bytes": 536_870_912,
    },
    # ── 下面四条流:补的是"发布器齐全、但一条也发不出去"的那四个平面 ─────────
    #
    # NATSBus._publish 走的是 **JetStream** (``js.publish``),而 JetStream 要求
    # 主题被某个流覆盖 —— 没有流,publish 直接报 ``no response from stream``。
    # 修之前 _STREAMS 只有上面三条,于是:
    #
    #   galaxy.device.*      整个 AIP v3 设备协议平面(注册/心跳/接管/…)
    #   galaxy.capability.*  能力上报与查询
    #   galaxy.presence.*    在场相位
    #   galaxy.audit.*       审计记录
    #
    # 这四个平面在**真实 NATS 服务器上一条都发不出去**。
    #
    # 为什么一直没被发现:进程内降级总线(``_local_publish``)根本没有流的概念,
    # 谁发都投得到 —— 全部单机测试与 CI 都跑在那条路径上,所以协议侧"28 个发布器
    # 全接齐了"是真的,"发得出去"却是假的。这条只有连真服务器才看得见,
    # 也正是必须连真服务器跑一遍的理由。
    #
    # 保留期按各平面的性质分开定,所以是四条独立的流而不是并进 GALAXY_EVENTS:
    # 心跳是高频且过期即无用的,审计是要留的记录,两者不该共用一套上限。
    "GALAXY_DEVICE": {
        "subjects": ["galaxy.device.>"],
        # 心跳占绝大多数:N 台设备 × 每 10s 一条。留量给够,但按时间淘汰 ——
        # 昨天的心跳没有任何价值,却会把注册/接管这类真正要回看的消息挤出去。
        "max_msgs": 200_000,
        "max_bytes": 268_435_456,  # 256 MB
        "max_age_s": 24 * 3600,
    },
    "GALAXY_CAPABILITY": {
        "subjects": ["galaxy.capability.>"],
        "max_msgs": 50_000,
        "max_bytes": 67_108_864,  # 64 MB
        "max_age_s": 7 * 24 * 3600,
    },
    "GALAXY_PRESENCE": {
        "subjects": ["galaxy.presence.>"],
        # 在场镜像按相位去重(见 lumiv_websocket_bridge._mirror_presence_to_mesh),
        # 所以这里是低频的;不去重的话这条流会被 5 Hz 的广播灌满。
        "max_msgs": 50_000,
        "max_bytes": 67_108_864,  # 64 MB
        "max_age_s": 24 * 3600,
    },
    "GALAXY_AUDIT": {
        "subjects": ["galaxy.audit.>"],
        # 审计是**记录**,不是遥测:不设 max_age,只受条数/字节上限约束。
        "max_msgs": 500_000,
        "max_bytes": 402_653_184,  # 384 MB
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# PR-2: Standardized topic namespace
# ═══════════════════════════════════════════════════════════════════════════════


class NATSTopics:
    """Canonical NATS subject prefixes for PR-2 unified bus.

    All internal publishers and subscribers MUST use these constants so that
    the topic contract is a single source of truth.

    Topic hierarchy:
      task.*          — task lifecycle (dispatch, result, cancel, status)
      device.*        — device events (register, heartbeat, status, presence)
      presence.*      — presence/projection events
      capability.*    — capability registration and resolution events
      audit.*         — audit log entries
    """

    # ── Task plane ───────────────────────────────────────────────────────────
    # 单数是规范面。复数 ``galaxy.tasks.*`` 是既有运转面,两者并存 ——
    # 见模块开头「单复数并存的现状」。订阅侧两个都订,不会漏也不会重。
    TASK_DISPATCH = "galaxy.task.dispatch"
    TASK_RESULT = "galaxy.task.result"
    TASK_CANCEL = "galaxy.task.cancel"
    TASK_CANCEL_RESULT = "galaxy.task.cancel_result"
    TASK_STATUS = "galaxy.task.status"
    TASK_DEADLETTER = "galaxy.task.deadletter"

    # ── Device plane ─────────────────────────────────────────────────────────
    DEVICE_REGISTER = "galaxy.device.register"
    DEVICE_HEARTBEAT = "galaxy.device.heartbeat"
    DEVICE_STATUS = "galaxy.device.status"
    DEVICE_PRESENCE = "galaxy.device.presence"

    # ── Presence plane ───────────────────────────────────────────────────────
    PRESENCE_STATE = "galaxy.presence.state"
    PRESENCE_PROJECTION = "galaxy.presence.projection"

    # ── Capability plane ─────────────────────────────────────────────────────
    CAPABILITY_REGISTERED = "galaxy.capability.registered"
    CAPABILITY_REMOVED = "galaxy.capability.removed"
    CAPABILITY_QUERY = "galaxy.capability.query"

    # ── Audit plane ──────────────────────────────────────────────────────────
    AUDIT_COMMAND = "galaxy.audit.command"
    AUDIT_RESULT = "galaxy.audit.result"
    AUDIT_VIOLATION = "galaxy.audit.violation"

    @classmethod
    def task_dispatch(cls, target: str) -> str:
        return f"{cls.TASK_DISPATCH}.{target}"

    @classmethod
    def task_result(cls, task_id: str) -> str:
        return f"{cls.TASK_RESULT}.{task_id}"

    @classmethod
    def device_heartbeat(cls, device_id: str) -> str:
        return f"{cls.DEVICE_HEARTBEAT}.{device_id}"

    @classmethod
    def capability_registered(cls, source: str) -> str:
        return f"{cls.CAPABILITY_REGISTERED}.{source}"


class WorkerLifecycleSubjects:
    """Canonical worker lifecycle subjects used by both publishers and consumers.

    这是**另一个平面**,不是任务平面的变体:``galaxy.workers.*`` 载 contracts.py
    的 ``Worker*`` 模型、对端是 MasterBrain;``galaxy.device.*`` 载 AIP v3 消息类、
    对端是各种设备。把 worker 生命周期消息转成 AIP v3 再发去设备平面,就是
    ``core/nats_bus.py`` 里那段「两个平面」注释记的那次事故。
    """

    REGISTER = "galaxy.workers.register"
    HEARTBEAT = "galaxy.workers.heartbeat"
    SHUTDOWN = "galaxy.workers.shutdown"
    RESULT = "galaxy.tasks.result.*"


# 所有流 max_bytes 的总和。JetStream **预留**这些额度:总和超过服务器的
# store 上限时,后建的流会被拒(``insufficient storage resources available``),
# 那个平面就整个发不出去。实测在一台 store 上限 3.45 GB 的服务器上,给审计
# 要 2 GB 就会把它挤掉 —— 所以这几个数不是随手填的预算,是**会互相挤兑的额度**。
# 加流或调大额度前,先看这个总和还剩多少余量。
TOTAL_STREAM_MAX_BYTES: int = sum(int(c["max_bytes"]) for c in _STREAMS.values())

__all__ = ["_STREAMS", "NATSTopics", "WorkerLifecycleSubjects", "TOTAL_STREAM_MAX_BYTES"]
