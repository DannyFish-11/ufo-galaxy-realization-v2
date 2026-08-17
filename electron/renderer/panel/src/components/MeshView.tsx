import { useState } from 'react';
import { apiUrl, getBackendUrl } from '@/lib/api';
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

  // NATS worker 开关:调用后端真实启停;最终的 running 以 panel feed
  // 回推为准。后端 toggle 端点现在立即返回(真正的 NATS 连接/嵌入式
  // 服务器拉起在后台跑,不再同步阻塞这次请求——之前这里能卡到一分
  // 多钟,却只有一个淡淡的 opacity 变化,跟卡死没区别)。workerBusy
  // 只覆盖"这次点击的 fetch 还没返回"这一瞬(通常几十毫秒);真正
  // "仍在后台连接中"的状态由 natsWorker.starting(WS 推送、跨会话/
  // 跨窗口一致)驱动,两者取或作为按钮的 pending 视觉态。
  const [workerBusy, setWorkerBusy] = useState(false);
  const [workerError, setWorkerError] = useState('');
  const pending = workerBusy || natsWorker.starting;
  const toggleWorker = async () => {
    if (pending) return;
    setWorkerBusy(true);
    setWorkerError('');
    try {
      const base = await getBackendUrl();
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      let out: any;
      try {
        const res = await fetch(apiUrl(base, '/api/v1/mesh/worker/toggle'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enable: !natsWorker.running }),
          signal: controller.signal,
        });
        out = await res.json();
      } finally {
        clearTimeout(timeoutId);
      }
      // 立即响应现在只代表"已发起"(starting=True)或"已在运行/已停止",不代表
      // 后台连接的最终结果——那个结果由 natsWorker.lastError(下面渲染)反映。
      if (!natsWorker.running && out.started === false && !out.starting && out.reason) {
        setWorkerError(out.reason);
      }
    } catch (e) {
      const msg = e instanceof DOMException && e.name === 'AbortError'
        ? '请求超时(后台仍可能在启动,可稍后查看状态)'
        : String(e);
      setWorkerError(msg);
    } finally {
      setWorkerBusy(false);
    }
  };
  // 优先展示 feed 推送的失败原因(后台连接真正跑完后才知道的结果);
  // 本地 workerError 只覆盖"这次点击的请求本身就失败"的即时反馈。
  const displayedError = (!natsWorker.running && natsWorker.lastError) || workerError;

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
            <span className={`dot tone-${natsWorker.running ? 'success' : natsWorker.starting ? 'warning' : 'danger'}`} />
            <div className="row-main">
              <div className="row-title">任务执行 Worker</div>
              <div className="row-meta mono">
                {natsWorker.starting
                  ? '启动中…（连接 NATS，可能需要几秒到十几秒）'
                  : natsWorker.running
                    ? `运行中 · ${natsWorker.workerId}`
                    : natsWorker.enabledByEnv
                      ? '未运行 · 多设备总开关已开'
                      : '未运行 · 单机模式'}
                {displayedError ? ` · ${displayedError}` : ''}
              </div>
            </div>
            <button
              role="switch"
              aria-checked={natsWorker.running}
              aria-busy={pending}
              aria-label={natsWorker.running ? '停止任务执行 Worker' : '启动任务执行 Worker'}
              className={`switch${natsWorker.running ? ' on' : ''}${pending ? ' busy' : ''}`}
              onClick={toggleWorker}
              disabled={pending}
            >
              <span className="switch-knob">{pending ? <span className="switch-spinner" /> : null}</span>
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
                <div className="row-meta mono">{(p.roles && p.roles.length ? p.roles : [p.role]).join(' · ')}</div>
              </div>
              <div className="row-right mono">{p.status}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
