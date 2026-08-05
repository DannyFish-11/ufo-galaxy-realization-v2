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

import type { RenderPosture } from '@/types/phase_contract.gen';
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
  'continuum_phase',
  'is_returning',
  'next_phases',
  'liminal_activity',
  'simulation',
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
