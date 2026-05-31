import React from 'react';
import type { Phase } from '@/types/phase';
import type { PhaseLabel } from '@/types/phase';
import './MainContent.css';

const TAB_TITLES = ['维态', '星元', '设置'];

interface Props {
  phase: Phase;
  label: PhaseLabel;
  activeTab: number;
}

const MainContent: React.FC<Props> = ({ phase, label, activeTab }) => {
  return (
    <main className={`main-content phase-${phase}`}>
      <header className="content-header">
        <div className="tab-title">{TAB_TITLES[activeTab]}</div>
        <div className="window-controls">
          <button className="win-btn minimize" aria-label="minimize">−</button>
          <button className="win-btn close" aria-label="close">×</button>
        </div>
      </header>

      <div className="content-body">
        <div className="content-card span-2">
          <div className="card-placeholder" />
        </div>
        <div className="content-card">
          <div className="card-placeholder" />
        </div>
        <div className="content-card">
          <div className="card-placeholder" />
        </div>
      </div>

      <div className="phase-indicator">
        <span className={`phase-badge ${phase}`}>{label}</span>
      </div>
    </main>
  );
};

export default React.memo(MainContent);