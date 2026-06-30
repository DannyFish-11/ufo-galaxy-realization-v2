import type { PanelData } from '@/hooks/usePanelData';

const MCP_TONE: Record<string, string> = {
  online: 'success',
  offline: 'danger',
  error: 'danger',
  unknown: 'warning',
};
const SKILL_TONE: Record<string, string> = {
  loaded: 'success',
  unloaded: 'warning',
  disabled: 'warning',
  error: 'danger',
};

export default function CapabilitiesView({ data }: { data: PanelData }) {
  const { mcpServers, skills, llmRouting } = data;

  return (
    <div className="view-scroll">
      <div className="view-inner">
        <h1 className="view-title">能力 · 工具与技能</h1>
        <p className="view-sub">MCP 服务、已装技能与模型路由。</p>

        <div className="section-header">模型路由</div>
        <div className="chip-row">
          <span className="chip accent">{llmRouting.lastModelUsed || '—'}</span>
          {llmRouting.activeProviders.map((p) => (
            <span key={p} className="chip">{p}</span>
          ))}
        </div>

        <div className="section-header">MCP 服务 ({mcpServers.length})</div>
        <div className="card-list">
          {mcpServers.length === 0
            ? <div className="empty-hint">未检测到 MCP 服务 · 配置后自动显示</div>
            : mcpServers.map((s) => (
            <div key={s.name} className="row-card">
              <span className={`dot tone-${MCP_TONE[s.status] || 'info'}`} />
              <div className="row-main">
                <div className="row-title">{s.name}</div>
                <div className="row-meta mono">{s.url}</div>
              </div>
              <div className="row-right mono">{s.toolsCount} 工具</div>
            </div>
          ))}
        </div>

        <div className="section-header">技能 ({skills.length})</div>
        <div className="card-list">
          {skills.length === 0
            ? <div className="empty-hint">暂无已加载技能</div>
            : skills.map((s) => (
            <div key={s.name} className="row-card">
              <span className={`dot tone-${SKILL_TONE[s.status] || 'info'}`} />
              <div className="row-main">
                <div className="row-title">
                  {s.name} <span className="row-ver mono">v{s.version}</span>
                </div>
                <div className="row-meta">{s.description}</div>
              </div>
              <div className="row-right mono">{s.status}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
