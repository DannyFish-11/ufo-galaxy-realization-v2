/**
 * three-scene.js
 * Three.js scene manager for UFO Galaxy Desktop Presence
 * Handles renderer, camera, scene setup, and resize handling.
 */

class ThreeScene {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            throw new Error(`Container element "${containerId}" not found`);
        }

        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.pixelRatio = Math.min(window.devicePixelRatio, 2);

        // Scene setup
        this.scene = new THREE.Scene();
        // Transparent background for overlay
        this.scene.background = null;

        // Camera
        this.camera = new THREE.PerspectiveCamera(
            60,
            this.width / this.height,
            0.1,
            1000
        );
        this.camera.position.set(0, 0, 5);

        // Renderer with alpha
        this.renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
            premultipliedAlpha: false
        });
        this.renderer.setSize(this.width, this.height);
        this.renderer.setPixelRatio(this.pixelRatio);
        this.renderer.setClearColor(0x000000, 0);
        this.renderer.sortObjects = true;
        this.renderer.domElement.style.display = 'block';
        this.renderer.domElement.style.width = '100%';
        this.renderer.domElement.style.height = '100%';

        this.container.appendChild(this.renderer.domElement);

        // Clock for animations
        this.clock = new THREE.Clock();
        this.elapsedTime = 0;

        // Animation frame ID
        this.animationId = null;

        // Resize handler bound
        this.onResize = this.onResize.bind(this);
        window.addEventListener('resize', this.onResize);

        // Check for Electron API
        if (window.electronAPI) {
            window.electronAPI.onWindowResize((size) => {
                this.width = size.width;
                this.height = size.height;
                this.updateSize();
            });
        }

        // Render targets for post-processing
        this.sceneRenderTarget = null;
        this.postProcessScene = null;
        this.postProcessCamera = null;
        this.postProcessQuad = null;
        this.crtMaterial = null;
        this.isPostProcessingEnabled = false;

        this.initPostProcessing();
    }

    initPostProcessing() {
        // Create render target for scene capture
        this.sceneRenderTarget = new THREE.WebGLRenderTarget(
            this.width * this.pixelRatio,
            this.height * this.pixelRatio,
            {
                minFilter: THREE.LinearFilter,
                magFilter: THREE.LinearFilter,
                format: THREE.RGBAFormat,
                stencilBuffer: false
            }
        );

        // Post-processing scene (fullscreen quad)
        this.postProcessScene = new THREE.Scene();
        this.postProcessCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

        // CRT post-processing material (initially disabled)
        this.crtMaterial = new THREE.ShaderMaterial({
            uniforms: {
                uTime: { value: 0.0 },
                uSceneTexture: { value: this.sceneRenderTarget.texture },
                uResolution: { value: new THREE.Vector2(this.width, this.height) },
                uScanlineIntensity: { value: 0.3 },
                uChromaticStrength: { value: 0.8 },
                uVignetteStrength: { value: 0.6 },
                uGrainIntensity: { value: 0.12 },
                uFlickerIntensity: { value: 0.04 },
                uCurvature: { value: 0.08 }
            },
            vertexShader: this.getBasicVertexShader(),
            fragmentShader: this.getCRTFragmentShader(),
            transparent: false,
            depthTest: false,
            depthWrite: false
        });

        const quadGeometry = new THREE.PlaneGeometry(2, 2);
        this.postProcessQuad = new THREE.Mesh(quadGeometry, this.crtMaterial);
        this.postProcessScene.add(this.postProcessQuad);
    }

    getBasicVertexShader() {
        return `
            varying vec2 vUv;
            void main() {
                vUv = uv;
                gl_Position = vec4(position.xy, 0.0, 1.0);
            }
        `;
    }

    getCRTFragmentShader() {
        // Inlined CRT shader (same as crt.frag)
        return `
            uniform float uTime;
            uniform sampler2D uSceneTexture;
            uniform vec2 uResolution;
            uniform float uScanlineIntensity;
            uniform float uChromaticStrength;
            uniform float uVignetteStrength;
            uniform float uGrainIntensity;
            uniform float uFlickerIntensity;
            uniform float uCurvature;

            varying vec2 vUv;

            float rand(vec2 co) {
                return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
            }

            float noise(vec2 p) {
                vec2 ip = floor(p);
                vec2 u = fract(p);
                u = u * u * (3.0 - 2.0 * u);
                float res = mix(
                    mix(rand(ip), rand(ip + vec2(1.0, 0.0)), u.x),
                    mix(rand(ip + vec2(0.0, 1.0)), rand(ip + vec2(1.0, 1.0)), u.x),
                    u.y
                );
                return res;
            }

            void main() {
                vec2 uv = vUv;
                vec2 centered = uv - 0.5;
                float dist = length(centered);
                float curvature = 1.0 + uCurvature * dist * dist;
                vec2 curvedUv = centered * curvature + 0.5;

                if (curvedUv.x < 0.0 || curvedUv.x > 1.0 || curvedUv.y < 0.0 || curvedUv.y > 1.0) {
                    gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
                    return;
                }

                float chromOffset = uChromaticStrength * dist * 0.02;
                vec2 chromDir = normalize(centered + 0.001);

                float r = texture2D(uSceneTexture, curvedUv + chromDir * chromOffset * 1.5).r;
                float g = texture2D(uSceneTexture, curvedUv + chromDir * chromOffset * 0.5).g;
                float b = texture2D(uSceneTexture, curvedUv - chromDir * chromOffset * 0.8).b;
                vec3 color = vec3(r, g, b);

                float scanlineY = gl_FragCoord.y;
                float scanline = sin(scanlineY * 3.14159265 / 1.0) * 0.5 + 0.5;
                scanline = 1.0 - (scanline * uScanlineIntensity);
                color *= scanline;

                float scanBand = sin(curvedUv.y * 20.0 + uTime * 0.5) * 0.5 + 0.5;
                scanBand = smoothstep(0.48, 0.52, scanBand) * 0.08;
                color += vec3(scanBand * 0.3, scanBand * 0.5, scanBand * 0.7);

                float holdLine = step(0.98, rand(vec2(floor(curvedUv.y * 300.0), floor(uTime * 10.0))));
                color *= 1.0 - holdLine * 0.3;

                float vignetteDist = length(centered * 1.5);
                float vignette = 1.0 - smoothstep(0.4, 1.2, vignetteDist);
                vignette = mix(1.0, vignette, uVignetteStrength);
                color *= vignette;

                float grain = noise(gl_FragCoord.xy * 0.5 + uTime * 100.0);
                grain = (grain - 0.5) * uGrainIntensity;
                color += grain;

                float flicker = 1.0 + (rand(vec2(uTime * 60.0, 0.0)) - 0.5) * uFlickerIntensity;
                color *= flicker;

                vec3 phosphorTint = vec3(0.85, 0.95, 0.90);
                color *= phosphorTint;

                float centerGlow = 1.0 - dist * 0.3;
                color *= centerGlow;

                color = clamp(color, 0.0, 1.0);
                gl_FragColor = vec4(color, 1.0);
            }
        `;
    }

    enablePostProcessing(enabled) {
        this.isPostProcessingEnabled = enabled;
    }

    updateCRTUniforms(overrides = {}) {
        const defaults = {
            uScanlineIntensity: 0.3,
            uChromaticStrength: 0.8,
            uVignetteStrength: 0.6,
            uGrainIntensity: 0.12,
            uFlickerIntensity: 0.04,
            uCurvature: 0.08
        };
        const settings = { ...defaults, ...overrides };
        for (const [key, value] of Object.entries(settings)) {
            if (this.crtMaterial.uniforms[key]) {
                this.crtMaterial.uniforms[key].value = value;
            }
        }
    }

    onResize() {
        this.width = window.innerWidth;
        this.height = window.innerHeight;
        this.updateSize();
    }

    updateSize() {
        this.pixelRatio = Math.min(window.devicePixelRatio, 2);

        this.camera.aspect = this.width / this.height;
        this.camera.updateProjectionMatrix();

        this.renderer.setSize(this.width, this.height);
        this.renderer.setPixelRatio(this.pixelRatio);

        // Update render target size
        if (this.sceneRenderTarget) {
            this.sceneRenderTarget.setSize(
                this.width * this.pixelRatio,
                this.height * this.pixelRatio
            );
        }

        // Update resolution uniform
        if (this.crtMaterial) {
            this.crtMaterial.uniforms.uResolution.value.set(this.width, this.height);
        }

        // Notify listeners
        if (this.onResizeCallback) {
            this.onResizeCallback(this.width, this.height);
        }
    }

    setResizeCallback(callback) {
        this.onResizeCallback = callback;
    }

    add(object) {
        this.scene.add(object);
    }

    remove(object) {
        this.scene.remove(object);
    }

    getScene() {
        return this.scene;
    }

    getCamera() {
        return this.camera;
    }

    getRenderer() {
        return this.renderer;
    }

    getElapsedTime() {
        return this.elapsedTime;
    }

    render() {
        this.elapsedTime = this.clock.getElapsedTime();

        if (this.crtMaterial) {
            this.crtMaterial.uniforms.uTime.value = this.elapsedTime;
        }

        if (this.isPostProcessingEnabled && this.sceneRenderTarget) {
            // Render scene to target
            this.renderer.setRenderTarget(this.sceneRenderTarget);
            this.renderer.setClearColor(0x000000, 0);
            this.renderer.clear();
            this.renderer.render(this.scene, this.camera);

            // Render post-processing quad to screen
            this.renderer.setRenderTarget(null);
            this.renderer.setClearColor(0x000000, 0);
            this.renderer.clear();
            this.renderer.render(this.postProcessScene, this.postProcessCamera);
        } else {
            this.renderer.setRenderTarget(null);
            this.renderer.setClearColor(0x000000, 0);
            this.renderer.clear();
            this.renderer.render(this.scene, this.camera);
        }
    }

    startRenderLoop(renderCallback) {
        const loop = () => {
            this.animationId = requestAnimationFrame(loop);
            if (renderCallback) {
                renderCallback(this.elapsedTime);
            }
            this.render();
        };
        loop();
    }

    stopRenderLoop() {
        if (this.animationId !== null) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
    }

    dispose() {
        this.stopRenderLoop();
        window.removeEventListener('resize', this.onResize);

        if (this.sceneRenderTarget) {
            this.sceneRenderTarget.dispose();
        }
        if (this.crtMaterial) {
            this.crtMaterial.dispose();
        }
        if (this.postProcessQuad) {
            this.postProcessQuad.geometry.dispose();
        }

        this.renderer.dispose();
        if (this.container.contains(this.renderer.domElement)) {
            this.container.removeChild(this.renderer.domElement);
        }
    }
}

// Expose globally
window.ThreeScene = ThreeScene;
