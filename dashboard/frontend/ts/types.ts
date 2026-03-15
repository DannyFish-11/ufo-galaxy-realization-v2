/**
 * Galaxy TypeScript 类型定义
 * =========================
 * 
 * 前后端共享的类型定义
 */

// ============================================================================
// 系统类型
// ============================================================================

export interface SystemInfo {
  name: string;
  version: string;
  description: string;
  ascii: string;
  features: SystemFeatures;
  nodes: number;
  code_lines: number;
  timestamp: string;
}

export interface SystemFeatures {
  ai_driven: boolean;
  multi_device: boolean;
  autonomous_learning: boolean;
  visual_understanding: boolean;
  self_programming: boolean;
  digital_twin: boolean;
}

// ============================================================================
// 设备类型
// ============================================================================

export type DevicePlatform = 'android' | 'windows' | 'macos' | 'linux' | 'ios' | 'tablet';

export type DeviceStatus = 'online' | 'offline' | 'busy' | 'idle' | 'error';

export interface Device {
  device_id: string;
  platform: DevicePlatform;
  name: string;
  status: DeviceStatus;
  capabilities: string[];
  registered_at: string;
}

export interface DeviceRegisterRequest {
  device_id: string;
  device_type: DevicePlatform;
  device_name: string;
}

// ============================================================================
// Agent 类型
// ============================================================================

export type TaskComplexity = 'low' | 'medium' | 'high' | 'critical';

export type AgentState = 'created' | 'running' | 'completed' | 'failed';

export interface AgentPermissions {
  filesystem: boolean;
  terminal: boolean;
  network: boolean;
  browser: boolean;
}

export interface Agent {
  agent_id: string;
  name: string;
  task: string;
  task_type: string;
  state: AgentState;
  complexity: TaskComplexity;
  llm_provider: string;
  device_id: string;
  target_device_id: string;
  permissions?: AgentPermissions;
}

// ============================================================================
// LLM 类型
// ============================================================================

export interface LLMProvider {
  provider: string;
  model: string;
  models?: string[];
  speed_score: number;
  quality_score: number;
  available: boolean;
  multimodal?: boolean;
  missing_env_key?: string;
}

// ============================================================================
// 孪生模型类型
// ============================================================================

export type CouplingMode = 'tight' | 'loose' | 'decoupled';

export interface AgentTwin {
  twin_id: string;
  agent_id: string;
  coupling_mode: CouplingMode;
  snapshot: Record<string, any>;
  behavior_history: BehaviorRecord[];
}

export interface BehaviorRecord {
  timestamp: string;
  update: Record<string, any>;
}

// ============================================================================
// 聊天类型
// ============================================================================

export interface ChatRequest {
  message: string;
  device_id?: string;
}

export interface ChatResponse {
  response: string;
  agent?: {
    id: string;
    llm: string;
  };
  executed?: boolean;
  timestamp: string;
}

// ============================================================================
// WebSocket 类型
// ============================================================================

export interface WSMessage {
  type: 'ping' | 'pong' | 'chat' | 'chat_response' | 'status_update'
    | 'capability_update' | 'device_update' | 'agent_update' | 'mcp_update' | 'skill_update'
    | 'connected' | 'device_connected' | 'device_disconnected' | 'device_status_update'
    | 'initial_status' | string;
  content?: string;
  data?: any;
  timestamp?: string;
}

// ============================================================================
// API 响应类型
// ============================================================================

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

// ============================================================================
// 多设备操作类型
// ============================================================================

export interface DeviceCommand {
  device_id: string;
  action: DeviceAction;
  params: Record<string, any>;
}

export type DeviceAction = 
  | 'click'
  | 'input'
  | 'scroll'
  | 'screenshot'
  | 'open_app'
  | 'press_key';

export interface ParallelExecuteRequest {
  commands: DeviceCommand[];
}

export interface ParallelExecuteResponse {
  success: boolean;
  results: Record<string, any>;
}

// ============================================================================
// MCP / 协议类型
// ============================================================================

export interface MCPServer {
  name: string;
  url: string;
  status: 'online' | 'offline' | 'error';
  tools_count: number;
}

export interface MCPTool {
  name: string;
  description: string;
  parameters: Record<string, any>;
  server_name: string;
}

export interface SkillInstance {
  name: string;
  version: string;
  status: 'loaded' | 'available' | 'loading';
  description: string;
}

// ============================================================================
// 设备节点类型
// ============================================================================

export interface DeviceNode {
  device_id: string;
  device_type: string;
  device_name: string;
  online: boolean;
  status: string;
  last_seen: string;
  capabilities: string[];
  metrics: Record<string, any>;
}

// ============================================================================
// 孪生命令配置
// ============================================================================

export interface TwinCommandConfig {
  task: string;
  strategy: string;
  member_count: number;
  providers: string[];
}

// ============================================================================
// 可观测性 / 实时状态面板类型
// ============================================================================

export interface CapabilityTool {
  name: string;
  source: string;
}

export interface CapabilityLoadStatus {
  count: number;
  tools: CapabilityTool[];
  error: string | null;
}

export interface GatewayStats {
  [key: string]: any;
}

export interface GatewayTrace {
  stats: GatewayStats;
  recent_calls: any[];
  error: string | null;
}

export interface DeviceHealthEntry {
  device_id: string;
  device_type: string;
  online: boolean;
  status: string;
  last_seen: string;
}

export interface DeviceHealth {
  registered: number;
  online: number;
  devices: DeviceHealthEntry[];
  error: string | null;
}

export interface ModelRouteStatus {
  default_model: string | null;
  active_provider: string | null;
  fallbacks: any[];
  router_stats?: any;
  error: string | null;
}

export interface ChannelEntry {
  enabled: boolean;
  reachable: boolean;
  error: string | null;
}

export interface NatsStatus {
  configured: boolean;
  url: string | null;
  connected: boolean;
  error: string | null;
}

export interface TailscaleStatus {
  enabled: boolean;
  host: string | null;
}

export interface LegacyProtocolStatus {
  enabled: boolean;
  note: string;
}

export interface ChannelStatus {
  nats: NatsStatus;
  tailscale: TailscaleStatus;
  webrtc: ChannelEntry;
  mqtt: ChannelEntry;
  scrcpy: ChannelEntry;
  legacy_protocols: LegacyProtocolStatus;
}

export interface LiveStatus {
  timestamp: number;
  observability_available: boolean;
  capability_load: CapabilityLoadStatus;
  gateway_trace: GatewayTrace;
  device_health: DeviceHealth;
  model_route: ModelRouteStatus;
  channel_status?: ChannelStatus;
}

// ============================================================================
// 提供商健康详情
// ============================================================================

export interface ProviderHealthDetail {
  provider: string;
  status: string;
  latency_avg_ms: number;
  error_rate: number;
  circuit_breaker_state: string;
  model: string;
  supports_tools: boolean;
  supports_json_mode: boolean;
  supports_vision: boolean;
  calls_count: number;
  tokens_used: number;
  total_cost: number;
}
