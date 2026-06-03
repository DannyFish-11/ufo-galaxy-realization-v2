/**
 * app.js
 * Galaxy V2 Desktop Presence — 三态状态机主控制器
 *
 * 三态：SILENT (WebGL Shader) / LIMINAL (CSS 3D) / MANIFEST (极简)
 *
 * v18: Liminal改为纯CSS 3D，不再依赖Three.js
 *      Silent保持WebGL Shader不变
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
        this.wsReconnectBaseInterval = 1000;   // 初始重连间隔 1秒
        this.wsReconnectMaxInterval = 30000;   // 最大重连间隔 30秒
        this.wsReconnectAttempts = 0;          // 重连次数（指数退避）
        this.wsReconnectTimer = null;
        this.wsUrl = 'ws://localhost:9000/ws/desktop-presence';

        // UI 元素引用
        this.wsStatusEl = document.getElementById('ws-status');
        this.wsStatusTextEl = document.getElementById('ws-status-text');

        this.init();
    }

    // ============================================
    // 初始化
    // ============================================
    init() {
        console.log('[ThreeStateManager] 初始化 Galaxy V2 三态系统 v18...');

        // 初始化各态
        this.silentState = new SilentState({ element: document.getElementById('sLayer') });
        // v18: LiminalState不再传threeContainer，纯CSS方案
        this.liminalState = new LiminalState({ element: document.getElementById('lLayer') });
        this.manifestState = new ManifestState({ element: document.getElementById('mLayer') });

        // 监听窗口变化
        window.addEventListener('resize', () => this.onWindowResize());

        // 连接 WebSocket
        this.connectWebSocket();

        // 进入初始态（Silent）
        this.enterState(Phase.SILENT);

        console.log('[ThreeStateManager] 初始化完成，当前阶段:', this.currentPhase);
    }

    /** 显示错误信息 */
    // P20 修复：添加唯一 ID，防止重复创建错误元素
    _showError(message) {
        const existing = document.getElementById('app-error-display');
        if (existing) existing.remove();

        const el = document.createElement('div');
        el.id = 'app-error-display';
        el.style.cssText = `
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
            color: rgba(255, 80, 80, 0.8); font-family: monospace; font-size: 14px;
            background: rgba(0, 0, 0, 0.6); padding: 20px; border-radius: 4px;
            z-index: 9999; letter-spacing: 2px; text-align: center;
        `;
        el.textContent = `[ERROR] ${message}`;
        document.body.appendChild(el);
    }

    /** 窗口大小变化 — 通知各态 */
    onWindowResize() {
        // Silent态需要更新WebGL渲染器尺寸
        if (this.silentState) this.silentState.onResize();
        // Liminal和Manifest是纯CSS，自适应无需处理
    }

    // ============================================
    // 状态管理
    // ============================================

    /**
     * 进入指定状态
     */
    enterState(phase, data = {}) {
        if (this.isTransitioning) {
            console.log('[ThreeStateManager] 转换进行中，排队:', phase);
            this.queuedTransition = { phase, data };
            return;
        }

        if (!Object.values(Phase).includes(phase)) {
            console.warn('[ThreeStateManager] 无效阶段:', phase);
            return;
        }

        const isValid = this.isValidTransition(this.currentPhase, phase);
        if (!isValid && !data.force) {
            console.warn(`[ThreeStateManager] 无效转换: ${this.currentPhase} -> ${phase}`);
            return;
        }

        this.isTransitioning = true;
        this.previousPhase = this.currentPhase;
        this.currentPhase = phase;

        console.log(`[ThreeStateManager] 转换: ${this.previousPhase} -> ${phase}`, data);

        // 退出当前态
        this._exitState(this.previousPhase);

        // P4 修复：100ms 延迟确保前一个态的 CSS 过渡开始执行
        setTimeout(() => {
            this._enterState(phase, data);
            this.isTransitioning = false;

            if (this.queuedTransition) {
                const queued = this.queuedTransition;
                this.queuedTransition = null;
                this.enterState(queued.phase, queued.data);
            }
        }, 100);
    }

    /** 进入具体状态 */
    _enterState(phase, data) {
        // P13 修复：根据态控制鼠标穿透
        const mouseIgnore = phase === Phase.LIMINAL ? false : true;
        if (window.electronAPI?.setIgnoreMouse) {
            window.electronAPI.setIgnoreMouse(mouseIgnore);
        }

        switch (phase) {
            case Phase.SILENT:
                // Silent态：桌面壁纸正常显示，鼠标穿透
                document.body.classList.remove('liminal-active');
                this.silentState.enter();
                break;

            case Phase.LIMINAL:
                // Liminal态：桌面背景变暗，空间层透过来，不穿透
                // 注意：silentState.exit() 已在 _exitState() 中调用，无需重复
                document.body.classList.add('liminal-active');
                this.liminalState.enter();
                break;

            case Phase.MANIFEST:
                // Manifest态：鼠标穿透，所有覆盖层淡出
                document.body.classList.remove('liminal-active');
                this.manifestState.enter();
                break;

            default:
                console.warn('[ThreeStateManager] 未知阶段:', phase);
                this.silentState.enter();
        }

        this.updateWSStatusText(phase);
    }

    /** 退出当前状态 */
    _exitState(phase) {
        switch (phase) {
            case Phase.SILENT:
                if (this.silentState) this.silentState.exit();
                break;
            case Phase.LIMINAL:
                if (this.liminalState) this.liminalState.exit();
                break;
            case Phase.MANIFEST:
                if (this.manifestState) this.manifestState.exit();
                break;
            default:
                break;
        }
    }

    /** 验证状态转换 */
    isValidTransition(from, to) {
        const transitions = {
            [Phase.SILENT]: [Phase.LIMINAL, Phase.MANIFEST, Phase.SILENT],
            [Phase.LIMINAL]: [Phase.MANIFEST, Phase.SILENT, Phase.LIMINAL],
            [Phase.MANIFEST]: [Phase.SILENT, Phase.LIMINAL, Phase.MANIFEST]
        };
        return transitions[from] && transitions[from].includes(to);
    }

    /** 更新状态显示文本 */
    updateWSStatusText(phase) {
        if (this.wsStatusTextEl) {
            this.wsStatusTextEl.textContent = phase.toUpperCase();
        }
        console.log('[ThreeStateManager] 当前阶段:', phase.toUpperCase());
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

                // P6 修复：连接成功后重置重连计数
                this.wsReconnectAttempts = 0;

                if (this.wsReconnectTimer) {
                    clearTimeout(this.wsReconnectTimer);
                    this.wsReconnectTimer = null;
                }

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

    /** P6 修复：指数退避重连策略 */
    scheduleReconnect() {
        if (this.wsReconnectTimer) return;
        
        // 指数退避：1s → 2s → 4s → 8s → ... → 30s(max)
        const interval = Math.min(
            this.wsReconnectBaseInterval * Math.pow(2, this.wsReconnectAttempts),
            this.wsReconnectMaxInterval
        );
        this.wsReconnectAttempts++;
        
        console.log(`[ThreeStateManager] ${interval}ms 后重连 (第${this.wsReconnectAttempts}次)...`);
        this.wsReconnectTimer = setTimeout(() => {
            this.wsReconnectTimer = null;
            this.connectWebSocket();
        }, interval);
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

            if (msgType === 'state_event') {
                this.handleAIPV3StateEvent(message);
                return;
            }

            switch (msgType) {
                case 'phase_change':
                    this.handlePhaseChange(message);
                    break;
                case 'update_result':
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

    handleAIPV3StateEvent(message) {
        const category = message.event_category || '';
        const action = message.event_action || '';
        const payload = message.payload || {};

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

        if (category === 'mesh') {
            if (action === 'joined' || action === 'coord_sync') {
                this.enterState(Phase.LIMINAL, { reason: `mesh_${action}` });
            }
            return;
        }

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

    handlePhaseChange(message) {
        const newPhase = message.phase;
        const reason = message.reason || '';

        if (!newPhase || !Object.values(Phase).includes(newPhase)) {
            console.warn('[ThreeStateManager] 无效阶段:', newPhase);
            return;
        }

        const isValid = this.isValidTransition(this.currentPhase, newPhase);
        if (!isValid) {
            console.warn(`[ThreeStateManager] 无效转换: ${this.currentPhase} -> ${newPhase}`);
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
            metadata: message.metadata || {},
            force: message.force || false
        };

        this.enterState(newPhase, stateData);
    }

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
    // 公共 API
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
    /** P5 修复：dispose 时清理全局引用 */
    dispose() {
        console.log('[ThreeStateManager] 清理中...');

        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
            this.wsReconnectTimer = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        if (this.silentState) this.silentState.dispose();
        if (this.liminalState) this.liminalState.dispose();
        if (this.manifestState) this.manifestState.dispose();

        // 清理全局引用
        if (window.stateManager === this) {
            window.stateManager = null;
        }

        console.log('[ThreeStateManager] 清理完成');
    }
}

// ============================================
// 应用入口
// ============================================
let stateManager = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] DOM 加载完成，初始化 Galaxy V2 v18...');
    try {
        stateManager = new ThreeStateManager();
        window.stateManager = stateManager;
        console.log('[App] Galaxy V2 v18 应用初始化成功');
    } catch (err) {
        console.error('[App] 初始化失败:', err);
    }
});

window.addEventListener('beforeunload', () => {
    if (stateManager) stateManager.dispose();
});

// ============================================
// 开发快捷键
// ============================================
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey) {
        switch (e.key) {
            case '1':
                console.log('[App] 快捷键: 强制 SILENT');
                if (stateManager) stateManager.forcePhase(Phase.SILENT);
                break;
            case '2':
                console.log('[App] 快捷键: 强制 LIMINAL');
                if (stateManager) stateManager.forcePhase(Phase.LIMINAL);
                break;
            case '3':
                console.log('[App] 快捷键: 强制 MANIFEST');
                if (stateManager) stateManager.forcePhase(Phase.MANIFEST, {
                    result: 'MANIFEST 态测试\n===================\n\n系统运行正常。\n等待进一步指令。'
                });
                break;
            case 'R':
            case 'r':
                console.log('[App] 快捷键: 强制重置');
                if (stateManager) stateManager.enterState(Phase.SILENT, { force: true });
                break;
        }
    }
});

console.log('[App] Galaxy V2 Desktop Presence v18 — Silent(WebGL) + Liminal(CSS3D) + Manifest');
