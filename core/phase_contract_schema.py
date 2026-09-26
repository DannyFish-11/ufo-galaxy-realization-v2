"""core.phase_contract_schema — 渲染契约的机器可读描述（给 TS 生成用）

``scripts/gen_ts_types.py`` 据此生成 ``electron/renderer/panel/src/types/phase_contract.gen.ts``。
原先写在 ``core/phase_contract.py`` 末尾：那个文件在文件大小门禁的基线上，而契约每加一位，
这张描述就跟着长一截 —— 按仓库的规矩拆出来，不抬基线。

**取值表仍然只有一份**，都在 :mod:`core.phase_contract`；这里只是把它们摆成生成端要的形状。
入口照旧是 :func:`core.phase_contract.render_contract_schema`。
"""

from __future__ import annotations

from typing import Any, Dict

from core.phase_contract import (
    _TRI_STATE_MAP,
    AMBIENT_ACTIONS,
    CHAIN_KINDS,
    FORBIDDEN_TRANSITIONS,
    FORM_SIGNATURES,
    HYBRID_EXECUTION_MODES,
    LIFECYCLE_STATES,
    LIMINAL_ACTIVITIES,
    MODALITY_STATES,
    PATHWAY_LIMITS,
    PATHWAY_MODALITIES,
    PATHWAY_MODES,
    PERCEPTION_MODALITIES,
    PHASE_TRANSITIONS,
    RENDER_PHASES,
    ROUTE_TYPES,
    RUNTIME_DOMAINS,
    SIMULATION_KINDS,
    SPATIAL_PRESENCES,
    THINKING_LOCI,
    TIER_KINDS,
    TRANSITION_KIND_OF,
    TRANSITION_KINDS,
    WORLD_MODEL_SOURCES,
    PostureSource,
)


def build_render_contract_schema() -> Dict[str, Any]:
    """见模块说明。每次调用都现组一份（调用方只有生成脚本和测试，不必缓存）。"""
    return {
        "phases": list(RENDER_PHASES),
        "transitions": {k: list(v) for k, v in PHASE_TRANSITIONS.items()},
        "forbidden": [{"from": a, "to": b, "why": why} for (a, b), why in FORBIDDEN_TRANSITIONS.items()],
        "tri_state_map": dict(_TRI_STATE_MAP),
        "lifecycle_states": list(LIFECYCLE_STATES),
        "liminal_activities": list(LIMINAL_ACTIVITIES),
        "simulation_kinds": list(SIMULATION_KINDS),
        "runtime_domains": list(RUNTIME_DOMAINS),
        "form_signatures": list(FORM_SIGNATURES),
        "spatial_presences": list(SPATIAL_PRESENCES),
        "chain_kinds": list(CHAIN_KINDS),
        "hybrid_execution_modes": list(HYBRID_EXECUTION_MODES),
        "world_model_sources": list(WORLD_MODEL_SOURCES),
        "perception_modalities": list(PERCEPTION_MODALITIES),
        "modality_states": list(MODALITY_STATES),
        "ambient_actions": list(AMBIENT_ACTIONS),
        "transition_kinds": list(TRANSITION_KINDS),
        "pathway_modalities": list(PATHWAY_MODALITIES),
        "pathway_modes": list(PATHWAY_MODES),
        # 空串是合法取值（没被限制），生成端要把它保留成联合类型的一支。
        "pathway_limits": list(PATHWAY_LIMITS),
        "tier_kinds": list(TIER_KINDS),
        "thinking_loci": list(THINKING_LOCI),
        "route_types": list(ROUTE_TYPES),
        "transition_kind_of": [{"from": a, "to": b, "kind": k} for (a, b), k in TRANSITION_KIND_OF.items()],
        "sources": [PostureSource.CONTINUUM, PostureSource.ANCHOR_ONLY],
        "chain_fields": [
            {"name": "kind", "ts": "ChainKind", "doc": "local / cross_device —— 决定 last_target 的含义"},
            {"name": "is_active", "ts": "boolean", "doc": "这条链是否跑过；false=还没跑过，不是「没有这条链」"},
            {"name": "total_executions", "ts": "number", "doc": "本会话内这条链上的总执行次数"},
            {"name": "canonical_executions", "ts": "number", "doc": "其中走完整规范链的次数"},
            {"name": "legacy_executions", "ts": "number", "doc": "其中走遗留／非规范路径的次数"},
            {"name": "chain_order", "ts": "string[]", "doc": "规范链的步骤名（有序）—— 空间里该画几段"},
            {"name": "last_step", "ts": "string | null", "doc": "最近一次到达的步骤名"},
            {"name": "last_target", "ts": "string | null", "doc": "local→task_id，cross_device→device_id"},
        ],
        "hybrid_fields": [
            {"name": "is_decided", "ts": "boolean", "doc": "本轮是否真的做过模式选择"},
            {"name": "mode", "ts": "HybridExecutionMode", "doc": "用什么手法动手；none=尚未决策"},
            {"name": "reason", "ts": "string", "doc": "选它的理由（后端策略引擎原文）"},
            {"name": "confidence", "ts": "number", "doc": "[0,1]：1=精确命中规则，0.5=启发式，0=兜底"},
        ],
        "modality_fields": [
            {"name": "modality", "ts": "PerceptionModality", "doc": "screen / camera / microphone / system_audio"},
            {"name": "state", "ts": "ModalityState", "doc": "五档之一 —— 刻意不是布尔，理由见该类型的注释"},
            {
                "name": "signal_age_s",
                "ts": "number | null",
                "doc": "距上次有信号多久（秒）；null=从没有过信号（与 0 是两件事）",
            },
        ],
        "perception_fields": [
            {"name": "source", "ts": "ViewSource", "doc": "unwired=进程里没有感知库，live=有"},
            {"name": "is_sensing", "ts": "boolean", "doc": "任一模态 live。便利位，由 modalities 推出"},
            {"name": "privacy_paused", "ts": "boolean", "doc": "隐私急停是否生效 —— 整体姿态，不是四条恰好都闭着"},
            {"name": "modalities", "ts": "ModalityView[]", "doc": "恒定四条，缺席的以 unavailable 出现"},
            {"name": "ambient_action", "ts": "AmbientAction", "doc": "自发注意力上一拍的决策；none=还没决策过"},
            {"name": "ambient_rationale", "ts": "string", "doc": "那一拍为什么这么决定（后端原文，已截断）"},
        ],
        "pathway_lane_fields": [
            {"name": "modality", "ts": "PathwayModality", "doc": "vision_in / audio_in / audio_out / video_in"},
            {
                "name": "mode",
                "ts": "PathwayMode",
                "doc": "native=一条通路直达；bridge=中间还有一段转换；unavailable=不通",
            },
            {
                "name": "limited_by",
                "ts": "PathwayLimit",
                "doc": "谁把它限制住的：model=换模型 / serving=开环境变量 / device=换设备 / provider=换一家；空串=没被限制",
            },
        ],
        "pathway_fields": [
            {"name": "locus", "ts": "string", "doc": "这份结论照着谁算的：local 或某家 provider 名；空串=没协商过"},
            {"name": "tier_kind", "ts": "TierKind", "doc": "本地档位形态；unknown=取不到档位表（不猜）"},
            {"name": "is_wired", "ts": "boolean", "doc": "false=这个进程里没有协商层，四条全是占位空态"},
            {"name": "lanes", "ts": "PathwayLane[]", "doc": "恒定四条，不通的以 unavailable 出现"},
            {"name": "native_count", "ts": "number", "doc": "走原生的条数（由 lanes 推出的便利位）"},
            {"name": "bridged_count", "ts": "number", "doc": "接了桥的条数（同上）"},
        ],
        "thinking_locus_fields": [
            {"name": "is_decided", "ts": "boolean", "doc": "本进程是否路由过角色；false 时下面几位都是空的"},
            {"name": "locus", "ts": "ThinkingLocus", "doc": "local / cloud；unknown=还没想过，**不是**本地"},
            {"name": "provider", "ts": "string", "doc": "选中的提供商名；未决策时空串"},
            {"name": "model", "ts": "string", "doc": "选中的型号"},
            {"name": "role", "ts": "string", "doc": "这次路由是为哪个协作角色做的"},
            {"name": "route_type", "ts": "RouteType", "doc": "dispatch=派活 / produce=产出 / gatekeep=把关"},
            {"name": "reason", "ts": "string", "doc": "路由理由（后端原文，已截断）"},
            {
                "name": "is_fallback",
                "ts": "boolean",
                "doc": "角色意图没被满足：派活落到云端，或把关回落本地 —— 该画得不一样",
            },
            {
                "name": "draft_active",
                "ts": "boolean",
                "doc": "本地这一轮开没开投机解码的草稿位；只在 locus=local 时有意义",
            },
            {
                "name": "draft_speedup",
                "ts": "number",
                "doc": "这台机器实测的倍数；0=没测过，<1=测过且更慢（那时 draft_active 为 false）",
            },
        ],
        "world_model_fields": [
            {"name": "is_wired", "ts": "boolean", "doc": "世界模型是否已接到渲染链路；当前恒 false"},
            {"name": "source", "ts": "WorldModelSource", "doc": "unwired=链路还没建，live=数就是这个"},
            {"name": "entity_count", "ts": "number", "doc": "已知实体数；unwired 时的 0 是「不知道」"},
            {"name": "entity_kinds", "ts": "string[]", "doc": "出现过的实体种类"},
        ],
        "simulation_fields": [
            {"name": "is_active", "ts": "boolean", "doc": "当前是否有推演在跑"},
            {"name": "simulation_kind", "ts": "SimulationKind", "doc": "none / speculative / sandbox"},
            {"name": "candidate_paths", "ts": "string[]", "doc": "正在评估的候选执行路径 —— 阈限态在权衡什么"},
            {"name": "committed_path", "ts": "string | null", "doc": "已提交的那条；仍在推演/全失败时 null"},
            {"name": "is_committed", "ts": "boolean", "doc": "committed_path !== null"},
            {"name": "step_count", "ts": "number", "doc": "已完成的推演步数"},
            {"name": "scenario_label", "ts": "string | null", "doc": "场景的人类可读标签"},
        ],
        "fields": [
            {"name": "lifecycle", "ts": "Lifecycle", "doc": "【主轴】主体生命周期 —— 渲染端的整体编排跟它走"},
            {
                "name": "previous_lifecycle",
                "ts": "Lifecycle | null",
                "doc": "主轴的上一档（相位事件自带 from_phase）；null=还没发生过转移",
            },
            {
                "name": "transition_kind",
                "ts": "TransitionKind",
                "doc": "刚才那次转移的性质（一拍性：只有转移后的第一份广播带着）",
            },
            {
                "name": "transition_seq",
                "ts": "number",
                "doc": "主轴转移过几次（驻留）—— 跟上次见过的比，变了就是发生过转移",
            },
            {
                "name": "last_transition",
                "ts": "TransitionKind",
                "doc": "最近那次转移的性质（驻留）—— 与 transition_seq 成对读",
            },
            {
                "name": "continuum_phase",
                "ts": "RenderPhase",
                "doc": "【副轴】内部连续体四相，提供主轴给不出的纹理",
            },
            {
                "name": "is_returning",
                "ts": "boolean",
                "doc": "副轴是否在返回弧上（receding）——把「刚做完」与「静息」分开的那一位",
            },
            {"name": "next_phases", "ts": "RenderPhase[]", "doc": "副轴从当前相位合法能去的下一相"},
            {
                "name": "liminal_activity",
                "ts": "LiminalActivity",
                # 取值列表由常量拼出，不手抄 —— 手抄那份漏掉过 understanding，而 TS 类型
                # 本身是从同一个常量生成的，于是【类型对、注释错】，评审时最难看出来。
                "doc": "阈限态里正在干嘛（有序递进）：" + " → ".join(LIMINAL_ACTIVITIES),
            },
            {"name": "simulation", "ts": "SimulationSummary", "doc": "沙盘推演摘要 —— 阈限态的可视内容之三"},
            {"name": "local_chain", "ts": "ExecutionChainView", "doc": "本机执行链 —— 阈限态的可视内容之一"},
            {
                "name": "cross_device_chain",
                "ts": "ExecutionChainView",
                "doc": "跨设备执行链 —— 阈限态的可视内容之二",
            },
            {"name": "world_model", "ts": "WorldModelView", "doc": "世界模型 —— 留出的位置，当前恒 unwired"},
            {
                "name": "perception",
                "ts": "PerceptionView",
                "doc": "**第一态的主体** —— 原生多模态摄入此刻的样子；不随相位裁剪",
            },
            {
                "name": "hybrid_execution",
                "ts": "HybridExecutionView",
                "doc": "表达期用什么手法动手（GUI／API／混合）",
            },
            {
                "name": "acting",
                "ts": "boolean",
                "doc": "此刻是否正在动手（操作这台机器）—— 外壳据此把「停」摆到最近处",
            },
            {
                "name": "stop_key",
                "ts": "string",
                "doc": "此刻按哪个键能叫停（如 Esc）；空 = 没有 —— 只在键盘监听确实占到时才有值",
            },
            {
                "name": "pathway",
                "ts": "ModalityPathwayView",
                "doc": "四条模态通路走原生还是走桥 —— perception 说有没有信号，这一位说它怎么进去的",
            },
            {
                "name": "thinking_locus",
                "ts": "ThinkingLocusView",
                "doc": "这一轮在哪儿想（本地／云端）；unknown=还没想过，不是本地",
            },
            {"name": "runtime_domain", "ts": "RuntimeDomain | null", "doc": "第二维：在哪儿跑；null=尚未判定"},
            {"name": "motion", "ts": "number", "doc": "抽象运动能量 [0,1]"},
            {"name": "intensity", "ts": "number", "doc": "整体在场强度 [0,1]"},
            {"name": "form_signature", "ts": "FormSignature", "doc": "形态提示；receding 对应 collapsing_field"},
            {"name": "spatial_presence", "ts": "SpatialPresence", "doc": "空间权重／贴近度"},
            {"name": "texture_hint", "ts": "string", "doc": "质感描述（soft_dissolve 等）；空串=无提示"},
            {"name": "presence_intensity", "ts": "number", "doc": "EMA 平滑的在场强度 [0,1]"},
            {"name": "coherence", "ts": "number", "doc": "信号成意图的程度 [0,1]"},
            {"name": "ambiguity", "ts": "number", "doc": "coherence 的反面 [0,1]"},
            {"name": "collapse_tendency", "ts": "number", "doc": "推向塌缩（liminal→manifest）的概率质量 [0,1]"},
            {"name": "retreat_tendency", "ts": "number", "doc": "推向 receding 的概率质量 [0,1]（不是退回上一档）"},
            {"name": "stability", "ts": "number", "doc": "时间稳定度 [0,1]，低值表示刚振荡过"},
            {"name": "source", "ts": "PhasePostureSource", "doc": "实算还是兜底"},
            {"name": "degraded", "ts": "boolean", "doc": "continuum 本拍是否降级"},
            {"name": "degrade_reason", "ts": "string | null", "doc": "仅 degraded=true 时有值"},
        ],
    }
