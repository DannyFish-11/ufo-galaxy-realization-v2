/**
 * Galaxy TypeScript API 客户端
 * ============================
 * 
 * 类型安全的 API 调用
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

/**
 * Galaxy API 客户端
 */
export class GalaxyAPI {
  private baseUrl: string;
  private ws: WebSocket | null = null;

  constructor(baseUrl: string = 'http://localhost:8085') {
    this.baseUrl = baseUrl;
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
  // WebSocket
  // ===========================================================================

  /**
   * 连接 WebSocket
   */
  connectWebSocket(onMessage: (data: WSMessage) => void): void {
    const wsUrl = this.baseUrl.replace('http://', 'ws://').replace('https://', 'wss://');
    this.ws = new WebSocket(`${wsUrl}/ws`);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSMessage;
        onMessage(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      // 自动重连
      setTimeout(() => this.connectWebSocket(onMessage), 5000);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
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

// 默认实例
export const galaxyAPI = new GalaxyAPI();
