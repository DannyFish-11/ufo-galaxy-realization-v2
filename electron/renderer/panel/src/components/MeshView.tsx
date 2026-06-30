import type { PanelData } from '@/hooks/usePanelData';

const STATUS_TONE: Record<string, string> = {
  online: 'success',
  active: 'success',
  degraded: 'warning',
  idle: 'warning',
  pending: 'warning',
  offline: 'danger',
  disconnected: 'danger',
  closed: 'danger',
};

export default function MeshView({ data }: { data: PanelData }) {
  const { topologyNodes, meshSession, nodeTopology } = data;

  return (
    <div className="view-scroll">
      <div className="view-inner">
        <h1 className="view-title">维态 · 设备网格</h1>
        <p className="view-sub">跨设备拓扑、Mesh 会话与节点健康。</p>

        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-num">{nodeTopology.totalNodes}</div>
            <div className="stat-cap">节点总数</div>
          </div>
          <div className="stat-card">
            <div className="stat-num tone-success">{nodeTopology.healthyNodes}</div>
            <div className="stat-cap">健康</div>
          </div>
          <div className="stat-card">
            <div className="stat-num tone-warning">{nodeTopology.degradedNodes}</div>
            <div className="stat-cap">降级</div>
          </div>
          <div className="stat-card">
            <div className="stat-num">{meshSession.participants.length}</div>
            <div className="stat-cap">会话成员</div>
          </div>
        </div>

        <div className="section-header">连接的设备</div>
        <div className="card-list">
          {topologyNodes.length === 0
            ? <div className="empty-hint">暂无连接设备 · 手机/手表接入后自动出现</div>
            : topologyNodes.map((n) => (
            <div key={n.id} className="row-card">
              <span className={`dot tone-${STATUS_TONE[n.status] || 'info'}`} />
              <div className="row-main">
                <div className="row-title">{n.label}</div>
                <div className="row-meta mono">{n.role} · {n.id}</div>
              </div>
              <div className="row-right mono">{n.messageCount.toLocaleString()} msg</div>
            </div>
          ))}
        </div>

        <div className="section-header">Mesh 会话</div>
        <div className="card-list">
          {meshSession.participants.length === 0
            ? <div className="empty-hint">
                {meshSession.status === 'closed' ? 'Mesh 未启用（单机模式）' : '等待设备加入…'}
              </div>
            : meshSession.participants.map((p) => (
            <div key={p.nodeId} className="row-card">
              <span className={`dot tone-${STATUS_TONE[p.status] || 'info'}`} />
              <div className="row-main">
                <div className="row-title">{p.nodeId}</div>
                <div className="row-meta mono">{p.role}</div>
              </div>
              <div className="row-right mono">{p.status}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
