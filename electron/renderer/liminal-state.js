/**
 * liminal-state.js
 * Liminal 阈限态 — 纯 CSS 实现
 *
 * 效果：
 * 1. 桌面推入深度（perspective-mode 类加在 body 上）
 * 2. 大气雾效（桌面边缘淡入虚空的 radial-gradient）
 * 3. 消失点光晕（纯宇宙蓝，blur 55px，6 秒呼吸）
 * 4. "正在理解"文字淡入
 *
 * 不再使用 Three.js，全部交给 CSS transitions/animations。
 */

class LiminalState {
    /**
     * @param {Object} cssOverlay - CSS 覆盖层对象，需包含 element 属性
     * @param {Object} threeScene - 保留兼容（不使用）
     */
    constructor(cssOverlay, threeScene) {
        this.element = cssOverlay?.element || document.getElementById('lLayer');
        this.desk = document.getElementById('desk');
        this.isActive = false;
        // threeScene 保留兼容但不使用 — 本态纯 CSS 驱动
        this.threeScene = threeScene;
    }

    // ---------- 生命周期 ----------

    /**
     * 进入阈限态 — 按设计时序执行
     * 1. 先让覆盖层可见
     * 2. 添加 perspective-mode 类到 body（触发 2.6s 桌面推入过渡）
     * 3. 添加 .on 类触发覆盖层内动画
     */
    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        // 下一帧再添加动画类，确保 display 先生效
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                document.body.classList.add('perspective-mode');
                this.element.classList.add('on');
            });
        });
    }

    /**
     * 退出阈限态 — 快速淡出
     * 1. 移除 perspective-mode（桌面恢复）
     * 2. 移除 .on（覆盖层淡出）
     * 3. 过渡完成后隐藏
     */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        document.body.classList.remove('perspective-mode');
        this.element.classList.remove('on');

        // 2.6s 后彻底隐藏（等待 cubic-bezier 过渡完成）
        setTimeout(() => {
            if (!this.isActive) this.setVisible(false);
        }, 2600);
    }

    /**
     * 每帧更新 — 纯 CSS 动画无需 JS 驱动
     * 保留接口供调用方使用
     */
    update(deltaTime) {
        // 所有动画由 CSS 处理，此处为空
    }

    /** 切换可见性 */
    setVisible(bool) {
        this.element.classList.toggle('on', bool);
        if (!bool) {
            document.body.classList.remove('perspective-mode');
        }
    }

    /** 窗口大小变化 — CSS 自适应，无需处理 */
    onResize() {
        // 纯 CSS 实现，vw/vh 自适应
    }

    /** 清理 */
    dispose() {
        this.isActive = false;
        document.body.classList.remove('perspective-mode');
        this.setVisible(false);
    }
}

window.LiminalState = LiminalState;
