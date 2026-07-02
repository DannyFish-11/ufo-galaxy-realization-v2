import { useEffect, useState } from 'react';
import { usePanelData } from '@/hooks/usePanelData';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useConversation } from '@/hooks/useConversation';
import { usePhase } from '@/hooks/usePhase';
import type { Phase } from '@/types/phase';
import IconRail, { ICONS, type TabDef } from '@/components/IconRail';
import ConversationView from '@/components/ConversationView';
import PresencePanel from '@/components/PresencePanel';
import MeshView from '@/components/MeshView';
import CapabilitiesView from '@/components/CapabilitiesView';
import SettingsTab from '@/components/SettingsTab';
import ModelsTab from '@/components/ModelsTab';
import DiagnosticsDrawer from '@/components/DiagnosticsDrawer';
import './App.css';

const TABS: TabDef[] = [
  { key: 'chat', label: '对话', icon: ICONS.chat },
  { key: 'mesh', label: '维态', icon: ICONS.mesh },
  { key: 'capability', label: '能力', icon: ICONS.capability },
  { key: 'models', label: '模型', icon: ICONS.models },
  { key: 'settings', label: '设置', icon: ICONS.settings },
];

function App() {
  const { panelData } = usePanelData();
  const { connected, lastMessage } = useWebSocket();
  const { turns: convTurns, speaking: convSpeaking } = useConversation(lastMessage);
  const { phase: wsPhase, handleMessage } = usePhase();

  const [activeTab, setActiveTab] = useState(0);
  const [streamPhase, setStreamPhase] = useState<Phase | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // WS 消息 → 三态
  useEffect(() => {
    handleMessage(lastMessage);
  }, [lastMessage, handleMessage]);

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

  return (
    <div className={`app phase-${effectivePhase}`}>
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
        {activeTab === 1 && <MeshView data={panelData} />}
        {activeTab === 2 && <CapabilitiesView data={panelData} />}
        {activeTab === 3 && (
          <div className="view-slot">
            <ModelsTab />
          </div>
        )}
        {activeTab === 4 && (
          <div className="view-slot">
            <SettingsTab />
          </div>
        )}
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
