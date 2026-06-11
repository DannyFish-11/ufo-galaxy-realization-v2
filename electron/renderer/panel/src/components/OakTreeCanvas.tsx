/**
 * OakTreeCanvas — 橡树根系节点可视化 + MCP/Skill 花草丛
 * Canvas 2D 绘制：树冠(模型簇) + 地面线 + 分形根系(100+节点) + 流动粒子 + 花草丛
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

// ── MCP/Skill 状态类型 ────────────────────────────

export interface MCPServerStatus {
  id: string;
  name: string;
  status: 'healthy' | 'degraded' | 'offline';
  active: boolean;
  toolCount: number;
  activeTools: number;
}

export interface SkillStatus {
  id: string;
  name: string;
  status: 'healthy' | 'degraded' | 'offline';
  active: boolean;
  callCount: number;
}

interface FlowParticle {
  t: number;      // 0-1 along root path
  speed: number;
  rootIndex: number;
  branchIndices: number[];
  alpha: number;
}

interface Firefly {
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  phase: number;
  speed: number;
  radius: number;
  alpha: number;
}

interface Props {
  nodes: TreeNode[];
  providers: ProviderCluster[];
  onNodeHover: (node: TreeNode | null) => void;
  mcpServers?: MCPServerStatus[];
  skills?: SkillStatus[];
}

// ── 默认 MCP/Skill 数据 ──────────────────────────

const DEFAULT_MCP_SERVERS: MCPServerStatus[] = [
  { id: 'filesystem', name: 'FileSystem', status: 'healthy', active: true, toolCount: 8, activeTools: 6 },
  { id: 'browser', name: 'Browser', status: 'healthy', active: true, toolCount: 6, activeTools: 5 },
  { id: 'database', name: 'Database', status: 'healthy', active: true, toolCount: 10, activeTools: 8 },
  { id: 'search', name: 'Search', status: 'degraded', active: true, toolCount: 4, activeTools: 2 },
  { id: 'terminal', name: 'Terminal', status: 'healthy', active: true, toolCount: 5, activeTools: 5 },
];

const DEFAULT_SKILLS: SkillStatus[] = [
  { id: 'code-gen', name: 'CodeGen', status: 'healthy', active: true, callCount: 1543 },
  { id: 'debug', name: 'Debug', status: 'healthy', active: true, callCount: 892 },
  { id: 'review', name: 'Review', status: 'healthy', active: true, callCount: 1205 },
  { id: 'doc-write', name: 'DocWrite', status: 'healthy', active: true, callCount: 678 },
  { id: 'test-gen', name: 'TestGen', status: 'degraded', active: true, callCount: 445 },
  { id: 'refactor', name: 'Refactor', status: 'healthy', active: true, callCount: 567 },
  { id: 'analyze', name: 'Analyze', status: 'healthy', active: true, callCount: 2341 },
  { id: 'deploy', name: 'Deploy', status: 'offline', active: false, callCount: 0 },
];

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

// 模型名称来自 2026 年 6 月各厂商最新 API 文档（与 ProviderPanel.tsx 同步）
const DEFAULT_CLUSTERS: ProviderCluster[] = [
  { id: 'anthropic', name: 'Anthropic', color: '#d4a57b', x: 0.20, y: 0.12, models: ['claude-fable-5', 'claude-opus-4-8', 'claude-sonnet-4-6'], activeModel: 'claude-fable-5' },
  { id: 'openai', name: 'OpenAI', color: '#10a37f', x: 0.42, y: 0.08, models: ['gpt-5.5', 'gpt-5.5-instant', 'gpt-5.5-pro'], activeModel: 'gpt-5.5' },
  { id: 'deepseek', name: 'DeepSeek', color: '#4f6ef7', x: 0.62, y: 0.10, models: ['deepseek-v4-pro', 'deepseek-v4-flash'], activeModel: 'deepseek-v4-pro' },
  { id: 'google', name: 'Google', color: '#4285f4', x: 0.80, y: 0.14, models: ['gemini-3.5-pro', 'gemini-3.5-flash'], activeModel: 'gemini-3.5-pro' },
  { id: 'qwen', name: 'Qwen', color: '#615ced', x: 0.35, y: 0.20, models: ['qwen3.7-max', 'qwen3.7-coder', 'qwen3.6-27b'], activeModel: 'qwen3.7-max' },
  { id: 'xai', name: 'xAI', color: '#1d9bf0', x: 0.72, y: 0.22, models: ['grok-4.3', 'grok-4.20'], activeModel: 'grok-4.3' },
];

// ── 花草丛绘制函数 ───────────────────────────────

function drawGrassBlade(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  height: number,
  angle: number,
  color: string,
  sway: number
) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle + sway * 0.15);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.quadraticCurveTo(height * 0.2, -height * 0.5, height * 0.1, -height);
  ctx.quadraticCurveTo(-height * 0.1, -height * 0.5, 0, 0);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

function drawFlower(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  petalColor: string,
  centerColor: string,
  type: 'square' | 'star',
  sway: number
) {
  ctx.save();
  ctx.translate(x + sway * 2, y);

  if (type === 'square') {
    // 方形工具花（MCP）
    for (let i = 0; i < 4; i++) {
      ctx.save();
      ctx.rotate((Math.PI / 2) * i + sway * 0.1);
      ctx.beginPath();
      ctx.roundRect(-size * 0.3, -size * 0.8, size * 0.6, size * 0.6, 2);
      ctx.fillStyle = petalColor;
      ctx.fill();
      ctx.restore();
    }
  } else {
    // 星形光芒花（Skill）
    const spikes = 5;
    const outerR = size;
    const innerR = size * 0.4;
    ctx.beginPath();
    for (let i = 0; i < spikes * 2; i++) {
      const r = i % 2 === 0 ? outerR : innerR;
      const a = (Math.PI / spikes) * i - Math.PI / 2 + sway * 0.05;
      const px = Math.cos(a) * r;
      const py = Math.sin(a) * r;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = petalColor;
    ctx.fill();
  }

  // 花心
  ctx.beginPath();
  ctx.arc(0, 0, size * 0.25, 0, Math.PI * 2);
  ctx.fillStyle = centerColor;
  ctx.fill();

  ctx.restore();
}

function drawFlowerBush(
  ctx: CanvasRenderingContext2D,
  centerX: number,
  groundY: number,
  density: number,       // 0-1 繁盛度
  type: 'mcp' | 'skill',
  status: 'healthy' | 'degraded' | 'offline',
  t: number,
  label?: string
) {
  const W = ctx.canvas.width;
  const H = ctx.canvas.height;
  const scale = Math.min(W / 1200, H / 800);
  const bushWidth = 80 * scale * (0.5 + density * 0.5);
  const bushHeight = 60 * scale * (0.4 + density * 0.6);
  const bladeCount = Math.floor(15 + density * 35);

  // 颜色根据状态变化
  const colorMap = {
    healthy: type === 'mcp'
      ? { grass: `rgba(80, 160, 120, ${0.5 + density * 0.4})`, flower: 'rgba(100, 200, 160, 0.85)', center: 'rgba(220, 255, 240, 0.9)' }
      : { grass: `rgba(160, 140, 80, ${0.5 + density * 0.4})`, flower: 'rgba(255, 220, 100, 0.85)', center: 'rgba(255, 248, 220, 0.9)' },
    degraded: type === 'mcp'
      ? { grass: `rgba(160, 140, 60, ${0.4 + density * 0.3})`, flower: 'rgba(200, 180, 80, 0.7)', center: 'rgba(255, 240, 200, 0.8)' }
      : { grass: `rgba(180, 120, 60, ${0.4 + density * 0.3})`, flower: 'rgba(255, 180, 60, 0.7)', center: 'rgba(255, 230, 180, 0.8)' },
    offline: { grass: `rgba(80, 80, 80, ${0.2 + density * 0.2})`, flower: 'rgba(120, 120, 120, 0.4)', center: 'rgba(200, 200, 200, 0.5)' },
  };
  const colors = colorMap[status];

  // 微风摆动
  const sway = Math.sin(t * 0.0012 + centerX * 0.01) * 0.15;

  // 草丛
  for (let i = 0; i < bladeCount; i++) {
    const offsetX = (Math.random() - 0.5) * bushWidth;
    const bladeH = (10 + Math.random() * 25) * scale * (0.5 + density * 0.5);
    const angle = (Math.random() - 0.5) * 0.6;
    const bladeSway = sway + Math.sin(t * 0.0015 + i * 0.5) * 0.08;
    const greenVar = Math.random() * 30;
    const grassColor = colors.grass.replace(/\d+\)$/, `${0.4 + Math.random() * 0.4})`);
    drawGrassBlade(ctx, centerX + offsetX, groundY, bladeH, angle, grassColor, bladeSway);
  }

  // 花朵（根据密度决定数量）
  const flowerCount = Math.floor(2 + density * 6);
  for (let i = 0; i < flowerCount; i++) {
    const fx = centerX + (Math.random() - 0.5) * bushWidth * 0.6;
    const fy = groundY - (15 + Math.random() * 30) * scale * (0.5 + density * 0.5);
    const fsize = (6 + Math.random() * 8) * scale;
    const flowerSway = Math.sin(t * 0.001 + i * 0.8 + centerX * 0.02) * 0.12;
    drawFlower(ctx, fx, fy, fsize, colors.flower, colors.center, type === 'mcp' ? 'square' : 'star', flowerSway);
  }

  // 标签
  if (label) {
    ctx.font = `bold ${10 * scale}px -apple-system, PingFang SC, sans-serif`;
    ctx.fillStyle = 'rgba(255, 248, 235, 0.7)';
    ctx.textAlign = 'center';
    ctx.fillText(label, centerX, groundY + 14 * scale);
  }
}

function drawFireflies(
  ctx: CanvasRenderingContext2D,
  fireflies: Firefly[],
  t: number
) {
  fireflies.forEach((f) => {
    // 更新位置
    f.x = f.baseX + Math.sin(t * 0.001 * f.speed + f.phase) * 30;
    f.y = f.baseY + Math.cos(t * 0.0018 * f.speed + f.phase * 1.3) * 20;
    const flicker = 0.4 + Math.sin(t * 0.003 + f.phase * 2) * 0.35;

    ctx.save();
    ctx.shadowBlur = 10;
    ctx.shadowColor = `rgba(180, 255, 160, ${flicker * 0.6})`;
    ctx.beginPath();
    ctx.arc(f.x, f.y, f.radius, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(200, 255, 180, ${flicker})`;
    ctx.fill();
    ctx.restore();
  });
}

function generateFireflies(count: number, W: number, groundY: number): Firefly[] {
  const flies: Firefly[] = [];
  for (let i = 0; i < count; i++) {
    const baseX = 80 + Math.random() * (W - 160);
    const baseY = groundY - 20 - Math.random() * 80;
    flies.push({
      x: baseX,
      y: baseY,
      baseX,
      baseY,
      phase: Math.random() * Math.PI * 2,
      speed: 0.5 + Math.random() * 1.5,
      radius: 1.5 + Math.random() * 2,
      alpha: 0.5 + Math.random() * 0.5,
    });
  }
  return flies;
}

// ── 组件 ─────────────────────────────────────────

const OakTreeCanvas: React.FC<Props> = ({ nodes: propNodes, providers, onNodeHover, mcpServers, skills }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<TreeNode[]>(propNodes.length > 0 ? propNodes : generateFractalNodes());
  const particlesRef = useRef<FlowParticle[]>(generateFlowParticles(nodesRef.current));
  const firefliesRef = useRef<Firefly[]>([]);
  const animRef = useRef<number>(0);
  const timeRef = useRef(0);
  const [hoveredNode, setHoveredNode] = useState<TreeNode | null>(null);
  const mouseRef = useRef({ x: 0, y: 0 });

  // MCP/Skill 数据
  const mcps = mcpServers && mcpServers.length > 0 ? mcpServers : DEFAULT_MCP_SERVERS;
  const sks = skills && skills.length > 0 ? skills : DEFAULT_SKILLS;

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

    // ── 左侧 MCP 花丛 ──
    const mcpX = W * 0.12;
    const mcpDensity = mcps.filter((m) => m.active).length / Math.max(mcps.length, 1);
    drawFlowerBush(ctx, mcpX, groundY, mcpDensity, 'mcp', 'healthy', t, 'MCP');

    mcps.forEach((mcp, i) => {
      if (mcp.status === 'offline') return;
      const itemX = mcpX + (i - mcps.length / 2) * 25 * (W / 1200);
      const itemDensity = mcp.active ? mcp.activeTools / Math.max(mcp.toolCount, 1) : 0.2;
      const itemStatus = mcp.status;
      drawFlowerBush(ctx, itemX, groundY, itemDensity, 'mcp', itemStatus, t, mcp.name);
    });

    // ── 右侧 Skill 花丛 ──
    const skillX = W * 0.88;
    const skillDensity = sks.filter((s) => s.active).length / Math.max(sks.length, 1);
    drawFlowerBush(ctx, skillX, groundY, skillDensity, 'skill', 'healthy', t, 'Skill');

    sks.forEach((skill, i) => {
      if (skill.status === 'offline') return;
      const itemX = skillX + (i - sks.length / 2) * 22 * (W / 1200);
      const itemDensity = skill.active ? Math.min(skill.callCount / 2000, 1) : 0.2;
      const itemStatus = skill.status;
      drawFlowerBush(ctx, itemX, groundY, itemDensity, 'skill', itemStatus, t, skill.name);
    });

    // ── 萤火虫粒子（healthy 状态下飞舞）─
    if (mcpDensity > 0.5 || skillDensity > 0.5) {
      if (firefliesRef.current.length === 0) {
        firefliesRef.current = generateFireflies(15, W, groundY);
      }
      drawFireflies(ctx, firefliesRef.current, t);
    }

    // ── 图例 ──
    ctx.save();
    const legendX = W - 110;
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

    // MCP/Skill 图例
    const mcpLegendY = legendY + 3 * 18 + 8;
    ctx.font = '10px -apple-system, sans-serif';
    ctx.fillStyle = 'rgba(100, 200, 160, 0.85)';
    ctx.textAlign = 'left';
    ctx.fillText('\u25A0 MCP', legendX, mcpLegendY);
    ctx.fillStyle = 'rgba(255, 220, 100, 0.85)';
    ctx.fillText('\u2605 Skill', legendX + 50, mcpLegendY);
    ctx.restore();

    timeRef.current += 16;
    animRef.current = requestAnimationFrame(draw);
  }, [providers, hoveredNode, mcps, sks]);

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
