import { useState } from 'react';
import { getBackendUrl } from '@/lib/api';
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
  const { topologyNodes, meshSession, nodeTopology, smartDeviceList, natsWorker } = data;

  // NATS worker 开关:调用后端真实启停;结果以 panel feed 回推的
  // running 为准(乐观态仅在等待期间显示)。
  const [workerBusy, setWorkerBusy] = useState(false);
  const [workerError, setWorkerError] = useState('');
  const toggleWorker = async () => {
    if (workerBusy) return;
    setWorkerBusy(true);
    setWorkerError('');
    try {
      const base = await getBackendUrl();
      const res = await fetch(`${base}/api/v1/mesh/worker/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable: !natsWorker.running }),
      });
      const out = await res.json();
      if (!natsWorker.running && !out.running) {
        // 启动请求但没启起来:如实显示后端原因(如 nats_unavailable)
        setWorkerError(out.reason || '启动失败');
      }
    } catch (e) {
      setWorkerError(String(e));
    } finally {
      setWorkerBusy(false);
    }
  };

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

        <div className="section-header">智能设备</div>
        <div className="card-list">
          {smartDeviceList.length === 0
            ? <div className="empty-hint">暂无智能设备 · 配置 Home Assistant 或局域网 mDNS 发现后自动出现</div>
            : smartDeviceList.map((d) => (
            <div key={d.deviceId} className="row-card">
              <span className={`dot tone-${d.online ? 'success' : 'danger'}`} />
              <div className="row-main">
                <div className="row-title">{d.name}</div>
                <div className="row-meta mono">{d.domain || d.protocol} · {d.deviceId}</div>
              </div>
              <div className="row-right mono">{d.state || (d.online ? 'online' : 'offline')}</div>
            </div>
          ))}
        </div>

        <div className="section-header">NATS Worker</div>
        <div className="card-list">
          <div className="row-card">
            <span className={`dot tone-${natsWorker.running ? 'success' : 'danger'}`} />
            <div className="row-main">
              <div className="row-title">任务执行 Worker</div>
              <div className="row-meta mono">
                {natsWorker.running
                  ? `运行中 · ${natsWorker.workerId}`
                  : natsWorker.enabledByEnv
                    ? '未运行 · 多设备总开关已开'
                    : '未运行 · 单机模式'}
                {workerError ? ` · ${workerError}` : ''}
              </div>
            </div>
            <button
              role="switch"
              aria-checked={natsWorker.running}
              aria-label={natsWorker.running ? '停止任务执行 Worker' : '启动任务执行 Worker'}
              className={`switch${natsWorker.running ? ' on' : ''}${workerBusy ? ' busy' : ''}`}
              onClick={toggleWorker}
              disabled={workerBusy}
            >
              <span className="switch-knob" />
            </button>
          </div>
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
