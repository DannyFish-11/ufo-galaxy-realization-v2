/**
 * WeitaiTab — 维态面板主容器
 * 左侧设备拓扑图 + 右侧三区域（Mesh会话、OpenClawd状态、NATS消息流）
 */

import React, { useMemo } from 'react';
import DeviceTopologyGraph, { TopologyNode, TopologyEdge } from './DeviceTopologyGraph';
import MeshSessionPanel, { MeshSessionInfo } from './MeshSessionPanel';
import OpenClawdStatusPanel, { OpenClawdStatus } from './OpenClawdStatusPanel';
import NATSMessageStream, { NATSMessage } from './NATSMessageStream';
import { PanelData } from '@/hooks/usePanelData';
import './WeitaiTab.css';

interface Props {
  data: PanelData;
}

const WeitaiTab: React.FC<Props> = ({ data }) => {
  // 将 PanelData 映射到各子组件所需类型
  const topologyNodes: TopologyNode[] = useMemo(() => {
    return (data.topologyNodes || []).map((n) => ({
      id: n.id,
      label: n.label,
      role: n.role,
      status: n.status,
      x: n.x,
      y: n.y,
      lastSeen: n.lastSeen,
      messageCount: n.messageCount,
    }));
  }, [data.topologyNodes]);

  const topologyEdges: TopologyEdge[] = useMemo(() => {
    return (data.topologyEdges || []).map((e) => ({
      from: e.from,
      to: e.to,
      label: e.label,
      active: e.active,
      messageRate: e.messageRate,
    }));
  }, [data.topologyEdges]);

  const meshSession: MeshSessionInfo = useMemo(() => {
    return data.meshSession || {
      sessionId: 'idle',
      status: 'pending',
      barrierStatus: 'closed',
      tickSequence: 0,
      participants: [],
      createdAt: Date.now(),
    };
  }, [data.meshSession]);

  const openclawdStatus: OpenClawdStatus = useMemo(() => {
    return data.openclawdStatus || {
      runtimeState: 'PAUSED',
      phase: 'silent',
      coherence: 0.0,
      activeTasks: 0,
      completedTasks: 0,
      connectedDevices: 0,
      lastTick: 0,
      uptime: 0,
    };
  }, [data.openclawdStatus]);

  const natsMessages: NATSMessage[] = useMemo(() => {
    return (data.natsMessages || []).map((m) => ({
      id: m.id,
      timestamp: m.timestamp,
      topic: m.topic,
      direction: m.direction,
      payload: m.payload,
      msgType: m.msgType as NATSMessage['msgType'],
    }));
  }, [data.natsMessages]);

  return (
    <div className="weitai-tab">
      {/* 左侧 — 设备拓扑图 */}
      <div className="weitai-left">
        <DeviceTopologyGraph
          nodes={topologyNodes}
          edges={topologyEdges}
        />
      </div>

      {/* 右侧 — 三区域垂直布局 */}
      <div className="weitai-right">
        {/* 上部 — Mesh 会话面板 */}
        <div className="mesh-session-section">
          <MeshSessionPanel session={meshSession} />
        </div>

        {/* 中部 — OpenClawd 状态面板 */}
        <div className="openclawd-section">
          <OpenClawdStatusPanel status={openclawdStatus} />
        </div>

        {/* 下部 — NATS 消息流面板 */}
        <div className="nats-section">
          <NATSMessageStream messages={natsMessages} />
        </div>
      </div>
    </div>
  );
};

export default React.memo(WeitaiTab);
