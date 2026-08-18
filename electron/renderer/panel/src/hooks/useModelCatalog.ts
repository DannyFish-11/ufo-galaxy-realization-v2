import { useCallback, useEffect, useRef, useState } from 'react';
import { apiUrl, getBackendUrl } from '@/lib/api';

/**
 * useModelCatalog — 档位模型目录 + 实时状态（去硬编码，单一真相源）
 *
 * 目录(tiers/models/能力)从后端 /api/v1/models/catalog 一次性取（派生自
 * core.model_catalog，前端不再硬编码 LOCAL_BRAINS）。安装/拉取状态从
 * /api/v1/models/status 在【后台静默轮询】，只更新状态徽标、不重取整份目录、
 * 不闪整页——满足"后台刷新但不影响前端视觉"。
 */

export interface ModelCaps {
  vision: boolean;
  audio_in: boolean;
  audio_out: boolean;
  tools: boolean;
}
export interface CatalogModel {
  tag: string;
  name: string;
  desc: string;
  source: string;        // local | container | cloud
  requires_gpu: boolean;
  size_mb: number;
  caps: ModelCaps;
}
export interface EffectiveIO {
  vision: string;        // native | none
  audio_in: string;      // native | asr_bridge
  audio_out: string;     // native | tts_bridge
  tools: boolean;
}
export interface CatalogTier {
  key: string;           // A | B | C
  label: string;
  desc: string;
  kind: string;          // single | composite
  models: CatalogModel[];
  effective_io: EffectiveIO;
}
export interface Catalog {
  current_tier: string;
  current_main_brain: string;
  tiers: CatalogTier[];
  /** 硬件适配诚实评估(后端 /catalog 附带;探测失败时 has_gpu 为 null) */
  hardware?: { has_gpu: boolean | null; can_run_local_multimodal?: boolean; max_model_size_mb?: number };
  /** 逐模型 GPU 适配:ok | no_gpu(需显卡但没有) | insufficient_vram(装不下) */
  gpu_fit?: Record<string, 'ok' | 'no_gpu' | 'insufficient_vram'>;
}
// 真 bug 修复(类型契约缺口):后端 core/routes/models.py::_catalog_placeholder()
// (探测超时/首次加载兜底)会产出 status:"unknown",但这里此前只声明了三个值——
// 当前因为 placeholder 条目总是同时带 ollama_reachable:false、被 StatusBadge
// 先挡住而没有可见问题,但类型本身是假的,一旦未来某个路径在 ollama_reachable
// 为 true 时也给出 "unknown",会被无声地当成 'absent'/'未安装' 误判。
export type ModelStatus = 'installed' | 'absent' | 'broken' | 'unknown';
export interface StatusEntry {
  status: ModelStatus;
  ollama_reachable: boolean;
  matched: string;
}

const STATUS_POLL_MS = 4000;

async function fetchCatalog(): Promise<Catalog> {
  const base = await getBackendUrl();
  const r = await fetch(apiUrl(base, '/api/v1/models/catalog'));
  if (!r.ok) throw new Error(`catalog ${r.status}`);
  return r.json();
}

async function fetchStatus(): Promise<Record<string, StatusEntry>> {
  const base = await getBackendUrl();
  const r = await fetch(apiUrl(base, '/api/v1/models/status'));
  if (!r.ok) throw new Error(`status ${r.status}`);
  const j = await r.json();
  return j.models ?? {};
}

export function useModelCatalog() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [status, setStatus] = useState<Record<string, StatusEntry>>({});
  const [error, setError] = useState<string | null>(null);
  const catalogRetry = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 目录：一次性取（失败则退避重试，界面照常渲染，不整页阻塞）。
  const loadCatalog = useCallback(async () => {
    try {
      const c = await fetchCatalog();
      // 成功即取消任何在途的失败重试计时器——否则用户点"重试"恢复后，之前排的
      // 4s 重试仍会再触发一次，后端偶发抖动就把已加载好的界面又翻回"目录暂不可达"。
      if (catalogRetry.current) { clearTimeout(catalogRetry.current); catalogRetry.current = null; }
      setCatalog(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '目录加载失败');
      if (catalogRetry.current) clearTimeout(catalogRetry.current);
      catalogRetry.current = setTimeout(() => { loadCatalog(); }, 4000);
    }
  }, []);

  // 状态：后台静默轮询，只更新徽标。
  const loadStatus = useCallback(async () => {
    try {
      setStatus(await fetchStatus());
    } catch {
      /* 静默：Ollama 未起等，下一轮再试，不打扰视觉 */
    }
  }, []);

  useEffect(() => {
    loadCatalog();
    loadStatus();
    const t = setInterval(loadStatus, STATUS_POLL_MS);
    return () => {
      clearInterval(t);
      if (catalogRetry.current) clearTimeout(catalogRetry.current);
    };
  }, [loadCatalog, loadStatus]);

  // 选档：POST /tier → 立刻本地乐观更新 current_tier + 立即刷一次状态。
  const selectTier = useCallback(async (tier: string, mainBrain?: string) => {
    const base = await getBackendUrl();
    const r = await fetch(apiUrl(base, '/api/v1/models/tier'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier, main_brain: mainBrain ?? null }),
    });
    const body = await r.json().catch(() => ({ success: false }));
    if (body.success) {
      setCatalog((prev) => prev ? {
        ...prev, current_tier: body.tier, current_main_brain: body.main_brain,
      } : prev);
      // 触发了后台拉取 → 尽快刷一次状态看到"拉取中/已装"。
      setTimeout(loadStatus, 800);
    }
    return body as { success: boolean; tier?: string; main_brain?: string; pulling?: string[]; error?: string };
  }, [loadStatus]);

  return { catalog, status, error, reloadCatalog: loadCatalog, selectTier };
}
