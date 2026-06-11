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

// ── MCP / Skill 状态接口 ─────────────────────────

export interface MCPServerStatus {
  name: string;
  url: string;
  status: 'online' | 'offline' | 'error' | 'unknown';
  toolsCount: number;
}

export interface SkillStatus {
  name: string;
  version: string;
  status: 'loaded' | 'unloaded' | 'error' | 'disabled';
  description: string;
}

interface Props {
  nodes: TreeNode[];
  providers: ProviderCluster[];
  onNodeHover: (node: TreeNode | null) => void;
  mcpServers?: MCPServerStatus[];
  skills?: SkillStatus[];
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

// 模型名称来自 2026 年 6 月各厂商最新 API 文档（与 ProviderPanel.tsx 同步）
const DEFAULT_CLUSTERS: ProviderCluster[] = [
  { id: 'anthropic', name: 'Anthropic', color: '#d4a57b', x: 0.20, y: 0.12, models: ['claude-fable-5', 'claude-opus-4-8', 'claude-sonnet-4-6'], activeModel: 'claude-fable-5' },
  { id: 'openai', name: 'OpenAI', color: '#10a37f', x: 0.42, y: 0.08, models: ['gpt-5.5', 'gpt-5.5-instant', 'gpt-5.5-pro'], activeModel: 'gpt-5.5' },
  { id: 'deepseek', name: 'DeepSeek', color: '#4f6ef7', x: 0.62, y: 0.10, models: ['deepseek-v4-pro', 'deepseek-v4-flash'], activeModel: 'deepseek-v4-pro' },
  { id: 'google', name: 'Google', color: '#4285f4', x: 0.80, y: 0.14, models: ['gemini-3.5-pro', 'gemini-3.5-flash'], activeModel: 'gemini-3.5-pro' },
  { id: 'qwen', name: 'Qwen', color: '#615ced', x: 0.35, y: 0.20, models: ['qwen3.7-max', 'qwen3.7-coder', 'qwen3.6-27b'], activeModel: 'qwen3.7-max' },
  { id: 'xai', name: 'xAI', color: '#1d9bf0', x: 0.72, y: 0.22, models: ['grok-4.3', 'grok-4.20'], activeModel: 'grok-4.3' },
];

// ── 默认 MCP / Skill 数据 ────────────────────────

const DEFAULT_MCP_SERVERS: MCPServerStatus[] = [
  { name: 'filesystem', url: 'http://localhost:8091', status: 'online', toolsCount: 8 },
  { name: 'web-search', url: 'http://localhost:8092', status: 'online', toolsCount: 3 },
  { name: 'code-executor', url: 'http://localhost:8093', status: 'error', toolsCount: 0 },
  { name: 'browser', url: 'http://localhost:8094', status: 'offline', toolsCount: 0 },
];

const DEFAULT_SKILLS: SkillStatus[] = [
  { name: 'planner', version: '2.1.0', status: 'loaded', description: '任务规划' },
  { name: 'coder', version: '1.8.0', status: 'loaded', description: '代码生成' },
  { name: 'grounding', version: '1.5.0', status: 'loaded', description: '视觉定位' },
  { name: 'voice', version: '0.9.0', status: 'unloaded', description: '语音识别' },
  { name: 'mesh-coord', version: '1.2.0', status: 'loaded', description: 'Mesh协调' },
  { name: 'memory', version: '1.0.0', status: 'error', description: '记忆管理' },
];

// ── 花草丛绘制工具函数 ──────────────────────────

/** 绘制单根草叶 */
function drawGrassBlade(
  ctx: CanvasRenderingContext2D,
  x: number, y: number,
  height: number, angle: number,
  color: string, sway: number
) {
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x, y);
  const tipX = x + Math.sin(angle + sway) * height * 0.5;
  const tipY = y - height;
  const cpx = x + Math.sin(angle + sway * 0.5) * height * 0.3;
  const cpy = y - height * 0.6;
  ctx.quadraticCurveTo(cpx, cpy, tipX, tipY);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.2;
  ctx.lineCap = 'round';
  ctx.stroke();
  ctx.restore();
}

/** 绘制花朵（MCP=方形工具花，Skill=星形花） */
function drawFlower(
  ctx: CanvasRenderingContext2D,
  x: number, y: number,
  type: 'mcp' | 'skill',
  color: string,
  scale: number,
  sway: number
) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(scale, scale);
  ctx.rotate(sway * 0.2);

  if (type === 'mcp') {
    // MCP = 方形花瓣（工具感）
    for (let i = 0; i < 4; i++) {
      const a = (Math.PI / 2) * i + sway * 0.3;
      const px = Math.cos(a) * 5;
      const py = Math.sin(a) * 5;
      ctx.fillStyle = color;
      ctx.fillRect(px - 2.5, py - 2.5, 5, 5);
    }
    // 中心
    ctx.beginPath();
    ctx.arc(0, 0, 3, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255, 248, 235, 0.9)';
    ctx.fill();
  } else {
    // Skill = 菱形花瓣（技能光芒）
    for (let i = 0; i < 5; i++) {
      const a = (Math.PI * 2 / 5) * i + sway * 0.3;
      ctx.save();
      ctx.rotate(a);
      ctx.beginPath();
      ctx.moveTo(0, -6);
      ctx.lineTo(2.5, -1);
      ctx.lineTo(0, 7);
      ctx.lineTo(-2.5, -1);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
      ctx.restore();
    }
    // 中心
    ctx.beginPath();
    ctx.arc(0, 0, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255, 248, 235, 0.9)';
    ctx.fill();
  }

  ctx.restore();
}

/** 绘制萤火虫/蝴蝶粒子 */
interface Firefly {
  x: number; y: number;
  vx: number; vy: number;
  alpha: number;
  phase: number;
}

function createFireflies(count: number, cx: number, cy: number, spread: number): Firefly[] {
  const ff: Firefly[] = [];
  for (let i = 0; i < count; i++) {
    ff.push({
      x: cx + (Math.random() - 0.5) * spread,
      y: cy + (Math.random() - 0.5) * spread * 0.3,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.15,
      alpha: 0.3 + Math.random() * 0.7,
      phase: Math.random() * Math.PI * 2,
    });
  }
  return ff;
}

function drawFireflies(ctx: CanvasRenderingContext2D, fireflies: Firefly[], t: number) {
  fireflies.forEach((f) => {
    f.x += f.vx;
    f.y += f.vy;
    // 边界反弹
    if (Math.abs(f.vx) < 0.05) f.vx += (Math.random() - 0.5) * 0.1;
    if (Math.abs(f.vy) < 0.02) f.vy += (Math.random() - 0.5) * 0.05;
    f.alpha = 0.2 + 0.5 * Math.abs(Math.sin(t * 0.003 + f.phase));

    ctx.beginPath();
    ctx.arc(f.x, f.y, 1.5, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(200, 255, 150, ${f.alpha})`;
    ctx.fill();
    // 微光晕
    ctx.beginPath();
    ctx.arc(f.x, f.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(200, 255, 150, ${f.alpha * 0.15})`;
    ctx.fill();
  });
}

/** 绘制完整的花草丛 */
function drawFlowerBush(
  ctx: CanvasRenderingContext2D,
  cx: number, cy: number,
  width: number,
  items: Array<{ name: string; status: string }>,
  type: 'mcp' | 'skill',
  time: number,
  fireflies: Firefly[] | null,
) {
  const activeCount = items.filter((i) =>
    type === 'mcp' ? i.status === 'online' : i.status === 'loaded'
  ).length;
  const totalCount = items.length || 1;
  const vitality = activeCount / totalCount; // 0-1 繁盛度

  // 状态颜色
  const bushColor =
    vitality > 0.6 ? `rgba(80, 160, 80, ${0.3 + vitality * 0.5})` :
    vitality > 0.2 ? `rgba(140, 160, 60, ${0.25 + vitality * 0.4})` :
                     `rgba(120, 100, 70, ${0.2 + vitality * 0.3})`;

  // 草叶密度随繁盛度增加
  const bladeCount = Math.floor(20 + vitality * 40);
  const windSway = Math.sin(time * 0.0015) * 0.15;

  for (let i = 0; i < bladeCount; i++) {
    const x = cx - width / 2 + (Math.random() * width);
    const h = 12 + Math.random() * 20 * vitality;
    const a = (Math.random() - 0.5) * 0.8;
    const sway = windSway + Math.sin(time * 0.002 + i * 0.5) * 0.1;
    drawGrassBlade(ctx, x, cy, h, a, bushColor, sway);
  }

  // 花朵位置（均匀分布）
  const flowerColors = type === 'mcp'
    ? ['#6b8f71', '#7a9e8a', '#8bb3a0', '#5d8a6b']
    : ['#c4956a', '#d4a56a', '#e8b87a', '#b8885a'];

  items.forEach((item, i) => {
    const isActive = type === 'mcp' ? item.status === 'online' : item.status === 'loaded';
    const fx = cx - width / 2 + (width / (items.length + 1)) * (i + 1);
    const fy = cy - 8 - Math.sin(time * 0.001 + i) * 3;
    const scale = isActive ? 0.8 + vitality * 0.4 : 0.4;
    const color = isActive
      ? flowerColors[i % flowerColors.length]
      : 'rgba(120, 110, 90, 0.5)';

    drawFlower(ctx, fx, fy, type, color, scale, windSway + i * 0.3);

    // 名称标签
    ctx.font = '8px -apple-system, sans-serif';
    ctx.fillStyle = isActive ? 'rgba(255, 248, 235, 0.65)' : 'rgba(255, 248, 235, 0.25)';
    ctx.textAlign = 'center';
    ctx.fillText(item.name, fx, fy + 14);
  });

  // 繁盛度指示
  ctx.font = 'bold 10px -apple-system, sans-serif';
  ctx.fillStyle = vitality > 0.6 ? 'rgba(100, 200, 130, 0.8)' :
                  vitality > 0.2 ? 'rgba(220, 180, 80, 0.8)' :
                                   'rgba(200, 80, 80, 0.6)';
  ctx.textAlign = 'center';
  const label = type === 'mcp' ? `MCP ${activeCount}/${totalCount}` : `Skills ${activeCount}/${totalCount}`;
  ctx.fillText(label, cx, cy + 26);

  // 萤火虫（仅在繁盛度高时）
  if (fireflies && vitality > 0.5) {
    drawFireflies(ctx, fireflies, time);
  }
}

// ── 组件 ─────────────────────────────────────────

const OakTreeCanvas: React.FC<Props> = ({ nodes: propNodes, providers, onNodeHover, mcpServers, skills }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<TreeNode[]>(propNodes.length > 0 ? propNodes : generateFractalNodes());
  const particlesRef = useRef<FlowParticle[]>(generateFlowParticles(nodesRef.current));
  const animRef = useRef<number>(0);
  const timeRef = useRef(0);
  const [hoveredNode, setHoveredNode] = useState<TreeNode | null>(null);
  const mouseRef = useRef({ x: 0, y: 0 });
  // MCP / Skill 数据 refs
  const mcpRef = useRef<MCPServerStatus[]>(mcpServers && mcpServers.length > 0 ? mcpServers : DEFAULT_MCP_SERVERS);
  const skillsRef = useRef<SkillStatus[]>(skills && skills.length > 0 ? skills : DEFAULT_SKILLS);
  // 萤火虫粒子
  const mcpFirefliesRef = useRef<Firefly[] | null>(null);
  const skillFirefliesRef = useRef<Firefly[] | null>(null);

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

    // ── 花草丛（MCP + Skill 状态可视化）─
    const mcps = mcpRef.current;
    const sks = skillsRef.current;

    // 初始化萤火虫（首次）
    if (!mcpFirefliesRef.current) {
      mcpFirefliesRef.current = createFireflies(6, W * 0.18, groundY + 10, 60);
    }
    if (!skillFirefliesRef.current) {
      skillFirefliesRef.current = createFireflies(8, W * 0.82, groundY + 10, 60);
    }

    // 左侧 — MCP 花丛
    drawFlowerBush(ctx, W * 0.18, groundY + 2, W * 0.28, mcps, 'mcp', t, mcpFirefliesRef.current);

    // 右侧 — Skill 花丛
    drawFlowerBush(ctx, W * 0.82, groundY + 2, W * 0.28, sks, 'skill', t, skillFirefliesRef.current);

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

    // MCP / Skill 图例（底部）
    const blY = H - 40;
    ctx.font = '9px -apple-system, sans-serif';
    ctx.fillStyle = 'rgba(255, 248, 235, 0.35)';
    ctx.textAlign = 'left';
    // MCP 图标
    ctx.fillStyle = 'rgba(107, 143, 113, 0.7)';
    ctx.fillRect(12, blY, 6, 6);
    ctx.fillStyle = 'rgba(255, 248, 235, 0.4)';
    ctx.fillText('MCP', 22, blY + 6);
    // Skill 图标
    ctx.fillStyle = 'rgba(196, 149, 106, 0.7)';
    const sx = 60;
    for (let i = 0; i < 5; i++) {
      const a = (Math.PI * 2 / 5) * i;
      ctx.save();
      ctx.translate(sx + 3, blY + 3);
      ctx.rotate(a);
      ctx.beginPath();
      ctx.moveTo(0, -4); ctx.lineTo(1.5, 0); ctx.lineTo(0, 4); ctx.lineTo(-1.5, 0);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }
    ctx.fillStyle = 'rgba(255, 248, 235, 0.4)';
    ctx.fillText('Skill', sx + 10, blY + 6);
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

  // MCP / Skill 数据更新
  useEffect(() => {
    if (mcpServers && mcpServers.length > 0) {
      mcpRef.current = mcpServers;
      mcpFirefliesRef.current = null; // 重新生成萤火虫位置
    }
  }, [mcpServers]);

  useEffect(() => {
    if (skills && skills.length > 0) {
      skillsRef.current = skills;
      skillFirefliesRef.current = null;
    }
  }, [skills]);

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
