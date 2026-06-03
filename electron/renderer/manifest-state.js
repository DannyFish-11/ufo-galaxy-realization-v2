/**
 * manifest-state.js — v40 Fixed
 * Manifest 显现态 — 极简
 *
 * 设计哲学：
 *   Manifest态是"结果"态——所有视觉完全由外部承载（后端推流、
 *   桌面窗口、用户应用）。覆盖层只需干净地让出空间。
 *
 * 修复：
 * - P16: 移除不存在的 three-container 引用（v18 遗留代码）
 * - P17: 统一使用 .on class（与 liminal-state.js 和 style.css 保持一致）
 * - P18: setVisible 方法使用 .on 而非 .active
 * - P19: 添加 silent-canvas-fallback 清理
 */

class ManifestState {
    /**
     * @param {Object} cssOverlay - CSS覆盖层对象（保留接口一致性）
     */
    constructor(cssOverlay) {
        this.element = cssOverlay?.element || document.getElementById('mLayer');
        this.isActive = false;

        // DOM 引用 — 用于控制其他态元素的淡出（双重保险）
        this.liminalLayer = document.getElementById('lLayer');
        this.silentCanvasContainer = document.getElementById('silent-canvas-container');
        this.silentFallback = document.getElementById('silent-canvas-fallback');
    }

    // ---------- 生命周期 ----------

    /** 进入 Manifest 态 — 清除所有覆盖 */
    enter() {
        if (this.isActive) return;
        this.isActive = true;

        // P17 修复：激活 Manifest 层使用 .on（与 style.css .m.on 一致）
        if (this.element) {
            this.element.classList.add('on');
        }

        // 确保 Silent 态的所有视觉元素完全淡出
        // （注：silentState.exit() 已在 _exitState() 中调用，此处作为双重保险）
        if (this.silentCanvasContainer) {
            this.silentCanvasContainer.classList.remove('active');
        }
        if (this.silentFallback) {
            this.silentFallback.classList.remove('active');
        }

        // 确保 Liminal 态的 CSS 覆盖层完全淡出
        // P17 修复：使用 .on 而非 .active（与 liminal-state.js 和 style.css 保持一致）
        if (this.liminalLayer) {
            this.liminalLayer.classList.remove('on');
        }

        console.log('[ManifestState] 进入 Manifest 态 — 所有覆盖层淡出，桌面完全可见');
    }

    /** 退出 Manifest 态 */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // P17 修复：使用 .on 而非 .active/.exiting
        if (this.element) {
            this.element.classList.remove('on');
        }

        console.log('[ManifestState] 退出 Manifest 态');
    }

    /** 切换可见性 — Manifest态无视觉表现，仅记录状态 */
    // P18 修复：使用 .on 而非 .active（与 style.css 中 .m.on 保持一致）
    setVisible(bool) {
        if (bool) {
            if (this.element) this.element.classList.add('on');
        } else {
            if (this.element) this.element.classList.remove('on');
        }
    }

    /** 窗口大小变化 — Manifest态无需处理 */
    onResize() {
        // Manifest态无视觉表现，无需响应resize
    }

    /** 清理 */
    dispose() {
        this.isActive = false;
        // P17 修复：统一使用 .on
        if (this.element) {
            this.element.classList.remove('on');
        }
        console.log('[ManifestState] 已清理');
    }
}

window.ManifestState = ManifestState;
