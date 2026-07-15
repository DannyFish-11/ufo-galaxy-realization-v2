import { useCallback, useEffect, useRef, useState } from 'react';
import type { Phase, PhaseLabel, WebSocketMessage } from '@/types/phase';
import { PHASE_CONFIG } from '@/types/phase';

interface UsePhaseReturn {
  phase: Phase;
  label: PhaseLabel;
  setPhase: (p: Phase) => void;
  handleMessage: (msg: WebSocketMessage | null) => void;
}

function isPhaseMessage(msg: WebSocketMessage | null): msg is WebSocketMessage & { phase: Phase } {
  if (!msg) return false;
  const type = msg.type || msg.event_type || '';
  return (
    type === 'PHASE_SILENT' || type === 'phase_silent' ||
    type === 'PHASE_LIMINAL' || type === 'phase_liminal' ||
    type === 'PHASE_MANIFEST' || type === 'phase_manifest' ||
    type === 'PHASE_TRANSITION' || type === 'phase_transition' ||
    // P30: 兼容主窗口 app.js 的消息类型
    type === 'phase_change' || type === 'state_event'
  );
}

// 后端在场桥用"存在模式"词汇 static/liminal/manifest 广播(见
// core/lumiv_websocket_bridge._build_message: payload.phase = _current_mode),
// 而面板三态词汇是 silent/liminal/manifest。"static" 等同于 "silent"(待机)。
// 之前只认 "silent" → 回到待机的 static 帧被丢弃 → 覆盖层/面板三态回不去 →
// 表现为"触发不了三态变化"。此处把 static/idle/quiet 都归一到 silent。
// 导出:usePanelData.ts 的 IPC 直推路径(handleState)也需要同一份归一化——
// 它此前直接把后端原始 payload.phase(如 "static")当 Phase 强制类型转换，
// 没有走这层映射，导致 presence-state 标签/光球/三态圆点在 WS 未连上或重连
// 期间短暂读到无效的 "static" 值而渲染异常。见 usePanelData.ts 的引用处。
export function _mapPhaseToken(raw: string): Phase | null {
  const t = raw.toLowerCase();
  if (t.includes('silent') || t.includes('static') || t.includes('idle') || t.includes('quiet')) return 'silent';
  if (t.includes('liminal') || t.includes('processing')) return 'liminal';
  if (t.includes('manifest') || t.includes('completed') || t.includes('active')) return 'manifest';
  return null;
}

function extractPhase(msg: WebSocketMessage): Phase | null {
  const byType = _mapPhaseToken(msg.type || msg.event_type || '');
  if (byType) return byType;

  // 关键修复：ambient state_event 的相位在 payload.phase 里（桥广播的结构），
  // 之前只看 msg.phase/target_phase → WS 环境三态永远取不到 → 面板三态不变。
  const payload = (msg.payload as { phase?: string } | undefined) || undefined;
  const target = msg.target_phase || msg.phase || payload?.phase;
  if (target && typeof target === 'string') {
    return _mapPhaseToken(target);
  }

  return null;
}

export function usePhase(): UsePhaseReturn {
  const [phase, setPhaseState] = useState<Phase>('silent');
  // P28 修复：使用 ref 避免 handleMessage 闭包陷阱
  const phaseRef = useRef<Phase>(phase);
  phaseRef.current = phase;

  const setPhase = useCallback((p: Phase) => {
    setPhaseState(p);
    console.log(`[Panel] Phase → ${p}`);
  }, []);

  // 从 URL 参数读取初始 phase（开发调试）
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialPhase = params.get('phase')?.toLowerCase() as Phase | null;
    if (initialPhase && ['silent', 'liminal', 'manifest'].includes(initialPhase)) {
      setPhase(initialPhase);
    }
  }, [setPhase]);

  // 键盘快捷键（开发调试：1/2/3）。输入框聚焦时不拦截，避免打字误触。
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return;
      if (e.key === '1') setPhase('silent');
      if (e.key === '2') setPhase('liminal');
      if (e.key === '3') setPhase('manifest');
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [setPhase]);

  // P28 修复：handleMessage 不再依赖 phase，使用 ref 获取最新值
  const handleMessage = useCallback((msg: WebSocketMessage | null) => {
    if (!isPhaseMessage(msg)) return;
    const newPhase = extractPhase(msg);
    // 使用 ref 比较，避免闭包陷阱
    if (newPhase && newPhase !== phaseRef.current) {
      setPhase(newPhase);
    }
  }, [setPhase]);

  return {
    phase,
    label: PHASE_CONFIG[phase].label,
    setPhase,
    handleMessage,
  };
}