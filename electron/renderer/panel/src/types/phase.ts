/**
 * 三态类型定义
 *
 * 注意分工：本文件是**展示**词汇（silent/liminal/manifest），
 * `phase_contract.gen.ts` 是后端**线上**词汇（static/...）与连续量契约。
 * 两者由 usePhase.ts 的 _mapPhaseToken 转换。
 */
import type { PhasePosture } from './phase_contract.gen';

export type { PhasePosture };

export type Phase = 'silent' | 'liminal' | 'manifest';

export type PhaseLabel = 'STANDBY' | 'THINKING...' | 'ONLINE';

export interface WebSocketMessage {
  type: string;
  event_type?: string;
  phase?: Phase;
  target_phase?: string;
  /**
   * 相位姿态：后端一直在算、此前从没送到前端的连续量。
   *
   * 在场桥的 payload 里（`payload.posture`）。类型从后端生成，
   * 见 `phase_contract.gen.ts` 与 `core/phase_contract.py`——
   * 不要在这里手写一份，那正是这套生成机制要消灭的漂移。
   *
   * 可选：老版本后端不发这个字段，读的时候要判空。
   */
  posture?: PhasePosture;
  [key: string]: unknown;
}

export interface PhaseConfig {
  label: PhaseLabel;
  dotClass: string;
  panelClass: string;
}

export const PHASE_CONFIG: Record<Phase, PhaseConfig> = {
  silent: {
    label: 'STANDBY',
    dotClass: 'dot-black',
    panelClass: 'phase-silent',
  },
  liminal: {
    label: 'THINKING...',
    dotClass: 'dot-white',
    panelClass: 'phase-liminal',
  },
  manifest: {
    label: 'ONLINE',
    dotClass: 'dot-gray',
    panelClass: 'phase-manifest',
  },
};

/** 三态中文名 — 静态(silent)/阈限态(liminal)/显现态(manifest),面板与左下角紧凑指示点共用。 */
export const PHASE_ZH: Record<Phase, string> = {
  silent: '静态',
  liminal: '阈限态',
  manifest: '显现态',
};

/** 三态紧凑指示点顺序,固定为 静态 → 阈限态 → 显现态,对应黑 → 灰 → 白。 */
export const TRI_PHASE_ORDER: Phase[] = ['silent', 'liminal', 'manifest'];