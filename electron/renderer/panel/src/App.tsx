import { useEffect, useState } from 'react';
import { usePanelData } from '@/hooks/usePanelData';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useConversation } from '@/hooks/useConversation';
import { usePhase } from '@/hooks/usePhase';
import { useRenderPosture } from '@/hooks/useRenderPosture';
import type { Phase } from '@/types/phase';
import IconRail, { ICONS, type TabDef } from '@/components/IconRail';
import ConversationView from '@/components/ConversationView';
import PresencePanel from '@/components/PresencePanel';
import MeshView from '@/components/MeshView';
import CapabilitiesView from '@/components/CapabilitiesView';
import PairingView from '@/components/PairingView';
import SettingsTab from '@/components/SettingsTab';
import ModelsTab from '@/components/ModelsTab';
import DiagnosticsDrawer from '@/components/DiagnosticsDrawer';
import './App.css';

const TABS: TabDef[] = [
  { key: 'chat', label: '对话', icon: ICONS.chat },
  { key: 'mesh', label: '维态', icon: ICONS.mesh },
  { key: 'capability', label: '能力', icon: ICONS.capability },
  { key: 'models', label: '模型', icon: ICONS.models },
  { key: 'pairing', label: '接设备', icon: ICONS.pairing },
  { key: 'settings', label: '设置', icon: ICONS.settings },
];

function App() {
  const { panelData } = usePanelData();
  const { connected, lastMessage } = useWebSocket();
  const { turns: convTurns, speaking: convSpeaking } = useConversation(lastMessage, connected);
  const { phase: wsPhase, handleMessage } = usePhase();
  // 双轴渲染契约:后端每帧都在发 payload.render,此前前端一行没读。
  const { posture, hasContract, missingFields, handleMessage: handlePosture } = useRenderPosture();

  const [activeTab, setActiveTab] = useState(0);
  const [streamPhase, setStreamPhase] = useState<Phase | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // WS 消息 → 三态
  useEffect(() => {
    handleMessage(lastMessage);
    handlePosture(lastMessage);
  }, [lastMessage, handleMessage, handlePosture]);

  // 有效三态:对话流式态优先 > 实时 WS 相位(真实请求驱动,权威) > IPC 慢轮询
  // feed(仅 WS 未连接时兜底)。
  //
  // 关键修复:之前反过来——IPC feed 非待机就优先于 WS。但 IPC feed
  // (/api/v1/panel/feed，5 秒轮询一次)的相位来自 unified_panel_aggregation
  // 的 _fill_from_runtime_projection：它读的是 DesktopPresenceRuntime【单例】
  // 上一个从未被赋值过的 _continuum_state 属性(真正的相位只挂在每次请求的
  // RuntimeSession 上，从未回写到单例)，永远取不到，于是落到
  // core.cognitive_field_engine 的独立"认知场"环境模拟状态兜底——这套状态
  // 跟真实对话请求的生命周期完全不同步。一旦轮询恰好读到它的非 silent 值，
  // 就会把这个跟对话无关的态摆在最前，面板表现为"直接跳到表达中"且卡住不回
  // 待机(因为它不是被真实请求的 SILENT→LIMINAL→MANIFEST→SILENT 驱动的)。
  // 而 WS(/ws/desktop-presence)由 GalaxyPresenceBridge 订阅 StateEventBus，
  // 是真正跟随每次请求实时更新的权威源——WS 已连接时应始终优先于慢轮询 feed。
  const ambient: Phase = connected ? wsPhase : panelData.phase;
  const effectivePhase: Phase = streamPhase ?? ambient;
  const streaming = streamPhase !== null;

  // ── 渲染契约 → DOM 边界 ──────────────────────────────────────────────────
  //
  // 这一段**只把契约摆到 DOM 上，不改变任何观感**:下面暴露的 class 与自定义属性,
  // 全仓没有任何一条样式规则消费它们(App.css / tokens.css 里搜不到 --rp- 、
  // continuum- 、liminal- 、is-returning)。面板长什么样、怎么动,与接入之前逐像素
  // 一致。
  //
  // 为什么先只接骨架:观感是要人眼确认的,而骨架不需要 —— 后端每帧算好的这 21 个
  // 字段能不能完整、带类型、可校验地到达渲染层,是个纯粹的事实问题,可以现在就焊死。
  // 焊死之后,将来真要做视觉时只需要写样式,不必再动一次数据链路。
  //
  // 连续量走 CSS 自定义属性、离散轴走 class 与 data-* :这是给样式层用的两种取值
  // 方式,不是两套数据。
  const postureVars = posture
    ? ({
        '--rp-motion': posture.motion,
        '--rp-intensity': posture.intensity,
        '--rp-presence': posture.presence_intensity,
        '--rp-coherence': posture.coherence,
        '--rp-ambiguity': posture.ambiguity,
        '--rp-collapse': posture.collapse_tendency,
        '--rp-retreat': posture.retreat_tendency,
        '--rp-stability': posture.stability,
      } as React.CSSProperties)
    : undefined;

  // 副轴单独成 class。它比主轴多一档 receding ——「刚做完、正在收」与「静息」
  // 在主轴上都是 silent(见 phase_contract.gen.ts 的 TRI_STATE_OF),只看主轴
  // 永远分不出这两者。
  const continuumClass = hasContract && posture ? ` continuum-${posture.continuum_phase}` : '';
  const returningClass = posture?.is_returning ? ' is-returning' : '';
  const activityClass = hasContract && posture ? ` liminal-${posture.liminal_activity}` : '';
  const degradedClass = posture?.degraded ? ' is-degraded' : '';

  // 离散字段走 data-*:它们不是数值,当 CSS 变量没有意义;放 data-* 之后样式层用
  // 属性选择器就能取,同时在 devtools 里直接看得见 —— 契约到没到、到的是什么,
  // 不用开控制台打日志。
  const postureData = posture
    ? {
        'data-rp-lifecycle': posture.lifecycle,
        'data-rp-continuum': posture.continuum_phase,
        'data-rp-activity': posture.liminal_activity,
        'data-rp-form': posture.form_signature,
        'data-rp-spatial': posture.spatial_presence,
        'data-rp-domain': posture.runtime_domain ?? '',
        'data-rp-texture': posture.texture_hint,
        'data-rp-source': posture.source,
        'data-rp-next': posture.next_phases.join(','),
        'data-rp-degrade-reason': posture.degrade_reason ?? '',
      }
    : {};

  // 契约漂移(后端少发了字段)要看得见,而不是靠某条样式取空才发现。
  const contractDrift = missingFields.length > 0 ? missingFields.join(',') : undefined;

  return (
    <div
      className={`app phase-${effectivePhase}${continuumClass}${returningClass}${activityClass}${degradedClass}`}
      style={postureVars}
      data-render-contract={hasContract ? 'live' : 'absent'}
      data-render-contract-drift={contractDrift}
      {...postureData}
    >
      <IconRail
        tabs={TABS}
        active={activeTab}
        onChange={setActiveTab}
        phase={effectivePhase}
        connected={connected}
        onToggleDrawer={() => setDrawerOpen((v) => !v)}
      />

      <main className="stage">
        {/* 对话常驻挂载(切到其他 tab 时隐藏而不卸载,保留上下文与在飞的流) */}
        <div className="view-slot" style={{ display: activeTab === 0 ? 'flex' : 'none' }}>
          <ConversationView onStreamPhase={setStreamPhase} />
        </div>
        <div className="view-slot" style={{ display: activeTab === 1 ? 'flex' : 'none' }}>
          <MeshView data={panelData} />
        </div>
        <div className="view-slot" style={{ display: activeTab === 2 ? 'flex' : 'none' }}>
          <CapabilitiesView data={panelData} />
        </div>
        <div className="view-slot" style={{ display: activeTab === 3 ? 'flex' : 'none' }}>
          <ModelsTab />
        </div>
        <div className="view-slot" style={{ display: activeTab === 4 ? 'flex' : 'none' }}>
          <PairingView />
        </div>
        <div className="view-slot" style={{ display: activeTab === 5 ? 'flex' : 'none' }}>
          <SettingsTab />
        </div>
      </main>

      <PresencePanel
        phase={effectivePhase}
        streaming={streaming}
        data={panelData}
        turns={convTurns}
        speaking={convSpeaking}
      />

      <DiagnosticsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        data={panelData}
      />
    </div>
  );
}

export default App;
