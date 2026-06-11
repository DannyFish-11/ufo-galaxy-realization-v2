import React from 'react';

export interface OpenClawdStatus {
  runtimeState: 'RUNNING' | 'PAUSED' | 'ERROR' | 'RESTARTING';
  phase: 'silent' | 'liminal' | 'manifest';
  coherence: number;
  activeTasks: number;
  completedTasks: number;
  connectedDevices: number;
  lastTick: number;
  uptime: number;
}

interface Props {
  status: OpenClawdStatus;
}

const DEFAULT_STATUS: OpenClawdStatus = {
  runtimeState: 'RUNNING',
  phase: 'liminal',
  coherence: 0.97,
  activeTasks: 4,
  completedTasks: 1523,
  connectedDevices: 3,
  lastTick: Date.now(),
  uptime: 86400,
};

const PHASE_CONFIG: Record<OpenClawdStatus['phase'], { color: string; label: string; glow: string }> = {
  silent:  { color: '#6b7280', label: 'SILENT',  glow: '0 0 12px rgba(107,114,128,0.4)' },
  liminal: { color: '#22d3ee', label: 'LIMINAL', glow: '0 0 16px rgba(34,211,238,0.5)' },
  manifest:{ color: '#f472b6', label: 'MANIFEST',glow: '0 0 20px rgba(244,114,182,0.6)' },
};

const STATE_COLORS: Record<OpenClawdStatus['runtimeState'], string> = {
  RUNNING: '#4ade80',
  PAUSED: '#fbbf24',
  ERROR: '#ef4444',
  RESTARTING: '#60a5fa',
};

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d}d`);
  parts.push(`${h.toString().padStart(2, '0')}h`);
  parts.push(`${m.toString().padStart(2, '0')}m`);
  return parts.join(' ');
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

function getCoherenceColor(c: number): string {
  if (c >= 0.9) return '#4ade80';
  if (c >= 0.7) return '#fbbf24';
  if (c >= 0.5) return '#fb923c';
  return '#ef4444';
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: 'rgba(255, 255, 255, 0.06)',
    backdropFilter: 'blur(16px) saturate(140%)',
    WebkitBackdropFilter: 'blur(16px) saturate(140%)',
    borderRadius: 12,
    border: '1px solid rgba(255, 255, 255, 0.08)',
    boxShadow: '0 4px 24px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.04)',
    padding: 20,
    color: '#e2e8f0',
    fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", "Consolas", monospace',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 14,
    fontWeight: 700,
    letterSpacing: '0.08em',
    color: '#f8fafc',
    textTransform: 'uppercase' as const,
  },
  stateRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 12,
  },
  pulseDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
  },
  stateLabel: {
    fontWeight: 600,
    fontSize: 11,
    letterSpacing: '0.05em',
  },
  phaseSection: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '16px 0',
  },
  phaseText: {
    fontSize: 36,
    fontWeight: 900,
    letterSpacing: '0.12em',
    transition: 'all 0.5s ease',
    textShadow: '0 2px 8px rgba(0,0,0,0.3)',
  },
  divider: {
    height: 1,
    background: 'rgba(255, 255, 255, 0.06)',
    border: 'none',
    margin: 0,
  },
  coherenceLabel: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 11,
    color: '#94a3b8',
    marginBottom: 6,
  },
  progressBarTrack: {
    height: 6,
    borderRadius: 3,
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: 3,
    transition: 'width 0.6s ease, background-color 0.6s ease',
  },
  grid2: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
  },
  statBox: {
    background: 'rgba(255, 255, 255, 0.04)',
    borderRadius: 8,
    padding: '10px 12px',
    border: '1px solid rgba(255, 255, 255, 0.05)',
  },
  statLabel: {
    fontSize: 10,
    color: '#64748b',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    marginBottom: 4,
  },
  statValue: {
    fontSize: 20,
    fontWeight: 700,
    color: '#f1f5f9',
  },
  footer: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 10,
    color: '#475569',
    marginTop: 4,
  },
};

const globalStyles = `
@keyframes pulse-glow {
  0%, 100% {
    box-shadow: 0 0 4px currentColor;
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 12px currentColor;
    opacity: 0.6;
  }
}
`;

const OpenClawdStatusPanel: React.FC<Props> = ({ status }) => {
  const s = status || DEFAULT_STATUS;
  const phaseCfg = PHASE_CONFIG[s.phase];
  const stateColor = STATE_COLORS[s.runtimeState];
  const coherenceColor = getCoherenceColor(s.coherence);
  const coherencePercent = Math.round(s.coherence * 100);

  return (
    <div style={styles.card}>
      <style>{globalStyles}</style>

      {/* Header: Title + State */}
      <div style={styles.header}>
        <span style={styles.title}>OpenClawd</span>
        <div style={styles.stateRow}>
          <span
            style={{
              ...styles.pulseDot,
              backgroundColor: stateColor,
              color: stateColor,
              animation: s.runtimeState === 'RUNNING' ? 'pulse-glow 2s infinite' : 'none',
            }}
          />
          <span style={{ ...styles.stateLabel, color: stateColor }}>
            {s.runtimeState}
          </span>
        </div>
      </div>

      {/* Phase Display */}
      <div style={styles.phaseSection}>
        <span
          style={{
            ...styles.phaseText,
            color: phaseCfg.color,
            textShadow: phaseCfg.glow,
          }}
        >
          {phaseCfg.label}
        </span>
      </div>

      <hr style={styles.divider} />

      {/* Coherence Bar */}
      <div>
        <div style={styles.coherenceLabel}>
          <span>COHERENCE</span>
          <span style={{ color: coherenceColor, fontWeight: 700 }}>{coherencePercent}%</span>
        </div>
        <div style={styles.progressBarTrack}>
          <div
            style={{
              ...styles.progressBarFill,
              width: `${coherencePercent}%`,
              backgroundColor: coherenceColor,
              boxShadow: `0 0 8px ${coherenceColor}40`,
            }}
          />
        </div>
      </div>

      <hr style={styles.divider} />

      {/* Stats Grid */}
      <div style={styles.grid2}>
        <div style={styles.statBox}>
          <div style={styles.statLabel}>Active Tasks</div>
          <div style={{ ...styles.statValue, color: '#fbbf24' }}>{s.activeTasks}</div>
        </div>
        <div style={styles.statBox}>
          <div style={styles.statLabel}>Completed</div>
          <div style={{ ...styles.statValue, color: '#4ade80' }}>{s.completedTasks.toLocaleString()}</div>
        </div>
        <div style={styles.statBox}>
          <div style={styles.statLabel}>Devices</div>
          <div style={{ ...styles.statValue, color: '#22d3ee' }}>{s.connectedDevices}</div>
        </div>
        <div style={styles.statBox}>
          <div style={styles.statLabel}>Uptime</div>
          <div style={styles.statValue}>{formatUptime(s.uptime)}</div>
        </div>
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        <span>Tick: {formatTimestamp(s.lastTick)}</span>
        <span>{s.connectedDevices} device{s.connectedDevices !== 1 ? 's' : ''} online</span>
      </div>
    </div>
  );
};

export default React.memo(OpenClawdStatusPanel);
