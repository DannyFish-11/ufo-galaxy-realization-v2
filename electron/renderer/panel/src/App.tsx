import { useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWebSocket } from '@/hooks/useWebSocket';
import { usePhase } from '@/hooks/usePhase';
import type { Phase } from '@/types/phase';
import './App.css';

const TABS = [
  { cn: '维态', en: 'Weitai' },
  { cn: '星元', en: 'Xingyuan' },
  { cn: '设置', en: 'Settings' },
];

const PHASE_LABELS: Record<Phase, string> = {
  silent: 'STANDBY',
  liminal: 'THINKING...',
  manifest: 'ONLINE',
};

function App() {
  const { connected, lastMessage } = useWebSocket();
  const { phase, label, handleMessage } = usePhase();
  const [activeTab, setActiveTab] = useState(0);

  useEffect(() => {
    handleMessage(lastMessage);
  }, [lastMessage, handleMessage]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key >= '1' && e.key <= '3') {
      setActiveTab(Number(e.key) - 1);
    }
  }, []);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className={`app-container phase-${phase}`}>
      {/* 背景层 */}
      <div className="bg-layer" />
      <div className="bg-blur" />

      {/* LIMINAL 脉冲边框 */}
      <AnimatePresence>
        {phase === 'liminal' && (
          <motion.div
            className="pulse-border"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
          />
        )}
      </AnimatePresence>

      {/* 面板 */}
      <div className="panel">
        {/* Galaxy 标题 */}
        <motion.h1
          className="title"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        >
          Galaxy
        </motion.h1>

        {/* Tab 列表 */}
        <nav className="tab-list">
          {TABS.map((tab, i) => (
            <motion.div
              key={tab.en}
              className={`tab ${activeTab === i ? 'active' : ''}`}
              onClick={() => setActiveTab(i)}
              initial={{ opacity: 0, x: -30 }}
              animate={{ opacity: activeTab === i ? 1 : 0.28, x: 0 }}
              whileHover={{ opacity: 0.6 }}
              transition={{ duration: 0.4, delay: i * 0.1 }}
            >
              <span className="tab-cn">{tab.cn}</span>
              <span className="tab-en">{tab.en}</span>
            </motion.div>
          ))}
        </nav>

        {/* 内容区（空的） */}
        <div className="content-area" />

        {/* 底部状态 */}
        <div className="status-bar">
          {/* 三个点 */}
          <div className="dots-row">
            {(['silent', 'liminal', 'manifest'] as Phase[]).map((p) => (
              <motion.div
                key={p}
                className={`dot ${p} ${phase === p ? 'active' : ''}`}
                animate={
                  phase === p
                    ? p === 'liminal'
                      ? {
                          scale: [1, 1.2, 1],
                          boxShadow: [
                            '0 0 8px rgba(255,255,255,0.2)',
                            '0 0 24px rgba(255,255,255,0.5)',
                            '0 0 8px rgba(255,255,255,0.2)',
                          ],
                        }
                      : { scale: 1, opacity: 1 }
                    : { scale: 0.85, opacity: 0.2 }
                }
                transition={
                  phase === p && p === 'liminal'
                    ? { duration: 1.8, repeat: Infinity, ease: 'easeInOut' }
                    : { duration: 0.4 }
                }
              />
            ))}
          </div>

          {/* STANDBY/THINKING.../ONLINE */}
          <AnimatePresence mode="wait">
            <motion.div
              key={phase}
              className={`status-text ${phase}`}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              transition={{ duration: 0.3 }}
            >
              {PHASE_LABELS[phase]}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

export default App;