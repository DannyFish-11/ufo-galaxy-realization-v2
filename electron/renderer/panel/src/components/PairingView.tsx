import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchWithTimeout, getBackendUrl } from '@/lib/api';
import './PairingView.css';

/**
 * PairingView — 「出示名片 / 谁进来了 / 哪条路通」三件事放一屏。
 *
 * 为什么这三件事必须在一起
 * ========================
 * 它们是同一个问题的三段：**让一台设备接进来**。
 *
 * 分开放的话，人要在三个地方来回切：在这里拿码、去另一处看它进来没有、
 * 再去第三处看为什么连不上。而这三件事发生在同一分钟里。
 *
 * 没有二维码是刻意的
 * ==================
 * 手机端和手表端目前都**没有扫码实现** —— 现在两边都是输 6 位短码。
 * 先把二维码画出来的话，那就是一个零消费方的能力：看着完整、按下去没有任何
 * 东西在另一头接。等设备侧真的接了扫码再补。
 */

type PathRow = {
  kind: string;
  up: boolean;
  url: string;
  reason: string;
  how_to_fix: string;
};

type Peer = {
  device_id: string;
  name?: string;
  trust?: string;
  capabilities?: string[];
  last_seen?: number;
};

type CardState = {
  code: string;
  link: string;
  expiresAt: number; // epoch seconds
} | null;

const KIND_LABEL: Record<string, string> = {
  lan: '局域网',
  tailscale: 'Tailscale',
  funnel: '公网（Funnel）',
};

const REASON_LABEL: Record<string, string> = {
  auth_disabled: '鉴权被关掉了 —— 不能把网关暴露到公网',
  no_token: '鉴权开着但一个可用令牌都没有',
  tailscale_unavailable: '本机没有可用的 Tailscale',
  unavailable: '不可用',
};

export default function PairingView() {
  const [card, setCard] = useState<CardState>(null);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const [paths, setPaths] = useState<PathRow[] | null>(null);
  const [peers, setPeers] = useState<Peer[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const baseRef = useRef<string | null>(null);

  const base = useCallback(async () => {
    if (!baseRef.current) baseRef.current = await getBackendUrl();
    return baseRef.current;
  }, []);

  // 倒计时只驱动显示，不驱动请求 —— 每秒打一次接口会把短码注册表冲垮。
  useEffect(() => {
    const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(t);
  }, []);

  const showCard = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetchWithTimeout(`${await base()}/api/v1/pair/card`, {}, 10000);
      const j = await r.json();
      if (!j.success) throw new Error(j.error || '取名片失败');
      setCard({ code: j.code, link: j.link, expiresAt: Math.floor(j.code_expires_at) });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [base]);

  const loadPaths = useCallback(async () => {
    try {
      const r = await fetchWithTimeout(`${await base()}/api/v1/pair/paths`, {}, 20000);
      const j = await r.json();
      if (j.success) setPaths(j.paths as PathRow[]);
    } catch {
      // 路径查询要跑一次 tailscale 子进程，慢或失败都不该让整屏空白。
      setPaths(null);
    }
  }, [base]);

  const loadPeers = useCallback(async () => {
    try {
      const r = await fetchWithTimeout(`${await base()}/api/v1/pair/peers`, {}, 10000);
      const j = await r.json();
      if (j.success) setPeers(j.peers as Peer[]);
    } catch {
      setPeers(null);
    }
  }, [base]);

  useEffect(() => {
    void loadPaths();
    void loadPeers();
    // 对端列表跟着配对动作变，10 秒一次够用；路径状态贵，只在进屏和手动刷新时查。
    const t = setInterval(() => void loadPeers(), 10000);
    return () => clearInterval(t);
  }, [loadPaths, loadPeers]);

  const remain = card ? card.expiresAt - now : 0;
  const expired = card !== null && remain <= 0;

  return (
    <div className="pairing-view">
      {/* ── 出示名片 ───────────────────────────────────────────── */}
      <section className="pv-card">
        <h3>让一台设备接进来</h3>
        <p className="pv-hint">
          点「出示名片」拿一个 6 位短码，在手机或手表上输进去。短码一次性、10 分钟过期。
        </p>

        {!card && (
          <button className="pv-primary" onClick={showCard} disabled={busy}>
            {busy ? '生成中…' : '出示名片'}
          </button>
        )}

        {card && (
          <div className={`pv-code-box${expired ? ' pv-expired' : ''}`}>
            <div className="pv-code">{card.code.split('').join(' ')}</div>
            <div className="pv-ttl">
              {expired ? (
                <span className="pv-warn">已过期 —— 再出示一次</span>
              ) : (
                <>
                  剩余 {Math.floor(remain / 60)}:{String(remain % 60).padStart(2, '0')}
                </>
              )}
            </div>
            <div className="pv-actions">
              <button onClick={showCard} disabled={busy}>
                换一个
              </button>
              <button
                onClick={() => void navigator.clipboard?.writeText(card.link)}
                title={card.link}
              >
                复制链接
              </button>
            </div>
          </div>
        )}

        {error && <div className="pv-error">{error}</div>}
      </section>

      {/* ── 路径状态盘 ─────────────────────────────────────────── */}
      <section className="pv-paths">
        <h3>
          这台机器怎么被连上
          <button className="pv-mini" onClick={() => void loadPaths()}>
            重新检测
          </button>
        </h3>
        {paths === null ? (
          <div className="pv-muted">检测中…（Funnel 那条要跑一次 tailscale，稍慢）</div>
        ) : (
          <ul className="pv-path-list">
            {paths.map((p) => (
              <li key={p.kind} className={p.up ? 'up' : 'down'}>
                <span className="pv-dot" />
                <span className="pv-kind">{KIND_LABEL[p.kind] ?? p.kind}</span>
                {p.up ? (
                  <code className="pv-url">{p.url}</code>
                ) : (
                  <span className="pv-why">
                    {REASON_LABEL[p.reason] ?? p.reason}
                    {p.how_to_fix && <em className="pv-fix">{p.how_to_fix}</em>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {paths !== null && (
          <p className="pv-verdict">
            {paths.find((p) => p.kind === 'funnel')?.up
              ? '手表带流量单独出门也连得上。'
              : '出门只能靠局域网或 tailnet —— 手表带流量单独用会连不上。'}
          </p>
        )}
      </section>

      {/* ── 已接进来的设备 ─────────────────────────────────────── */}
      <section className="pv-peers">
        <h3>已接进来的设备</h3>
        {peers === null ? (
          <div className="pv-muted">读取中…</div>
        ) : peers.length === 0 ? (
          <div className="pv-muted">还没有设备接进来。</div>
        ) : (
          <ul className="pv-peer-list">
            {peers.map((p) => (
              <li key={p.device_id}>
                <span className="pv-peer-name">{p.name || p.device_id}</span>
                <span className={`pv-trust pv-trust-${p.trust ?? 'unknown'}`}>{p.trust ?? 'unknown'}</span>
                <code className="pv-peer-id">{p.device_id}</code>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
