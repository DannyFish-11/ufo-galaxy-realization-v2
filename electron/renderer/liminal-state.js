/**
 * liminal-state.js — 觉醒态视觉系统
 *
 * 哲学："思考是一种美学"
 * 智能体正在觉醒、感知、规划——视觉效果传达"生命力"而非"科技感"
 *
 * 视觉核心：一个柔和光球、三颗轨道粒子、一行极简文字
 * 参考：Siri被唤醒时的光效，苹果级的克制与优雅
 */

class LiminalState {
    /**
     * @param {HTMLElement} cssOverlay — CSS覆盖层容器
     * @param {Object} threeScene — Three.js场景包装器
     */
    constructor(cssOverlay, threeScene) {
        this.cssOverlay = cssOverlay;
        this.threeScene = threeScene;
        this.scene = threeScene ? threeScene.getScene() : null;

        // 运行时状态
        this.isActive = false;
        this.isVisible = false;
        this.entering = false;
        this.exiting = false;
        this.elapsedTime = 0;

        // 动画缓动系数（spring: stiffness 300, damping 25）
        this.springStiffness = 300;
        this.springDamping = 25;
        this.springVelocity = 0;
        this.springValue = 0;      // 当前值（光晕入场用）
        this.springTarget = 0;

        // 强调色（优先从CSS变量读取，fallback到系统蓝）
        this.accentColor = this._readAccentColor();

        // CSS DOM元素
        this.els = {};          // 所有动态创建的DOM元素

        // Three.js 对象（轨道粒子用ShaderMaterial实现）
        this.orbitGroup = null;
        this.orbitParticles = null;
        this.orbitMaterial = null;

        // 呼吸动画状态
        this.breathPhase = 0;

        // 文字内容池
        this.thinkingTexts = [
            '正在理解…',
            '正在感知…',
            '正在思考…',
            '正在构想…',
            '正在觉醒…'
        ];
        this.currentTextIndex = 0;

        this._buildCSS();
        if (this.scene) {
            this._buildThreeJS();
        }
        this._injectStyles();
    }

    // ============================================
    // 1. 构建CSS覆盖层（核心视觉）
    // ============================================

    _buildCSS() {
        // 1. 背景遮罩 — 纯黑，用于让前景更清晰
        const mask = document.createElement('div');
        mask.id = 'liminal-mask';
        mask.className = 'liminal-element';
        this.cssOverlay.appendChild(mask);
        this.els.mask = mask;

        // 2. 中心光晕容器 — 位于黄金分割点
        const glowContainer = document.createElement('div');
        glowContainer.id = 'liminal-glow-container';
        glowContainer.className = 'liminal-element';
        this.cssOverlay.appendChild(glowContainer);
        this.els.glowContainer = glowContainer;

        // 2a. 主光晕 — radial-gradient + 高斯模糊
        const glowCore = document.createElement('div');
        glowCore.id = 'liminal-glow-core';
        glowCore.className = 'liminal-element';
        glowContainer.appendChild(glowCore);
        this.els.glowCore = glowCore;

        // 2b. 光晕内层（更亮的核心）
        const glowInner = document.createElement('div');
        glowInner.id = 'liminal-glow-inner';
        glowInner.className = 'liminal-element';
        glowContainer.appendChild(glowInner);
        this.els.glowInner = glowInner;

        // 3. 轨道粒子容器 — 3个小圆点围绕中心旋转
        const orbitContainer = document.createElement('div');
        orbitContainer.id = 'liminal-orbit-container';
        orbitContainer.className = 'liminal-element';
        this.cssOverlay.appendChild(orbitContainer);
        this.els.orbitContainer = orbitContainer;

        // 3颗轨道粒子
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement('div');
            dot.className = 'liminal-orbit-dot liminal-element';
            dot.dataset.index = i;
            orbitContainer.appendChild(dot);
        }
        this.els.orbitDots = orbitContainer.querySelectorAll('.liminal-orbit-dot');

        // 4. 思考文字 — 极简，位于光晕下方
        const textEl = document.createElement('div');
        textEl.id = 'liminal-text';
        textEl.className = 'liminal-element';
        textEl.textContent = this.thinkingTexts[0];
        this.cssOverlay.appendChild(textEl);
        this.els.text = textEl;

        // 5. 屏幕边缘微光 — 模仿Siri的四周光晕
        const edgeGlow = document.createElement('div');
        edgeGlow.id = 'liminal-edge-glow';
        edgeGlow.className = 'liminal-element';
        this.cssOverlay.appendChild(edgeGlow);
        this.els.edgeGlow = edgeGlow;

        // 初始全部隐藏
        this._hideAll();
    }

    // ============================================
    // 2. 构建Three.js对象（轨道粒子ShaderMaterial）
    // ============================================

    _buildThreeJS() {
        // 轨道粒子组 — 使用Three.js的ShaderMaterial实现更流畅的轨道运动
        this.orbitGroup = new THREE.Group();

        // 为3颗粒子创建独立的shader材质
        const particleGeometry = new THREE.BufferGeometry();
        // 3个粒子，每个一个点
        const positions = new Float32Array([
            0, 0, 0,   // 粒子0
            0, 0, 0,   // 粒子1
            0, 0, 0    // 粒子2
        ]);
        particleGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

        // 粒子颜色（白色，带alpha）
        const colors = new Float32Array([
            1.0, 1.0, 1.0,
            1.0, 1.0, 1.0,
            1.0, 1.0, 1.0
        ]);
        particleGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        // 粒子相位偏移（均匀分布在360度）
        const phases = new Float32Array([0, Math.PI * 2 / 3, Math.PI * 4 / 3]);
        particleGeometry.setAttribute('phase', new THREE.BufferAttribute(phases, 1));

        this.orbitMaterial = new THREE.ShaderMaterial({
            uniforms: {
                uTime: { value: 0 },
                uOrbitRadius: { value: 1.2 },   // 120px in world units
                uParticleSize: { value: 6.0 },
                uOpacity: { value: 0.0 },
                uOrbitSpeed: { value: Math.PI * 2 / 3.0 }  // 3秒/圈
            },
            vertexShader: `
                attribute float phase;
                varying float vAlpha;
                uniform float uTime;
                uniform float uOrbitRadius;
                uniform float uParticleSize;
                uniform float uOrbitSpeed;

                void main() {
                    // 轨道角度 = 时间 * 角速度 + 相位偏移
                    float angle = uTime * uOrbitSpeed + phase;

                    // 圆形轨道（XZ平面）
                    float x = cos(angle) * uOrbitRadius;
                    float z = sin(angle) * uOrbitRadius;

                    vec3 orbitPos = vec3(x, 0.0, z);

                    // 投影到屏幕空间
                    vec4 mvPosition = modelViewMatrix * vec4(orbitPos, 1.0);
                    gl_Position = projectionMatrix * mvPosition;

                    // 粒子大小（固定像素大小）
                    gl_PointSize = uParticleSize;

                    // 根据轨道位置计算淡入淡出 —
                    // 在后方（z < 0）时更淡，前方（z > 0）时更亮
                    vAlpha = smoothstep(-uOrbitRadius, uOrbitRadius, z) * 0.4 + 0.15;
                }
            `,
            fragmentShader: `
                varying float vAlpha;
                uniform float uOpacity;

                void main() {
                    // 圆形粒子（从中心向边缘衰减）
                    vec2 coord = gl_PointCoord - vec2(0.5);
                    float dist = length(coord);
                    if (dist > 0.5) discard;

                    // 边缘柔化（高斯近似）
                    float alpha = smoothstep(0.5, 0.1, dist) * vAlpha * uOpacity;

                    gl_FragColor = vec4(1.0, 1.0, 1.0, alpha);
                }
            `,
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending
        });

        this.orbitParticles = new THREE.Points(particleGeometry, this.orbitMaterial);
        this.orbitGroup.add(this.orbitParticles);

        // 将轨道组添加到场景（放置在黄金分割点位置）
        this.orbitGroup.position.set(0, -1.5, 0); // 偏下1/3
        this.scene.add(this.orbitGroup);
    }

    // ============================================
    // 3. 注入CSS动画样式
    // ============================================

    _injectStyles() {
        const styleId = 'liminal-state-styles';
        if (document.getElementById(styleId)) return;

        const accent = this.accentColor;

        const css = `
            /* ===== Liminal State — 觉醒态视觉系统 ===== */

            #liminal-mask {
                position: absolute;
                inset: 0;
                background: #000000;
                opacity: 0;
                pointer-events: none;
                transition: opacity 400ms cubic-bezier(0.33, 1, 0.68, 1);
                z-index: 1;
            }

            #liminal-glow-container {
                position: absolute;
                left: 50%;
                top: 62%;  /* 黄金分割点：偏下1/3 */
                transform: translate(-50%, -50%) scale(0.85);
                width: 280px;
                height: 280px;
                opacity: 0;
                pointer-events: none;
                z-index: 2;
                mix-blend-mode: screen;
                will-change: transform, opacity;
            }

            #liminal-glow-core {
                position: absolute;
                inset: 0;
                border-radius: 50%;
                background: radial-gradient(
                    circle at 50% 50%,
                    ${accent}88 0%,
                    ${accent}33 35%,
                    ${accent}08 65%,
                    transparent 85%
                );
                filter: blur(60px);
                will-change: opacity, transform;
            }

            #liminal-glow-inner {
                position: absolute;
                left: 50%;
                top: 50%;
                transform: translate(-50%, -50%);
                width: 120px;
                height: 120px;
                border-radius: 50%;
                background: radial-gradient(
                    circle at 50% 50%,
                    ${accent}AA 0%,
                    ${accent}44 40%,
                    transparent 75%
                );
                filter: blur(20px);
                will-change: opacity, transform;
            }

            #liminal-orbit-container {
                position: absolute;
                left: 50%;
                top: 62%;
                transform: translate(-50%, -50%);
                width: 240px;
                height: 240px;
                opacity: 0;
                pointer-events: none;
                z-index: 3;
                will-change: opacity;
            }

            .liminal-orbit-dot {
                position: absolute;
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.4);
                box-shadow: 0 0 6px rgba(255, 255, 255, 0.2);
                left: 50%;
                top: 50%;
                margin-left: -3px;
                margin-top: -3px;
                will-change: transform;
            }

            #liminal-text {
                position: absolute;
                left: 50%;
                top: calc(62% + 160px);
                transform: translateX(-50%) translateY(8px);
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
                font-size: 14px;
                font-weight: 400;
                color: rgba(255, 255, 255, 0.7);
                letter-spacing: 0.08em;
                opacity: 0;
                pointer-events: none;
                z-index: 2;
                white-space: nowrap;
                text-align: center;
                will-change: opacity, transform;
                transition: opacity 500ms cubic-bezier(0.33, 1, 0.68, 1),
                            transform 500ms cubic-bezier(0.33, 1, 0.68, 1);
            }

            #liminal-edge-glow {
                position: absolute;
                inset: 0;
                opacity: 0;
                pointer-events: none;
                z-index: 0;
                box-shadow: inset 0 0 60px ${accent}0A;
                will-change: opacity;
                transition: opacity 600ms cubic-bezier(0.33, 1, 0.68, 1);
            }

            /* 入场完成后的状态类 */
            .liminal-entered #liminal-mask {
                opacity: 0.12;
            }
            .liminal-entered #liminal-glow-container {
                opacity: 1;
                transform: translate(-50%, -50%) scale(1);
            }
            .liminal-entered #liminal-orbit-container {
                opacity: 1;
            }
            .liminal-entered #liminal-text {
                opacity: 1;
                transform: translateX(-50%) translateY(0);
            }
            .liminal-entered #liminal-edge-glow {
                opacity: 1;
            }
        `;

        const styleSheet = document.createElement('style');
        styleSheet.id = styleId;
        styleSheet.textContent = css;
        document.head.appendChild(styleSheet);
    }

    // ============================================
    // 4. 入场动画 — 精确的时序编排
    // ============================================

    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.entering = true;
        this.exiting = false;

        // 显示所有元素
        this.setVisible(true);

        // 重置动画状态
        this.springValue = 0;
        this.springVelocity = 0;
        this.springTarget = 1;
        this.elapsedTime = 0;
        this.breathPhase = 0;

        // 选择一条思考文字
        this.currentTextIndex = Math.floor(Math.random() * this.thinkingTexts.length);
        this.els.text.textContent = this.thinkingTexts[this.currentTextIndex];

        // ===== 精确时序编排 =====

        // 50ms — 背景遮罩淡入（400ms, ease-out cubic）
        setTimeout(() => {
            if (!this.isActive) return;
            this.els.mask.style.opacity = '0.12';
            this.els.mask.style.transition = 'opacity 400ms cubic-bezier(0.33, 1, 0.68, 1)';
        }, 50);

        // 100ms — 中心光晕出现（由spring动画驱动）
        // spring在update()中处理

        // 150ms — 轨道粒子开始运动
        setTimeout(() => {
            if (!this.isActive) return;
            // 粒子容器淡入
            this.els.orbitContainer.style.opacity = '1';
            this.els.orbitContainer.style.transition = 'opacity 500ms cubic-bezier(0.33, 1, 0.68, 1)';
            // Three.js粒子材质淡入
            if (this.orbitMaterial) {
                this._animateUniform(this.orbitMaterial.uniforms.uOpacity, 0, 0.4, 500);
            }
        }, 150);

        // 200ms — 思考文字淡入（500ms, ease-out cubic）
        setTimeout(() => {
            if (!this.isActive) return;
            this.els.text.style.opacity = '0.7';
            this.els.text.style.transform = 'translateX(-50%) translateY(0)';
        }, 200);

        // 100ms — 边缘微光淡入
        setTimeout(() => {
            if (!this.isActive) return;
            this.els.edgeGlow.style.opacity = '0.04';
        }, 100);

        // 800ms — 标记入场完成
        setTimeout(() => {
            if (!this.isActive || this.exiting) return;
            this.entering = false;
        }, 800);

        // 禁用Three.js后处理（确保光效清晰）
        if (this.threeScene && this.threeScene.enablePostProcessing) {
            this.threeScene.enablePostProcessing(false);
        }
    }

    // ============================================
    // 5. 退场动画 — 快速同步淡出
    // ============================================

    exit() {
        if (!this.isActive) return;
        this.isActive = false;
        this.entering = false;
        this.exiting = true;

        // 所有元素在400ms内同步淡出
        const fadeOutStyle = 'opacity 400ms cubic-bezier(0.55, 0, 1, 0.45)';

        this.els.mask.style.transition = fadeOutStyle;
        this.els.mask.style.opacity = '0';

        this.els.glowContainer.style.transition = fadeOutStyle;
        this.els.glowContainer.style.opacity = '0';
        this.els.glowContainer.style.transform = 'translate(-50%, -50%) scale(0.95)';

        this.els.orbitContainer.style.transition = fadeOutStyle;
        this.els.orbitContainer.style.opacity = '0';

        this.els.text.style.transition = fadeOutStyle;
        this.els.text.style.opacity = '0';
        this.els.text.style.transform = 'translateX(-50%) translateY(4px)';

        this.els.edgeGlow.style.transition = fadeOutStyle;
        this.els.edgeGlow.style.opacity = '0';

        // Three.js粒子淡出
        if (this.orbitMaterial) {
            this._animateUniform(this.orbitMaterial.uniforms.uOpacity,
                this.orbitMaterial.uniforms.uOpacity.value, 0, 400);
        }

        // 400ms后完全隐藏
        setTimeout(() => {
            if (!this.exiting) return;
            this.setVisible(false);
            this.exiting = false;
            this.springTarget = 0;
            this.springValue = 0;
        }, 400);
    }

    // ============================================
    // 6. 每帧更新 — 呼吸动画 + 轨道旋转
    // ============================================

    update(deltaTime) {
        if (!this.isActive && !this.entering && !this.exiting) return;

        this.elapsedTime += deltaTime;

        // 入场期间：spring动画驱动光晕出现
        if (this.entering) {
            this._updateSpring(deltaTime);
            this._applyGlowEntrance();
        }

        // 稳定态：呼吸动画
        if (this.isActive && !this.entering) {
            this._updateBreath(deltaTime);
        }

        // 始终更新：CSS轨道粒子旋转（3秒/圈）
        this._updateOrbitParticles(deltaTime);

        // 始终更新：Three.js ShaderMaterial
        if (this.orbitMaterial) {
            this.orbitMaterial.uniforms.uTime.value = this.elapsedTime;
        }

        // 边缘微光呼吸（8秒周期）
        if (this.isActive && !this.entering) {
            this._updateEdgeGlow(deltaTime);
        }
    }

    /**
     * Spring物理模拟 — stiffness:300, damping:25
     * 用于光晕入场的弹性效果
     */
    _updateSpring(dt) {
        // 固定时间步长保证稳定性
        const step = 0.016;
        const steps = Math.ceil(dt / step);
        const h = dt / steps;

        for (let i = 0; i < steps; i++) {
            const force = this.springStiffness * (this.springTarget - this.springValue);
            this.springVelocity += (force - this.springDamping * this.springVelocity) * h;
            this.springValue += this.springVelocity * h;
        }

        // 接近目标时停止
        if (Math.abs(this.springTarget - this.springValue) < 0.001 &&
            Math.abs(this.springVelocity) < 0.001) {
            this.springValue = this.springTarget;
        }
    }

    /**
     * 应用光晕入场动画（spring驱动）
     */
    _applyGlowEntrance() {
        const v = this.springValue;
        // spring值映射到opacity和scale
        const opacity = Math.min(v * 1.2, 1);  // 快速达到满opacity
        const scale = 0.85 + v * 0.15;         // 0.85 → 1.0

        this.els.glowContainer.style.opacity = String(opacity);
        this.els.glowContainer.style.transform =
            `translate(-50%, -50%) scale(${scale})`;
    }

    /**
     * 呼吸动画 — 光晕的有机律动
     * opacity: 0.5↔0.7, scale: 1↔1.03, 周期4秒
     */
    _updateBreath(dt) {
        this.breathPhase += dt * (Math.PI * 2 / 4.0); // 4秒周期

        const breathNorm = Math.sin(this.breathPhase) * 0.5 + 0.5; // 0↔1

        // opacity: 0.5 → 0.7
        const opacity = 0.5 + breathNorm * 0.2;
        // scale: 1.0 → 1.03
        const scale = 1.0 + breathNorm * 0.03;

        // 应用给内层光晕（更微妙的变化）
        this.els.glowCore.style.opacity = String(opacity);
        this.els.glowInner.style.opacity = String(0.6 + breathNorm * 0.15);
        this.els.glowInner.style.transform =
            `translate(-50%, -50%) scale(${scale})`;
    }

    /**
     * CSS轨道粒子更新 — 3秒/圈，120px半径
     */
    _updateOrbitParticles(dt) {
        if (!this.els.orbitDots) return;

        const speed = (Math.PI * 2) / 3.0; // 角速度：3秒/圈
        const radius = 120; // 像素半径

        this.els.orbitDots.forEach((dot, i) => {
            const phaseOffset = (i / 3) * Math.PI * 2; // 均匀分布
            const angle = this.elapsedTime * speed + phaseOffset;

            const x = Math.cos(angle) * radius;
            const y = Math.sin(angle) * radius;

            // Z轴深度模拟：在后方的粒子更淡
            // cos(angle) > 0 时在前方，< 0 时在后方
            const depthRatio = Math.sin(angle); // -1 ~ 1
            const alpha = 0.15 + (depthRatio + 1) * 0.125; // 0.15 ~ 0.4
            const scale = 0.7 + (depthRatio + 1) * 0.15;   // 0.7 ~ 1.0

            dot.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
            dot.style.opacity = String(alpha);
        });
    }

    /**
     * 屏幕边缘微光 — 缓慢收缩扩散，8秒周期
     * 模仿Siri唤醒时的边缘光效
     */
    _updateEdgeGlow(dt) {
        const phase = this.elapsedTime * (Math.PI * 2 / 8.0); // 8秒周期
        const breath = Math.sin(phase) * 0.5 + 0.5; // 0↔1

        // 光晕强度在 0.02 ~ 0.06 之间呼吸
        const opacity = 0.02 + breath * 0.04;
        const spread = 40 + breath * 30; // 40px ~ 70px

        this.els.edgeGlow.style.opacity = String(opacity);
        this.els.edgeGlow.style.boxShadow =
            `inset 0 0 ${spread}px ${this.accentColor}15`;
    }

    // ============================================
    // 7. 工具方法
    // ============================================

    /**
     * 读取系统强调色
     */
    _readAccentColor() {
        // 尝试从CSS变量读取
        const rootStyles = getComputedStyle(document.documentElement);
        const cssAccent = rootStyles.getPropertyValue('--accent-color').trim();
        if (cssAccent) return cssAccent;

        // 检测macOS/iOS系统强调色
        const testEl = document.createElement('div');
        testEl.style.color = '-apple-system-control-accent';
        document.body.appendChild(testEl);
        const computedColor = getComputedStyle(testEl).color;
        document.body.removeChild(testEl);

        if (computedColor && computedColor !== 'rgb(0, 0, 0)') {
            return computedColor;
        }

        // Fallback: 苹果蓝
        return '#007AFF';
    }

    /**
     * 统一属性的简单动画（用于Three.js uniforms）
     */
    _animateUniform(uniform, from, to, duration) {
        const startTime = performance.now();
        const tick = () => {
            const elapsed = performance.now() - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const eased = this._easeOutCubic(progress);
            uniform.value = from + (to - from) * eased;
            if (progress < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    }

    /**
     * ease-out cubic 缓动
     */
    _easeOutCubic(t) {
        return 1 - Math.pow(1 - t, 3);
    }

    /**
     * 设置思考文字
     */
    setText(text) {
        if (this.els.text) {
            this.els.text.textContent = text;
        }
    }

    // ============================================
    // 8. 可见性控制
    // ============================================

    setVisible(visible) {
        this.isVisible = visible;

        if (visible) {
            this.cssOverlay.classList.remove('hidden');
            if (this.orbitGroup) this.orbitGroup.visible = true;
        } else {
            this.cssOverlay.classList.add('hidden');
            if (this.orbitGroup) this.orbitGroup.visible = false;
        }
    }

    _hideAll() {
        this.els.mask.style.opacity = '0';
        this.els.glowContainer.style.opacity = '0';
        this.els.glowContainer.style.transform = 'translate(-50%, -50%) scale(0.85)';
        this.els.orbitContainer.style.opacity = '0';
        this.els.text.style.opacity = '0';
        this.els.text.style.transform = 'translateX(-50%) translateY(8px)';
        this.els.edgeGlow.style.opacity = '0';
        if (this.orbitMaterial) {
            this.orbitMaterial.uniforms.uOpacity.value = 0;
        }
    }

    // ============================================
    // 9. 清理
    // ============================================

    dispose() {
        this.isActive = false;

        // 移除CSS样式
        const styleSheet = document.getElementById('liminal-state-styles');
        if (styleSheet) styleSheet.remove();

        // 移除DOM元素
        Object.values(this.els).forEach(el => {
            if (el && el.parentNode) el.remove();
        });
        this.els = {};

        // 释放Three.js资源
        if (this.orbitParticles) {
            this.orbitParticles.geometry.dispose();
            this.orbitMaterial.dispose();
            this.scene.remove(this.orbitGroup);
        }
        this.orbitParticles = null;
        this.orbitMaterial = null;
        this.orbitGroup = null;
    }
}

window.LiminalState = LiminalState;
