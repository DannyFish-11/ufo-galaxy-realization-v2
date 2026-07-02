/**
 * 三态类型定义
 */

export type Phase = 'silent' | 'liminal' | 'manifest';

export type PhaseLabel = 'STANDBY' | 'THINKING...' | 'ONLINE';

export interface WebSocketMessage {
  type: string;
  event_type?: string;
  phase?: Phase;
  target_phase?: string;
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