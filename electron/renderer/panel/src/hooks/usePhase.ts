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

function extractPhase(msg: WebSocketMessage): Phase | null {
  const type = (msg.type || msg.event_type || '').toLowerCase();

  if (type.includes('silent')) return 'silent';
  if (type.includes('liminal') || type.includes('processing')) return 'liminal';
  if (type.includes('manifest') || type.includes('completed')) return 'manifest';

  // transition 消息中的 target_phase
  const target = msg.target_phase || msg.phase;
  if (target && typeof target === 'string') {
    const t = target.toLowerCase();
    if (t.includes('silent')) return 'silent';
    if (t.includes('liminal') || t.includes('processing')) return 'liminal';
    if (t.includes('manifest') || t.includes('completed')) return 'manifest';
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

  // 键盘快捷键（开发调试：1/2/3）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
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