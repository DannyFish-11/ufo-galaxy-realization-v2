/**
 * liminal-state.js — v18
 * Liminal 阈限态 — "空间被打开"
 *
 * 技术方案：纯CSS 3D Transforms（无Three.js）
 * - CSS perspective + rotateX 创造桌面推入深度感
 * - 四面墙壁（floor/ceiling/left/right）形成空间
 * - 渐变边界（mask-image）消除硬边
 * - 消失点光球 — 粉紫蓝连续光谱
 *
 * 进入/退出：只操作CSS类，保持与旧版相同的API接口
 */

class LiminalState {
    /**
     * @param {Object} cssOverlay - CSS覆盖层对象
     * @param {Object} threeContainer - 保留参数兼容（不再使用）
     */
    constructor(cssOverlay, threeContainer) {
        this.element = cssOverlay?.element || document.getElementById('lLayer');
        // threeContainer 参数保留兼容，但不再使用
        this.container = threeContainer || document.getElementById('three-container');
        this.isActive = false;
        this.isAnimating = false;

        // 不再需要 Three.js 对象
        this.scene = null;
        this.camera = null;
        this.renderer = null;

        console.log('[LiminalState] v18 纯CSS 3D 初始化完成');
    }

    // ---------- 生命周期（CSS类操作，无Three.js） ----------

    /** 进入阈限态 — 激活CSS覆盖层 */
    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.isAnimating = true;

        // 激活CSS覆盖层
        if (this.element) {
            this.element.classList.remove('exiting');
            this.element.classList.add('active');
        }

        // 延迟标记动画完成（给CSS过渡时间）
        setTimeout(() => {
            this.isAnimating = false;
        }, 2500);

        console.log('[LiminalState] 进入 Liminal 态 — CSS 3D深度空间');
    }

    /** 退出阈限态 — 淡出 */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;
        this.isAnimating = true;

        if (this.element) {
            this.element.classList.remove('active');
            this.element.classList.add('exiting');
        }

        // 清理退出动画类
        setTimeout(() => {
            if (this.element) {
                this.element.classList.remove('exiting');
            }
            this.isAnimating = false;
        }, 600);

        console.log('[LiminalState] 退出 Liminal 态 — 淡出');
    }

    /** 每帧更新 — v18无需渲染循环 */
    update(deltaTime) {
        // 纯CSS方案，无需JS渲染循环
    }

    /** 窗口大小变化 — 纯CSS自适应，无需处理 */
    onResize() {
        // CSS 3D自动响应窗口变化
    }

    /** 清理 */
    dispose() {
        this.isActive = false;
        this.isAnimating = false;

        if (this.element) {
            this.element.classList.remove('active');
            this.element.classList.remove('exiting');
        }

        console.log('[LiminalState] 已清理');
    }
}

window.LiminalState = LiminalState;
