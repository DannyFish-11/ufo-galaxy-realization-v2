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