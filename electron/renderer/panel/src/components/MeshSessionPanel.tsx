import React from 'react';

export interface MeshParticipantInfo {
  nodeId: string;
  role: string;
  status: 'active' | 'idle' | 'disconnected';
  lastSeen: number;
}

export interface MeshSessionInfo {
  sessionId: string;
  status: 'active' | 'pending' | 'closed';
  barrierStatus: string;
  tickSequence: number;
  participants: MeshParticipantInfo[];
  createdAt: number;
}

interface Props {
  session: MeshSessionInfo;
}

const DEFAULT_SESSION: MeshSessionInfo = {
  sessionId: 'mesh-session-001',
  status: 'active',
  barrierStatus: 'released',
  tickSequence: 12847,
  participants: [
    { nodeId: 'desktop', role: 'coordinator', status: 'active', lastSeen: Date.now() },
    { nodeId: 'android_01', role: 'participant', status: 'active', lastSeen: Date.now() },
    { nodeId: 'wear_01', role: 'participant', status: 'active', lastSeen: Date.now() },
  ],
  createdAt: Date.now() - 3600000,
};

const BARRIER_COLORS: Record<string, { color: string; bg: string; label: string }> = {
  released: { color: '#4ade80', bg: 'rgba(74,222,128,0.12)', label: 'RELEASED' },
  waiting:  { color: '#fbbf24', bg: 'rgba(251,191,36,0.12)', label: 'WAITING' },
  failed:   { color: '#ef4444', bg: 'rgba(239,68,68,0.12)', label: 'FAILED' },
};

const STATUS_COLORS: Record<MeshSessionInfo['status'], string> = {
  active: '#4ade80',
  pending: '#fbbf24',
  closed: '#6b7280',
};

const PARTICIPANT_STATUS_COLORS: Record<MeshParticipantInfo['status'], string> = {
  active: '#4ade80',
  idle: '#fbbf24',
  disconnected: '#ef4444',
};

const ROLE_ICON: Record<string, string> = {
  coordinator: '◆',
  participant: '●',
  observer: '○',
};

function getRelativeTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 1000) return 'just now';
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

function formatDate(ts: number): string {
  return new Date(ts).toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
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
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    display: 'inline-block',
  },
  sessionIdRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 12px',
    borderRadius: 8,
    background: 'rgba(255, 255, 255, 0.04)',
    border: '1px solid rgba(255, 255, 255, 0.05)',
  },
  sessionIdLabel: {
    fontSize: 10,
    color: '#64748b',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
  },
  sessionIdValue: {
    fontSize: 16,
    fontWeight: 700,
    color: '#e2e8f0',
    letterSpacing: '0.03em',
    cursor: 'pointer',
  },
  divider: {
    height: 1,
    background: 'rgba(255, 255, 255, 0.06)',
    border: 'none',
    margin: 0,
  },
  infoGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
  },
  infoBox: {
    background: 'rgba(255, 255, 255, 0.04)',
    borderRadius: 8,
    padding: '10px 12px',
    border: '1px solid rgba(255, 255, 255, 0.05)',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  infoLabel: {
    fontSize: 10,
    color: '#64748b',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
  },
  infoValue: {
    fontSize: 14,
    fontWeight: 700,
    color: '#f1f5f9',
  },
  tickValue: {
    fontSize: 22,
    fontWeight: 900,
    color: '#f8fafc',
    letterSpacing: '0.04em',
  },
  barrierBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 10px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: '0.06em',
    alignSelf: 'flex-start',
  },
  participantsHeader: {
    fontSize: 11,
    color: '#94a3b8',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
  },
  participantList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  participantRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 10px',
    borderRadius: 6,
    background: 'rgba(255, 255, 255, 0.03)',
    border: '1px solid rgba(255, 255, 255, 0.04)',
    transition: 'background 0.2s',
  },
  participantAvatar: {
    width: 28,
    height: 28,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 13,
    fontWeight: 700,
    flexShrink: 0,
    background: 'rgba(255, 255, 255, 0.08)',
    color: '#e2e8f0',
  },
  participantInfo: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 1,
    minWidth: 0,
  },
  participantId: {
    fontSize: 12,
    fontWeight: 600,
    color: '#f1f5f9',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  participantRole: {
    fontSize: 10,
    color: '#64748b',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
  },
  participantMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
  },
  participantStatusDot: {
    width: 7,
    height: 7,
    borderRadius: '50%',
  },
  participantLastSeen: {
    fontSize: 10,
    color: '#475569',
    minWidth: 44,
    textAlign: 'right' as const,
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
@keyframes tick-flash {
  0% { color: #22d3ee; text-shadow: 0 0 12px rgba(34,211,238,0.6); }
  100% { color: #f8fafc; text-shadow: none; }
}

.mesh-participant-row:hover {
  background: rgba(255, 255, 255, 0.06) !important;
}

.mesh-session-id-copied {
  animation: fadeInOut 1.5s ease;
}

@keyframes fadeInOut {
  0% { opacity: 0; }
  20% { opacity: 1; }
  80% { opacity: 1; }
  100% { opacity: 0; }
}
`;

const MeshSessionPanel: React.FC<Props> = ({ session }) => {
  const s = session || DEFAULT_SESSION;
  const barrierCfg = BARRIER_COLORS[s.barrierStatus] || { color: '#9ca3af', bg: 'rgba(156,163,175,0.12)', label: s.barrierStatus.toUpperCase() };
  const statusColor = STATUS_COLORS[s.status] || '#9ca3af';
  const [copied, setCopied] = React.useState(false);
  const [flashTick, setFlashTick] = React.useState(false);
  const prevTickRef = React.useRef(s.tickSequence);

  React.useEffect(() => {
    if (s.tickSequence !== prevTickRef.current) {
      setFlashTick(true);
      const timer = setTimeout(() => setFlashTick(false), 600);
      prevTickRef.current = s.tickSequence;
      return () => clearTimeout(timer);
    }
  }, [s.tickSequence]);

  const handleCopySessionId = () => {
    navigator.clipboard?.writeText(s.sessionId).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div style={styles.card}>
      <style>{globalStyles}</style>

      {/* Header */}
      <div style={styles.header}>
        <span style={styles.title}>Mesh Session</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ ...styles.statusDot, backgroundColor: statusColor }} />
          <span style={{ fontSize: 11, color: statusColor, fontWeight: 700, letterSpacing: '0.05em' }}>
            {s.status.toUpperCase()}
          </span>
        </div>
      </div>

      {/* Session ID */}
      <div style={styles.sessionIdRow}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
          <span style={styles.sessionIdLabel}>Session ID</span>
          <span
            style={styles.sessionIdValue}
            onClick={handleCopySessionId}
            title="Click to copy"
          >
            {s.sessionId}
          </span>
        </div>
        {copied && (
          <span style={{ fontSize: 10, color: '#4ade80', fontWeight: 600 }}>Copied!</span>
        )}
      </div>

      <hr style={styles.divider} />

      {/* Info Grid: Tick + Barrier */}
      <div style={styles.infoGrid}>
        <div style={styles.infoBox}>
          <span style={styles.infoLabel}>Tick Sequence</span>
          <span
            style={{
              ...styles.tickValue,
              animation: flashTick ? 'tick-flash 0.6s ease' : 'none',
            }}
          >
            {s.tickSequence.toLocaleString()}
          </span>
        </div>
        <div style={styles.infoBox}>
          <span style={styles.infoLabel}>Barrier</span>
          <span
            style={{
              ...styles.barrierBadge,
              color: barrierCfg.color,
              backgroundColor: barrierCfg.bg,
              border: `1px solid ${barrierCfg.color}30`,
            }}
          >
            <span style={{ ...styles.statusDot, backgroundColor: barrierCfg.color }} />
            {barrierCfg.label}
          </span>
        </div>
      </div>

      <hr style={styles.divider} />

      {/* Participants List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={styles.participantsHeader}>Participants</span>
          <span style={{ fontSize: 10, color: '#475569' }}>{s.participants.length} node(s)</span>
        </div>
        <div style={styles.participantList}>
          {s.participants.map((p) => {
            const statusColor = PARTICIPANT_STATUS_COLORS[p.status];
            const icon = ROLE_ICON[p.role] || '●';
            return (
              <div
                key={p.nodeId}
                className="mesh-participant-row"
                style={styles.participantRow}
                title={`${p.nodeId} (${p.role}) - ${p.status}`}
              >
                <div style={styles.participantAvatar}>{icon}</div>
                <div style={styles.participantInfo}>
                  <span style={styles.participantId}>{p.nodeId}</span>
                  <span style={styles.participantRole}>{p.role}</span>
                </div>
                <div style={styles.participantMeta}>
                  <span
                    style={{
                      ...styles.participantStatusDot,
                      backgroundColor: statusColor,
                      boxShadow: `0 0 6px ${statusColor}60`,
                    }}
                  />
                  <span style={styles.participantLastSeen}>{getRelativeTime(p.lastSeen)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        <span>Created {formatDate(s.createdAt)}</span>
        <span>{s.participants.filter((p) => p.status === 'active').length} active</span>
      </div>
    </div>
  );
};

export default React.memo(MeshSessionPanel);
