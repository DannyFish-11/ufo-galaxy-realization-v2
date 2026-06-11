/**
 * OakTreeCanvas — 橡树根系节点可视化
 * Canvas 2D 绘制：树冠(模型簇) + 地面线 + 分形根系(100+节点) + 流动粒子
 */

import React, { useRef, useEffect, useCallback, useState } from 'react';

// ── 类型 ─────────────────────────────────────────

export interface TreeNode {
  id: string;
  x: number;      // 0-1 normalized
  y: number;      // 0-1 normalized
  depth: number;  // root depth 0-6
  parent: string | null;
  status: 'healthy' | 'degraded' | 'offline';
  role: string;
  rootIndex: number; // which main root branch
}

export interface ProviderCluster {
  id: string;
  name: string;
  color: string;
  x: number;  // 0-1 in canopy area
  y: number;
  models: string[];
  activeModel: string;
}

interface FlowParticle {
  t: number;      // 0-1 along root path
  speed: number;
  rootIndex: number;
  branchIndices: number[];
  alpha: number;
}

interface Props {
  nodes: TreeNode[];
  providers: ProviderCluster[];
  onNodeHover: (node: TreeNode | null) => void;
}

// ── 分形根系生成 ─────────────────────────────────

function generateFractalNodes(): TreeNode[] {
  const nodes: TreeNode[] = [];
  const rootY = 0.40; // ground line

  // 根节点（树干底部）
  nodes.push({
    id: 'root',
    x: 0.5,
    y: rootY,
    depth: 0,
    parent: null,
    status: 'healthy',
    role: 'root',
    rootIndex: -1,
  });

  // 5 条主根
  const mainRootAngles = [-0.6, -0.25, 0, 0.25, 0.6]; // radians from vertical
  const mainRootLengths = [0.12, 0.14, 0.10, 0.14, 0.12];

  for (let r = 0; r < 5; r++) {
    const angle = mainRootAngles[r] + (Math.random() - 0.5) * 0.15;
    const len = mainRootLengths[r];
    const x1 = 0.5 + Math.sin(angle) * len * 1.5;
    const y1 = rootY + Math.cos(angle) * len;

    const id = `root_${r}`;
    nodes.push({
      id,
      x: Math.max(0.02, Math.min(0.98, x1)),
      y: Math.min(0.95, y1),
      depth: 1,
      parent: 'root',
      status: Math.random() > 0.9 ? 'degraded' : 'healthy',
      role: 'main_root',
      rootIndex: r,
    });

    // 递归分叉
    growBranches(nodes, id, x1, y1, angle, 2, r, 0.072);
  }

  // 确保至少 100 个节点
  let extraId = 1000;
  const leafNodes = nodes.filter((n) => n.depth >= 4);
  while (nodes.length < 120 && leafNodes.length > 0) {
    const parent = leafNodes[Math.floor(Math.random() * leafNodes.length)];
    const angle = (Math.random() - 0.5) * 1.2;
    const len = 0.03 + Math.random() * 0.04;
    nodes.push({
      id: `extra_${extraId++}`,
      x: Math.max(0.02, Math.min(0.98, parent.x + Math.sin(angle) * len)),
      y: Math.min(0.97, parent.y + Math.cos(angle) * len * 0.5),
      depth: parent.depth + 1,
      parent: parent.id,
      status: Math.random() > 0.85 ? 'offline' : 'healthy',
      role: ['compute', 'storage', 'routing', 'cache', 'gateway'][Math.floor(Math.random() * 5)],
      rootIndex: parent.rootIndex,
    });
  }

  return nodes;
}

function growBranches(
  nodes: TreeNode[],
  parentId: string,
  px: number,
  py: number,
  pAngle: number,
  depth: number,
  rootIdx: number,
  length: number
) {
  if (depth > 6 || py > 0.95) return;

  const numBranches = depth < 3 ? 2 + Math.floor(Math.random() * 2) : 1 + Math.floor(Math.random() * 2);

  for (let b = 0; b < numBranches; b++) {
    const spread = 0.7 - depth * 0.08;
    const angle = pAngle + (Math.random() - 0.5) * spread * 2;
    const len = length * (0.65 + Math.random() * 0.2);
    const nx = px + Math.sin(angle) * len * 1.5;
    const ny = py + Math.cos(angle) * len;

    if (nx < 0.01 || nx > 0.99 || ny > 0.96) continue;

    const id = `${parentId}_${b}`;
    nodes.push({
      id,
      x: nx,
      y: ny,
      depth,
      parent: parentId,
      status: Math.random() > (0.92 - depth * 0.03) ? 'degraded' : 'healthy',
      role: ['compute', 'storage', 'routing', 'cache'][Math.floor(Math.random() * 4)],
      rootIndex: rootIdx,
    });

    growBranches(nodes, id, nx, ny, angle, depth + 1, rootIdx, len);
  }
}

function generateFlowParticles(nodes: TreeNode[]): FlowParticle[] {
  const particles: FlowParticle[] = [];
  const rootBranches = nodes.filter((n) => n.depth >= 2 && n.depth <= 4);

  for (let i = 0; i < 30; i++) {
    const branch = rootBranches[Math.floor(Math.random() * rootBranches.length)];
    if (!branch) continue;
    particles.push({
      t: Math.random(),
      speed: 0.003 + Math.random() * 0.005,
      rootIndex: branch.rootIndex,
      branchIndices: [],
      alpha: 0.4 + Math.random() * 0.6,
    });
  }
  return particles;
}

// ── 默认 Provider 簇 ─────────────────────────────

const DEFAULT_CLUSTERS: ProviderCluster[] = [
  { id: 'anthropic', name: 'Anthropic', color: '#d4a030', x: 0.20, y: 0.12, models: ['claude-opus-4-8-20250529', 'claude-sonnet-4-6-20251022'], activeModel: 'claude-opus-4-8-20250529' },
  { id: 'openai', name: 'OpenAI', color: '#10a37f', x: 0.42, y: 0.08, models: ['gpt-5.5', 'gpt-5.5-instant'], activeModel: 'gpt-5.5' },
  { id: 'deepseek', name: 'DeepSeek', color: '#4f6ef7', x: 0.62, y: 0.10, models: ['deepseek-v4-pro'], activeModel: 'deepseek-v4-pro' },
  { id: 'google', name: 'Google', color: '#4285f4', x: 0.80, y: 0.14, models: ['gemini-3.5-pro'], activeModel: 'gemini-3.5-pro' },
  { id: 'qwen', name: 'Qwen', color: '#615ced', x: 0.35, y: 0.20, models: ['qwen3.7-max'], activeModel: 'qwen3.7-max' },
  { id: 'xai', name: 'xAI', color: '#1d9bf0', x: 0.72, y: 0.22, models: ['grok-4.1'], activeModel: 'grok-4.1' },
];

// ── 组件 ─────────────────────────────────────────

const OakTreeCanvas: React.FC<Props> = ({ nodes: propNodes, providers, onNodeHover }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<TreeNode[]>(propNodes.length > 0 ? propNodes : generateFractalNodes());
  const particlesRef = useRef<FlowParticle[]>(generateFlowParticles(nodesRef.current));
  const animRef = useRef<number>(0);
  const timeRef = useRef(0);
  const [hoveredNode, setHoveredNode] = useState<TreeNode | null>(null);
  const mouseRef = useRef({ x: 0, y: 0 });

  // 绘制主循环
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const t = timeRef.current;

    ctx.clearRect(0, 0, W, H);

    const groundY = H * 0.40;
    const nodes = nodesRef.current;
    const clusters = providers.length > 0 ? providers : DEFAULT_CLUSTERS;

    // ── 树冠贝塞尔曲线 ──
    ctx.save();
    ctx.beginPath();
    const sway = Math.sin(t * 0.001) * 3;
    ctx.moveTo(W * 0.35 + sway, groundY);
    ctx.bezierCurveTo(
      W * 0.30 + sway, H * 0.15,
      W * 0.40, H * 0.02,
      W * 0.50, H * 0.05
    );
    ctx.bezierCurveTo(
      W * 0.65, H * 0.00,
      W * 0.72, H * 0.12,
      W * 0.65 + sway, groundY
    );
    ctx.closePath();

    // 树冠填充 — 深绿半透明
    const canopyGrad = ctx.createRadialGradient(W * 0.50, H * 0.15, 0, W * 0.50, H * 0.15, W * 0.25);
    canopyGrad.addColorStop(0, 'rgba(60, 100, 60, 0.25)');
    canopyGrad.addColorStop(0.6, 'rgba(40, 70, 45, 0.15)');
    canopyGrad.addColorStop(1, 'rgba(20, 40, 25, 0.05)');
    ctx.fillStyle = canopyGrad;
    ctx.fill();
    ctx.restore();

    // ── Provider 簇（树冠中的模型节点）─
    clusters.forEach((cluster) => {
      const cx = cluster.x * W;
      const cy = cluster.y * H;

      // 外发光
      ctx.save();
      ctx.shadowBlur = 20;
      ctx.shadowColor = `${cluster.color}44`;
      ctx.beginPath();
      ctx.arc(cx, cy, 18, 0, Math.PI * 2);
      ctx.fillStyle = `${cluster.color}22`;
      ctx.fill();
      ctx.restore();

      // 内核
      ctx.beginPath();
      ctx.arc(cx, cy, 10, 0, Math.PI * 2);
      ctx.fillStyle = `${cluster.color}88`;
      ctx.fill();
      ctx.strokeStyle = `${cluster.color}cc`;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // 名称
      ctx.font = '11px -apple-system, PingFang SC, sans-serif';
      ctx.fillStyle = 'rgba(255, 248, 235, 0.75)';
      ctx.textAlign = 'center';
      ctx.fillText(cluster.name, cx, cy - 18);

      // 活跃模型
      ctx.font = '9px monospace';
      ctx.fillStyle = cluster.color;
      ctx.fillText(cluster.activeModel, cx, cy + 26);

      // 轨道小点
      const orbitAngle = t * 0.002 + clusters.indexOf(cluster) * 1.0;
      const orbitR = 24;
      const ox = cx + Math.cos(orbitAngle) * orbitR;
      const oy = cy + Math.sin(orbitAngle) * orbitR * 0.5;
      ctx.beginPath();
      ctx.arc(ox, oy, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = `${cluster.color}aa`;
      ctx.fill();
    });

    // ── 树干 ──
    ctx.save();
    const trunkGrad = ctx.createLinearGradient(W * 0.48, 0, W * 0.52, 0);
    trunkGrad.addColorStop(0, 'rgba(120, 90, 60, 0.6)');
    trunkGrad.addColorStop(0.5, 'rgba(160, 120, 70, 0.5)');
    trunkGrad.addColorStop(1, 'rgba(120, 90, 60, 0.6)');
    ctx.fillStyle = trunkGrad;
    ctx.fillRect(W * 0.47, groundY - H * 0.05, W * 0.06, H * 0.055);
    ctx.restore();

    // ── 地面线 ──
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(0, groundY);
    ctx.lineTo(W, groundY);
    ctx.strokeStyle = 'rgba(212, 175, 55, 0.3)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([8, 4]);
    ctx.stroke();

    // 地面线发光
    ctx.beginPath();
    ctx.moveTo(0, groundY);
    ctx.lineTo(W, groundY);
    ctx.strokeStyle = 'rgba(212, 175, 55, 0.08)';
    ctx.lineWidth = 6;
    ctx.setLineDash([]);
    ctx.stroke();
    ctx.restore();

    // ── 根系（分形线条）─
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    // 按深度排序绘制
    const sortedNodes = [...nodes].sort((a, b) => a.depth - b.depth);

    sortedNodes.forEach((node) => {
      if (!node.parent) return;
      const parent = nodeMap.get(node.parent);
      if (!parent) return;

      const x1 = parent.x * W;
      const y1 = parent.y * H;
      const x2 = node.x * W;
      const y2 = node.y * H;

      // 根须透明度随深度递减
      const alpha = Math.max(0.12, 0.55 - node.depth * 0.07);

      ctx.beginPath();
      ctx.moveTo(x1, y1);
      // 轻微曲线
      const cpx = (x1 + x2) / 2 + (Math.random() - 0.5) * 8;
      const cpy = (y1 + y2) / 2;
      ctx.quadraticCurveTo(cpx, cpy, x2, y2);
      ctx.strokeStyle = `rgba(212, 175, 55, ${alpha})`;
      ctx.lineWidth = Math.max(0.5, 2.5 - node.depth * 0.35);
      ctx.stroke();
    });

    // ── 根尖节点 ──
    const tipNodes = nodes.filter((n) => n.depth >= 3);
    tipNodes.forEach((node) => {
      const x = node.x * W;
      const y = node.y * H;
      const isHovered = hoveredNode?.id === node.id;

      // 状态色
      const statusColor =
        node.status === 'healthy'
          ? 'rgba(100, 200, 130, 0.8)'
          : node.status === 'degraded'
            ? 'rgba(220, 180, 80, 0.7)'
            : 'rgba(200, 80, 80, 0.5)';

      const r = isHovered ? 5 : 2.5;

      if (isHovered) {
        ctx.save();
        ctx.shadowBlur = 12;
        ctx.shadowColor = statusColor;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = statusColor;
        ctx.fill();
        ctx.restore();
      } else {
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = statusColor;
        ctx.fill();
      }
    });

    // ── 流动粒子 ──
    const particles = particlesRef.current;
    particles.forEach((p) => {
      p.t += p.speed;
      if (p.t > 1) p.t = 0;

      // 找到对应的根节点路径
      const branchNodes = nodes
        .filter((n) => n.rootIndex === p.rootIndex && n.depth >= 2)
        .sort((a, b) => a.depth - b.depth);

      if (branchNodes.length < 2) return;

      const idx = Math.floor(p.t * (branchNodes.length - 1));
      const n1 = branchNodes[Math.min(idx, branchNodes.length - 1)];
      const n2 = branchNodes[Math.min(idx + 1, branchNodes.length - 1)];
      const frac = p.t * (branchNodes.length - 1) - idx;

      const px = (n1.x + (n2.x - n1.x) * frac) * W;
      const py = (n1.y + (n2.y - n1.y) * frac) * H;

      ctx.beginPath();
      ctx.arc(px, py, 2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, 220, 140, ${p.alpha * 0.7})`;
      ctx.fill();
    });

    // ── 图例 ──
    ctx.save();
    const legendX = W - 90;
    const legendY = 16;
    [
      { label: 'Healthy', color: 'rgba(100, 200, 130, 0.8)' },
      { label: 'Degraded', color: 'rgba(220, 180, 80, 0.7)' },
      { label: 'Offline', color: 'rgba(200, 80, 80, 0.5)' },
    ].forEach((item, i) => {
      ctx.beginPath();
      ctx.arc(legendX, legendY + i * 18, 4, 0, Math.PI * 2);
      ctx.fillStyle = item.color;
      ctx.fill();
      ctx.font = '10px -apple-system, sans-serif';
      ctx.fillStyle = 'rgba(255, 248, 235, 0.45)';
      ctx.textAlign = 'left';
      ctx.fillText(item.label, legendX + 10, legendY + i * 18 + 3);
    });
    ctx.restore();

    timeRef.current += 16;
    animRef.current = requestAnimationFrame(draw);
  }, [providers, hoveredNode]);

  // 启动/停止动画
  useEffect(() => {
    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, [draw]);

  // Canvas 尺寸自适应
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = parent.clientWidth * dpr;
      canvas.height = parent.clientHeight * dpr;
      canvas.style.width = `${parent.clientWidth}px`;
      canvas.style.height = `${parent.clientHeight}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.scale(dpr, dpr);
    };

    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  // 鼠标交互
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      mouseRef.current = { x, y };

      // 查找最近的节点
      let closest: TreeNode | null = null;
      let closestDist = Infinity;
      const tipNodes = nodesRef.current.filter((n) => n.depth >= 3);

      tipNodes.forEach((node) => {
        const dx = node.x - x;
        const dy = node.y - y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 0.03 && dist < closestDist) {
          closestDist = dist;
          closest = node;
        }
      });

      setHoveredNode(closest);
      onNodeHover(closest);
    },
    [onNodeHover]
  );

  const handleMouseLeave = useCallback(() => {
    setHoveredNode(null);
    onNodeHover(null);
  }, [onNodeHover]);

  return (
    <div className="oak-canvas-container">
      <canvas
        ref={canvasRef}
        className="oak-canvas"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      />
      {hoveredNode && (
        <div
          className="node-tooltip"
          style={{
            left: `${hoveredNode.x * 100}%`,
            top: `${hoveredNode.y * 100}%`,
          }}
        >
          <div className="tooltip-id">{hoveredNode.id}</div>
          <div className="tooltip-role">{hoveredNode.role}</div>
          <div className={`tooltip-status status-${hoveredNode.status}`}>
            {hoveredNode.status}
          </div>
        </div>
      )}
    </div>
  );
};

export { generateFractalNodes, generateFlowParticles };
export default React.memo(OakTreeCanvas);
