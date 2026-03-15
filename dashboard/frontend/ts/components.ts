/**
 * Galaxy TypeScript 前端组件
 * ==========================
 * 
 * 类型安全的前端组件
 */

import type { Device, Agent, LLMProvider, LiveStatus, ChannelStatus } from './types';
import { galaxyAPI } from './api';

/**
 * ASCII 艺术字组件
 */
export class AsciiArtComponent {
  private container: HTMLElement;
  private style: 'minimal' | 'normal' | 'large';

  constructor(container: HTMLElement, style: 'minimal' | 'normal' | 'large' = 'minimal') {
    this.container = container;
    this.style = style;
  }

  async render(): Promise<void> {
    try {
      const { ascii } = await galaxyAPI.getAsciiArt(this.style);
      this.container.innerHTML = `<pre class="ascii-art">${ascii}</pre>`;
    } catch (error) {
      console.error('Failed to load ASCII art:', error);
    }
  }
}

/**
 * 系统状态组件
 */
export class SystemStatusComponent {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async render(): Promise<void> {
    try {
      const info = await galaxyAPI.getSystemInfo();
      this.container.innerHTML = `
        <div class="system-status">
          <h2>${info.name} v${info.version}</h2>
          <p>${info.description}</p>
          <div class="features">
            ${Object.entries(info.features)
              .filter(([_, enabled]) => enabled)
              .map(([name, _]) => `<span class="feature">✅ ${name}</span>`)
              .join('')}
          </div>
          <div class="stats">
            <span>节点: ${info.nodes}</span>
            <span>代码: ${info.code_lines.toLocaleString()} 行</span>
          </div>
        </div>
      `;
    } catch (error) {
      console.error('Failed to load system status:', error);
    }
  }
}

/**
 * 设备列表组件
 */
export class DeviceListComponent {
  private container: HTMLElement;
  private devices: Device[] = [];

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async load(): Promise<void> {
    try {
      const { devices } = await galaxyAPI.getDevices();
      this.devices = devices;
    } catch (error) {
      console.error('Failed to load devices:', error);
    }
  }

  render(): void {
    if (this.devices.length === 0) {
      this.container.innerHTML = '<p class="no-devices">没有已连接的设备</p>';
      return;
    }

    this.container.innerHTML = `
      <div class="device-list">
        ${this.devices.map(device => `
          <div class="device-card ${device.status}">
            <span class="device-icon">${this.getDeviceIcon(device.platform)}</span>
            <div class="device-info">
              <span class="device-name">${device.name}</span>
              <span class="device-platform">${device.platform}</span>
            </div>
            <span class="device-status ${device.status}">${device.status}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  private getDeviceIcon(platform: string): string {
    const icons: Record<string, string> = {
      android: '📱',
      windows: '💻',
      macos: '🍎',
      linux: '🐧',
      ios: '📱',
      tablet: '📲',
    };
    return icons[platform] || '📟';
  }
}

/**
 * Agent 列表组件
 */
export class AgentListComponent {
  private container: HTMLElement;
  private agents: Agent[] = [];

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async load(): Promise<void> {
    try {
      const { agents } = await galaxyAPI.getAgents();
      this.agents = agents;
    } catch (error) {
      console.error('Failed to load agents:', error);
    }
  }

  render(): void {
    if (this.agents.length === 0) {
      this.container.innerHTML = '<p class="no-agents">没有活动的 Agent</p>';
      return;
    }

    this.container.innerHTML = `
      <div class="agent-list">
        ${this.agents.map(agent => `
          <div class="agent-card ${agent.state}">
            <div class="agent-header">
              <span class="agent-name">${agent.name}</span>
              <span class="agent-state ${agent.state}">${agent.state}</span>
            </div>
            <div class="agent-details">
              <span class="agent-task">${agent.task}</span>
              <span class="agent-llm">LLM: ${agent.llm_provider}</span>
              <span class="agent-complexity">复杂度: ${agent.complexity}</span>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }
}

/**
 * 聊天组件
 */
export class ChatComponent {
  private container: HTMLElement;
  private messages: Array<{ role: 'user' | 'assistant'; content: string }> = [];
  private inputElement: HTMLInputElement | null = null;
  private messagesElement: HTMLElement | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    this.container.innerHTML = `
      <div class="chat-container">
        <div class="chat-messages" id="chat-messages"></div>
        <div class="chat-input-container">
          <input type="text" id="chat-input" placeholder="输入消息..." />
          <button id="chat-send">发送</button>
        </div>
      </div>
    `;

    this.messagesElement = this.container.querySelector('#chat-messages');
    this.inputElement = this.container.querySelector('#chat-input');
    const sendButton = this.container.querySelector('#chat-send');

    if (sendButton && this.inputElement) {
      sendButton.addEventListener('click', () => this.sendMessage());
      this.inputElement.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') this.sendMessage();
      });
    }
  }

  private async sendMessage(): Promise<void> {
    if (!this.inputElement || !this.messagesElement) return;

    const message = this.inputElement.value.trim();
    if (!message) return;

    // 添加用户消息
    this.messages.push({ role: 'user', content: message });
    this.renderMessages();
    this.inputElement.value = '';

    try {
      // 发送到后端
      const response = await galaxyAPI.chat(message);
      
      // 添加助手消息
      this.messages.push({ role: 'assistant', content: response.response });
      this.renderMessages();
    } catch (error) {
      this.messages.push({ role: 'assistant', content: '❌ 发生错误，请重试。' });
      this.renderMessages();
    }
  }

  private renderMessages(): void {
    if (!this.messagesElement) return;

    this.messagesElement.innerHTML = this.messages.map(msg => `
      <div class="chat-message ${msg.role}">
        <div class="message-content">${this.escapeHtml(msg.content)}</div>
      </div>
    `).join('');

    // 滚动到底部
    this.messagesElement.scrollTop = this.messagesElement.scrollHeight;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

/**
 * LLM 提供商组件
 */
export class LLMProviderComponent {
  private container: HTMLElement;
  private providers: LLMProvider[] = [];

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async load(): Promise<void> {
    try {
      const { providers } = await galaxyAPI.getLLMProviders();
      this.providers = providers;
    } catch (error) {
      console.error('Failed to load LLM providers:', error);
    }
  }

  render(): void {
    this.container.innerHTML = `
      <div class="llm-providers">
        ${this.providers.map(provider => `
          <div class="provider-card ${provider.available ? 'available' : 'unavailable'}">
            <div class="provider-header">
              <span class="provider-status">${provider.available ? '🟢' : '⚫'}</span>
              <span class="provider-name">${provider.provider}</span>
              ${provider.multimodal ? '<span class="provider-badge multimodal" title="原生多模态（图像/音频/视频）">👁 多模态</span>' : ''}
            </div>
            <span class="provider-model">${provider.model}</span>
            <div class="provider-scores">
              <span>速度: ${provider.speed_score}/10</span>
              <span>质量: ${provider.quality_score}/10</span>
            </div>
            ${!provider.available && provider.missing_env_key
              ? `<div class="provider-missing-key" title="在 .env 文件中设置此变量以启用">
                   ⚠️ 需配置: <code>${provider.missing_env_key}</code>
                 </div>`
              : ''}
          </div>
        `).join('')}
      </div>
    `;
  }
}

/**
 * 实时状态面板组件
 *
 * 轮询 /api/v1/observability/live-status 并展示：
 *   - 能力加载状态（CapabilityRegistry 工具数量）
 *   - 网关追踪统计（CommandRouter 路由数 + 近期 3 条调用）
 *   - 设备健康（注册数 / 在线数）
 *   - 活跃模型路由
 */
export class LiveStatusPanel {
  private container: HTMLElement;
  private pollInterval: number;
  private timerId: ReturnType<typeof setInterval> | null = null;
  private status: LiveStatus | null = null;
  private errorMessage: string | null = null;

  /**
   * @param container   挂载面板的 DOM 元素
   * @param pollInterval 轮询间隔（毫秒，默认 5000）
   */
  constructor(container: HTMLElement, pollInterval: number = 5000) {
    this.container = container;
    this.pollInterval = pollInterval;
  }

  /** 启动自动轮询并立即渲染一次 */
  start(): void {
    this.fetch();
    this.timerId = setInterval(() => this.fetch(), this.pollInterval);
  }

  /** 停止轮询 */
  stop(): void {
    if (this.timerId !== null) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
  }

  private async fetch(): Promise<void> {
    try {
      this.status = await galaxyAPI.getLiveStatus();
      this.errorMessage = null;
    } catch (err) {
      this.errorMessage = err instanceof Error ? err.message : String(err);
    }
    this.render();
  }

  private render(): void {
    if (this.errorMessage) {
      this.container.innerHTML = `
        <div class="live-status-panel error">
          <p class="live-status-error">⚠️ 实时状态加载失败: ${this.escapeHtml(this.errorMessage)}</p>
        </div>`;
      return;
    }

    if (!this.status) {
      this.container.innerHTML = `<div class="live-status-panel loading"><p>加载中…</p></div>`;
      return;
    }

    const s = this.status;
    const updated = new Date(s.timestamp * 1000).toLocaleTimeString();

    this.container.innerHTML = `
      <div class="live-status-panel">
        <div class="live-status-header">
          <h3>🔴 实时状态面板</h3>
          <span class="live-status-updated">更新于 ${updated}</span>
        </div>

        <div class="live-status-grid">

          <!-- 能力加载 -->
          <div class="live-status-card ${s.capability_load.error ? 'card-error' : 'card-ok'}">
            <div class="card-title">⚡ 能力加载</div>
            ${s.capability_load.error
              ? `<p class="card-error-msg">${this.escapeHtml(s.capability_load.error)}</p>`
              : `<div class="card-stat">${s.capability_load.count} 个工具已注册</div>
                 <ul class="card-list">
                   ${s.capability_load.tools.slice(0, 5).map(t =>
                     `<li><span class="tool-name">${this.escapeHtml(t.name)}</span>
                          <span class="tool-source">[${this.escapeHtml(t.source)}]</span></li>`
                   ).join('')}
                   ${s.capability_load.count > 5
                     ? `<li class="more">…还有 ${s.capability_load.count - 5} 个</li>`
                     : ''}
                 </ul>`
            }
          </div>

          <!-- 网关追踪 -->
          <div class="live-status-card ${s.gateway_trace.error ? 'card-error' : 'card-ok'}">
            <div class="card-title">🌐 网关追踪</div>
            ${s.gateway_trace.error
              ? `<p class="card-error-msg">${this.escapeHtml(s.gateway_trace.error)}</p>`
              : `<div class="card-stat">
                   路由总数: ${s.gateway_trace.stats['total_routed'] ?? '—'}
                 </div>
                 <ul class="card-list">
                   ${s.gateway_trace.recent_calls.slice(0, 3).map((c: any) =>
                     `<li>${this.escapeHtml(c.command_id ?? '?')} → ${this.escapeHtml(c.status ?? '?')}</li>`
                   ).join('')}
                 </ul>`
            }
          </div>

          <!-- 设备健康 -->
          <div class="live-status-card ${s.device_health.error ? 'card-error' : 'card-ok'}">
            <div class="card-title">📱 设备健康</div>
            ${s.device_health.error
              ? `<p class="card-error-msg">${this.escapeHtml(s.device_health.error)}</p>`
              : `<div class="card-stat">
                   注册: ${s.device_health.registered} &nbsp;|&nbsp;
                   在线: <span class="online-count">${s.device_health.online}</span>
                 </div>
                 <ul class="card-list">
                   ${s.device_health.devices.slice(0, 5).map(d =>
                     `<li>
                       <span class="device-status-dot ${d.online ? 'dot-online' : 'dot-offline'}">●</span>
                       ${this.escapeHtml(d.device_id)} (${this.escapeHtml(d.device_type)})
                     </li>`
                   ).join('')}
                   ${s.device_health.registered > 5
                     ? `<li class="more">…还有 ${s.device_health.registered - 5} 台</li>`
                     : ''}
                 </ul>`
            }
          </div>

          <!-- 模型路由 -->
          <div class="live-status-card ${s.model_route.error ? 'card-error' : 'card-ok'}">
            <div class="card-title">🤖 模型路由</div>
            ${s.model_route.error
              ? `<p class="card-error-msg">${this.escapeHtml(s.model_route.error)}</p>`
              : `<div class="card-stat">
                   活跃: ${this.escapeHtml(s.model_route.active_provider ?? '—')}
                 </div>
                 <div class="card-detail">
                   默认模型: ${this.escapeHtml(s.model_route.default_model ?? '—')}
                 </div>
                 ${s.model_route.fallbacks.length > 0
                   ? `<div class="card-detail">
                        Fallback: ${s.model_route.fallbacks.map((f: any) =>
                          this.escapeHtml(f.provider ?? f)
                        ).join(', ')}
                      </div>`
                   : ''}`
            }
          </div>

          <!-- 通信通道状态 -->
          ${s.channel_status ? this.renderChannelStatus(s.channel_status) : ''}

        </div>
      </div>`;
  }

  private renderChannelStatus(ch: ChannelStatus): string {
    const dot = (isHealthy: boolean) => `<span class="${isHealthy ? 'dot-online' : 'dot-offline'}">●</span>`;
    const row = (label: string, isHealthy: boolean, detail: string) =>
      `<li>${dot(isHealthy)} <span>${this.escapeHtml(label)}</span>
         <span class="card-detail" style="margin-left:4px">${this.escapeHtml(detail)}</span></li>`;

    return `
      <div class="live-status-card card-ok">
        <div class="card-title">📡 通信通道状态</div>
        <ul class="card-list">
          ${row(
            'NATS',
            ch.nats.connected,
            ch.nats.configured ? (ch.nats.connected ? '已连接' : (ch.nats.error ?? '未连接')) : '未配置 GALAXY_NATS_URL'
          )}
          ${row(
            'Tailscale',
            ch.tailscale.enabled,
            ch.tailscale.enabled ? (ch.tailscale.host ? `host: ${ch.tailscale.host}` : '已启用') : '未启用 GALAXY_TAILSCALE_ENABLED'
          )}
          ${row(
            'WebRTC',
            ch.webrtc.enabled && ch.webrtc.reachable,
            ch.webrtc.enabled ? (ch.webrtc.reachable ? '节点可达' : (ch.webrtc.error ?? '节点不可达')) : '未启用 GALAXY_ENABLE_WEBRTC'
          )}
          ${row(
            'MQTT',
            ch.mqtt.enabled && ch.mqtt.reachable,
            ch.mqtt.enabled ? (ch.mqtt.reachable ? '节点可达' : (ch.mqtt.error ?? '节点不可达')) : '未启用 GALAXY_ENABLE_MQTT'
          )}
          ${row(
            'Scrcpy',
            ch.scrcpy.enabled && ch.scrcpy.reachable,
            ch.scrcpy.enabled ? (ch.scrcpy.reachable ? '节点可达' : (ch.scrcpy.error ?? '节点不可达')) : '未启用 GALAXY_ENABLE_SCRCPY'
          )}
          ${row(
            'Legacy 协议 (/ws/ufo3)',
            false,
            ch.legacy_protocols.enabled ? '⚠️ 已启用（兼容模式）' : '已禁用（推荐）'
          )}
        </ul>
      </div>`;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
