/**
 * manifest-state.js
 * Manifest 显现态 — 极简
 *
 * 什么都不做。只有退出逻辑。
 * 所有视觉完全由外部（如后端推流或桌面窗口本身）承载。
 */

class ManifestState {
    /**
     * @param {Object} cssOverlay - CSS 覆盖层对象（不使用，仅保留接口一致性）
     */
    constructor(cssOverlay) {
        // 空
    }

    /** 不做任何事 */
    enter() {
        // 空
    }

    /** 不做任何事 */
    exit() {
        // 空
    }

    /** 不做任何事 */
    setVisible(bool) {
        // 空
    }

    /** 不做任何事 */
    onResize() {
        // 空
    }

    /** 不做任何事 */
    dispose() {
        // 空
    }
}

window.ManifestState = ManifestState;
