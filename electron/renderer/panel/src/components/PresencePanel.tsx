import { useEffect, useRef, useState } from 'react';
import type { Phase } from '@/types/phase';
import { PHASE_ZH } from '@/types/phase';
import type { PanelData } from '@/hooks/usePanelData';
import type { ConversationTurn } from '@/hooks/useConversation';
import { getBackendUrl } from '@/lib/api';

interface PresencePanelProps {
  phase: Phase;
  streaming: boolean;
  data: PanelData;
  turns?: ConversationTurn[];
  speaking?: boolean;
}

interface PerceptionStatus {
  camera: boolean;
  screen: boolean;
  audio: boolean;
}

function usePerception(): PerceptionStatus {
  const [p, setP] = useState<PerceptionStatus>({
    camera: false,
    screen: false,
    audio: false,
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
          // 修复:后端 /api/perception/desktop/status 返回 {success, store: {...}}——
          // 字段全部嵌在 store 下,之前直接读 d.camera_received 等顶层键,永远是
          // undefined,导致"感知·SENSES"三个药丸无论摄像头/屏幕/麦克风是否真的在
          // 工作,永远显示未激活。
          const s = d?.store ?? {};
          setP({
            camera: Boolean(s.camera_received ?? s.camera_fresh),
            screen: Boolean(s.screen_received ?? s.screen_fresh),
            audio: Boolean(s.audio_received ?? s.audio_fresh),
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

export default function PresencePanel({ phase, streaming, data, turns = [], speaking = false }: PresencePanelProps) {
  const perc = usePerception();
  const intensity = Math.round((data.presenceIntensity || 0) * 100);
  const coherence = Math.round((data.coherence || 0) * 100);
  const model = data.llmRouting?.lastModelUsed || '—';

  // 实时上下文自动滚到底
  const ctxRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (ctxRef.current) ctxRef.current.scrollTop = ctxRef.current.scrollHeight;
  }, [turns]);

  return (
    <aside className="presence glass">
      <div className="presence-head">
        <div className={`orb phase-${phase}`} />
        <div className="presence-title">
          <div className="presence-state">{PHASE_ZH[phase]}</div>
          <div className="presence-sub">
            {speaking ? '正在朗读…' : streaming ? '正在实时生成…' : '在场'}
          </div>
        </div>
      </div>

      {/* 实时上下文：语音/打字对话内容实时同步（与在场共用 WS 通道） */}
      <div className="presence-section">
        <div className="section-header">实时上下文 · CONTEXT</div>
        <div className="ctx-stream" ref={ctxRef}>
          {turns.length === 0 ? (
            <div className="ctx-empty">对话开始后，这里实时显示听到的与 AI 的回应</div>
          ) : (
            turns.map((t) => (
              <div key={t.id} className={`ctx-turn ctx-${t.role}`}>
                <span className="ctx-who">{t.role === 'ai' ? 'AI' : '你'}</span>
                {t.source === 'voice' && <span className="ctx-src">语音</span>}
                <span className="ctx-text">{t.text}</span>
              </div>
            ))
          )}
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
