/**
 * app.js
 * Galaxy V2 Desktop Presence — 三态状态机主控制器
 *
 * 三态：SILENT (WebGL Shader) / LIMINAL (Three.js 3D) / MANIFEST (极简)
 *
 * 状态转换：
 *   SILENT -> LIMINAL: 后端请求处理中
 *   LIMINAL -> MANIFEST: 后端返回结果
 *   MANIFEST -> SILENT: 任务完成 / 关闭
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
        this.wsUrl = 'ws://localhost:9000/ws/desktop-presence';

        // UI 元素引用
        this.wsStatusEl = document.getElementById('ws-status');
        this.wsStatusTextEl = document.getElementById('ws-status-text');

        // 动画循环引用（仅用于协调，各态有自己的渲染循环）
        this._rafId = null;
        this._lastTime = 0;

        this.init();
    }

    // ============================================
    // 初始化
    // ============================================
    init() {
        console.log('[ThreeStateManager] 初始化 Galaxy V2 三态系统...');

        // 检查 Three.js 是否可用
        if (typeof THREE === 'undefined') {
            console.error('[ThreeStateManager] Three.js 未加载！检查网络或CDN');
            // 显示错误提示
            this._showError('Three.js 加载失败');
            return;
        }
        console.log('[ThreeStateManager] Three.js 版本:', THREE.REVISION);

        // 初始化各态
        this.silentState = new SilentState({ element: document.getElementById('sLayer') });
        this.liminalState = new LiminalState(
            { element: document.getElementById('lLayer') },
            document.getElementById('three-container')
        );
        this.manifestState = new ManifestState({ element: document.getElementById('mLayer') });

        // 启动协调渲染循环
        this._startCoordinationLoop();

        // 监听窗口变化
        window.addEventListener('resize', () => this.onWindowResize());

        // 连接 WebSocket
        this.connectWebSocket();

        // 进入初始态（Silent）
        this.enterState(Phase.SILENT);

        console.log('[ThreeStateManager] 初始化完成，当前阶段:', this.currentPhase);
    }

    /** 显示错误信息 */
    _showError(message) {
        const el = document.createElement('div');
        el.style.cssText = `
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
            color: rgba(255, 80, 80, 0.8); font-family: monospace; font-size: 14px;
            background: rgba(0, 0, 0, 0.6); padding: 20px; border-radius: 4px;
            z-index: 9999; letter-spacing: 2px; text-align: center;
        `;
        el.textContent = `[ERROR] ${message}`;
        document.body.appendChild(el);
    }

    // ============================================
    // 协调渲染循环
    // 各态（Silent/Liminal）有自己的独立渲染循环，
    // 此处仅用于协调和通用更新
    // ============================================
    _startCoordinationLoop() {
        const loop = (time) => {
            this._rafId = requestAnimationFrame(loop);
            const deltaTime = Math.min((time - this._lastTime) / 1000, 0.1);
            this._lastTime = time;

            if (deltaTime > 0) {
                this.onRenderFrame(deltaTime);
            }
        };
        this._lastTime = performance.now();
        this._rafId = requestAnimationFrame(loop);
    }

    onRenderFrame(deltaTime) {
        // 当前态的 update（各态自主管理自己的 Three.js 渲染循环，
        // 这里仅保留接口供额外逻辑使用）
        switch (this.currentPhase) {
            case Phase.SILENT:
                // SilentState 有自己的 _render 循环
                break;
            case Phase.LIMINAL:
                // LiminalState 有自己的 _render 循环
                if (this.liminalState) {
                    this.liminalState.update(deltaTime);
                }
                break;
            case Phase.MANIFEST:
                // Manifest 纯CSS，无需JS更新
                break;
        }
    }

    /** 窗口大小变化 — 通知各态 */
    onWindowResize() {
        if (this.silentState) this.silentState.onResize();
        if (this.liminalState) this.liminalState.onResize();
        if (this.manifestState) this.manifestState.onResize();
    }

    // ============================================
    // 状态管理
    // ============================================

    /**
     * 进入指定状态
     * @param {string} phase - 目标阶段
     * @param {Object} data - 附加数据
     */
    enterState(phase, data = {}) {
        if (this.isTransitioning) {
            console.log('[ThreeStateManager] 转换进行中，排队:', phase);
            this.queuedTransition = { phase, data };
            return;
        }

        // 验证目标态
        if (!Object.values(Phase).includes(phase)) {
            console.warn('[ThreeStateManager] 无效阶段:', phase);
            return;
        }

        // 校验状态转换合法性
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

        // 短暂延迟后进入新态（给退出动画留出时间）
        setTimeout(() => {
            this._enterState(phase, data);

            this.isTransitioning = false;

            // 处理排队的转换
            if (this.queuedTransition) {
                const queued = this.queuedTransition;
                this.queuedTransition = null;
                this.enterState(queued.phase, queued.data);
            }
        }, 50);
    }

    /** 进入具体状态 */
    _enterState(phase, data) {
        switch (phase) {
            case Phase.SILENT:
                // 先确保 Liminal 态的 Three.js 场景已停止
                if (this.liminalState && this.previousPhase === Phase.LIMINAL) {
                    // LiminalState 的 exit 会在 _exitState 中被调用
                    // 这里额外确保 three-container 隐藏
                    const threeContainer = document.getElementById('three-container');
                    if (threeContainer) threeContainer.classList.remove('active');
                }
                this.silentState.enter();
                break;

            case Phase.LIMINAL:
                // 先确保 Silent 态的 WebGL 已停止
                if (this.silentState) {
                    this.silentState.exit();
                }
                this.liminalState.enter();
                break;

            case Phase.MANIFEST:
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
                // 无前态
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

    // ---------- AIP v3 STATE_EVENT 处理 ----------
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

    // ---------- 兼容旧格式 phase_change ----------
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

    /** 格式化 AIP v3 任务结果 */
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

    // ---------- 连接状态 UI ----------
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

        // 停止协调循环
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }

        // 关闭 WebSocket
        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        // 清理各态
        if (this.silentState) this.silentState.dispose();
        if (this.liminalState) this.liminalState.dispose();
        if (this.manifestState) this.manifestState.dispose();

        console.log('[ThreeStateManager] 清理完成');
    }
}

// ============================================
// 应用入口
// ============================================
let stateManager = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] DOM 加载完成，初始化 Galaxy V2 ThreeStateManager...');

    try {
        stateManager = new ThreeStateManager();
        window.stateManager = stateManager;
        console.log('[App] Galaxy V2 应用初始化成功');
    } catch (err) {
        console.error('[App] 初始化失败:', err);
    }
});

window.addEventListener('beforeunload', () => {
    if (stateManager) {
        stateManager.dispose();
    }
});

// ============================================
// 开发快捷键
// ============================================
document.addEventListener('keydown', (e) => {
    // Ctrl+Shift+1/2/3 手动切换三态
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
                // 强制重置所有状态
                console.log('[App] 快捷键: 强制重置');
                if (stateManager) {
                    stateManager.enterState(Phase.SILENT, { force: true });
                }
                break;
        }
    }
});

console.log('[App] Galaxy V2 Desktop Presence — 三态系统已加载 (WebGL Shader + Three.js 3D)');
