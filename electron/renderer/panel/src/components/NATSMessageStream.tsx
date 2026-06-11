import React from 'react';

export interface NATSMessage {
  id: string;
  timestamp: number;
  topic: string;
  direction: 'in' | 'out';
  payload: string;
  msgType: 'mesh_join' | 'mesh_leave' | 'mesh_result' | 'mesh_topology' | 'coord_sync' | 'human_input' | 'heartbeat' | 'error' | 'other';
}

interface Props {
  messages: NATSMessage[];
  maxMessages?: number;
}

const DEFAULT_MESSAGES: NATSMessage[] = [
  { id: '1', timestamp: Date.now() - 30000, topic: 'mesh.join', direction: 'in', payload: '{device_id: "android_01", role: "participant"}', msgType: 'mesh_join' },
  { id: '2', timestamp: Date.now() - 25000, topic: 'coord.sync', direction: 'in', payload: '{tick: 12847, barrier: "released"}', msgType: 'coord_sync' },
  { id: '3', timestamp: Date.now() - 20000, topic: 'mesh.topology', direction: 'in', payload: '{peers: 3, status: "stable"}', msgType: 'mesh_topology' },
  { id: '4', timestamp: Date.now() - 15000, topic: 'human_input', direction: 'in', payload: '{device_id: "wear_01", text: "确认执行"}', msgType: 'human_input' },
  { id: '5', timestamp: Date.now() - 10000, topic: 'mesh.result', direction: 'out', payload: '{task_id: "task_01", status: "completed"}', msgType: 'mesh_result' },
  { id: '6', timestamp: Date.now() - 5000, topic: 'heartbeat', direction: 'in', payload: '{device_id: "android_01", latency_ms: 23}', msgType: 'heartbeat' },
];

const MSG_TYPE_COLORS: Record<NATSMessage['msgType'], string> = {
  mesh_join: '#4ade80',
  mesh_leave: '#f87171',
  mesh_result: '#c084fc',
  mesh_topology: '#22d3ee',
  coord_sync: '#60a5fa',
  human_input: '#fbbf24',
  heartbeat: '#9ca3af',
  error: '#ef4444',
  other: '#d1d5db',
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toTimeString().slice(0, 8);
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: '#0d1117',
    borderRadius: 8,
    border: '1px solid #30363d',
    padding: 12,
    fontFamily: '"SF Mono", "Fira Code", "Cascadia Code", "Consolas", monospace',
    fontSize: 12,
    color: '#c9d1d9',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
    paddingBottom: 8,
    borderBottom: '1px solid #21262d',
    flexShrink: 0,
  },
  headerTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: '#e6edf3',
    letterSpacing: '0.05em',
  },
  headerBadge: {
    fontSize: 10,
    padding: '2px 6px',
    borderRadius: 4,
    backgroundColor: '#21262d',
    color: '#8b949e',
  },
  messageList: {
    flex: 1,
    overflowY: 'auto',
    overflowX: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  messageRow: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
    padding: '3px 6px',
    borderRadius: 4,
    animation: 'slideInUp 0.3s ease-out',
    lineHeight: 1.5,
    wordBreak: 'break-all' as const,
  },
  timestamp: {
    color: '#484f58',
    flexShrink: 0,
    minWidth: 58,
  },
  direction: {
    flexShrink: 0,
    fontWeight: 700,
    minWidth: 14,
    textAlign: 'center' as const,
  },
  topic: {
    flexShrink: 0,
    minWidth: 90,
    fontWeight: 600,
  },
  separator: {
    color: '#30363d',
    flexShrink: 0,
  },
  payload: {
    color: '#8b949e',
    opacity: 0.85,
  },
  emptyState: {
    color: '#484f58',
    textAlign: 'center' as const,
    padding: 24,
    fontStyle: 'italic',
  },
};

const globalStyles = `
@keyframes slideInUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.nats-message-row:hover {
  background-color: #161b22;
}

.nats-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.nats-scrollbar::-webkit-scrollbar-track {
  background: #0d1117;
}
.nats-scrollbar::-webkit-scrollbar-thumb {
  background: #30363d;
  border-radius: 3px;
}
.nats-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #484f58;
}
`;

const NATSMessageStream: React.FC<Props> = ({ messages, maxMessages = 50 }) => {
  const displayMessages = messages.length > 0 ? messages : DEFAULT_MESSAGES;
  const trimmedMessages = displayMessages.slice(-maxMessages);
  const listRef = React.useRef<HTMLDivElement>(null);
  const prevLenRef = React.useRef(trimmedMessages.length);

  React.useEffect(() => {
    if (listRef.current && trimmedMessages.length > prevLenRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
    prevLenRef.current = trimmedMessages.length;
  }, [trimmedMessages.length]);

  React.useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, []);

  return (
    <div style={styles.container}>
      <style>{globalStyles}</style>
      <div style={styles.header}>
        <span style={styles.headerTitle}>NATS / MESH STREAM</span>
        <span style={styles.headerBadge}>
          {trimmedMessages.length}/{maxMessages}
        </span>
      </div>
      <div ref={listRef} style={styles.messageList} className="nats-scrollbar">
        {trimmedMessages.length === 0 ? (
          <div style={styles.emptyState}>Waiting for messages...</div>
        ) : (
          trimmedMessages.map((msg) => {
            const color = MSG_TYPE_COLORS[msg.msgType] || MSG_TYPE_COLORS.other;
            const dirChar = msg.direction === 'in' ? '<' : '>';
            const dirColor = msg.direction === 'in' ? '#4ade80' : '#f87171';
            return (
              <div
                key={msg.id}
                className="nats-message-row"
                style={{
                  ...styles.messageRow,
                }}
                title={`${msg.msgType} | ${msg.topic}`}
              >
                <span style={styles.timestamp}>{formatTime(msg.timestamp)}</span>
                <span style={{ ...styles.direction, color: dirColor }}>{dirChar}</span>
                <span style={{ ...styles.topic, color }}>{msg.topic}</span>
                <span style={styles.separator}>|</span>
                <span style={styles.payload}>{msg.payload}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default React.memo(NATSMessageStream);
