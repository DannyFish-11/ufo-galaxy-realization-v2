import React, { useState } from 'react';
import type { PhaseLabel } from '@/types/phase';
import StatusDots from './StatusDots';
import type { Phase } from '@/types/phase';
import './Sidebar.css';

interface Tab {
  cn: string;
  en: string;
}

const TABS: Tab[] = [
  { cn: '维态', en: 'Weitai' },
  { cn: '星元', en: 'Xingyuan' },
  { cn: '设置', en: 'Settings' },
];

interface Props {
  phase: Phase;
  label: PhaseLabel;
  connected: boolean;
  onTabChange?: (index: number) => void;
}

const Sidebar: React.FC<Props> = ({ phase, label, connected, onTabChange }) => {
  const [activeTab, setActiveTab] = useState(0);

  const handleTabClick = (index: number) => {
    setActiveTab(index);
    onTabChange?.(index);
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1 className="brand-title">Galaxy</h1>
        <div className={`connection-badge ${connected ? 'online' : 'offline'}`}>
          {connected ? 'ON' : 'OFF'}
        </div>
      </div>

      <nav className="tab-nav">
        {TABS.map((tab, i) => (
          <button
            key={tab.en}
            className={`tab-item ${activeTab === i ? 'active' : ''}`}
            onClick={() => handleTabClick(i)}
          >
            <div className="tab-icon" />
            <div className="tab-text">
              <span className="tab-cn">{tab.cn}</span>
              <span className="tab-en">{tab.en}</span>
            </div>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <StatusDots phase={phase} />
        <div className={`status-label phase-${phase}`}>{label}</div>
      </div>
    </aside>
  );
};

export default React.memo(Sidebar);