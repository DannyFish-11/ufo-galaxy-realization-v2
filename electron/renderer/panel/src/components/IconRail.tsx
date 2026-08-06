import type { Phase } from '@/types/phase';
import { PHASE_ZH, TRI_PHASE_ORDER } from '@/types/phase';

export interface TabDef {
  key: string;
  label: string;
  icon: JSX.Element;
}

interface IconRailProps {
  tabs: TabDef[];
  active: number;
  onChange: (i: number) => void;
  phase: Phase;
  connected: boolean;
  onToggleDrawer: () => void;
}

export default function IconRail({
  tabs,
  active,
  onChange,
  phase,
  connected,
  onToggleDrawer,
}: IconRailProps) {
  return (
    <nav className="rail glass">
      <div className="rail-brand" title="Galaxy">
        <span className="rail-brand-dot" />
      </div>

      <div className="rail-tabs">
        {tabs.map((t, i) => (
          <button
            key={t.key}
            className={`rail-tab ${active === i ? 'active' : ''}`}
            onClick={() => onChange(i)}
            title={t.label}
            aria-label={t.label}
            aria-current={active === i}
          >
            <span className="rail-rail-edge" />
            <span className="rail-icon">{t.icon}</span>
          </button>
        ))}
      </div>

      <div className="rail-bottom">
        <button
          className="rail-tab"
          onClick={onToggleDrawer}
          title="诊断"
          aria-label="诊断抽屉"
        >
          <span className="rail-icon">{ICONS.diagnostics}</span>
        </button>
        <div
          className={`tri-compact ${connected ? 'connected' : ''}`}
          title={connected ? `三态 · ${PHASE_ZH[phase]}` : '未连接'}
        >
          {TRI_PHASE_ORDER.map((p) => (
            <span
              key={p}
              className={`tri-compact-dot tri-${p} ${phase === p ? 'active' : ''}`}
            />
          ))}
        </div>
      </div>
    </nav>
  );
}

// ── 内联图标(线性,1.6 描边,继承 currentColor) ────────────────────────
const S = {
  width: 22,
  height: 22,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

export const ICONS = {
  chat: (
    <svg {...S}>
      <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.6 8.6 0 0 1-3.9-.9L3 21l1.9-5.6a8.5 8.5 0 1 1 16.1-3.9Z" />
    </svg>
  ),
  mesh: (
    <svg {...S}>
      <circle cx="12" cy="5" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M12 7v3m0 0-5.5 6.2M12 10l5.5 6.2" />
    </svg>
  ),
  capability: (
    <svg {...S}>
      <path d="M12 2 4 6v6c0 5 3.5 8 8 10 4.5-2 8-5 8-10V6Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
  models: (
    <svg {...S}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3" />
    </svg>
  ),
  settings: (
    <svg {...S}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7 19.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.7 7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9.4A1.6 1.6 0 0 0 10.5 3V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9.4a1.6 1.6 0 0 0 1.5 1.1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" />
    </svg>
  ),
  pairing: (
    <svg {...S}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M14 14h3v3h-3zm5 0h2m-2 5h2m-5 0h2" />
    </svg>
  ),
  diagnostics: (
    <svg {...S}>
      <path d="M3 12h4l2 6 4-12 2 6h6" />
    </svg>
  ),
};
