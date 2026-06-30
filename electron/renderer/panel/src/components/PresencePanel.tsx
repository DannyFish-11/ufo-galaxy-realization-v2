import { useEffect, useState } from 'react';
import type { Phase } from '@/types/phase';
import type { PanelData } from '@/hooks/usePanelData';
import { getBackendUrl } from '@/lib/api';

interface PresencePanelProps {
  phase: Phase;
  streaming: boolean;
  data: PanelData;
}

const PHASE_LABEL: Record<Phase, string> = {
  silent: '待机',
  liminal: '思考中',
  manifest: '表达中',
};

interface PerceptionStatus {
  camera: boolean;
  screen: boolean;
  audio: boolean;
  model: string;
}

function usePerception(): PerceptionStatus {
  const [p, setP] = useState<PerceptionStatus>({
    camera: false,
    screen: false,
    audio: false,
    model: '',
  });

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const base = await getBackendUrl();
        const resp = await fetch(`${base}/api/perception/desktop/status`);
        if (resp.ok && alive) {
          const d = await resp.json();
          setP({
            camera: Boolean(d?.camera_received ?? d?.camera ?? d?.camera_fresh),
            screen: Boolean(d?.screen_received ?? d?.screen ?? d?.screen_fresh),
            audio: Boolean(d?.audio_received ?? d?.audio ?? d?.audio_fresh),
            model: String(d?.model ?? ''),
          });
        }
      } catch {
        /* 感知未通不影响对话;静默 */
      }
      if (alive) timer = setTimeout(poll, 4000);
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);

  return p;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-row">
      <span className="metric-label">{label}</span>
      <span className="metric-value mono">{value}</span>
    </div>
  );
}

export default function PresencePanel({ phase, streaming, data }: PresencePanelProps) {
  const perc = usePerception();
  const intensity = Math.round((data.presenceIntensity || 0) * 100);
  const coherence = Math.round((data.coherence || 0) * 100);
  const model = data.llmRouting?.lastModelUsed || perc.model || '—';

  return (
    <aside className="presence glass">
      <div className="presence-head">
        <div className={`orb phase-${phase}`} />
        <div className="presence-title">
          <div className="presence-state">{PHASE_LABEL[phase]}</div>
          <div className="presence-sub">{streaming ? '正在实时生成…' : '在场'}</div>
        </div>
      </div>

      <div className="presence-section">
        <div className="section-header">三态 · TRI-STATE</div>
        <div className="tri-dots">
          {(['silent', 'liminal', 'manifest'] as Phase[]).map((p) => (
            <div key={p} className="tri-dot-wrap">
              <span
                className={`tri-dot phase-${p} ${phase === p ? 'active' : ''}`}
              />
              <span className="tri-dot-label">{PHASE_LABEL[p]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="presence-section">
        <div className="section-header">在场 · PRESENCE</div>
        <div className="bar-row">
          <span className="bar-label">强度</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${intensity}%` }} />
          </div>
          <span className="bar-num mono">{intensity}</span>
        </div>
        <div className="bar-row">
          <span className="bar-label">连贯</span>
          <div className="bar-track">
            <div
              className="bar-fill coherence"
              style={{ width: `${coherence}%` }}
            />
          </div>
          <span className="bar-num mono">{coherence}</span>
        </div>
      </div>

      <div className="presence-section">
        <div className="section-header">主脑 · BRAIN</div>
        <Metric label="模型" value={model} />
        <Metric
          label="运行"
          value={data.openclawdStatus?.runtimeState || '—'}
        />
        <Metric
          label="任务"
          value={`${data.openclawdStatus?.activeTasks ?? 0} 活跃`}
        />
      </div>

      <div className="presence-section">
        <div className="section-header">感知 · SENSES</div>
        <div className="senses-row">
          <span className={`sense-pill ${perc.screen ? 'on' : ''}`}>屏幕</span>
          <span className={`sense-pill ${perc.camera ? 'on' : ''}`}>摄像头</span>
          <span className={`sense-pill ${perc.audio ? 'on' : ''}`}>麦克风</span>
        </div>
      </div>
    </aside>
  );
}
