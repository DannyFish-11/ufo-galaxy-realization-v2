/**
 * manifest-state.js
 * Manifest State —— 行动即语言
 *
 * 零UI面板设计。智能体直接在桌面上执行操作——打开应用、点击UI、输入文字。
 * 用户看到的只有一个18px光点光标 + 运动轨迹 + 点击涟漪。
 * 没有任何弹窗、对话框、卡片、面板。工具消失，只剩行动。
 *
 * 视觉元素：
 *   1. 操作光标 —— 18px圆形光点，白色，opacity 0.7
 *   2. 运动轨迹 —— Canvas 2D绘制，渐消线，系统强调色
 *   3. 点击涟漪 —— CSS动画扩散圆环
 *   4. 背景 —— 完全透明，用户看到真实桌面
 */

class ManifestState {
    /**
     * @param {ThreeScene} threeScene —— 兼容原有接口，实际不使用Three.js
     */
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.isActive = false;

        // ---- 光标元素 ----
        this.cursorEl = null;
        this.cursorX = 0;
        this.cursorY = 0;
        this.cursorTargetX = 0;
        this.cursorTargetY = 0;
        this.cursorVelX = 0;
        this.cursorVelY = 0;
        this.cursorVisible = false;

        // ---- 弹簧物理参数 ----
        this.spring = {
            stiffness: 400,
            damping: 30,
            mass: 0.5
        };

        // ---- 轨迹系统 ----
        this.trailCanvas = null;
        this.trailCtx = null;
        this.trailPoints = [];
        this.trailMaxPoints = 200;
        this.trailFadeTime = 1000;
        this.trailWidth = 2;
        this.trailColor = this._getAccentColor();

        // ---- 涟漪系统 ----
        this.rippleContainer = null;

        // ---- 动画状态 ----
        this.entering = false;
        this.exiting = false;
        this.elapsed = 0;

        // ---- resize处理器（用于清理） ----
        this._onResize = () => this._resizeTrailCanvas();

        // ---- 时序常数 ----
        this.TIMING = {
            LIMINAL_FADE_START: 0.1,
            LIMINAL_FADE_DURATION: 0.4,
            CURSOR_APPEAR_DELAY: 0.3,
            CURSOR_APPEAR_DURATION: 0.2,
            CURSOR_FADE_DURATION: 0.6,
            TRAIL_FADE_DURATION: 1.0
        };

        this._build();
    }

    // ============================================
    // 构建DOM元素
    // ============================================

    _build() {
        // ---- 创建光标元素 ----
        this.cursorEl = document.createElement('div');
        this.cursorEl.id = 'manifest-cursor';
        this.cursorEl.style.cssText = `
            position: fixed;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.7);
            box-shadow:
                0 0 6px rgba(255, 255, 255, 0.5),
                0 0 20px rgba(255, 255, 255, 0.2),
                0 0 40px rgba(255, 255, 255, 0.1);
            pointer-events: none;
            z-index: 9999;
            opacity: 0;
            transform: translate(-50%, -50%) scale(0);
            will-change: transform, opacity;
            transition: none;
        `;
        document.body.appendChild(this.cursorEl);

        // ---- 创建轨迹Canvas ----
        this.trailCanvas = document.createElement('canvas');
        this.trailCanvas.id = 'manifest-trail-canvas';
        this.trailCtx = this.trailCanvas.getContext('2d');
        this._resizeTrailCanvas();
        this.trailCanvas.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            pointer-events: none;
            z-index: 9998;
            opacity: 0;
            transition: opacity ${this.TIMING.TRAIL_FADE_DURATION}s cubic-bezier(0.33, 1, 0.68, 1);
        `;
        document.body.appendChild(this.trailCanvas);

        // ---- 创建涟漪容器 ----
        this.rippleContainer = document.createElement('div');
        this.rippleContainer.id = 'manifest-ripple-container';
        this.rippleContainer.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            pointer-events: none;
            z-index: 9997;
        `;
        document.body.appendChild(this.rippleContainer);

        // ---- 监听窗口大小变化 ----
        window.addEventListener('resize', this._onResize);
    }

    /**
     * 调整轨迹Canvas尺寸匹配屏幕
     */
    _resizeTrailCanvas() {
        const dpr = Math.min(window.devicePixelRatio, 2);
        this.trailCanvas.width = window.innerWidth * dpr;
        this.trailCanvas.height = window.innerHeight * dpr;
        this.trailCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    /**
     * 获取系统强调色
     */
    _getAccentColor() {
        return '#007AFF';
    }

    // ============================================
    // 可见性控制
    // ============================================

    setVisible(visible) {
        if (this.cursorEl) {
            this.cursorEl.style.display = visible ? 'block' : 'none';
        }
        if (this.trailCanvas) {
            this.trailCanvas.style.display = visible ? 'block' : 'none';
        }
        if (this.rippleContainer) {
            this.rippleContainer.style.display = visible ? 'block' : 'none';
        }
    }

    // ============================================
    // 状态过渡
    // ============================================

    /**
     * 进入Manifest态
     * @param {string} resultText —— 兼容接口，本实现不使用（零UI面板）
     *
     * 时序：
     *   0ms   —— 开始执行
     *   100ms —— Liminal光晕和粒子开始消散（400ms, ease-in cubic）
     *   300ms —— 操作光标在目标位置出现（200ms, spring）
     *   400ms —— Liminal视觉完全消失，光标开始移动、点击、操作
     */
    enter(resultText) {
        if (this.isActive) return;
        this.isActive = true;

        this.entering = true;
        this.exiting = false;
        this.elapsed = 0;
        this.cursorVisible = false;

        // 重置光标位置到屏幕中心
        this.cursorX = window.innerWidth / 2;
        this.cursorY = window.innerHeight / 2;
        this.cursorTargetX = this.cursorX;
        this.cursorTargetY = this.cursorY;
        this.cursorVelX = 0;
        this.cursorVelY = 0;

        // 清空轨迹和涟漪
        this.trailPoints = [];
        this.trailCtx.clearRect(0, 0, this.trailCanvas.width, this.trailCanvas.height);
        this.rippleContainer.innerHTML = '';

        // 显示元素（初始不可见）
        this.setVisible(true);
        this.cursorEl.style.opacity = '0';
        this.cursorEl.style.transform = 'translate(-50%, -50%) scale(0)';
        this.trailCanvas.style.opacity = '0';

        // 触发Liminal消散
        this._fadeOutLiminal();
    }

    /**
     * 退出Manifest态
     *
     * 时序：
     *   0ms   —— 操作完成信号
     *   200ms —— 光标淡出（600ms, ease-out cubic）
     *   500ms —— 轨迹渐消（1000ms）
     *   800ms —— 完全回到Silent态
     */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        this.entering = false;
        this.exiting = true;
        this.exitProgress = 0;

        // 光标淡出
        const dur = this.TIMING.CURSOR_FADE_DURATION;
        this.cursorEl.style.transition =
            `opacity ${dur}s cubic-bezier(0.33, 1, 0.68, 1), ` +
            `transform ${dur}s cubic-bezier(0.33, 1, 0.68, 1)`;
        this.cursorEl.style.opacity = '0';
        this.cursorEl.style.transform = 'translate(-50%, -50%) scale(0.5)';
        this.cursorEl.style.animation = 'none';
        this.cursorVisible = false;

        // 轨迹渐消
        this.trailCanvas.style.opacity = '0';
    }

    /**
     * 触发Liminal元素的消散
     */
    _fadeOutLiminal() {
        const liminalOverlay = document.getElementById('liminal-overlay');
        if (liminalOverlay) {
            liminalOverlay.style.transition =
                `opacity ${this.TIMING.LIMINAL_FADE_DURATION}s cubic-bezier(0.32, 0, 0.67, 0)`;
            liminalOverlay.style.opacity = '0';
        }

        // 全局标记，LiminalState的update循环可检测
        window._manifestTransitionActive = true;

        setTimeout(() => {
            window._manifestTransitionActive = false;
        }, (this.TIMING.LIMINAL_FADE_START + this.TIMING.LIMINAL_FADE_DURATION) * 1000);
    }

    /**
     * 设置Liminal叠加层opacity
     */
    _setLiminalOpacity(opacity) {
        const liminalOverlay = document.getElementById('liminal-overlay');
        if (liminalOverlay) {
            liminalOverlay.style.opacity = String(Math.max(0, opacity));
        }
    }

    /**
     * 重置Liminal叠加层（为下次进入做准备）
     */
    _resetLiminal() {
        const liminalOverlay = document.getElementById('liminal-overlay');
        if (liminalOverlay) {
            liminalOverlay.style.transition = 'none';
            liminalOverlay.style.opacity = '1';
        }
    }

    // ============================================
    // 操作模拟（供智能体调用）
    // ============================================

    /**
     * 移动光标到指定位置（带动画）
     * 使用弹簧物理，不是线性插值
     * @param {number} x —— 目标X坐标
     * @param {number} y —— 目标Y坐标
     */
    moveCursorTo(x, y) {
        if (!this.isActive) return;
        this.cursorTargetX = x;
        this.cursorTargetY = y;
    }

    /**
     * 模拟点击（产生涟漪）
     * @param {number} x —— 点击X坐标
     * @param {number} y —— 点击Y坐标
     */
    simulateClick(x, y) {
        if (!this.isActive) return;
        this.moveCursorTo(x, y);
        setTimeout(() => this._createRipple(x, y), 50);
    }

    /**
     * 模拟双击（两个连续涟漪）
     * @param {number} x —— 双击X坐标
     * @param {number} y —— 双击Y坐标
     */
    simulateDoubleClick(x, y) {
        if (!this.isActive) return;
        this.moveCursorTo(x, y);
        setTimeout(() => this._createRipple(x, y, 'white'), 50);
        setTimeout(() => this._createRipple(x, y, 'accent'), 250);
    }

    /**
     * 模拟拖拽操作
     * @param {number} fromX —— 起始X
     * @param {number} fromY —— 起始Y
     * @param {number} toX —— 目标X
     * @param {number} toY —— 目标Y
     */
    simulateDrag(fromX, fromY, toX, toY) {
        if (!this.isActive) return;

        // 瞬移到起始位置
        this.cursorX = fromX;
        this.cursorY = fromY;
        this.cursorTargetX = fromX;
        this.cursorTargetY = fromY;
        this.cursorVelX = 0;
        this.cursorVelY = 0;

        // 短暂停顿后弹簧移动到目标位置
        setTimeout(() => {
            this.moveCursorTo(toX, toY);
        }, 100);
    }

    /**
     * 模拟文字输入
     * 可选：在光标附近显示极小的文字提示（无打字机效果，直接显示）
     * @param {string} text —— 输入的文字
     * @param {number} x —— 显示位置X（可选，默认光标位置）
     * @param {number} y —— 显示位置Y（可选）
     */
    simulateType(text, x, y) {
        if (!this.isActive) return;

        const posX = x !== undefined ? x : this.cursorX;
        const posY = y !== undefined ? y : this.cursorY;

        this.moveCursorTo(posX, posY);
        this._showTypeHint(text, posX, posY);
    }

    /**
     * 模拟右键点击
     * @param {number} x —— X坐标
     * @param {number} y —— Y坐标
     */
    simulateRightClick(x, y) {
        if (!this.isActive) return;
        this.moveCursorTo(x, y);
        // 右键使用强调色涟漪
        setTimeout(() => this._createRipple(x, y, 'accent'), 50);
    }

    // ============================================
    // 涟漪渲染
    // ============================================

    /**
     * 创建点击涟漪
     * @param {number} x —— 中心X
     * @param {number} y —— 中心Y
     * @param {string} variant —— 'white'或'accent'
     */
    _createRipple(x, y, variant = 'white') {
        const isAccent = variant === 'accent';
        const ripple = document.createElement('div');

        // 强调色用hex转rgb，白色直接用rgb值
        let colorStr;
        if (isAccent) {
            const r = parseInt(this.trailColor.slice(1, 3), 16);
            const g = parseInt(this.trailColor.slice(3, 5), 16);
            const b = parseInt(this.trailColor.slice(5, 7), 16);
            colorStr = `${r}, ${g}, ${b}`;
        } else {
            colorStr = '255, 255, 255';
        }
        const baseOpacity = isAccent ? '0.15' : '0.25';

        ripple.style.cssText = `
            position: absolute;
            left: ${x}px;
            top: ${y}px;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            border: 2px solid rgba(${colorStr}, ${baseOpacity});
            background: ${isAccent ? `rgba(${colorStr}, 0.05)` : 'transparent'};
            pointer-events: none;
            animation: manifestRipple 400ms cubic-bezier(0.33, 1, 0.68, 1) forwards;
        `;

        this.rippleContainer.appendChild(ripple);

        // 动画结束后移除DOM
        setTimeout(() => {
            if (ripple.parentNode) {
                ripple.parentNode.removeChild(ripple);
            }
        }, 420);
    }

    /**
     * 显示输入提示（极小文字，淡入淡出）
     */
    _showTypeHint(text, x, y) {
        const hint = document.createElement('div');
        hint.textContent = text;
        hint.style.cssText = `
            position: absolute;
            left: ${x + 16}px;
            top: ${y - 10}px;
            color: rgba(255, 255, 255, 0.35);
            font-size: 10px;
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', sans-serif;
            letter-spacing: 0.3px;
            pointer-events: none;
            white-space: nowrap;
            opacity: 0;
            transition: opacity 0.3s ease-out;
        `;

        this.rippleContainer.appendChild(hint);

        // 淡入
        requestAnimationFrame(() => {
            hint.style.opacity = '1';
        });

        // 短暂显示后淡出
        setTimeout(() => {
            hint.style.transition = 'opacity 0.6s ease-out';
            hint.style.opacity = '0';
            setTimeout(() => {
                if (hint.parentNode) {
                    hint.parentNode.removeChild(hint);
                }
            }, 600);
        }, 1200);
    }

    // ============================================
    // 轨迹渲染
    // ============================================

    /**
     * 添加轨迹点
     */
    _addTrailPoint(x, y) {
        const speed = Math.sqrt(
            this.cursorVelX * this.cursorVelX +
            this.cursorVelY * this.cursorVelY
        );

        this.trailPoints.push({
            x: x,
            y: y,
            opacity: Math.min(speed * 0.02, 0.3),
            velocity: speed,
            timestamp: performance.now()
        });

        if (this.trailPoints.length > this.trailMaxPoints) {
            this.trailPoints.shift();
        }
    }

    /**
     * 更新轨迹衰减
     * 每帧调用，使用惯性衰减 opacity *= 0.95
     */
    updateTrail(deltaTime) {
        if (this.trailPoints.length < 2) return;

        const now = performance.now();
        const decay = 0.95;

        for (let i = this.trailPoints.length - 1; i >= 0; i--) {
            const point = this.trailPoints[i];
            const age = now - point.timestamp;

            if (age > this.trailFadeTime) {
                this.trailPoints.splice(i, 1);
                continue;
            }

            // 基于时间的opacity衰减 + 惯性衰减
            const timeFade = 1 - (age / this.trailFadeTime);
            point.opacity *= decay;
            point.opacity = Math.min(point.opacity, timeFade * 0.3);

            if (point.opacity < 0.001) {
                this.trailPoints.splice(i, 1);
            }
        }
    }

    /**
     * 绘制轨迹到Canvas
     */
    _drawTrail() {
        const ctx = this.trailCtx;
        const width = window.innerWidth;
        const height = window.innerHeight;

        ctx.clearRect(0, 0, width, height);

        if (this.trailPoints.length < 2) return;

        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        // 绘制连接线段
        for (let i = 1; i < this.trailPoints.length; i++) {
            const prev = this.trailPoints[i - 1];
            const curr = this.trailPoints[i];

            if (prev.opacity < 0.001 || curr.opacity < 0.001) continue;

            const avgOpacity = (prev.opacity + curr.opacity) / 2;

            // 主轨迹线
            ctx.beginPath();
            ctx.moveTo(prev.x, prev.y);
            ctx.lineTo(curr.x, curr.y);
            ctx.strokeStyle = this._trailColorWithOpacity(avgOpacity);
            ctx.lineWidth = this.trailWidth;
            ctx.stroke();

            // 外发光（仅在opacity较高时）
            if (avgOpacity > 0.08) {
                ctx.beginPath();
                ctx.moveTo(prev.x, prev.y);
                ctx.lineTo(curr.x, curr.y);
                ctx.strokeStyle = this._trailColorWithOpacity(avgOpacity * 0.25);
                ctx.lineWidth = this.trailWidth + 6;
                ctx.stroke();
            }
        }
    }

    /**
     * 生成轨迹颜色（带opacity）
     */
    _trailColorWithOpacity(opacity) {
        const r = parseInt(this.trailColor.slice(1, 3), 16);
        const g = parseInt(this.trailColor.slice(3, 5), 16);
        const b = parseInt(this.trailColor.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${opacity})`;
    }

    // ============================================
    // 光标弹簧物理
    // ============================================

    /**
     * 使用弹簧物理更新光标位置
     * stiffness: 400, damping: 30, mass: 0.5
     */
    _updateCursorSpring(deltaTime) {
        const dt = Math.min(deltaTime, 0.033);
        const { stiffness, damping, mass } = this.spring;

        const dx = this.cursorTargetX - this.cursorX;
        const dy = this.cursorTargetY - this.cursorY;

        // F = kx - cv
        this.cursorVelX += (dx * stiffness - damping * this.cursorVelX) * dt / mass;
        this.cursorVelY += (dy * stiffness - damping * this.cursorVelY) * dt / mass;

        this.cursorX += this.cursorVelX * dt;
        this.cursorY += this.cursorVelY * dt;
    }

    /**
     * 更新光标DOM位置
     */
    _renderCursor() {
        this.cursorEl.style.left = `${this.cursorX}px`;
        this.cursorEl.style.top = `${this.cursorY}px`;
    }

    // ============================================
    // 主更新循环（每帧调用）
    // ============================================

    update(deltaTime) {
        const needsUpdate = this.isActive || this.entering || this.exiting;
        if (!needsUpdate) return;

        this.elapsed += deltaTime;

        // 进入阶段
        if (this.entering) {
            this._handleEnterPhase(deltaTime);
        }

        // 退出阶段
        if (this.exiting) {
            this._handleExitPhase(deltaTime);
        }

        // 活跃阶段：更新光标 + 轨迹
        if (this.isActive && this.cursorVisible) {
            // 弹簧物理更新光标位置
            this._updateCursorSpring(deltaTime);

            // 添加轨迹点（仅当速度足够时）
            const speed = Math.sqrt(
                this.cursorVelX * this.cursorVelX +
                this.cursorVelY * this.cursorVelY
            );
            if (speed > 1) {
                this._addTrailPoint(this.cursorX, this.cursorY);
            }

            // 渲染光标位置
            this._renderCursor();

            // 更新并绘制轨迹
            this.updateTrail(deltaTime);
            this._drawTrail();
        }
    }

    /**
     * 处理进入阶段的时序动画
     */
    _handleEnterPhase(deltaTime) {
        const t = this.elapsed;
        const T = this.TIMING;

        // 阶段1: Liminal消散
        if (t >= T.LIMINAL_FADE_START) {
            if (t < T.LIMINAL_FADE_START + T.LIMINAL_FADE_DURATION) {
                const fadeProgress = (t - T.LIMINAL_FADE_START) / T.LIMINAL_FADE_DURATION;
                this._setLiminalOpacity(1 - fadeProgress);
            } else {
                this._setLiminalOpacity(0);
            }
        }

        // 阶段2: 光标出现（spring动画）
        if (t >= T.CURSOR_APPEAR_DELAY && !this.cursorVisible) {
            this.cursorVisible = true;
            this.cursorEl.style.transition = 'none';
            this.cursorEl.style.opacity = '1';
            this.cursorEl.style.animation =
                `manifestCursorAppear ${T.CURSOR_APPEAR_DURATION}s cubic-bezier(0.16, 1, 0.3, 1) forwards, ` +
                `manifestCursorPulse 3s ease-in-out infinite`;

            // 轨迹Canvas淡入
            this.trailCanvas.style.opacity = '1';
        }

        // 进入完成标记
        if (t >= T.CURSOR_APPEAR_DELAY + T.CURSOR_APPEAR_DURATION) {
            this.entering = false;
        }
    }

    /**
     * 处理退出阶段的时序动画
     */
    _handleExitPhase(deltaTime) {
        this.exitProgress += deltaTime;
        const T = this.TIMING;

        // 等待所有淡出动画完成后清理
        const totalExitTime = 0.2 + T.CURSOR_FADE_DURATION + T.TRAIL_FADE_DURATION;
        if (this.exitProgress >= totalExitTime) {
            this.exiting = false;
            this.setVisible(false);

            // 重置Liminal叠加层
            this._resetLiminal();

            // 清理残留状态
            this.trailPoints = [];
            this.trailCtx.clearRect(0, 0, window.innerWidth, window.innerHeight);
            this.rippleContainer.innerHTML = '';
        }
    }

    // ============================================
    // 兼容接口
    // ============================================

    /**
     * 设置结果文本 —— 兼容接口，零UI设计下无显示
     */
    setResult(text) {
        // 新设计不显示任何结果面板
        // 保留此方法以保持API兼容
    }

    // ============================================
    // 清理
    // ============================================

    dispose() {
        // 移除resize监听
        window.removeEventListener('resize', this._onResize);

        // 移除光标元素
        if (this.cursorEl && this.cursorEl.parentNode) {
            this.cursorEl.parentNode.removeChild(this.cursorEl);
            this.cursorEl = null;
        }

        // 移除轨迹Canvas
        if (this.trailCanvas && this.trailCanvas.parentNode) {
            this.trailCanvas.parentNode.removeChild(this.trailCanvas);
            this.trailCanvas = null;
        }

        // 移除涟漪容器
        if (this.rippleContainer && this.rippleContainer.parentNode) {
            this.rippleContainer.parentNode.removeChild(this.rippleContainer);
            this.rippleContainer = null;
        }

        // 清理状态
        this.trailPoints = [];
        this.isActive = false;
        this.entering = false;
        this.exiting = false;
    }
}

window.ManifestState = ManifestState;
