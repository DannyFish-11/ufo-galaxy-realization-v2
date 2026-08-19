/**
 * useRenderPosture — 消费后端每帧广播的**双轴渲染契约**。
 *
 * 后端一直在发，前端一直没收
 * ==========================
 * `core/lumiv_websocket_bridge._render_payload()` 每一帧都算出一份完整的
 * `RenderPosture`（见 `core/phase_contract.py`），挂在 `payload.render` 上广播。
 * `scripts/gen_ts_types.py` 也据此生成了 `types/phase_contract.gen.ts`。
 *
 * 而在本文件之前：`payload.render` **零读取**，`RenderPosture` **零 import**。
 * 面板读的是 `payload.phase` —— 那个被压扁成三档的一维遗留字符串。后端每帧算好
 * 的连续量、副轴、阈限活动，到了面板边界全部丢掉。
 *
 * 本文件只做骨架，不做观感
 * ========================
 * 这一层负责把契约**完整、带类型、可校验**地送到 DOM 边界为止：21 个字段一个不少，
 * 连续量夹紧，缺字段可判定。**它不改变面板任何视觉表现** —— 没有任何样式规则消费
 * 它暴露的 class 与自定义属性（见 `App.tsx` 的说明）。观感是下一步的事，那一步需要
 * 人眼确认；骨架这一步不需要，所以先把骨架焊死。
 *
 * 双轴是什么意思
 * ==============
 * - **主轴** `lifecycle`：silent / liminal / manifest —— 就是面板原来那三档。
 * - **副轴** `continuum_phase`：formless / liminal / manifest / **receding**。
 *
 * 副轴多出来的那一档 `receding` 是关键：它把「刚做完、正在收」与「静息」分开。
 * 主轴把两者都报成 silent（见生成文件里的 `TRI_STATE_OF`），所以只看主轴的面板
 * 永远画不出「刚回答完」和「一直没动静」的区别 —— 而这两件事对用户的含义完全不同。
 *
 * 降级
 * ====
 * 老后端不发 `payload.render`。这时 `posture` 为 null，调用方按原来的三档走 ——
 * 面板不会因为契约缺席而空白。收到过一次之后保留最后一份好值，避免中间帧
 * （比如没带 render 的 ambient_tick）把已经拿到的姿态抹掉。
 */
import { useCallback, useState } from 'react';

import type {
  ExecutionChainView,
  HybridExecutionView,
  ModalityPathwayView,
  PathwayModality,
  PerceptionModality,
  PerceptionView,
  RenderPosture,
  ThinkingLocusView,
  WorldModelView,
} from '@/types/phase_contract.gen';
import type { WebSocketMessage } from '@/types/phase';

interface UseRenderPostureReturn {
  /** 最后一份有效的渲染契约；从未收到过则为 null。 */
  posture: RenderPosture | null;
  /** 是否收到过契约 —— 调用方据此决定走契约还是退回三档。 */
  hasContract: boolean;
  /**
   * 最近一帧里**缺席**的契约字段名。空数组 = 这一帧是完整的。
   *
   * 单独暴露而不是静默补默认值：后端少发一个字段是**契约漂移**，不是正常降级。
   * 补上默认值会让它看起来一切正常，而面板其实已经在拿假数据画图 —— 那正是这套
   * 生成机制要消灭的东西。这里把它变成可观测的事实。
   */
  missingFields: string[];
  handleMessage: (msg: WebSocketMessage | null) => void;
}

/**
 * `RenderPosture` 的全部字段名。
 *
 * 手写一份是有意的：它是**前端这一侧对契约的期望**。后端删字段时，
 * `missingFields` 会立刻报出来，而不是等到某个样式取 `var()` 取空才发现。
 * 与生成文件的一致性由 `tests/test_render_contract_wire_completeness.py` 机器校验。
 */
export const RENDER_POSTURE_FIELDS = [
  'lifecycle',
  'previous_lifecycle',
  'transition_kind',
  'continuum_phase',
  'is_returning',
  'next_phases',
  'liminal_activity',
  'simulation',
  'local_chain',
  'cross_device_chain',
  'world_model',
  'perception',
  'hybrid_execution',
  'pathway',
  'thinking_locus',
  'runtime_domain',
  'motion',
  'intensity',
  'form_signature',
  'spatial_presence',
  'texture_hint',
  'presence_intensity',
  'coherence',
  'ambiguity',
  'collapse_tendency',
  'retreat_tendency',
  'stability',
  'source',
  'degraded',
  'degrade_reason',
] as const;

/** 契约里取值域是 [0,1] 的那些连续量。 */
export const RENDER_POSTURE_UNIT_FIELDS = [
  'motion',
  'intensity',
  'presence_intensity',
  'coherence',
  'ambiguity',
  'collapse_tendency',
  'retreat_tendency',
  'stability',
] as const;

/**
 * 后端 `ExecutionChainView.empty()` 的等价空态 —— 「这条链存在但还没跑过」。
 *
 * 与后端那份逐字段对应（`core/phase_contract.py`）。这里要有一份，是因为帧里
 * 缺了这条链时下游仍需一个**语义正确**的对象：`is_active === false` 说的是
 * 「还没跑过」，读到 `undefined` 说的是「不知道」，两者对渲染是两回事。
 */
export function _emptyChain(kind: 'local' | 'cross_device'): ExecutionChainView {
  return {
    kind,
    is_active: false,
    total_executions: 0,
    canonical_executions: 0,
    legacy_executions: 0,
    chain_order: [],
    last_step: null,
    last_target: null,
  };
}

/**
 * 后端 `PerceptionView.unwired()` 的等价空态 —— 这个进程里没有感知库。
 *
 * 四条模态**恒定存在**（缺席的以 `unavailable` 出现），所以这里也必须给满四条：
 * 渲染端要能把「这一侧不亮」画出来，而不是遍历一个长度会变的数组。
 */
const PERCEPTION_MODALITY_ORDER: PerceptionModality[] = [
  'screen',
  'camera',
  'microphone',
  'system_audio',
];

export const UNWIRED_PERCEPTION: PerceptionView = {
  source: 'unwired',
  is_sensing: false,
  privacy_paused: false,
  modalities: PERCEPTION_MODALITY_ORDER.map((modality) => ({
    modality,
    state: 'unavailable' as const,
    signal_age_s: null,
  })),
  ambient_action: 'none',
  ambient_rationale: '',
};

/** 后端 `WorldModelView.unwired()` 的等价空态 —— 世界模型这条链路还没建。 */
export const UNWIRED_WORLD_MODEL: WorldModelView = {
  is_wired: false,
  source: 'unwired',
  entity_count: 0,
  entity_kinds: [],
};

/**
 * 后端 `ModalityPathwayView.unwired()` 的等价空态 —— 这个进程里没有协商层。
 *
 * 四条通路**恒定存在**（不通的以 `unavailable` 出现），理由与 `PerceptionView`
 * 的四条模态相同：渲染端要能把「这一侧不通」画出来，而不是遍历一个长度会变的数组。
 */
const PATHWAY_MODALITY_ORDER: PathwayModality[] = ['vision_in', 'audio_in', 'audio_out', 'video_in'];

export const UNWIRED_PATHWAY: ModalityPathwayView = {
  locus: '',
  tier_kind: 'unknown',
  is_wired: false,
  lanes: PATHWAY_MODALITY_ORDER.map((modality) => ({
    modality,
    mode: 'unavailable' as const,
    limited_by: '' as const,
  })),
  native_count: 0,
  bridged_count: 0,
};

/**
 * 后端 `ThinkingLocusView.undecided()` 的等价空态 —— 本进程还没路由过任何角色。
 *
 * `locus` 是 `'unknown'` 而**不是** `'local'`：把没发生过的事当成本地，渲染端会在
 * 一个还没开始想的时刻画出「本地在想」。
 */
export const UNDECIDED_THINKING_LOCUS: ThinkingLocusView = {
  is_decided: false,
  locus: 'unknown',
  provider: '',
  model: '',
  role: '',
  route_type: 'unknown',
  reason: '',
  is_fallback: false,
};

/** 后端 `HybridExecutionView.undecided()` 的等价空态 —— 本轮还没选执行手法。 */
export const UNDECIDED_HYBRID_EXECUTION: HybridExecutionView = {
  is_decided: false,
  mode: 'none',
  reason: '',
  confidence: 0,
};

/** 帧里这一格不是对象时换成给定空态。 */
function _objOr<T>(raw: unknown, fallback: T): T {
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as T) : fallback;
}

/** 帧里这条链不是对象时换成对应种类的零态。 */
function _chainOr(raw: unknown, kind: 'local' | 'cross_device'): ExecutionChainView {
  return _objOr<ExecutionChainView>(raw, _emptyChain(kind));
}

/** 把 [0,1] 的连续量夹紧；后端理论上已经保证，但契约跨进程，别人发什么都可能。 */
export function _clamp01(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return 0;
  return n < 0 ? 0 : n > 1 ? 1 : n;
}

/** 列出这一帧缺了哪些契约字段（`null` 是合法取值，不算缺）。 */
export function _missingFields(raw: Record<string, unknown>): string[] {
  return RENDER_POSTURE_FIELDS.filter((f) => !(f in raw));
}

/**
 * 从一条 WS 消息里取渲染契约。取不到返回 null。
 *
 * 只认 `payload.render` —— 那是 `_render_payload()` 挂的位置。不去猜别的字段：
 * 猜错了会静默拿到半份姿态，比没拿到更难查。
 */
export function _extractRenderPosture(
  msg: WebSocketMessage | null,
): { posture: RenderPosture; missing: string[] } | null {
  if (!msg) return null;
  const payload = (msg.payload as { render?: unknown } | undefined) || undefined;
  const raw = payload?.render;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;

  const rec = raw as Record<string, unknown>;
  // lifecycle 是主轴，没有它这份姿态就不成立 —— 宁可当作没收到。
  if (typeof rec.lifecycle !== 'string') return null;

  const normalised: Record<string, unknown> = { ...rec };
  for (const f of RENDER_POSTURE_UNIT_FIELDS) {
    normalised[f] = _clamp01(rec[f]);
  }
  // next_phases 是数组：非数组一律当空，别让下游 .map 炸掉。
  normalised.next_phases = Array.isArray(rec.next_phases) ? rec.next_phases : [];
  normalised.is_returning = Boolean(rec.is_returning);
  normalised.degraded = Boolean(rec.degraded);
  // 嵌套视图同样只做「形状可用」的兜底，不补内容：不是对象就换成后端契约里
  // 那份**语义明确的空态**，而不是 `{}` —— `{}` 会让下游读到 undefined，
  // 分不清「这条链还没跑过」和「这一帧没带这条链」。
  normalised.local_chain = _chainOr(rec.local_chain, 'local');
  normalised.cross_device_chain = _chainOr(rec.cross_device_chain, 'cross_device');
  normalised.world_model = _objOr(rec.world_model, UNWIRED_WORLD_MODEL);
  // 感知这一格额外校验 modalities 是不是数组：它是第一态唯一的视觉依据，
  // 拿到一个非数组会让下游 .map 直接炸掉整个覆盖层。
  const percept = _objOr<PerceptionView>(rec.perception, UNWIRED_PERCEPTION);
  normalised.perception = Array.isArray(percept.modalities)
    ? percept
    : { ...percept, modalities: UNWIRED_PERCEPTION.modalities };
  normalised.hybrid_execution = _objOr(rec.hybrid_execution, UNDECIDED_HYBRID_EXECUTION);
  // 通路这一格与感知同样要校验数组：lanes 是第一态氛围光的形状依据，
  // 拿到一个非数组会让下游 .map 直接炸掉整个覆盖层。
  const pathway = _objOr<ModalityPathwayView>(rec.pathway, UNWIRED_PATHWAY);
  normalised.pathway = Array.isArray(pathway.lanes)
    ? pathway
    : { ...pathway, lanes: UNWIRED_PATHWAY.lanes };
  normalised.thinking_locus = _objOr(rec.thinking_locus, UNDECIDED_THINKING_LOCUS);

  return { posture: normalised as unknown as RenderPosture, missing: _missingFields(rec) };
}

export function useRenderPosture(): UseRenderPostureReturn {
  const [posture, setPosture] = useState<RenderPosture | null>(null);
  const [missingFields, setMissingFields] = useState<string[]>([]);
  const handleMessage = useCallback((msg: WebSocketMessage | null) => {
    const next = _extractRenderPosture(msg);
    // 没带 render 的帧不清空 —— 保留最后一份好值。
    if (next === null) return;
    setPosture(next.posture);
    setMissingFields(next.missing);
  }, []);

  return { posture, hasContract: posture !== null, missingFields, handleMessage };
}
