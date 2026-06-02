/**
 * app.js
 * Galaxy V2 Desktop Presence — 三态状态机
 *
 * 三态：SILENT (静默) / LIMINAL (阈限) / MANIFEST (显现)
 * 纯 CSS 实现，不使用 Three.js
 *
 * 状态转换：
 *   SILENT -> LIMINAL: 后端请求处理中 (phase_change: liminal)
 *   LIMINAL -> MANIFEST: 后端返回结果 (phase_change: manifest)
 *   MANIFEST -> SILENT: 任务完成 / 关闭 (phase_change: silent)
 *   任意 -> SILENT: 重置命令
 *
 * WebSocket: ws://localhost:9000/ws/desktop-presence
 */

// ============================================
// 阶段枚举
// ============================================
const Phase = {
    SILENT: 'silent',
    LIMINAL: 'liminal',
    MANIFEST: 'manifest'
};

// ============================================
// 三态管理器
// ============================================
class ThreeStateManager {
    constructor() {
        this.currentPhase = Phase.SILENT;
        this.previousPhase = null;
        this.isTransitioning = false;
        this.queuedTransition = null;

        // 各态实例
        this.silentState = null;
        this.liminalState = null;
        this.manifestState = null;

        // WebSocket
        this.ws = null;
        this.wsReconnectInterval = 3000;
        this.wsReconnectTimer = null;
        // WebSocket 端点：Galaxy Gateway 端口 9000
        this.wsUrl = 'ws://localhost:9000/ws/desktop-presence';

        // UI 元素
        this.wsStatusEl = document.getElementById('ws-status');
        this.wsStatusTextEl = document.getElementById('ws-status-text');

        // 动画循环引用
        this._rafId = null;
        this._lastTime = 0;

        this.init();
    }

    // ============================================
    // 初始化
    // ============================================
    init() {
        console.log('[ThreeStateManager] 初始化...');

        // 为各态准备 cssOverlay 对象
        const silentOverlay = { element: document.getElementById('sLayer') };
        const liminalOverlay = { element: document.getElementById('lLayer') };
        const manifestOverlay = { element: document.getElementById('mLayer') };

        // 初始化各态 —— 纯 CSS 实现，不再使用 Three.js
        this.silentState = new SilentState(silentOverlay);
        this.liminalState = new LiminalState(liminalOverlay, null);
        this.manifestState = new ManifestState(manifestOverlay);

        // 启动轻量级动画循环（供需要 update 的态使用）
        this._startRenderLoop();

        // 监听窗口变化
        window.addEventListener('resize', () => this.onWindowResize());

        // 连接 WebSocket
        this.connectWebSocket();

        // 进入初始态
        this.enterState(Phase.SILENT);

        console.log('[ThreeStateManager] 初始化完成，当前阶段:', this.currentPhase);
    }

    // ============================================
    // 轻量级渲染循环
    // ============================================
    _startRenderLoop() {
        const loop = (time) => {
            this._rafId = requestAnimationFrame(loop);
            const deltaTime = Math.min((time - this._lastTime) / 1000, 0.1); // 秒，限制最大步长
            this._lastTime = time;

            if (deltaTime > 0) {
                this.onRenderFrame(deltaTime);
            }
        };
        this._lastTime = performance.now();
        this._rafId = requestAnimationFrame(loop);
    }

    onRenderFrame(deltaTime) {
        // 调用当前态的 update（即使为空也保留接口）
        switch (this.currentPhase) {
            case Phase.SILENT:
                // Silent 纯 CSS，无需 JS 更新
                break;
            case Phase.LIMINAL:
                this.liminalState.update(deltaTime);
                break;
            case Phase.MANIFEST:
                // Manifest 纯 CSS，无需 JS 更新
                break;
        }
    }

    onWindowResize() {
        if (this.silentState) this.silentState.onResize();
        if (this.liminalState) this.liminalState.onResize();
        if (this.manifestState) this.manifestState.onResize();
    }

    // ============================================
    // 状态管理
    // ============================================
    enterState(phase, data = {}) {
        if (this.isTransitioning) {
            console.log('[ThreeStateManager] 转换进行中，排队:', phase);
            this.queuedTransition = { phase, data };
            return;
        }

        this.isTransitioning = true;
        this.previousPhase = this.currentPhase;
        this.currentPhase = phase;

        console.log(`[ThreeStateManager] 转换: ${this.previousPhase} -> ${phase}`, data);

        // 退出当前态
        this.exitCurrentState(this.previousPhase);

        // 短暂延迟后进入新态，给退出动画留出时间
        setTimeout(() => {
            switch (phase) {
                case Phase.SILENT:
                    this.silentState.enter();
                    this.updateWSStatusText(phase);
                    break;

                case Phase.LIMINAL:
                    this.liminalState.enter();
                    this.updateWSStatusText(phase);
                    break;

                case Phase.MANIFEST:
                    this.manifestState.enter();
                    this.updateWSStatusText(phase);
                    break;

                default:
                    console.warn('[ThreeStateManager] 未知阶段:', phase);
                    this.silentState.enter();
                    this.currentPhase = Phase.SILENT;
            }

            this.isTransitioning = false;

            // 处理排队的转换
            if (this.queuedTransition) {
                const queued = this.queuedTransition;
                this.queuedTransition = null;
                this.enterState(queued.phase, queued.data);
            }
        }, 100);
    }

    exitCurrentState(phase) {
        switch (phase) {
            case Phase.SILENT:
                this.silentState.exit();
                break;
            case Phase.LIMINAL:
                this.liminalState.exit();
                break;
            case Phase.MANIFEST:
                this.manifestState.exit();
                break;
            default:
                // 无前态
                break;
        }
    }

    updateWSStatusText(phase) {
        console.log('[ThreeStateManager] 阶段更新:', phase.toUpperCase());
    }

    // ============================================
    // WebSocket 通信
    // ============================================
    connectWebSocket() {
        console.log('[ThreeStateManager] 连接 WebSocket:', this.wsUrl);
        this.updateConnectionStatus('connecting');

        try {
            this.ws = new WebSocket(this.wsUrl);

            this.ws.onopen = () => {
                console.log('[ThreeStateManager] WebSocket 已连接');
                this.updateConnectionStatus('connected');

                if (this.wsReconnectTimer) {
                    clearTimeout(this.wsReconnectTimer);
                    this.wsReconnectTimer = null;
                }

                // 发送注册消息
                this.wsSend({
                    type: 'register',
                    client: 'desktop-presence',
                    version: '2.0.0'
                });
            };

            this.ws.onmessage = (event) => {
                this.handleWebSocketMessage(event.data);
            };

            this.ws.onerror = (error) => {
                console.error('[ThreeStateManager] WebSocket 错误:', error);
                this.updateConnectionStatus('disconnected');
            };

            this.ws.onclose = (event) => {
                console.log('[ThreeStateManager] WebSocket 关闭:', event.code, event.reason);
                this.updateConnectionStatus('disconnected');
                this.scheduleReconnect();
            };

        } catch (err) {
            console.error('[ThreeStateManager] WebSocket 连接失败:', err);
            this.updateConnectionStatus('disconnected');
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        if (this.wsReconnectTimer) return;

        console.log(`[ThreeStateManager] ${this.wsReconnectInterval}ms 后重连...`);
        this.wsReconnectTimer = setTimeout(() => {
            this.wsReconnectTimer = null;
            this.connectWebSocket();
        }, this.wsReconnectInterval);
    }

    wsSend(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    }

    handleWebSocketMessage(data) {
        try {
            const message = JSON.parse(data);
            console.log('[ThreeStateManager] WS 消息:', message);

            const msgType = message.type;

            // AIP v3 STATE_EVENT 格式
            if (msgType === 'state_event') {
                this.handleAIPV3StateEvent(message);
                return;
            }

            // 兼容旧格式
            switch (msgType) {
                case 'phase_change':
                    this.handlePhaseChange(message);
                    break;

                case 'update_result':
                    // 仅更新结果文字，不切换态
                    console.log('[ThreeStateManager] 结果更新:', message.result);
                    break;

                case 'task_result':
                case 'goal_execution_result':
                    console.log('[ThreeStateManager] 任务结果:', message.result || message.data);
                    break;

                case 'ping':
                    this.wsSend({ type: 'pong', timestamp: Date.now() });
                    break;

                case 'heartbeat_ack':
                    console.log('[ThreeStateManager] 心跳 ACK');
                    break;

                case 'status':
                    console.log('[ThreeStateManager] 服务器状态:', message.status);
                    break;

                default:
                    console.log('[ThreeStateManager] 未知消息类型:', msgType);
            }
        } catch (err) {
            console.error('[ThreeStateManager] 解析 WS 消息失败:', err, data);
        }
    }

    // 处理 AIP v3 STATE_EVENT 消息进行态转换
    handleAIPV3StateEvent(message) {
        const category = message.event_category || '';
        const action = message.event_action || '';
        const payload = message.payload || {};

        // 阶段转换
        if (category === 'phase' || category === 'desktop_presence') {
            const phaseMap = {
                'silent': Phase.SILENT,
                'liminal': Phase.LIMINAL,
                'manifest': Phase.MANIFEST,
                'processing': Phase.LIMINAL,
                'completed': Phase.MANIFEST,
                'dismissed': Phase.SILENT,
            };
            const targetPhase = phaseMap[action.toLowerCase()];
            if (targetPhase) {
                this.handlePhaseChange({
                    phase: targetPhase,
                    reason: payload.reason || 'aip_v3_state_event',
                    result: payload.result || payload.message,
                    metadata: payload.metadata || {},
                    force: message.force || false,
                });
            }
            return;
        }

        // 任务生命周期
        if (category === 'task') {
            if (action === 'started' || action === 'assigned') {
                this.enterState(Phase.LIMINAL, { reason: 'task_started' });
            } else if (action === 'completed' || action === 'done') {
                this.enterState(Phase.MANIFEST, {
                    result: this.formatTaskResult(message),
                    reason: 'task_completed'
                });
            } else if (action === 'failed' || action === 'cancelled') {
                const errorText = payload.error || payload.message || '任务失败';
                this.enterState(Phase.MANIFEST, {
                    result: `[错误] ${errorText}`,
                    reason: action
                });
            }
            return;
        }

        // 网格协调事件
        if (category === 'mesh') {
            if (action === 'joined' || action === 'coord_sync') {
                this.enterState(Phase.LIMINAL, { reason: `mesh_${action}` });
            }
            return;
        }

        // 设备生命周期事件
        if (category === 'device' || category === 'state_sync') {
            const deviceId = message.device_id || payload.device_id || 'system';
            if (this.currentPhase === Phase.SILENT) {
                if (['registered', 'unregistered', 'online', 'offline'].includes(action)) {
                    this.enterState(Phase.MANIFEST, {
                        result: `[${deviceId}] ${action}`,
                        reason: 'device_event'
                    });
                    setTimeout(() => this.enterState(Phase.SILENT, { reason: 'auto_dismiss' }), 3000);
                }
            }
            return;
        }

        console.log('[ThreeStateManager] 未处理的 STATE_EVENT:', category, action);
    }

    // 格式化 AIP v3 任务结果
    formatTaskResult(message) {
        const payload = message.payload || {};
        const result = message.result || payload.result || payload.message || '';
        if (typeof result === 'string') return result;
        if (typeof result === 'object') {
            try {
                return JSON.stringify(result, null, 2);
            } catch {
                return String(result);
            }
        }
        return String(result);
    }

    handlePhaseChange(message) {
        const newPhase = message.phase;
        const reason = message.reason || '';

        if (!newPhase || !Object.values(Phase).includes(newPhase)) {
            console.warn('[ThreeStateManager] 无效阶段:', newPhase);
            return;
        }

        // 校验状态转换
        const isValid = this.isValidTransition(this.currentPhase, newPhase);
        if (!isValid) {
            console.warn(
                `[ThreeStateManager] 无效转换: ${this.currentPhase} -> ${newPhase}`
            );
            if (message.force) {
                console.log('[ThreeStateManager] 强制转换允许');
            } else {
                return;
            }
        }

        console.log(`[ThreeStateManager] 阶段切换: ${this.currentPhase} -> ${newPhase} (${reason})`);

        const stateData = {
            result: message.result || message.data,
            reason: reason,
            metadata: message.metadata || {}
        };

        this.enterState(newPhase, stateData);
    }

    isValidTransition(from, to) {
        const transitions = {
            [Phase.SILENT]: [Phase.LIMINAL, Phase.MANIFEST, Phase.SILENT],
            [Phase.LIMINAL]: [Phase.MANIFEST, Phase.SILENT, Phase.LIMINAL],
            [Phase.MANIFEST]: [Phase.SILENT, Phase.LIMINAL, Phase.MANIFEST]
        };
        return transitions[from] && transitions[from].includes(to);
    }

    updateConnectionStatus(status) {
        if (!this.wsStatusEl || !this.wsStatusTextEl) return;

        this.wsStatusEl.className = '';

        switch (status) {
            case 'connected':
                this.wsStatusEl.classList.add('ws-connected');
                this.wsStatusTextEl.textContent = 'ONLINE';
                break;
            case 'connecting':
                this.wsStatusEl.classList.add('ws-connecting');
                this.wsStatusTextEl.textContent = 'CONNECTING';
                break;
            case 'disconnected':
                this.wsStatusEl.classList.add('ws-disconnected');
                this.wsStatusTextEl.textContent = 'OFFLINE';
                break;
        }
    }

    // ============================================
    // 公共 API（手动控制）
    // ============================================
    forcePhase(phase, data = {}) {
        console.log('[ThreeStateManager] 强制切换阶段:', phase);
        this.enterState(phase, { ...data, force: true });
    }

    getCurrentPhase() {
        return this.currentPhase;
    }

    // ============================================
    // 清理
    // ============================================
    dispose() {
        console.log('[ThreeStateManager] 清理中...');

        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }

        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
        }

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        if (this.silentState) this.silentState.dispose();
        if (this.liminalState) this.liminalState.dispose();
        if (this.manifestState) this.manifestState.dispose();
    }
}

// ============================================
// 应用入口
// ============================================
let stateManager = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] DOM 加载完成，初始化 ThreeStateManager...');

    try {
        stateManager = new ThreeStateManager();
        window.stateManager = stateManager;
        console.log('[App] 应用初始化成功');
    } catch (err) {
        console.error('[App] 初始化失败:', err);
    }
});

window.addEventListener('beforeunload', () => {
    if (stateManager) {
        stateManager.dispose();
    }
});

// 开发快捷键：Ctrl+Shift+1/2/3 手动切换三态
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey) {
        switch (e.key) {
            case '1':
                console.log('[App] 开发快捷键: 强制 SILENT');
                if (stateManager) stateManager.forcePhase(Phase.SILENT);
                break;
            case '2':
                console.log('[App] 开发快捷键: 强制 LIMINAL');
                if (stateManager) stateManager.forcePhase(Phase.LIMINAL);
                break;
            case '3':
                console.log('[App] 开发快捷键: 强制 MANIFEST');
                if (stateManager) stateManager.forcePhase(Phase.MANIFEST, {
                    result: 'MANIFEST 态激活\n===================\n\n系统运行正常。\n等待进一步指令。'
                });
                break;
        }
    }
});

console.log('[App] Galaxy V2 Desktop Presence — 应用模块已加载');
