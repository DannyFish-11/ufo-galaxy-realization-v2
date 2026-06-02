/**
 * manifest-state.js
 * Manifest 显现态 — 极简
 *
 * 设计哲学：
 *   Manifest态是"结果"态——所有视觉完全由外部承载（后端推流、
 *   桌面窗口、用户应用）。覆盖层只需干净地让出空间。
 *
 * 行为：
 *   1. 进入时：确保Liminal态的所有元素（Three.js场景、CSS覆盖层）
 *      在0.6秒内完全淡出
 *   2. 激活时：什么都不做——桌面完全可见
 *   3. 退出时：准备进入下一个态
 *
 * 色调：无——Manifest态没有自己的视觉表现
 */

class ManifestState {
    /**
     * @param {Object} cssOverlay - CSS覆盖层对象（保留接口一致性）
     */
    constructor(cssOverlay) {
        this.element = cssOverlay?.element || document.getElementById('mLayer');
        this.isActive = false;

        // DOM 引用 — 用于控制Liminal态元素的淡出
        this.liminalLayer = document.getElementById('lLayer');
        this.threeContainer = document.getElementById('three-container');
        this.silentLayer = document.getElementById('sLayer');
    }

    // ---------- 生命周期 ----------

    /** 进入 Manifest 态 — 清除所有覆盖 */
    enter() {
        if (this.isActive) return;
        this.isActive = true;

        // 激活Manifest层（虽然它是空的，但保持状态一致性）
        if (this.element) {
            this.element.classList.remove('exiting');
            this.element.classList.add('active');
        }

        // 确保 Silent 态隐藏
        const silentCanvas = document.getElementById('silent-canvas-container');
        if (silentCanvas) {
            silentCanvas.classList.remove('active');
        }
        if (this.silentLayer) {
            // 不直接操作类，而是通过app.js调用silentState.exit()
        }

        // 确保 Liminal 态的 CSS 覆盖层完全淡出
        if (this.liminalLayer) {
            this.liminalLayer.classList.remove('active');
            this.liminalLayer.classList.add('exiting');
        }

        // 确保 Three.js 容器隐藏
        if (this.threeContainer) {
            this.threeContainer.classList.remove('active');
        }

        console.log('[ManifestState] 进入 Manifest 态 — 所有覆盖层淡出，桌面完全可见');
    }

    /** 退出 Manifest 态 */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // 添加退出动画类
        if (this.element) {
            this.element.classList.remove('active');
            this.element.classList.add('exiting');
        }

        // 清理退出动画类
        setTimeout(() => {
            if (this.element) {
                this.element.classList.remove('exiting');
            }
        }, 600);

        console.log('[ManifestState] 退出 Manifest 态');
    }

    /** 切换可见性 — Manifest态无视觉表现，仅记录状态 */
    setVisible(bool) {
        if (bool) {
            if (this.element) this.element.classList.add('active');
        } else {
            if (this.element) this.element.classList.remove('active');
        }
    }

    /** 窗口大小变化 — Manifest态无需处理 */
    onResize() {
        // Manifest态无视觉表现，无需响应resize
    }

    /** 清理 */
    dispose() {
        this.isActive = false;
        if (this.element) {
            this.element.classList.remove('active');
            this.element.classList.remove('exiting');
        }
        console.log('[ManifestState] 已清理');
    }
}

window.ManifestState = ManifestState;
