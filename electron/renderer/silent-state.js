/**
 * silent-state.js
 * 静默态 —— "等待是一种尊重"
 * 
 * 设计哲学：
 *   智能体存在但完全不可见，不占用用户的任何注意力。
 *   唯一可选指示器是右上角一个 16px 的小圆点，opacity 0.15，
 *   hover 时升至 0.4。没有呼吸动画，没有 HUD 边角，没有科技蓝。
 *   像 macOS 原生菜单栏图标那样自然。
 * 
 * 技术方案：纯 CSS overlay，不需要 WebGL。
 */

class SilentState {
    /**
     * @param {Object} cssOverlay - DOM 元素引用
     * @param {HTMLElement} cssOverlay.element - 覆盖层容器
     */
    constructor(cssOverlay) {
        this.overlay = cssOverlay?.element || this._createOverlay();
        this.dot = this._createDot();
        this.overlay.appendChild(this.dot);
        this.isActive = false;
    }

    /** 创建覆盖层容器 —— 全屏透明，仅指示器区域响应鼠标 */
    _createOverlay() {
        const el = document.createElement('div');
        el.id = 'silent-overlay';
        el.style.cssText = `
            position: fixed;
            inset: 0;
            pointer-events: none;
            opacity: 0;
            z-index: 100;
            transition: opacity 400ms cubic-bezier(0.33, 1, 0.68, 1);
        `;
        document.body.appendChild(el);
        return el;
    }

    /** 创建指示器圆点 —— 右上角 16px，系统强调色 */
    _createDot() {
        const dot = document.createElement('div');
        dot.className = 'silent-dot';
        dot.style.cssText = `
            position: absolute;
            top: 24px;
            right: 24px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: var(--accent-color, #007AFF);
            opacity: 0.15;
            pointer-events: auto;
            transition: opacity 300ms cubic-bezier(0.33, 1, 0.68, 1);
            cursor: default;
        `;

        // hover 时 opacity 升至 0.4
        dot.addEventListener('mouseenter', () => { dot.style.opacity = '0.4'; });
        dot.addEventListener('mouseleave', () => { dot.style.opacity = '0.15'; });

        return dot;
    }

    /** 淡入 —— opacity 0→1, 400ms */
    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.overlay.style.opacity = '1';
    }

    /** 淡出 —— opacity 1→0, 300ms */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;
        this.overlay.style.opacity = '0';
    }

    /** 直接设置可见性（无过渡） */
    setVisible(visible) {
        this.isActive = visible;
        this.overlay.style.transition = 'none';
        this.overlay.style.opacity = visible ? '1' : '0';
        // 恢复过渡，使下一次 enter/exit 仍有动画
        requestAnimationFrame(() => {
            this.overlay.style.transition = 'opacity 400ms cubic-bezier(0.33, 1, 0.68, 1)';
        });
    }

    /** 窗口大小变化 — 静默态无需处理（纯CSS自适应） */
    onResize() {
        // 覆盖层使用 position:fixed + inset:0，自动适应窗口
        // 指示器使用 position:absolute + top/right，自动保持在右上角
    }

    /** 清理 DOM */
    dispose() {
        if (this.overlay && this.overlay.parentNode) {
            this.overlay.parentNode.removeChild(this.overlay);
        }
        this.overlay = null;
        this.dot = null;
    }
}

window.SilentState = SilentState;
