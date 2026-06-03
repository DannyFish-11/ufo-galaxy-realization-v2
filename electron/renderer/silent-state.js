/**
 * silent-state.js — v39 Fixed
 * Silent 静默态 — "存在但不被注意"
 *
 * 技术方案：WebGL Fragment Shader + Perlin Noise（本地 Three.js）
 * 视觉：极淡的底部/边缘蓝紫光晕，像 Siri 唤醒时的屏幕边缘发光
 * 特征：8秒慢呼吸，几乎看不见，但你感觉到"有什么在那里"
 *
 * 修复：
 * - P1: 使用 window.THREE（preload 本地加载，无需 CDN）
 * - P2: exit() 时 dispose 所有 WebGL 资源，防止内存泄漏
 * - P3: 添加 try-catch 错误边界，WebGL 失败时 graceful degradation
 */

class SilentState {
    constructor(cssOverlay, threeContainer) {
        this.element = cssOverlay?.element || document.getElementById('sLayer');
        this.canvasContainer = document.getElementById('silent-canvas-container');
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.material = null;
        this.mesh = null;
        this.geometry = null;
        this.uniforms = null;
        this.animationId = null;
        this.fallbackEl = document.getElementById('silent-canvas-fallback');
        this.isActive = false;
        this.startTime = null;
        this.isDisposed = false;
        this.useWebGL = false;
    }

    /** 检查 Three.js 是否可用 */
    _checkTHREE() {
        if (typeof window.THREE === 'undefined') {
            console.warn('[SilentState] window.THREE 不可用 — 可能是 preload 加载失败');
            return false;
        }
        return true;
    }

    /** 初始化 WebGL 场景 */
    initWebGL() {
        if (this.isDisposed || this.renderer) return;

        // P1 修复：使用 window.THREE（preload 本地加载）
        if (!this._checkTHREE()) {
            console.warn('[SilentState] WebGL 不可用 — Silent 态将以 CSS 降级模式运行');
            return;
        }

        try {
            const container = this.canvasContainer;
            if (!container) return;

            const width = window.innerWidth;
            const height = window.innerHeight;

            // 创建渲染器
            this.renderer = new window.THREE.WebGLRenderer({
                antialias: false,
                alpha: true,
                premultipliedAlpha: false
            });
            this.renderer.setSize(width, height);
            this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            this.renderer.setClearColor(0x000000, 0);
            this.renderer.domElement.style.width = '100%';
            this.renderer.domElement.style.height = '100%';
            this.renderer.domElement.style.display = 'block';
            container.appendChild(this.renderer.domElement);

            // 场景和相机
            this.scene = new window.THREE.Scene();
            this.camera = new window.THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

            // 自定义 Perlin noise shader
            this.uniforms = {
                uTime: { value: 0.0 },
                uResolution: { value: new window.THREE.Vector2(width, height) },
                uViewportRes: { value: new window.THREE.Vector2(width, height) }
            };

            this.material = new window.THREE.ShaderMaterial({
                uniforms: this.uniforms,
                transparent: true,
                depthWrite: false,
                vertexShader: this._getVertexShader(),
                fragmentShader: this._getFragmentShader()
            });

            this.geometry = new window.THREE.PlaneGeometry(2, 2);
            this.mesh = new window.THREE.Mesh(this.geometry, this.material);
            this.scene.add(this.mesh);

        } catch (err) {
            console.error('[SilentState] WebGL 初始化失败:', err);
            this._cleanupPartial();
        }
    }

    /** 清理部分初始化的资源 */
    _cleanupPartial() {
        if (this.geometry) { this.geometry.dispose(); this.geometry = null; }
        if (this.material) { this.material.dispose(); this.material = null; }
        if (this.renderer) {
            this.renderer.dispose();
            this.renderer = null;
        }
    }

    /** Vertex Shader */
    _getVertexShader() {
        return `
            varying vec2 vUv;
            void main() {
                vUv = uv;
                gl_Position = vec4(position, 1.0);
            }
        `;
    }

    /** Fragment Shader — Perlin noise organic glow */
    _getFragmentShader() {
        return `
            uniform float uTime;
            uniform vec2 uResolution;
            uniform vec2 uViewportRes;
            varying vec2 vUv;

            // Perlin noise 2D
            vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x, 289.0);}
            vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}
            vec2 fade(vec2 t) {return t*t*t*(t*(t*6.0-15.0)+10.0);}

            float cnoise(vec2 P){
                vec4 Pi = floor(P.xyxy) + vec4(0.0, 0.0, 1.0, 1.0);
                vec4 Pf = fract(P.xyxy) - vec4(0.0, 0.0, 1.0, 1.0);
                Pi = mod(Pi, 289.0);
                vec4 ix = Pi.xzxz;
                vec4 iy = Pi.yyww;
                vec4 fx = Pf.xzxz;
                vec4 fy = Pf.yyww;
                vec4 i = permute(permute(ix) + iy);
                vec4 gx = 2.0 * fract(i * 0.0243902439) - 1.0;
                vec4 gy = abs(gx) - 0.5;
                vec4 tx = floor(gx + 0.5);
                gx = gx - tx;
                vec2 g00 = vec2(gx.x,gy.x);
                vec2 g10 = vec2(gx.y,gy.y);
                vec2 g01 = vec2(gx.z,gy.z);
                vec2 g11 = vec2(gx.w,gy.w);
                vec4 norm = 1.79284291400159 - 0.85373472095314 * vec4(dot(g00,g00), dot(g01,g01), dot(g10,g10), dot(g11,g11));
                g00 *= norm.x; g01 *= norm.y; g10 *= norm.z; g11 *= norm.w;
                float n00 = dot(g00, vec2(fx.x, fy.x));
                float n10 = dot(g10, vec2(fx.y, fy.y));
                float n01 = dot(g01, vec2(fx.z, fy.z));
                float n11 = dot(g11, vec2(fx.w, fy.w));
                vec2 fade_xy = fade(Pf.xy);
                vec2 n_x = mix(vec2(n00, n01), vec2(n10, n11), fade_xy.x);
                float n_xy = mix(n_x.x, n_x.y, fade_xy.y);
                return 2.3 * n_xy;
            }

            void main(){
                vec2 uv = gl_FragCoord.xy / uViewportRes;
                float aspect = uViewportRes.x / uViewportRes.y;

                // 时间推进（极慢，0.03倍速）
                float time = uTime * 0.03;

                // 多层 Perlin noise 叠加
                float noise1 = cnoise(uv * 3.0 + time * 0.5);
                float noise2 = cnoise(uv * 6.0 - time * 0.3);
                float noise3 = cnoise(uv * 12.0 + time * 0.2);

                // 有机纹理组合
                float organicPattern = noise1 * 0.5 + noise2 * 0.3 + noise3 * 0.2;
                organicPattern = organicPattern * 0.5 + 0.5;

                // 垂直分布：底部更亮，向上渐隐
                float verticalDist = 1.0 - uv.y;
                verticalDist = pow(verticalDist, 1.8);

                // 水平分布：两侧比中间亮（环绕感）
                float horizontalDist = abs(uv.x - 0.5) * 2.0;
                horizontalDist = pow(horizontalDist, 0.6);

                // 组合分布
                float distribution = verticalDist * 0.6 + horizontalDist * 0.4;
                distribution = smoothstep(0.0, 1.0, distribution);

                // 边缘柔化
                float edgeFade = smoothstep(0.0, 0.15, uv.y);
                distribution *= edgeFade;

                // 有机流动
                float flow = sin(time * 0.5 + organicPattern * 6.28) * 0.5 + 0.5;
                float glow = organicPattern * distribution * flow;

                // 8秒慢呼吸（修复：振幅 0.3→0.35，更明显）
                float breathe = sin(uTime * 0.785) * 0.35 + 0.65;

                // 纯宇宙蓝 rgb(40,75,180)
                vec3 color = vec3(0.157, 0.294, 0.706);
                // opacity 0.12（修复：0.08→0.12，6-15%）
                float alpha = glow * 0.12 * breathe;

                // 微妙顶部紫光边缘
                float topEdge = smoothstep(0.85, 1.0, uv.y);
                float topGlow = topEdge * horizontalDist * 0.015 * breathe;

                // 颜色混合
                vec3 topColor = vec3(0.4, 0.25, 0.7);
                color = mix(color, topColor, topEdge * 0.15);

                gl_FragColor = vec4(color, alpha + topGlow);
            }
        `;
    }

    // ---------- 生命周期 ----------

    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.isDisposed = false;

        this.initWebGL();

        // P12: 标记是否使用 WebGL
        this.useWebGL = (this.renderer !== null);

        if (this.useWebGL) {
            // WebGL 模式：显示 canvas
            if (this.canvasContainer) {
                this.canvasContainer.classList.add('active');
            }
            this.startTime = performance.now();
            this.animate();
        } else {
            // CSS fallback 模式：显示 fallback 元素
            if (this.fallbackEl) {
                this.fallbackEl.classList.add('active');
            }
        }

        if (this.element) {
            this.element.classList.add('on');
        }
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        if (this.canvasContainer) {
            this.canvasContainer.classList.remove('active');
        }
        // P12: 清理 CSS fallback
        if (this.fallbackEl) {
            this.fallbackEl.classList.remove('active');
        }
        if (this.element) {
            this.element.classList.remove('on');
        }

        // 停止渲染循环
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }

        // P2 修复：exit() 时 dispose 所有 WebGL 资源
        this._disposeWebGL();

        console.log('[SilentState] 退出 Silent 态');
    }

    /** P2 修复：完全 dispose 所有 WebGL 资源 */
    _disposeWebGL() {
        if (this.mesh) {
            this.scene?.remove(this.mesh);
            this.mesh = null;
        }
        if (this.geometry) {
            this.geometry.dispose();
            this.geometry = null;
        }
        if (this.material) {
            this.material.dispose();
            this.material = null;
        }
        if (this.renderer) {
            // 移除 canvas
            const canvas = this.renderer.domElement;
            if (canvas && canvas.parentNode) {
                canvas.parentNode.removeChild(canvas);
            }
            this.renderer.dispose();
            this.renderer = null;
        }
        this.scene = null;
        this.camera = null;
        this.uniforms = null;
    }

    /** 完全清理 */
    dispose() {
        this.isActive = false;
        this.isDisposed = true;

        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }

        this._disposeWebGL();

        if (this.element) {
            this.element.classList.remove('on');
        }
        if (this.canvasContainer) {
            this.canvasContainer.classList.remove('active');
        }

        console.log('[SilentState] 已完全清理');
    }

    // ---------- 渲染循环 ----------

    animate() {
        if (!this.isActive || this.isDisposed) return;

        // P1 修复：使用 window.THREE
        if (!this.renderer || !this.scene || !this.camera || !this.uniforms) {
            // WebGL 不可用，跳过渲染（CSS 降级模式）
            return;
        }

        this.animationId = requestAnimationFrame(() => this.animate());

        const elapsed = (performance.now() - this.startTime) / 1000.0;
        this.uniforms.uTime.value = elapsed;

        this.renderer.render(this.scene, this.camera);
    }

    // ---------- 工具 ----------

    onResize() {
        if (!this.renderer || !this.uniforms || this.isDisposed) return;

        const width = window.innerWidth;
        const height = window.innerHeight;

        this.renderer.setSize(width, height);
        this.uniforms.uResolution.value.set(width, height);
        this.uniforms.uViewportRes.value.set(width, height);
    }
}

window.SilentState = SilentState;
