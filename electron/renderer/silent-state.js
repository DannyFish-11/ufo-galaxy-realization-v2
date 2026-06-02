/**
 * silent-state.js
 * Silent 静默态 — 纯 CSS 实现
 *
 * 效果：桌面完全可见，覆盖层只有三层极淡光晕 + 屏幕边缘氛围灯
 * - 三层 radial-gradient 叠加，8 秒呼吸动画
 * - box-shadow: inset 屏幕边缘氛围灯，同步呼吸
 */

class SilentState {
    /**
     * @param {Object} cssOverlay - CSS 覆盖层对象，需包含 element 属性
     */
    constructor(cssOverlay) {
        this.element = cssOverlay?.element || document.getElementById('sLayer');
        this.isActive = false;
    }

    // ---------- 生命周期 ----------

    /** 进入静默态：opacity 0→1，400ms */
    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        // 强制重排后触发淡入
        this.element.style.transition = 'none';
        this.element.style.opacity = '0';
        this.element.offsetHeight; // 强制同步重排
        this.element.style.transition = 'opacity 400ms ease-out';
        this.element.style.opacity = '1';
    }

    /** 退出静默态：opacity 1→0，300ms */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        this.element.style.transition = 'opacity 300ms ease-in';
        this.element.style.opacity = '0';

        // 300ms 后隐藏
        setTimeout(() => {
            if (!this.isActive) this.setVisible(false);
        }, 300);
    }

    /** 切换可见性 */
    setVisible(bool) {
        this.element.classList.toggle('on', bool);
    }

    /** 窗口大小变化 — CSS 自适应，无需处理 */
    onResize() {
        // 纯 CSS 实现，自适应无需操作
    }

    /** 清理 */
    dispose() {
        this.isActive = false;
        this.setVisible(false);
    }
}

window.SilentState = SilentState;
