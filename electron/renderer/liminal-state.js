/**
 * liminal-state.js — v39 Fixed
 * Liminal 阈限态 — "空间被打开"
 *
 * 技术方案：纯CSS（无Three.js）
 * - .space 层 CSS 3D纵深（perspective + rotateX）
 * - .l-glow 蓝紫粉边缘光雾叠加
 * - 进入/退出：操作CSS class
 */

class LiminalState {
    constructor(cssOverlay, threeContainer) {
        this.element = cssOverlay?.element || document.getElementById('lLayer');
        this.spaceLayer = document.getElementById('spaceLayer');
        this.isActive = false;
        this.isAnimating = false;
    }

    /** 进入阈限态 */
    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.isAnimating = true;

        // 激活Liminal覆盖层（使用.on class与CSS匹配）
        if (this.element) {
            this.element.classList.add('on');
        }

        // 激活空间层（背后3D纵深）
        if (this.spaceLayer) {
            this.spaceLayer.classList.add('active');
        }

        // 标记动画完成
        setTimeout(() => {
            this.isAnimating = false;
        }, 3000);

        console.log('[LiminalState] 进入 Liminal 态 — 空间打开');
    }

    /** 退出阈限态 */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;
        this.isAnimating = true;

        // 关闭Liminal覆盖层
        if (this.element) {
            this.element.classList.remove('on');
        }

        // 关闭空间层
        if (this.spaceLayer) {
            this.spaceLayer.classList.remove('active');
        }

        setTimeout(() => {
            this.isAnimating = false;
        }, 600);

        console.log('[LiminalState] 退出 Liminal 态');
    }

    /** 每帧更新 — 纯CSS，无需JS渲染 */
    update(deltaTime) {}

    /** 窗口大小变化 — 纯CSS自适应 */
    onResize() {}

    /** 清理 */
    dispose() {
        this.isActive = false;
        this.isAnimating = false;
        if (this.element) {
            this.element.classList.remove('on');
        }
        if (this.spaceLayer) {
            this.spaceLayer.classList.remove('active');
        }
        console.log('[LiminalState] 已清理');
    }
}

window.LiminalState = LiminalState;
