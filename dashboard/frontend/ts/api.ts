/**
 * Galaxy TypeScript API 客户端
 * ============================
 * 
 * 类型安全的 API 调用
 *
 * API 基址解析优先级（高→低）：
 *   1. window.__GALAXY_API_BASE__       — 由后端模板注入（最高优先级）
 *   2. window.__GALAXY_CONFIG__.api_base — 由后端配置块注入
 *   3. runtime/entrypoint.json 动态拉取  — 由 unified_launcher 写入
 *   4. 硬编码默认值 http://localhost:9000 — fallback（与 unified_launcher 默认端口一致）
 */

import type {
  SystemInfo,
  Device,
  DeviceRegisterRequest,
  Agent,
  AgentPermissions,
  LLMProvider,
  ChatRequest,
  ChatResponse,
  WSMessage,
  DeviceCommand,
  ParallelExecuteResponse,
  LiveStatus,
} from './types';

// 扩展 Window 接口，支持后端注入的全局配置
declare global {
  interface Window {
    /** 后端模板直接注入的 API 基址（最高优先级） */
    __GALAXY_API_BASE__?: string;
    /** 后端注入的完整配置块 */
    __GALAXY_CONFIG__?: { api_base?: string; [key: string]: unknown };
  }
}

/** 默认 Galaxy API 基址，与 unified_launcher / port_config.py 保持一致（端口 9000） */
const _DEFAULT_API_BASE = 'http://localhost:9000';

/**
 * 解析 Galaxy API 基址。
 *
 * 优先级（高→低）：
 *   1. window.__GALAXY_API_BASE__       — 后端模板注入
 *   2. window.__GALAXY_CONFIG__.api_base — 后端配置块
 *   3. 硬编码默认值（同步 fallback）
 *
 * 若需要同时读取 runtime/entrypoint.json，请使用异步工厂
 * {@link GalaxyAPI.create}。
 */
function resolveApiBase(): string {
  if (typeof window !== 'undefined') {
    const injected = window.__GALAXY_API_BASE__?.trim();
    if (injected) return injected.replace(/\/$/, '');

    const cfgBase = window.__GALAXY_CONFIG__?.api_base?.trim();
    if (cfgBase) return cfgBase.replace(/\/$/, '');
  }
  return _DEFAULT_API_BASE;
}

/**
 * Galaxy API 客户端
 */
export class GalaxyAPI {
  private baseUrl: string;
  private ws: WebSocket | null = null;

  /**
   * @param baseUrl - API 基址。若不传，使用 {@link resolveApiBase} 自动解析。
   */
  constructor(baseUrl?: string) {
    this.baseUrl = (baseUrl ?? resolveApiBase()).replace(/\/$/, '');
  }

  /**
   * 异步工厂方法：创建 GalaxyAPI 实例，自动解析 API 基址。
   *
   * 解析顺序（高→低）：
   *   1. window.__GALAXY_API_BASE__
   *   2. window.__GALAXY_CONFIG__.api_base
   *   3. runtime/entrypoint.json（由 unified_launcher 写入）
   *   4. 默认值 http://localhost:9000
   */
  static async create(): Promise<GalaxyAPI> {
    // 优先使用同步来源
    const syncBase = resolveApiBase();
    if (syncBase !== _DEFAULT_API_BASE) {
      return new GalaxyAPI(syncBase);
    }

    // 尝试从 runtime/entrypoint.json 获取（由 unified_launcher 启动时写入）
    try {
      const resp = await fetch('/runtime/entrypoint.json', { cache: 'no-store' });
      if (resp.ok) {
        const data = await resp.json() as { api_base?: string };
        if (data?.api_base) {
          return new GalaxyAPI(data.api_base.replace(/\/$/, ''));
        }
      }
    } catch {
      // entrypoint.json 不可用时静默降级
    }

    return new GalaxyAPI(syncBase);
  }

  // ===========================================================================
  // 系统 API
  // ===========================================================================

  /**
   * 获取系统信息
   */
  async getSystemInfo(): Promise<SystemInfo> {
    const response = await fetch(`${this.baseUrl}/api/v1/system/info`);
    return response.json();
  }

  /**
   * 获取 ASCII 艺术字
   */
  async getAsciiArt(style: 'minimal' | 'normal' | 'large' = 'minimal'): Promise<{ ascii: string }> {
    const response = await fetch(`${this.baseUrl}/api/v1/ascii?style=${style}`);
    return response.json();
  }

  // ===========================================================================
  // 聊天 API
  // ===========================================================================

  /**
   * 发送聊天消息
   */
  async chat(message: string, deviceId?: string): Promise<ChatResponse> {
    const response = await fetch(`${this.baseUrl}/api/v1/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, device_id: deviceId } as ChatRequest),
    });
    return response.json();
  }

  // ===========================================================================
  // 设备 API
  // ===========================================================================

  /**
   * 获取设备列表
   */
  async getDevices(): Promise<{ devices: Device[] }> {
    const response = await fetch(`${this.baseUrl}/api/v1/devices`);
    return response.json();
  }

  /**
   * 注册设备
   */
  async registerDevice(request: DeviceRegisterRequest): Promise<{ status: string; device: Device }> {
    const response = await fetch(`${this.baseUrl}/api/v1/devices/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    return response.json();
  }

  // ===========================================================================
  // Agent API
  // ===========================================================================

  /**
   * 获取 Agent 列表
   */
  async getAgents(): Promise<{ agents: Agent[] }> {
    const response = await fetch(`${this.baseUrl}/api/v1/agents`);
    return response.json();
  }

  /**
   * 获取 LLM 提供商列表
   */
  async getLLMProviders(): Promise<{ providers: LLMProvider[] }> {
    const response = await fetch(`${this.baseUrl}/api/v1/llm/providers`);
    return response.json();
  }

  /**
   * 从模板创建 Agent（含权限）
   */
  async createAgent(template: string, permissions: AgentPermissions): Promise<{ success: boolean; agent: Agent }> {
    const response = await fetch(`${this.baseUrl}/api/v1/agents/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template, permissions }),
    });
    return response.json();
  }

  /**
   * 动态生成 Agent（含权限）
   */
  async createAgentDynamic(taskDescription: string, permissions: AgentPermissions): Promise<{ success: boolean; agent: Agent }> {
    const response = await fetch(`${this.baseUrl}/api/v1/agents/create/dynamic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_description: taskDescription, permissions }),
    });
    return response.json();
  }

  // ===========================================================================
  // 多设备操作 API
  // ===========================================================================

  /**
   * 并行执行多设备命令
   */
  async executeParallel(commands: DeviceCommand[]): Promise<ParallelExecuteResponse> {
    const response = await fetch(`${this.baseUrl}/api/v1/execute/parallel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ commands }),
    });
    return response.json();
  }

  // ===========================================================================
  // WebSocket & SSE 实时状态订阅 (PR4)
  // ===========================================================================

  /**
   * 连接 WebSocket（实时状态频道 /ws/status）
   *
   * 服务端通过此端点推送：
   *   capability_update, device_update, agent_update, mcp_update, skill_update
   *   以及原有的 device_connected / device_status_update 等事件。
   *
   * 如果 WebSocket 不可用（网络/代理限制），可改用 {@link connectSSE}。
   */
  connectWebSocket(onMessage: (data: WSMessage) => void): void {
    const wsUrl = this.baseUrl.replace('http://', 'ws://').replace('https://', 'wss://');
    // 连接到统一状态频道 /ws/status（推送 capability_update / device_update 等实时事件）
    this.ws = new WebSocket(`${wsUrl}/ws/status`);

    this.ws.onopen = () => {
      console.log('[Galaxy] WebSocket connected to /ws/status');
      // Send ping to confirm channel is alive
      this.sendWSMessage({ type: 'ping' });
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSMessage;
        onMessage(data);
      } catch (e) {
        console.error('[Galaxy] Failed to parse WebSocket message:', e);
      }
    };

    this.ws.onclose = () => {
      console.log('[Galaxy] WebSocket disconnected, retrying in 5s…');
      // 自动重连（优雅降级）
      setTimeout(() => this.connectWebSocket(onMessage), 5000);
    };

    this.ws.onerror = (error) => {
      console.error('[Galaxy] WebSocket error:', error);
    };
  }

  /**
   * 通过 SSE 订阅实时事件（WebSocket 不可用时的降级方案）
   *
   * 服务端端点：GET /api/v1/stream
   * 推送：capability_update, device_update, agent_update, mcp_update, skill_update
   *
   * @param onMessage - 每次收到事件时的回调（与 connectWebSocket 使用相同的 WSMessage 类型）
   * @returns 关闭函数 —— 调用后断开 SSE 连接
   */
  connectSSE(onMessage: (data: WSMessage) => void): () => void {
    const url = `${this.baseUrl}/api/v1/stream`;
    let es: EventSource;
    let closed = false;

    const connect = () => {
      if (closed) return;
      es = new EventSource(url);

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSMessage;
          onMessage(data);
        } catch (e) {
          console.error('[Galaxy] Failed to parse SSE message:', e);
        }
      };

      es.onerror = () => {
        if (!closed) {
          es.close();
          // Retry after 5 seconds on error (consistent with WebSocket reconnect delay)
          setTimeout(connect, 5_000);
        }
      };
    };

    connect();

    return () => {
      closed = true;
      if (es) es.close();
    };
  }

  /**
   * 订阅实时状态更新（自动选择 WebSocket 或 SSE）
   *
   * 优先尝试 WebSocket（/ws/status）；若浏览器不支持 WebSocket（极少见），
   * 则降级到 SSE（/api/v1/stream）。
   *
   * @param onMessage - 实时事件回调
   * @returns 取消订阅函数
   */
  subscribeUpdates(onMessage: (data: WSMessage) => void): () => void {
    if (typeof WebSocket !== 'undefined') {
      this.connectWebSocket(onMessage);
      return () => this.disconnectWebSocket();
    }
    // Fallback: SSE
    return this.connectSSE(onMessage);
  }

  /**
   * 发送 WebSocket 消息
   */
  sendWSMessage(message: WSMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  /**
   * 断开 WebSocket
   */
  disconnectWebSocket(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  // ===========================================================================
  // 可观测性 / 实时状态面板 API
  // ===========================================================================

  /**
   * 获取实时状态面板聚合数据（一次调用，涵盖能力加载、网关追踪、设备健康、模型路由）
   */
  async getLiveStatus(): Promise<LiveStatus> {
    const response = await fetch(`${this.baseUrl}/api/v1/observability/live-status`);
    return response.json();
  }

  /**
   * 获取活跃 LLM 路由及 Fallback 状态
   */
  async getModelRouteStatus(): Promise<any> {
    const response = await fetch(`${this.baseUrl}/api/v1/observability/model-route`);
    return response.json();
  }

  /**
   * 获取网关及设备在线状态汇总
   */
  async getGatewayStatus(): Promise<any> {
    const response = await fetch(`${this.baseUrl}/api/v1/observability/gateway`);
    return response.json();
  }

  /**
   * 获取近期工具 / 设备调用记录
   */
  async getRecentCalls(limit: number = 20): Promise<{ count: number; calls: any[] }> {
    const response = await fetch(
      `${this.baseUrl}/api/v1/observability/recent-calls?limit=${limit}`
    );
    return response.json();
  }

  /**
   * 获取可观测性统计信息
   */
  async getObservabilityStats(): Promise<any> {
    const response = await fetch(`${this.baseUrl}/api/v1/observability/stats`);
    return response.json();
  }
}

// 默认实例（同步解析，优先使用注入的全局配置；需要异步解析请用 GalaxyAPI.create()）
export const galaxyAPI = new GalaxyAPI();
