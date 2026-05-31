import React from 'react';
import type { Phase } from '@/types/phase';
import './StatusDots.css';

interface Props {
  phase: Phase;
}

const DOTS: { id: Phase; label: string }[] = [
  { id: 'silent', label: 'SILENT' },
  { id: 'liminal', label: 'LIMINAL' },
  { id: 'manifest', label: 'MANIFEST' },
];

const StatusDots: React.FC<Props> = ({ phase }) => {
  return (
    <div className="status-dots-container">
      <div className="dots-row">
        {DOTS.map((dot) => (
          <div
            key={dot.id}
            className={`status-dot ${dot.id} ${phase === dot.id ? 'active' : ''}`}
            title={dot.label}
            data-phase={dot.id}
          />
        ))}
      </div>
    </div>
  );
};

export default React.memo(StatusDots);