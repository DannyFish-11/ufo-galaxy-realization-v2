/**
 * app.js
 * Three-State State Machine for UFO Galaxy Desktop Presence
 *
 * States:
 *   SILENT  -> Static transparent overlay with breathing particle avatar
 *   LIMINAL -> Perspective tunnel with FOV distortion + liquid ink flow
 *   MANIFEST -> CRT monitor effect with result display
 *
 * Transitions:
 *   SILENT → LIMINAL: Backend requests processing (phase_change: liminal)
 *   LIMINAL → MANIFEST: Backend returns result (phase_change: manifest)
 *   MANIFEST → SILENT: Task complete / dismissed (phase_change: silent)
 *   Any → SILENT: Reset command
 */

// ============================================
// State Enum
// ============================================
const Phase = {
    SILENT: 'silent',
    LIMINAL: 'liminal',
    MANIFEST: 'manifest'
};

// ============================================
// ThreeStateManager
// ============================================
class ThreeStateManager {
    constructor() {
        this.currentPhase = Phase.SILENT;
        this.previousPhase = null;
        this.isTransitioning = false;

        // Three.js scene manager
        this.threeScene = null;

        // State instances
        this.silentState = null;
        this.liminalState = null;
        this.manifestState = null;

        // WebSocket
        this.ws = null;
        this.wsReconnectInterval = 3000;
        this.wsReconnectTimer = null;
        // PR-WEBSOCKET-PORT-FIX: /ws/desktop-presence is served by Galaxy Gateway
        // on port 8765 (gateway port), NOT on web_ui_port (16201).
        this.wsUrl = 'ws://localhost:8765/ws/desktop-presence';

        // UI elements
        this.wsStatusEl = document.getElementById('ws-status');
        this.wsStatusTextEl = document.getElementById('ws-status-text');
        this.crtPhaseEl = document.getElementById('crt-phase');

        // Initialize
        this.init();
    }

    // ============================================
    // Initialization
    // ============================================
    init() {
        console.log('[ThreeStateManager] Initializing...');

        // Initialize Three.js scene
        this.threeScene = new ThreeScene('canvas-container');

        // Initialize states
        this.silentState = new SilentState(this.threeScene);
        this.liminalState = new LiminalState(this.threeScene);
        this.manifestState = new ManifestState(this.threeScene);

        // Start render loop
        this.threeScene.startRenderLoop((time) => {
            this.onRenderFrame(time);
        });

        // Set resize callback
        this.threeScene.setResizeCallback((w, h) => {
            console.log(`[ThreeStateManager] Window resized: ${w}x${h}`);
            this.onWindowResize(w, h);
        });

        // Connect WebSocket
        this.connectWebSocket();

        // Enter initial state
        this.enterState(Phase.SILENT);

        console.log('[ThreeStateManager] Initialized. Current phase:', this.currentPhase);
    }

    // ============================================
    // Render Loop
    // ============================================
    onRenderFrame(time) {
        const deltaTime = this.threeScene.clock.getDelta();

        // Update current state
        switch (this.currentPhase) {
            case Phase.SILENT:
                this.silentState.update(deltaTime);
                break;
            case Phase.LIMINAL:
                this.liminalState.update(deltaTime);
                break;
            case Phase.MANIFEST:
                this.manifestState.update(deltaTime);
                break;
        }
    }

    onWindowResize(width, height) {
        // Notify states that need to handle resize
        // States reference the scene which already updated camera/renderer
    }

    // ============================================
    // State Management
    // ============================================
    enterState(phase, data = {}) {
        if (this.isTransitioning) {
            console.log('[ThreeStateManager] Transition in progress, queueing:', phase);
            this.queuedTransition = { phase, data };
            return;
        }

        this.isTransitioning = true;
        this.previousPhase = this.currentPhase;
        this.currentPhase = phase;

        console.log(`[ThreeStateManager] Transition: ${this.previousPhase} → ${phase}`, data);

        // Exit previous state
        this.exitCurrentState(this.previousPhase);

        // Enter new state after brief delay for exit animation
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
                    const resultText = data.result || data.message || '';
                    this.manifestState.enter(resultText);
                    this.updateWSStatusText(phase);
                    break;

                default:
                    console.warn('[ThreeStateManager] Unknown phase:', phase);
                    this.silentState.enter();
                    this.currentPhase = Phase.SILENT;
            }

            this.isTransitioning = false;

            // Process queued transition if any
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
                // No previous state
                break;
        }
    }

    updateWSStatusText(phase) {
        if (this.crtPhaseEl) {
            this.crtPhaseEl.textContent = phase.toUpperCase();
        }
    }

    // ============================================
    // WebSocket Communication
    // ============================================
    connectWebSocket() {
        console.log('[ThreeStateManager] Connecting WebSocket:', this.wsUrl);
        this.updateConnectionStatus('connecting');

        try {
            this.ws = new WebSocket(this.wsUrl);

            this.ws.onopen = () => {
                console.log('[ThreeStateManager] WebSocket connected');
                this.updateConnectionStatus('connected');

                // Clear reconnect timer
                if (this.wsReconnectTimer) {
                    clearTimeout(this.wsReconnectTimer);
                    this.wsReconnectTimer = null;
                }

                // Send registration message
                this.wsSend({
                    type: 'register',
                    client: 'desktop-presence',
                    version: '1.0.0'
                });
            };

            this.ws.onmessage = (event) => {
                this.handleWebSocketMessage(event.data);
            };

            this.ws.onerror = (error) => {
                console.error('[ThreeStateManager] WebSocket error:', error);
                this.updateConnectionStatus('disconnected');
            };

            this.ws.onclose = (event) => {
                console.log('[ThreeStateManager] WebSocket closed:', event.code, event.reason);
                this.updateConnectionStatus('disconnected');
                this.scheduleReconnect();
            };

        } catch (err) {
            console.error('[ThreeStateManager] WebSocket connection failed:', err);
            this.updateConnectionStatus('disconnected');
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        if (this.wsReconnectTimer) return;

        console.log(`[ThreeStateManager] Reconnecting in ${this.wsReconnectInterval}ms...`);
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
            console.log('[ThreeStateManager] WS message:', message);

            // PR-AIPV3-PHASE: Support both legacy format and AIP v3 STATE_EVENT
            const msgType = message.type;

            // AIP v3 STATE_EVENT format: {type: "state_event", event_category: "phase", event_action: "liminal"}
            if (msgType === 'state_event') {
                this.handleAIPV3StateEvent(message);
                return;
            }

            // Legacy format support (backward compatible)
            switch (msgType) {
                case 'phase_change':
                    this.handlePhaseChange(message);
                    break;

                case 'update_result':
                    // Update result text in manifest state without changing phase
                    if (this.manifestState && message.result) {
                        this.manifestState.setResult(message.result);
                    }
                    break;

                case 'task_result':
                case 'goal_execution_result':
                    // AIP v3 task result — update manifest display
                    if (this.manifestState && (message.result || message.data)) {
                        const resultText = this.formatTaskResult(message);
                        this.manifestState.setResult(resultText);
                    }
                    break;

                case 'ping':
                    this.wsSend({ type: 'pong', timestamp: Date.now() });
                    break;

                case 'heartbeat_ack':
                    console.log('[ThreeStateManager] Heartbeat ACK received');
                    break;

                case 'status':
                    console.log('[ThreeStateManager] Server status:', message.status);
                    break;

                default:
                    console.log('[ThreeStateManager] Unknown message type:', msgType);
            }
        } catch (err) {
            console.error('[ThreeStateManager] Failed to parse WS message:', err, data);
        }
    }

    // PR-AIPV3-PHASE: Handle AIP v3 STATE_EVENT messages for phase transitions
    handleAIPV3StateEvent(message) {
        const category = message.event_category || '';
        const action = message.event_action || '';
        const payload = message.payload || {};

        // Phase transitions via STATE_EVENT
        if (category === 'phase' || category === 'desktop_presence') {
            const phaseMap = {
                'silent': Phase.SILENT,
                'liminal': Phase.LIMINAL,
                'manifest': Phase.MANIFEST,
                'processing': Phase.LIMINAL,    // backward compat
                'completed': Phase.MANIFEST,     // backward compat
                'dismissed': Phase.SILENT,       // backward compat
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

        // Task lifecycle events
        if (category === 'task') {
            if (action === 'started' || action === 'assigned') {
                this.enterState(Phase.LIMINAL, { reason: 'task_started' });
            } else if (action === 'completed' || action === 'done') {
                const resultText = this.formatTaskResult(message);
                this.enterState(Phase.MANIFEST, { result: resultText, reason: 'task_completed' });
            } else if (action === 'failed' || action === 'cancelled') {
                const errorText = payload.error || payload.message || 'Task failed';
                this.enterState(Phase.MANIFEST, { result: `[ERROR] ${errorText}`, reason: action });
            }
            return;
        }

        // Mesh coordination events
        if (category === 'mesh') {
            if (action === 'joined' || action === 'coord_sync') {
                this.enterState(Phase.LIMINAL, { reason: `mesh_${action}` });
            }
            return;
        }

        // Device lifecycle events (display briefly in manifest)
        if (category === 'device' || category === 'state_sync') {
            const deviceId = message.device_id || payload.device_id || 'system';
            const statusText = `[${deviceId}] ${action}`;
            if (this.currentPhase === Phase.SILENT) {
                // Brief manifest flash for important device events
                if (action === 'registered' || action === 'unregistered' || action === 'online' || action === 'offline') {
                    this.enterState(Phase.MANIFEST, { result: statusText, reason: 'device_event' });
                    // Auto-return to silent after 3 seconds
                    setTimeout(() => this.enterState(Phase.SILENT, { reason: 'auto_dismiss' }), 3000);
                }
            }
            return;
        }

        console.log('[ThreeStateManager] Unhandled STATE_EVENT:', category, action);
    }

    // Format AIP v3 task result for display
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
            console.warn('[ThreeStateManager] Invalid phase:', newPhase);
            return;
        }

        // Validate state transitions
        const isValid = this.isValidTransition(this.currentPhase, newPhase);
        if (!isValid) {
            console.warn(
                `[ThreeStateManager] Invalid transition: ${this.currentPhase} → ${newPhase}`
            );
            // Allow forced transitions from backend
            if (message.force) {
                console.log('[ThreeStateManager] Forced transition allowed');
            } else {
                return;
            }
        }

        console.log(`[ThreeStateManager] Phase change: ${this.currentPhase} → ${newPhase} (${reason})`);

        // Extract relevant data for the new state
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
    // Public API for manual control
    // ============================================
    forcePhase(phase, data = {}) {
        console.log('[ThreeStateManager] Force phase:', phase);
        this.enterState(phase, { ...data, force: true });
    }

    setResult(resultText) {
        if (this.manifestState) {
            this.manifestState.setResult(resultText);
        }
    }

    getCurrentPhase() {
        return this.currentPhase;
    }

    // ============================================
    // Cleanup
    // ============================================
    dispose() {
        console.log('[ThreeStateManager] Disposing...');

        // Stop reconnect
        if (this.wsReconnectTimer) {
            clearTimeout(this.wsReconnectTimer);
        }

        // Close WebSocket
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        // Stop typing
        if (this.manifestState) {
            this.manifestState.dispose();
        }

        // Dispose states
        if (this.silentState) this.silentState.dispose();
        if (this.liminalState) this.liminalState.dispose();
        if (this.manifestState) this.manifestState.dispose();

        // Dispose Three.js scene
        if (this.threeScene) {
            this.threeScene.dispose();
        }
    }
}

// ============================================
// Application Entry Point
// ============================================
let stateManager = null;

document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] DOM loaded, initializing ThreeStateManager...');

    try {
        stateManager = new ThreeStateManager();

        // Expose to window for debugging
        window.stateManager = stateManager;

        console.log('[App] Application initialized successfully');
    } catch (err) {
        console.error('[App] Failed to initialize:', err);
    }
});

// Handle page unload
window.addEventListener('beforeunload', () => {
    if (stateManager) {
        stateManager.dispose();
    }
});

// Keyboard shortcuts (dev mode only)
// F12 is handled by Electron main.js (toggles React control panel)
document.addEventListener('keydown', (e) => {
    // Ctrl+Shift+1/2/3 for manual phase switching (dev only)
    if (e.ctrlKey && e.shiftKey) {
        switch (e.key) {
            case '1':
                console.log('[App] Dev shortcut: force SILENT');
                if (stateManager) stateManager.forcePhase(Phase.SILENT);
                break;
            case '2':
                console.log('[App] Dev shortcut: force LIMINAL');
                if (stateManager) stateManager.forcePhase(Phase.LIMINAL);
                break;
            case '3':
                console.log('[App] Dev shortcut: force MANIFEST');
                if (stateManager) stateManager.forcePhase(Phase.MANIFEST, {
                    result: 'MANIFEST STATE ACTIVATED\n===================\n\nThis is a test of the CRT display system.\n\nAll systems operational.\nAwaiting further instructions.'
                });
                break;
        }
    }
});

// Log startup
console.log('[App] UFO Galaxy Desktop Presence - App module loaded');
