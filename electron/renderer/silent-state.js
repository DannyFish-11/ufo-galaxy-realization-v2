/**
 * silent-state.js
 * Silent 静默态 — "呼吸的深海"
 *
 * 技术方案：全屏 WebGL Fragment Shader（Three.js）
 * - PlaneGeometry(2,2) + OrthographicCamera 全屏四边形
 * - 3层 Perlin noise 叠加产生有机波动
 * - 光晕限制在屏幕底部40% + 两侧边缘
 * - 8秒慢呼吸周期
 *
 * 色调：rgb(40,75,180) @ 4-10% opacity
 */

// ---------- Vertex Shader — 传递UV坐标 ----------
const SILENT_VERTEX_SHADER = `
varying vec2 vUv;
void main(){
    vUv = uv;
    gl_Position = vec4(position, 1.0);
}
`;

// ---------- Fragment Shader — 3层Perlin noise有机波动 ----------
const SILENT_FRAGMENT_SHADER = `
// ============================================
// Classic Perlin 3D Noise — 完整实现
// ============================================
vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x, 289.0);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159 - 0.85373472095314 * r;}
vec3 fade(vec3 t){return t*t*t*(t*(t*6.0-15.0)+10.0);}

float cnoise(vec3 P){
  vec3 Pi0 = floor(P);
  vec3 Pi1 = Pi0 + vec3(1.0);
  Pi0 = mod(Pi0, 289.0);
  Pi1 = mod(Pi1, 289.0);
  vec3 Pf0 = fract(P);
  vec3 Pf1 = Pf0 - vec3(1.0);
  vec4 ix = vec4(Pi0.x, Pi1.x, Pi0.x, Pi1.x);
  vec4 iy = vec4(Pi0.yy, Pi1.yy);
  vec4 iz0 = Pi0.zzzz;
  vec4 iz1 = Pi1.zzzz;
  vec4 ixy = permute(permute(ix) + iy);
  vec4 ixy0 = permute(ixy + iz0);
  vec4 ixy1 = permute(ixy + iz1);
  vec4 gx0 = ixy0 / 7.0;
  vec4 gy0 = fract(floor(gx0) / 7.0) - 0.5;
  gx0 = fract(gx0);
  vec4 gz0 = vec4(0.5) - abs(gx0) - abs(gy0);
  vec4 sz0 = step(gz0, vec4(0.0));
  gx0 -= sz0 * (step(0.0, gx0) - 0.5);
  gy0 -= sz0 * (step(0.0, gy0) - 0.5);
  vec4 gx1 = ixy1 / 7.0;
  vec4 gy1 = fract(floor(gx1) / 7.0) - 0.5;
  gx1 = fract(gx1);
  vec4 gz1 = vec4(0.5) - abs(gx1) - abs(gy1);
  vec4 sz1 = step(gz1, vec4(0.0));
  gx1 -= sz1 * (step(0.0, gx1) - 0.5);
  gy1 -= sz1 * (step(0.0, gy1) - 0.5);
  vec3 g000 = vec3(gx0.x,gy0.x,gz0.x);
  vec3 g100 = vec3(gx0.y,gy0.y,gz0.y);
  vec3 g010 = vec3(gx0.z,gy0.z,gz0.z);
  vec3 g110 = vec3(gx0.w,gy0.w,gz0.w);
  vec3 g001 = vec3(gx1.x,gy1.x,gz1.x);
  vec3 g101 = vec3(gx1.y,gy1.y,gz1.y);
  vec3 g011 = vec3(gx1.z,gy1.z,gz1.z);
  vec3 g111 = vec3(gx1.w,gy1.w,gz1.w);
  vec4 norm0 = taylorInvSqrt(vec4(dot(g000,g000),dot(g010,g010),dot(g100,g100),dot(g110,g110)));
  g000 *= norm0.x; g010 *= norm0.y; g100 *= norm0.z; g110 *= norm0.w;
  vec4 norm1 = taylorInvSqrt(vec4(dot(g001,g001),dot(g011,g011),dot(g101,g101),dot(g111,g111)));
  g001 *= norm1.x; g011 *= norm1.y; g101 *= norm1.z; g111 *= norm1.w;
  float n000 = dot(g000, Pf0);
  float n100 = dot(g100, vec3(Pf1.x, Pf0.yz));
  float n010 = dot(g010, vec3(Pf0.x, Pf1.y, Pf0.z));
  float n110 = dot(g110, vec3(Pf1.xy, Pf0.z));
  float n001 = dot(g001, vec3(Pf0.xy, Pf1.z));
  float n101 = dot(g101, vec3(Pf1.x, Pf0.y, Pf1.z));
  float n011 = dot(g011, vec3(Pf0.x, Pf1.yz));
  float n111 = dot(g111, Pf1);
  vec3 fade_xyz = fade(Pf0);
  vec4 n_z = mix(vec4(n000, n100, n010, n110), vec4(n001, n101, n011, n111), fade_xyz.z);
  vec2 n_yz = mix(n_z.xy, n_z.zw, fade_xyz.y);
  float n_xyz = mix(n_yz.x, n_yz.y, fade_xyz.x);
  return 2.2 * n_xyz;
}

// ============================================
// Uniforms & Main
// ============================================
uniform float uTime;
varying vec2 vUv;

void main(){
  vec2 uv = vUv;
  
  // ---------- 三层 Perlin noise 叠加 ----------
  // Layer 1: 大尺度慢波（频率0.5，速度0.1）— 整体光晕缓慢变形
  float n1 = cnoise(vec3(uv * 0.5, uTime * 0.1));
  // Layer 2: 中区域流动（频率2.0，速度0.3）— 光晕内部流动感
  float n2 = cnoise(vec3(uv * 2.0, uTime * 0.3));
  // Layer 3: 细微扰动（频率8.0，速度0.5）— 边缘不规则感
  float n3 = cnoise(vec3(uv * 8.0, uTime * 0.5));
  
  // 加权合成：大尺度占主导，细微扰动最少
  float noise = n1 * 0.5 + n2 * 0.35 + n3 * 0.15;
  
  // ---------- 光晕区域限制 ----------
  // 计算到边缘的最小距离（底部和两侧）
  float edgeDist = min(min(uv.x, 1.0 - uv.x), uv.y);
  // smoothstep将光晕限制在边缘附近，noise增加边缘不规则感
  float glow = smoothstep(0.4, 0.0, edgeDist + noise * 0.15);
  
  // ---------- 8秒慢呼吸 ----------
  // sin周期 = 2π/0.785 ≈ 8秒
  float breathe = sin(uTime * 0.785) * 0.3 + 0.7;
  
  // ---------- 颜色输出 ----------
  // 纯宇宙蓝 rgb(40,75,180) → vec3(0.157, 0.294, 0.706)
  vec3 color = vec3(0.157, 0.294, 0.706);
  // opacity 4-10%: glow(0~1) * 0.08 * breathe(0.4~1.0) → 0~0.08
  float alpha = glow * 0.08 * breathe;
  
  gl_FragColor = vec4(color, alpha);
}
`;

// ============================================
// SilentState 类
// ============================================
class SilentState {
    /**
     * @param {Object} overlay - 覆盖层对象，需包含 element 属性
     */
    constructor(overlay) {
        this.element = overlay?.element || document.getElementById('sLayer');
        this.canvasContainer = document.getElementById('silent-canvas-container');
        this.isActive = false;

        // Three.js 对象
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.material = null;
        this.mesh = null;
        this.clock = null;

        // 动画循环
        this._rafId = null;
        this._isDisposed = false;

        // 初始化 WebGL 场景
        this._initWebGL();
    }

    // ---------- WebGL 初始化 ----------
    _initWebGL() {
        // 创建场景
        this.scene = new THREE.Scene();

        // 正交相机 — 全屏四边形不需要透视
        this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

        // WebGL 渲染器 — alpha透明， premultipliedAlpha
        this.renderer = new THREE.WebGLRenderer({
            alpha: true,
            premultipliedAlpha: false,
            antialias: false // 全屏Shader不需要抗锯齿
        });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.domElement.style.width = '100%';
        this.renderer.domElement.style.height = '100%';
        this.renderer.domElement.style.display = 'block';

        // Shader 材质
        this.material = new THREE.ShaderMaterial({
            vertexShader: SILENT_VERTEX_SHADER,
            fragmentShader: SILENT_FRAGMENT_SHADER,
            uniforms: {
                uTime: { value: 0.0 }
            },
            transparent: true,
            depthWrite: false,
            depthTest: false
        });

        // 全屏四边形 — PlaneGeometry(2,2) 正好填满正交相机视野
        const geometry = new THREE.PlaneGeometry(2, 2);
        this.mesh = new THREE.Mesh(geometry, this.material);
        this.scene.add(this.mesh);

        // 时钟
        this.clock = new THREE.Clock();

        // 将 canvas 注入容器
        if (this.canvasContainer) {
            this.canvasContainer.appendChild(this.renderer.domElement);
        }

        console.log('[SilentState] WebGL Shader 场景初始化完成');
    }

    // ---------- 动画循环 ----------
    _startRenderLoop() {
        const loop = () => {
            if (this._isDisposed) return;
            this._rafId = requestAnimationFrame(loop);
            this._render();
        };
        this._rafId = requestAnimationFrame(loop);
    }

    _render() {
        if (!this.isActive || !this.material || !this.renderer) return;

        // 更新时间uniform
        const elapsed = this.clock.getElapsedTime();
        this.material.uniforms.uTime.value = elapsed;

        // 渲染
        this.renderer.render(this.scene, this.camera);
    }

    _stopRenderLoop() {
        if (this._rafId !== null) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
    }

    // ---------- 生命周期 ----------

    /** 进入静默态 */
    enter() {
        if (this.isActive) return;
        this.isActive = true;

        // 显示容器
        if (this.canvasContainer) {
            this.canvasContainer.classList.add('active');
        }

        // 启动动画循环
        this.clock.start();
        this._startRenderLoop();

        console.log('[SilentState] 进入 Silent 态 — WebGL Shader 呼吸启动');
    }

    /** 退出静默态 */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // 停止动画
        this._stopRenderLoop();
        this.clock.stop();

        // 隐藏容器
        if (this.canvasContainer) {
            this.canvasContainer.classList.remove('active');
        }

        console.log('[SilentState] 退出 Silent 态');
    }

    /** 窗口大小变化 */
    onResize() {
        if (!this.renderer) return;

        const w = window.innerWidth;
        const h = window.innerHeight;

        // 更新渲染器尺寸
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        console.log('[SilentState] 窗口 resize:', w, 'x', h);
    }

    /** 清理 */
    dispose() {
        this._isDisposed = true;
        this.isActive = false;
        this._stopRenderLoop();

        if (this.renderer) {
            this.renderer.dispose();
            if (this.renderer.domElement && this.renderer.domElement.parentNode) {
                this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
            }
            this.renderer = null;
        }

        if (this.material) {
            this.material.dispose();
            this.material = null;
        }

        if (this.mesh) {
            if (this.mesh.geometry) this.mesh.geometry.dispose();
            this.mesh = null;
        }

        this.scene = null;
        this.camera = null;
        this.clock = null;

        console.log('[SilentState] 已清理');
    }
}

window.SilentState = SilentState;
