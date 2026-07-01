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

  // 有效三态:对话流式态优先 > 任一通道(IPC feed / WS)的非待机态 > 待机
  const ambient: Phase = panelData.phase !== 'silent' ? panelData.phase : wsPhase;
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
