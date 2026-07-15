import { Fragment } from 'react';
import type { PanelData } from '@/hooks/usePanelData';

interface DiagnosticsDrawerProps {
  open: boolean;
  onClose: () => void;
  data: PanelData;
}

export default function DiagnosticsDrawer({ open, onClose, data }: DiagnosticsDrawerProps) {
  return (
    <>
      <div
        className={`drawer-scrim ${open ? 'open' : ''}`}
        onClick={onClose}
        aria-hidden={!open}
      />
      <aside className={`drawer glass-strong ${open ? 'open' : ''}`} aria-hidden={!open}>
        <div className="drawer-head">
          <span className="drawer-title">诊断 · DIAGNOSTICS</span>
          <button className="drawer-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>

        <div className="drawer-scroll">
          {data.diagnostics && data.diagnostics.length > 0 && (
            <>
              <div className="section-header" style={{ color: '#ffb454' }}>
                ⚠ 诊断告警 · 缺协议头 URL
              </div>
              <div className="nats-list">
                {data.diagnostics.map((d, i) => (
                  <div
                    key={i}
                    className="nats-row"
                    style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}
                  >
                    <span className="nats-topic mono" style={{ color: '#ffb454' }}>
                      [{d.ts}] {d.url}
                    </span>
                    {d.culprit && (
                      <span className="nats-payload mono" style={{ opacity: 0.7 }}>
                        ↳ {d.culprit}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {data.startupTiming && data.startupTiming.length > 0 && (
            <>
              <div className="section-header">⏱ 启动耗时 · 各阶段</div>
              <div className="kv mono">
                {data.startupTiming.map((t, i) => (
                  <Fragment key={i}>
                    <span style={t.seconds >= 3 ? { color: '#ffb454' } : undefined}>{t.name}</span>
                    <span style={t.seconds >= 3 ? { color: '#ffb454' } : undefined}>
                      {t.seconds.toFixed(2)}s
                    </span>
                  </Fragment>
                ))}
              </div>
            </>
          )}

          <div className="section-header">NATS 消息流</div>
          <div className="nats-list">
            {data.natsMessages.map((m) => (
              <div key={m.id} className="nats-row">
                <span className={`nats-dir ${m.direction}`}>
                  {m.direction === 'in' ? '◀' : '▶'}
                </span>
                <span className="nats-topic mono">{m.topic}</span>
                <span className="nats-payload mono">{m.payload}</span>
              </div>
            ))}
          </div>

          <div className="section-header">运行时</div>
          <div className="kv mono">
            <span>coherence</span><span>{data.coherence.toFixed(2)}</span>
            {/* 真 bug 修复:collapseTendency(collapse_tendency)后端从未产出过
                (核对 core/routes/panel.py::build_panel_feed 与
                core/lumiv_websocket_bridge.py 全文,均无此字段的真实来源)——
                永远显示 0.00,紧挨着真正实时的 coherence 却让人误以为也是活的
                指标。已确认没有任何生产者,直接去掉这行死数字,而不是继续假装
                有数据。*/}
            <span>uptime</span><span>{data.openclawdStatus.uptime}s</span>
            <span>completed</span><span>{data.openclawdStatus.completedTasks}</span>
            <span>tick</span><span>{data.meshSession.tickSequence}</span>
            <span>barrier</span><span>{data.meshSession.barrierStatus}</span>
          </div>

          <div className="section-header">成本</div>
          <div className="kv mono">
            <span>usd</span><span>${data.costSummary.totalUsd.toFixed(4)}</span>
            <span>in</span><span>{data.costSummary.tokensInput}</span>
            <span>out</span><span>{data.costSummary.tokensOutput}</span>
          </div>
        </div>
      </aside>
    </>
  );
}
