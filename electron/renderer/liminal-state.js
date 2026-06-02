/**
 * liminal-state.js
 * Liminal 阈限态 — "空间被打开"
 *
 * 技术方案：Three.js 3D 透视
 * 1. 桌面壁纸作为 Texture 贴在 PlaneGeometry 上
 * 2. PerspectiveCamera, FOV 60
 * 3. 相机从正前方推入 — 2.6秒 ease-out-expo
 * 4. 指数雾 FogExp2 增加深度感
 * 5. 消失点光球 — ShaderMaterial + FBM noise 脉动效果
 *
 * 色调：rgb(60,100,220) @ 10-20%
 */

// ============================================
// 消失点光球 — Vertex Shader
// ============================================
const ORB_VERTEX_SHADER = `
varying vec2 vUv;
void main(){
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

// ============================================
// 消失点光球 — Fragment Shader (FBM noise)
// ============================================
const ORB_FRAGMENT_SHADER = `
// ---------- Classic Perlin 3D Noise ----------
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

// ---------- FBM (Fractal Brownian Motion) ----------
float fbm(vec3 p){
  float sum = 0.0;
  float amp = 1.0;
  float freq = 1.0;
  for(int i = 0; i < 5; i++){
    sum += cnoise(p * freq) * amp;
    amp *= 0.5;
    freq *= 2.0;
  }
  return sum;
}

// ---------- Uniforms & Main ----------
uniform float uTime;
varying vec2 vUv;

void main(){
  vec2 uv = vUv - 0.5;
  float dist = length(uv);
  
  // 脉动效果 — 1Hz脉动
  float pulse = sin(uTime * 1.0) * 0.15 + 1.0;
  float shape = smoothstep(0.5 * pulse, 0.0, dist);
  
  // FBM noise 扰动 — 增加有机感
  float n = fbm(vec3(uv * 3.0, uTime * 0.2));
  shape *= 0.7 + n * 0.3;
  
  // 颜色：rgb(60,100,220)
  vec3 color = vec3(0.235, 0.392, 0.863);
  float alpha = shape * 0.15;
  
  gl_FragColor = vec4(color, alpha);
}
`;

// ============================================
// 缓动函数 — easeOutExpo
// ============================================
function easeOutExpo(t) {
    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
}

// ============================================
// LiminalState 类
// ============================================
class LiminalState {
    /**
     * @param {Object} cssOverlay - CSS覆盖层对象
     * @param {Object} threeContainer - Three.js容器DOM元素
     */
    constructor(cssOverlay, threeContainer) {
        this.element = cssOverlay?.element || document.getElementById('lLayer');
        this.container = threeContainer || document.getElementById('three-container');
        this.isActive = false;
        this.isAnimating = false;

        // Three.js 核心对象
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.desktopPlane = null;      // 桌面壁纸平面
        this.orbMesh = null;           // 消失点光球
        this.orbMaterial = null;       // 光球Shader材质
        this.clock = null;

        // 相机动画状态
        this.cameraAnim = {
            startPos: new THREE.Vector3(0, 0, 5),
            targetPos: new THREE.Vector3(0, 0.3, 2.5),
            startRotX: 0,
            targetRotX: 0.07, // 轻微俯视
            duration: 2.6,    // 2.6秒
            elapsed: 0,
            active: false
        };

        // 桌面平面缩放动画
        this.planeAnim = {
            startScale: 1.0,
            targetScale: 0.80,
            duration: 2.6,
            elapsed: 0,
            active: false
        };

        // 动画循环
        this._rafId = null;
        this._isDisposed = false;

        // 初始化 Three.js 场景
        this._initThreeJS();
    }

    // ---------- Three.js 场景初始化 ----------
    _initThreeJS() {
        // 创建场景
        this.scene = new THREE.Scene();

        // 指数雾 — 增加深度感
        this.scene.fog = new THREE.FogExp2(0x080C18, 0.08);

        // 透视相机 — FOV 60
        this.camera = new THREE.PerspectiveCamera(
            60,
            window.innerWidth / window.innerHeight,
            0.1,
            100
        );
        this.camera.position.copy(this.cameraAnim.startPos);
        this.camera.lookAt(0, 0, 0);

        // WebGL 渲染器
        this.renderer = new THREE.WebGLRenderer({
            alpha: true,
            antialias: true
        });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setClearColor(0x000000, 0); // 透明背景
        this.renderer.domElement.style.width = '100%';
        this.renderer.domElement.style.height = '100%';
        this.renderer.domElement.style.display = 'block';

        // 注入容器
        if (this.container) {
            this.container.appendChild(this.renderer.domElement);
        }

        // ---------- 桌面壁纸平面 ----------
        // 使用程序化生成的深色渐变纹理作为桌面壁纸
        const desktopTexture = this._createDesktopTexture();
        const planeGeometry = new THREE.PlaneGeometry(5, 3);
        const planeMaterial = new THREE.MeshBasicMaterial({
            map: desktopTexture,
            transparent: true,
            opacity: 0.9,
            side: THREE.DoubleSide
        });
        this.desktopPlane = new THREE.Mesh(planeGeometry, planeMaterial);
        this.desktopPlane.position.set(0, 0, 0);
        this.scene.add(this.desktopPlane);

        // ---------- 消失点光球 ----------
        const orbGeometry = new THREE.PlaneGeometry(1.5, 1.5);
        this.orbMaterial = new THREE.ShaderMaterial({
            vertexShader: ORB_VERTEX_SHADER,
            fragmentShader: ORB_FRAGMENT_SHADER,
            uniforms: {
                uTime: { value: 0.0 }
            },
            transparent: true,
            depthWrite: false,
            side: THREE.DoubleSide
        });
        this.orbMesh = new THREE.Mesh(orbGeometry, this.orbMaterial);
        // 光球位于"消失点"——画面上方中心
        this.orbMesh.position.set(0, 0.5, -2);
        this.scene.add(this.orbMesh);

        // 时钟
        this.clock = new THREE.Clock(false); // 不自动启动

        console.log('[LiminalState] Three.js 3D 场景初始化完成');
    }

    /**
     * 创建程序化桌面纹理
     * 使用 Canvas 生成深蓝灰渐变，模拟真实桌面壁纸
     */
    _createDesktopTexture() {
        const canvas = document.createElement('canvas');
        canvas.width = 1024;
        canvas.height = 768;
        const ctx = canvas.getContext('2d');

        // 基础深色渐变
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
        gradient.addColorStop(0, '#0C101C');
        gradient.addColorStop(0.5, '#0E1220');
        gradient.addColorStop(1, '#111828');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // 添加一些微妙的径向渐变增加真实感
        const grad1 = ctx.createRadialGradient(
            canvas.width * 0.2, canvas.height * 0.3, 0,
            canvas.width * 0.2, canvas.height * 0.3, canvas.width * 0.5
        );
        grad1.addColorStop(0, 'rgba(12, 16, 28, 0.6)');
        grad1.addColorStop(1, 'transparent');
        ctx.fillStyle = grad1;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const grad2 = ctx.createRadialGradient(
            canvas.width * 0.8, canvas.height * 0.7, 0,
            canvas.width * 0.8, canvas.height * 0.7, canvas.width * 0.45
        );
        grad2.addColorStop(0, 'rgba(17, 24, 40, 0.4)');
        grad2.addColorStop(1, 'transparent');
        ctx.fillStyle = grad2;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // 添加细微噪点纹理
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const data = imageData.data;
        for (let i = 0; i < data.length; i += 4) {
            const noise = (Math.random() - 0.5) * 3;
            data[i] = Math.max(0, Math.min(255, data[i] + noise));
            data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise));
            data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise));
        }
        ctx.putImageData(imageData, 0, 0);

        const texture = new THREE.CanvasTexture(canvas);
        texture.needsUpdate = true;
        return texture;
    }

    // ---------- 相机动画 ----------
    _updateCameraAnimation(deltaTime) {
        const anim = this.cameraAnim;
        if (!anim.active) return;

        anim.elapsed += deltaTime;
        const t = Math.min(anim.elapsed / anim.duration, 1.0);
        const eased = easeOutExpo(t);

        // 位置插值
        this.camera.position.lerpVectors(anim.startPos, anim.targetPos, eased);

        // 旋转插值（X轴轻微俯视）
        const currentRotX = THREE.MathUtils.lerp(anim.startRotX, anim.targetRotX, eased);
        this.camera.rotation.x = currentRotX;

        // 确保相机始终看向中心
        this.camera.lookAt(0, 0, 0);

        if (t >= 1.0) {
            anim.active = false;
            console.log('[LiminalState] 相机动画完成');
        }
    }

    // ---------- 桌面平面缩放动画 ----------
    _updatePlaneAnimation(deltaTime) {
        const anim = this.planeAnim;
        if (!anim.active) return;

        anim.elapsed += deltaTime;
        const t = Math.min(anim.elapsed / anim.duration, 1.0);
        const eased = easeOutExpo(t);

        const scale = THREE.MathUtils.lerp(anim.startScale, anim.targetScale, eased);
        this.desktopPlane.scale.set(scale, scale, 1);

        if (t >= 1.0) {
            anim.active = false;
        }
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
        if (!this.isActive && !this.isAnimating) return;
        if (!this.renderer || !this.scene || !this.camera) return;

        const deltaTime = this.clock.getDelta();
        const elapsed = this.clock.getElapsedTime();

        // 更新光球 Shader uniform
        if (this.orbMaterial) {
            this.orbMaterial.uniforms.uTime.value = elapsed;
        }

        // 更新相机动画
        this._updateCameraAnimation(deltaTime);

        // 更新平面缩放动画
        this._updatePlaneAnimation(deltaTime);

        // 光球呼吸旋转（微妙地增加活力）
        if (this.orbMesh) {
            this.orbMesh.rotation.z = Math.sin(elapsed * 0.3) * 0.05;
        }

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

    /** 进入阈限态 */
    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.isAnimating = true;

        // 显示 Three.js 容器
        if (this.container) {
            this.container.classList.add('active');
        }

        // 显示 CSS 覆盖层（大气雾效、文字等）
        if (this.element) {
            this.element.classList.remove('exiting');
            this.element.classList.add('active');
        }

        // 重置相机位置
        this.camera.position.copy(this.cameraAnim.startPos);
        this.camera.rotation.set(0, 0, 0);

        // 重置桌面平面
        this.desktopPlane.scale.set(1, 1, 1);

        // 启动相机动画
        this.cameraAnim.elapsed = 0;
        this.cameraAnim.active = true;

        // 启动缩放动画
        this.planeAnim.elapsed = 0;
        this.planeAnim.active = true;

        // 启动时钟和渲染循环
        this.clock.start();
        this._startRenderLoop();

        console.log('[LiminalState] 进入 Liminal 态 — Three.js 3D透视动画启动');
    }

    /** 退出阈限态 — 0.6秒淡出 */
    exit() {
        if (!this.isActive) return;
        this.isActive = false;
        this.isAnimating = true;

        // CSS覆盖层添加退出动画
        if (this.element) {
            this.element.classList.remove('active');
            this.element.classList.add('exiting');
        }

        // 0.6秒后停止Three.js渲染
        setTimeout(() => {
            this._stopRenderLoop();
            this.clock.stop();

            // 隐藏容器
            if (this.container) {
                this.container.classList.remove('active');
            }

            // 清理退出动画类
            if (this.element) {
                this.element.classList.remove('exiting');
            }

            this.isAnimating = false;
        }, 600);

        console.log('[LiminalState] 退出 Liminal 态 — 0.6秒淡出');
    }

    /** 每帧更新 — 外部render循环也调用 */
    update(deltaTime) {
        // 主要逻辑在 _render 中处理
    }

    /** 窗口大小变化 */
    onResize() {
        if (!this.renderer || !this.camera) return;

        const w = window.innerWidth;
        const h = window.innerHeight;

        // 更新相机宽高比
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();

        // 更新渲染器尺寸
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        console.log('[LiminalState] 窗口 resize:', w, 'x', h);
    }

    /** 清理 */
    dispose() {
        this._isDisposed = true;
        this.isActive = false;
        this.isAnimating = false;
        this._stopRenderLoop();

        if (this.renderer) {
            this.renderer.dispose();
            if (this.renderer.domElement && this.renderer.domElement.parentNode) {
                this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
            }
            this.renderer = null;
        }

        if (this.desktopPlane) {
            if (this.desktopPlane.geometry) this.desktopPlane.geometry.dispose();
            if (this.desktopPlane.material) {
                if (this.desktopPlane.material.map) this.desktopPlane.material.map.dispose();
                this.desktopPlane.material.dispose();
            }
            this.desktopPlane = null;
        }

        if (this.orbMaterial) {
            this.orbMaterial.dispose();
            this.orbMaterial = null;
        }

        if (this.orbMesh) {
            if (this.orbMesh.geometry) this.orbMesh.geometry.dispose();
            this.orbMesh = null;
        }

        if (this.scene && this.scene.fog) {
            this.scene.fog = null;
        }

        this.scene = null;
        this.camera = null;
        this.clock = null;

        console.log('[LiminalState] 已清理');
    }
}

window.LiminalState = LiminalState;
