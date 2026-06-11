import React, { useRef, useEffect, useState, useCallback } from 'react';

// =============================================================================
// Type Definitions
// =============================================================================

export interface TopologyNode {
  id: string;
  label: string;
  role: 'controller' | 'participant' | 'gateway' | 'wearable';
  status: 'online' | 'degraded' | 'offline';
  x: number; // 0-1 normalized
  y: number; // 0-1 normalized
  lastSeen: number;
  messageCount: number;
}

export interface TopologyEdge {
  from: string;
  to: string;
  label?: string;
  active: boolean;
  messageRate: number;
}

export interface PulseMessage {
  id: string;
  edgeIndex: number;
  progress: number;
  type: string;
}

interface Props {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  pulseMessages?: PulseMessage[];
  onNodeClick?: (node: TopologyNode) => void;
}

// Internal physics node with runtime state
interface PhysicsNode extends TopologyNode {
  px: number; // physics x (pixels)
  py: number; // physics y (pixels)
  vx: number;
  vy: number;
  radius: number;
  baseRadius: number;
  scaleAnim: number;
  targetScale: number;
  spawnProgress: number; // 0-1 for spawn animation
  pulsePhase: number;
}

interface PhysicsEdge extends TopologyEdge {
  fromIdx: number;
  toIdx: number;
  length: number;
  particles: EdgeParticle[];
}

interface EdgeParticle {
  progress: number;
  speed: number;
  size: number;
  alpha: number;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  node: TopologyNode | null;
}

// =============================================================================
// Constants
// =============================================================================

const NODE_COLORS: Record<string, string> = {
  online: '#4ade80',
  degraded: '#facc15',
  offline: '#6b7280',
};

const ROLE_RADIUS: Record<string, number> = {
  controller: 30,
  gateway: 22,
  participant: 20,
  wearable: 16,
};

const DEFAULT_NODES: TopologyNode[] = [
  {
    id: 'openclawd',
    label: 'OpenClawd',
    role: 'controller',
    status: 'online',
    x: 0.5,
    y: 0.5,
    lastSeen: Date.now(),
    messageCount: 12847,
  },
  {
    id: 'desktop',
    label: 'Desktop',
    role: 'gateway',
    status: 'online',
    x: 0.5,
    y: 0.15,
    lastSeen: Date.now(),
    messageCount: 8432,
  },
  {
    id: 'android',
    label: 'Android',
    role: 'participant',
    status: 'online',
    x: 0.2,
    y: 0.75,
    lastSeen: Date.now(),
    messageCount: 2156,
  },
  {
    id: 'wearos',
    label: 'WearOS',
    role: 'wearable',
    status: 'online',
    x: 0.8,
    y: 0.75,
    lastSeen: Date.now(),
    messageCount: 987,
  },
  {
    id: 'ipad',
    label: 'iPad',
    role: 'participant',
    status: 'online',
    x: 0.85,
    y: 0.3,
    lastSeen: Date.now(),
    messageCount: 1543,
  },
];

const DEFAULT_EDGES: TopologyEdge[] = [
  { from: 'openclawd', to: 'desktop', label: 'IPC', active: true, messageRate: 45 },
  { from: 'openclawd', to: 'android', label: 'Mesh/NATS', active: true, messageRate: 23 },
  { from: 'openclawd', to: 'wearos', label: 'Mesh/NATS', active: true, messageRate: 12 },
  { from: 'desktop', to: 'android', label: 'AIP', active: true, messageRate: 8 },
  { from: 'openclawd', to: 'ipad', label: 'Mesh/NATS', active: true, messageRate: 18 },
];

// =============================================================================
// Helper Functions
// =============================================================================

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function dist(x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  return Math.sqrt(dx * dx + dy * dy);
}

// Get point on quadratic bezier curve at t (0-1)
function bezierPoint(
  p0: [number, number],
  p1: [number, number],
  p2: [number, number],
  t: number
): [number, number] {
  const mt = 1 - t;
  const x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0];
  const y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1];
  return [x, y];
}

// Get control point for curved edge
function getControlPoint(
  from: [number, number],
  to: [number, number],
  curvature = 0.2
): [number, number] {
  const mx = (from[0] + to[0]) / 2;
  const my = (from[1] + to[1]) / 2;
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  // Perpendicular offset
  const nx = -dy / len;
  const ny = dx / len;
  const offset = len * curvature;
  return [mx + nx * offset, my + ny * offset];
}

// =============================================================================
// Icon Drawing Functions
// =============================================================================

function drawDesktopIcon(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: string
): void {
  const s = r * 0.6;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.5;
  // Monitor
  ctx.strokeRect(cx - s * 0.8, cy - s * 0.6, s * 1.6, s * 1.0);
  // Stand
  ctx.beginPath();
  ctx.moveTo(cx, cy + s * 0.4);
  ctx.lineTo(cx, cy + s * 0.7);
  ctx.stroke();
  // Base
  ctx.beginPath();
  ctx.moveTo(cx - s * 0.4, cy + s * 0.7);
  ctx.lineTo(cx + s * 0.4, cy + s * 0.7);
  ctx.stroke();
  ctx.restore();
}

function drawAndroidIcon(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: string
): void {
  const s = r * 0.5;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.5;
  // Phone body
  const w = s * 1.0;
  const h = s * 1.6;
  ctx.beginPath();
  ctx.roundRect(cx - w / 2, cy - h / 2, w, h, s * 0.15);
  ctx.stroke();
  // Screen
  ctx.fillStyle = hexToRgba(color, 0.3);
  ctx.beginPath();
  ctx.roundRect(cx - w * 0.38, cy - h * 0.32, w * 0.76, h * 0.64, s * 0.08);
  ctx.fill();
  // Home button
  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.arc(cx, cy + h * 0.38, s * 0.12, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawWearableIcon(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: string
): void {
  const s = r * 0.5;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.5;
  // Watch body (rounded rect)
  const w = s * 1.0;
  const h = s * 1.2;
  ctx.beginPath();
  ctx.roundRect(cx - w / 2, cy - h / 2, w, h, s * 0.25);
  ctx.stroke();
  // Screen
  ctx.fillStyle = hexToRgba(color, 0.3);
  ctx.beginPath();
  ctx.roundRect(cx - w * 0.35, cy - h * 0.35, w * 0.7, h * 0.7, s * 0.12);
  ctx.fill();
  // Straps
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx - w * 0.25, cy - h / 2);
  ctx.lineTo(cx - w * 0.2, cy - h * 0.85);
  ctx.lineTo(cx + w * 0.2, cy - h * 0.85);
  ctx.lineTo(cx + w * 0.25, cy - h / 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(cx - w * 0.25, cy + h / 2);
  ctx.lineTo(cx - w * 0.2, cy + h * 0.85);
  ctx.lineTo(cx + w * 0.2, cy + h * 0.85);
  ctx.lineTo(cx + w * 0.25, cy + h / 2);
  ctx.stroke();
  ctx.restore();
}

function drawControllerIcon(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: string
): void {
  const s = r * 0.5;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = hexToRgba(color, 0.15);
  ctx.lineWidth = 1.5;
  // Hexagon shape
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 6;
    const x = cx + s * Math.cos(angle);
    const y = cy + s * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  // Inner dot
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(cx, cy, s * 0.2, 0, Math.PI * 2);
  ctx.fill();
  // Orbital ring
  ctx.strokeStyle = hexToRgba(color, 0.4);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, s * 1.4, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawIPadIcon(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: string
): void {
  const s = r * 0.5;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  // Tablet body
  const w = s * 1.3;
  const h = s * 1.7;
  ctx.beginPath();
  ctx.roundRect(cx - w / 2, cy - h / 2, w, h, s * 0.12);
  ctx.stroke();
  // Screen
  ctx.fillStyle = hexToRgba(color, 0.3);
  ctx.beginPath();
  ctx.roundRect(cx - w * 0.4, cy - h * 0.38, w * 0.8, h * 0.76, s * 0.06);
  ctx.fill();
  // Home indicator
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(cx - s * 0.2, cy + h * 0.4, s * 0.4, s * 0.06, s * 0.03);
  ctx.stroke();
  ctx.restore();
}

// =============================================================================
// Main Component
// =============================================================================

const DeviceTopologyGraph: React.FC<Props> = ({
  nodes: propNodes,
  edges: propEdges,
  pulseMessages: propPulseMessages,
  onNodeClick,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef<number>(0);
  const physicsNodesRef = useRef<PhysicsNode[]>([]);
  const physicsEdgesRef = useRef<PhysicsEdge[]>([]);
  const mouseRef = useRef({ x: -1, y: -1 });
  const timeRef = useRef(0);
  const tooltipRef = useRef<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    node: null,
  });

  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    node: null,
  });

  // Use default data if props are empty
  const nodes = propNodes.length > 0 ? propNodes : DEFAULT_NODES;
  const edges = propEdges.length > 0 ? propEdges : DEFAULT_EDGES;

  // Initialize physics state from props
  const initPhysics = useCallback(
    (width: number, height: number) => {
      const existingNodes = physicsNodesRef.current;
      const pNodes: PhysicsNode[] = nodes.map((n) => {
        const existing = existingNodes.find((en) => en.id === n.id);
        if (existing) {
          // Update existing node properties, keep physics state
          return {
            ...existing,
            ...n,
            baseRadius: ROLE_RADIUS[n.role] || 20,
            radius: existing.radius,
          };
        }
        // New node
        const px = n.x * width;
        const py = n.y * height;
        return {
          ...n,
          px,
          py,
          vx: 0,
          vy: 0,
          baseRadius: ROLE_RADIUS[n.role] || 20,
          radius: ROLE_RADIUS[n.role] || 20,
          scaleAnim: 1,
          targetScale: 1,
          spawnProgress: 0,
          pulsePhase: Math.random() * Math.PI * 2,
        };
      });
      physicsNodesRef.current = pNodes;

      // Build edge map
      const nodeIdxMap = new Map<string, number>();
      pNodes.forEach((n, i) => nodeIdxMap.set(n.id, i));

      const existingEdges = physicsEdgesRef.current;
      const pEdges: PhysicsEdge[] = edges.map((e) => {
        const existing = existingEdges.find(
          (ee) => ee.from === e.from && ee.to === e.to
        );
        return {
          ...e,
          fromIdx: nodeIdxMap.get(e.from) ?? -1,
          toIdx: nodeIdxMap.get(e.to) ?? -1,
          length: 120,
          particles: existing?.particles || [],
        };
      });
      physicsEdgesRef.current = pEdges;
    },
    [nodes, edges]
  );

  // Force-directed layout step
  const applyForces = useCallback(
    (width: number, height: number) => {
      const pNodes = physicsNodesRef.current;
      const pEdges = physicsEdgesRef.current;
      if (pNodes.length === 0) return;

      const centerX = width / 2;
      const centerY = height / 2;

      // 1. Center attraction (stronger for controller)
      for (const n of pNodes) {
        const toCenterX = centerX - n.px;
        const toCenterY = centerY - n.py;
        const distToCenter = Math.sqrt(toCenterX * toCenterX + toCenterY * toCenterY);
        const strength = n.role === 'controller' ? 0.003 : 0.001;
        // Normalize by distance to prevent extreme forces at edges
        const normalizedStrength = strength / (1 + distToCenter * 0.001);
        n.vx += toCenterX * normalizedStrength;
        n.vy += toCenterY * normalizedStrength;
      }

      // 2. Node repulsion (Coulomb-like)
      for (let i = 0; i < pNodes.length; i++) {
        for (let j = i + 1; j < pNodes.length; j++) {
          const a = pNodes[i];
          const b = pNodes[j];
          const dx = b.px - a.px;
          const dy = b.py - a.py;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const minDist = a.radius + b.radius + 40;
          if (d < minDist * 3) {
            const force = (5000 / (d * d + 100)) * 0.5;
            const fx = (dx / d) * force;
            const fy = (dy / d) * force;
            a.vx -= fx;
            a.vy -= fy;
            b.vx += fx;
            b.vy += fy;
          }
        }
      }

      // 3. Spring force along edges
      for (const e of pEdges) {
        if (e.fromIdx < 0 || e.toIdx < 0) continue;
        const a = pNodes[e.fromIdx];
        const b = pNodes[e.toIdx];
        const dx = b.px - a.px;
        const dy = b.py - a.py;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetLen = e.length;
        const displacement = d - targetLen;
        const springK = 0.01;
        const force = displacement * springK;
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }

      // 4. Damping & integration
      for (const n of pNodes) {
        n.vx *= 0.92;
        n.vy *= 0.92;
        n.px += n.vx;
        n.py += n.vy;

        // Keep within bounds with padding
        const pad = n.radius + 10;
        n.px = Math.max(pad, Math.min(width - pad, n.px));
        n.py = Math.max(pad, Math.min(height - pad, n.py));
      }
    },
    []
  );

  // Main render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = rect.width + 'px';
      canvas.style.height = rect.height + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { width: rect.width, height: rect.height };
    };

    let { width, height } = resize();
    initPhysics(width, height);

    const handleResize = () => {
      const size = resize();
      width = size.width;
      height = size.height;
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouseRef.current.x = e.clientX - rect.left;
      mouseRef.current.y = e.clientY - rect.top;
    };

    const handleMouseLeave = () => {
      mouseRef.current.x = -1;
      mouseRef.current.y = -1;
      tooltipRef.current = { visible: false, x: 0, y: 0, node: null };
      setTooltip({ visible: false, x: 0, y: 0, node: null });
    };

    const handleClick = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const pNodes = physicsNodesRef.current;
      for (const n of pNodes) {
        const d = dist(mx, my, n.px, n.py);
        if (d < n.radius * n.scaleAnim + 5) {
          onNodeClick?.(n);
          break;
        }
      }
    };

    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseleave', handleMouseLeave);
    canvas.addEventListener('click', handleClick);

    const animate = (ts: number) => {
      timeRef.current = ts;
      const dt = 0.016; // ~60fps

      ctx.clearRect(0, 0, width, height);

      // Background gradient
      const bgGrad = ctx.createRadialGradient(
        width / 2,
        height / 2,
        0,
        width / 2,
        height / 2,
        Math.max(width, height) * 0.7
      );
      bgGrad.addColorStop(0, 'rgba(15,20,40,0.3)');
      bgGrad.addColorStop(1, 'rgba(5,8,20,0.5)');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      const pNodes = physicsNodesRef.current;
      const pEdges = physicsEdgesRef.current;

      // Physics step (every frame for smooth settling)
      applyForces(width, height);

      // --- Draw Edges ---
      for (let ei = 0; ei < pEdges.length; ei++) {
        const e = pEdges[ei];
        if (e.fromIdx < 0 || e.toIdx < 0) continue;
        const a = pNodes[e.fromIdx];
        const b = pNodes[e.toIdx];
        if (!a || !b) continue;

        const from: [number, number] = [a.px, a.py];
        const to: [number, number] = [b.px, b.py];
        const cp = getControlPoint(from, to, 0.15);

        // Edge base color
        const edgeAlpha = e.active ? 0.35 : 0.12;
        const edgeColor = e.active ? 'rgba(100,150,255,' : 'rgba(100,120,160,';

        ctx.save();

        // Glow for active edges
        if (e.active) {
          ctx.shadowColor = 'rgba(100,150,255,0.3)';
          ctx.shadowBlur = 8;
        }

        // Main curve
        ctx.strokeStyle = edgeColor + edgeAlpha + ')';
        ctx.lineWidth = e.active ? 2 : 1;
        ctx.beginPath();
        ctx.moveTo(from[0], from[1]);
        ctx.quadraticCurveTo(cp[0], cp[1], to[0], to[1]);
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Edge label
        if (e.label) {
          const mid = bezierPoint(from, cp, to, 0.5);
          const perpX = -(to[1] - from[1]);
          const perpY = to[0] - from[0];
          const perpLen = Math.sqrt(perpX * perpX + perpY * perpY) || 1;
          const labelOffset = 14;
          const lx = mid[0] + (perpX / perpLen) * labelOffset;
          const ly = mid[1] + (perpY / perpLen) * labelOffset;

          ctx.font = '10px monospace';
          const tm = ctx.measureText(e.label);
          const bw = tm.width + 8;
          const bh = 16;
          ctx.fillStyle = 'rgba(10,15,35,0.85)';
          ctx.strokeStyle = 'rgba(100,150,255,0.2)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.roundRect(lx - bw / 2, ly - bh / 2, bw, bh, 4);
          ctx.fill();
          ctx.stroke();

          ctx.fillStyle = 'rgba(150,180,220,0.8)';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(e.label, lx, ly);
        }

        // Message rate indicator dots along the edge
        if (e.active && e.messageRate > 0) {
          const particleCount = Math.min(Math.floor(e.messageRate / 5), 8);
          const time = ts * 0.001;

          for (let pi = 0; pi < particleCount; pi++) {
            const speed = 0.3 + (e.messageRate / 100) * 0.5;
            let progress = ((time * speed + pi / particleCount) % 1);
            // Reverse some particles
            if (pi % 2 === 1) progress = 1 - progress;

            const pt = bezierPoint(from, cp, to, progress);
            const particleSize = 1.5 + (e.messageRate / 60);
            const particleAlpha = 0.4 + 0.4 * Math.sin(progress * Math.PI);

            ctx.beginPath();
            ctx.arc(pt[0], pt[1], particleSize, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(200,220,255,${particleAlpha})`;
            ctx.fill();

            // Glow
            ctx.beginPath();
            ctx.arc(pt[0], pt[1], particleSize * 3, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(100,180,255,${particleAlpha * 0.15})`;
            ctx.fill();
          }
        }

        ctx.restore();
      }

      // --- Draw Prop Pulse Messages ---
      if (propPulseMessages && propPulseMessages.length > 0) {
        for (const pm of propPulseMessages) {
          const e = pEdges[pm.edgeIndex];
          if (!e || e.fromIdx < 0 || e.toIdx < 0) continue;
          const a = pNodes[e.fromIdx];
          const b = pNodes[e.toIdx];
          if (!a || !b) continue;

          const from: [number, number] = [a.px, a.py];
          const to: [number, number] = [b.px, b.py];
          const cp = getControlPoint(from, to, 0.15);
          const pt = bezierPoint(from, cp, to, pm.progress);

          // Pulse glow
          ctx.save();
          ctx.shadowColor = '#60a5fa';
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], 4, 0, Math.PI * 2);
          ctx.fillStyle = '#93c5fd';
          ctx.fill();
          ctx.restore();

          // Outer ring
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], 7, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(147,197,253,${0.3 * (1 - Math.abs(pm.progress - 0.5) * 2)})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }

      // --- Draw Nodes ---
      let hoveredNode: PhysicsNode | null = null;
      const mx = mouseRef.current.x;
      const my = mouseRef.current.y;

      // Sort: controller on top
      const sortedNodes = [...pNodes].sort((a, b) => {
        if (a.role === 'controller') return 1;
        if (b.role === 'controller') return -1;
        return 0;
      });

      for (const n of sortedNodes) {
        // Spawn animation
        if (n.spawnProgress < 1) {
          n.spawnProgress = Math.min(1, n.spawnProgress + dt * 2);
        }
        const spawnScale = n.spawnProgress < 1
          ? 0.5 + 0.5 * (1 - Math.pow(1 - n.spawnProgress, 3))
          : 1;

        // Breathing pulse (online nodes)
        const breathSpeed = n.role === 'controller' ? 1.5 : 1;
        const breathAmp = n.status === 'online' ? 0.04 : 0.015;
        n.pulsePhase += dt * breathSpeed;
        const breathScale = 1 + Math.sin(n.pulsePhase) * breathAmp;
        n.scaleAnim = breathScale;
        n.radius = n.baseRadius * breathScale * spawnScale;

        // Check hover
        const dMouse = dist(mx, my, n.px, n.py);
        const isHovered = dMouse < n.radius + 5;
        if (isHovered) hoveredNode = n;

        const color = NODE_COLORS[n.status] || '#6b7280';
        const isController = n.role === 'controller';

        ctx.save();

        // Outer glow for online nodes
        if (n.status === 'online') {
          ctx.shadowColor = color;
          ctx.shadowBlur = isController ? 25 : 12;
        }

        // Halo ring for controller
        if (isController) {
          const haloR = n.radius * 1.6 + Math.sin(n.pulsePhase * 0.7) * 4;
          ctx.beginPath();
          ctx.arc(n.px, n.py, haloR, 0, Math.PI * 2);
          ctx.strokeStyle = hexToRgba(color, 0.15 + 0.1 * Math.sin(n.pulsePhase));
          ctx.lineWidth = 2;
          ctx.stroke();

          // Second halo
          const haloR2 = n.radius * 2.0 + Math.cos(n.pulsePhase * 0.5) * 6;
          ctx.beginPath();
          ctx.arc(n.px, n.py, haloR2, 0, Math.PI * 2);
          ctx.strokeStyle = hexToRgba(color, 0.08);
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        ctx.shadowBlur = 0;

        // Node background circle
        const grad = ctx.createRadialGradient(
          n.px - n.radius * 0.2,
          n.py - n.radius * 0.2,
          0,
          n.px,
          n.py,
          n.radius
        );
        grad.addColorStop(0, hexToRgba('#1a2035', 0.95));
        grad.addColorStop(1, hexToRgba('#0f1425', 0.95));
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(n.px, n.py, n.radius, 0, Math.PI * 2);
        ctx.fill();

        // Border
        ctx.strokeStyle = hexToRgba(color, isHovered ? 1 : 0.7);
        ctx.lineWidth = isHovered ? 2.5 : 1.5;
        ctx.beginPath();
        ctx.arc(n.px, n.py, n.radius, 0, Math.PI * 2);
        ctx.stroke();

        // Status dot
        const dotR = n.radius * 0.18;
        const dotAngle = -Math.PI * 0.25;
        const dotX = n.px + Math.cos(dotAngle) * (n.radius - dotR - 2);
        const dotY = n.py + Math.sin(dotAngle) * (n.radius - dotR - 2);
        ctx.beginPath();
        ctx.arc(dotX, dotY, dotR, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        // Pulsing status ring for online
        if (n.status === 'online') {
          const pulseR = dotR * (1.5 + 0.5 * Math.sin(ts * 0.005 + n.pulsePhase));
          ctx.beginPath();
          ctx.arc(dotX, dotY, pulseR, 0, Math.PI * 2);
          ctx.strokeStyle = hexToRgba(color, 0.3);
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        // Icon
        ctx.shadowBlur = 0;
        switch (n.role) {
          case 'controller':
            drawControllerIcon(ctx, n.px, n.py, n.radius, color);
            break;
          case 'gateway':
            drawDesktopIcon(ctx, n.px, n.py, n.radius, color);
            break;
          case 'participant':
            if (n.id === 'ipad') {
              drawIPadIcon(ctx, n.px, n.py, n.radius, color);
            } else {
              drawAndroidIcon(ctx, n.px, n.py, n.radius, color);
            }
            break;
          case 'wearable':
            drawWearableIcon(ctx, n.px, n.py, n.radius, color);
            break;
        }

        // Label below node
        ctx.font = `${isController ? 700 : 500} ${isController ? 12 : 11}px system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const labelY = n.py + n.radius + 6;

        // Label background
        const labelText = n.label;
        const labelM = ctx.measureText(labelText);
        const labelW = labelM.width + 8;
        const labelH = 16;
        ctx.fillStyle = 'rgba(8,12,28,0.8)';
        ctx.beginPath();
        ctx.roundRect(n.px - labelW / 2, labelY - 2, labelW, labelH, 4);
        ctx.fill();

        ctx.fillStyle = isHovered ? '#ffffff' : hexToRgba('#c8d4e8', 0.9);
        ctx.fillText(labelText, n.px, labelY);

        ctx.restore();
      }

      // --- Tooltip ---
      if (hoveredNode) {
        const tipX = hoveredNode.px + hoveredNode.radius + 12;
        const tipY = hoveredNode.py - 40;
        const tw = 160;
        const th = 78;
        const tx = Math.min(tipX, width - tw - 10);
        const ty = Math.max(5, Math.min(tipY, height - th - 5));

        ctx.save();
        // Tooltip background (liquid glass style)
        ctx.fillStyle = 'rgba(10,15,35,0.88)';
        ctx.strokeStyle = 'rgba(100,150,255,0.25)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(tx, ty, tw, th, 8);
        ctx.fill();
        ctx.stroke();

        // Title
        ctx.font = '600 12px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillStyle = '#ffffff';
        ctx.fillText(hoveredNode.label, tx + 10, ty + 8);

        // Role
        ctx.font = '10px system-ui, sans-serif';
        ctx.fillStyle = 'rgba(180,200,230,0.7)';
        ctx.fillText(
          `Role: ${hoveredNode.role}`,
          tx + 10,
          ty + 24
        );

        // Status with color
        ctx.fillStyle = NODE_COLORS[hoveredNode.status] || '#6b7280';
        ctx.fillText(
          `Status: ${hoveredNode.status}`,
          tx + 10,
          ty + 38
        );

        // Message count
        ctx.fillStyle = 'rgba(180,200,230,0.7)';
        ctx.fillText(
          `Msgs: ${hoveredNode.messageCount.toLocaleString()}`,
          tx + 10,
          ty + 52
        );

        ctx.restore();

        // Update react tooltip state for any DOM-based tooltip needs
        if (!tooltipRef.current.visible || tooltipRef.current.node?.id !== hoveredNode.id) {
          tooltipRef.current = {
            visible: true,
            x: mx,
            y: my,
            node: hoveredNode,
          };
          setTooltip(tooltipRef.current);
        }
      } else {
        if (tooltipRef.current.visible) {
          tooltipRef.current = { visible: false, x: 0, y: 0, node: null };
          setTooltip(tooltipRef.current);
        }
      }

      animFrameRef.current = requestAnimationFrame(animate);
    };

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animFrameRef.current);
      resizeObserver.disconnect();
      canvas.removeEventListener('mousemove', handleMouseMove);
      canvas.removeEventListener('mouseleave', handleMouseLeave);
      canvas.removeEventListener('click', handleClick);
    };
  }, [initPhysics, applyForces, onNodeClick, propPulseMessages]);

  // Re-init physics when nodes/edges change
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      initPhysics(rect.width, rect.height);
    }
  }, [propNodes, propEdges, initPhysics]);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '300px',
        background: 'rgba(0,0,0,0.3)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderRadius: '12px',
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,0.08)',
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          display: 'block',
          width: '100%',
          height: '100%',
          cursor: 'crosshair',
        }}
      />
      {/* Optional DOM tooltip overlay */}
      {tooltip.visible && tooltip.node && (
        <div
          style={{
            position: 'absolute',
            left: tooltip.x + 20,
            top: tooltip.y - 10,
            pointerEvents: 'none',
            zIndex: 10,
          }}
        />
      )}
    </div>
  );
};

export default DeviceTopologyGraph;
