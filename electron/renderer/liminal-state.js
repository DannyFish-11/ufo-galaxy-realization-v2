/**
 * liminal-state.js
 * Liminal State: Perspective tunnel with FOV distortion
 * - Custom Vertex Shader for FOV perspective warp
 * - Vanishing point at screen center
 * - Simplex noise liquid ink flow along perspective lines
 */

class LiminalState {
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.scene = threeScene.getScene();
        this.isActive = false;

        // Tunnel components
        this.tunnelGroup = null;
        this.tunnelMesh = null;
        this.tunnelMaterial = null;
        this.particleSystem = null;
        this.flowLines = [];

        // Animation parameters
        this.tunnelRotation = 0;
        this.flowSpeed = 0.6;
        this.tunnelDepth = 30;

        // Load shaders and build
        this.build();
    }

    async loadShader(url) {
        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`Failed to load ${url}`);
            return await response.text();
        } catch (err) {
            console.warn(`Failed to load shader from ${url}, using fallback`, err);
            return null;
        }
    }

    async build() {
        // Try to load external shaders, use fallbacks if unavailable
        let vertexShader = await this.loadShader('./shaders/liminal.vert');
        let fragmentShader = await this.loadShader('./shaders/liminal.frag');

        // Fallback vertex shader (FOV distortion)
        if (!vertexShader) {
            vertexShader = this.getFallbackVertexShader();
        }

        // Fallback fragment shader (liquid ink flow)
        if (!fragmentShader) {
            fragmentShader = this.getFallbackFragmentShader();
        }

        // Create tunnel group
        this.tunnelGroup = new THREE.Group();

        // Main tunnel mesh - high segment count for smooth distortion
        const tunnelGeometry = new THREE.PlaneGeometry(
            20,      // width
            15,      // height
            80,      // width segments (high for smooth FOV warp)
            60       // height segments
        );

        // Create tunnel material with custom shaders
        this.tunnelMaterial = new THREE.ShaderMaterial({
            uniforms: {
                uTime: { value: 0.0 },
                uTunnelDepth: { value: this.tunnelDepth },
                uDistortionStrength: { value: 3.5 },
                uTunnelSpeed: { value: this.flowSpeed },
                uInkIntensity: { value: 1.2 },
                uInkColor1: { value: new THREE.Color(0x1a2332) },
                uInkColor2: { value: new THREE.Color(0x2d3a4a) },
                uInkColor3: { value: new THREE.Color(0x0d1520) },
                uResolution: { value: new THREE.Vector2(
                    window.innerWidth,
                    window.innerHeight
                )}
            },
            vertexShader: vertexShader,
            fragmentShader: fragmentShader,
            transparent: true,
            side: THREE.DoubleSide,
            depthWrite: true,
            depthTest: true,
            blending: THREE.AdditiveBlending
        });

        this.tunnelMesh = new THREE.Mesh(tunnelGeometry, this.tunnelMaterial);
        this.tunnelGroup.add(this.tunnelMesh);

        // Create additional tunnel depth layers
        this.createDepthLayers();

        // Create flowing particles
        this.createFlowParticles();

        // Create perspective flow lines
        this.createFlowLines();

        // Add ambient lighting for the tunnel
        this.tunnelLight = new THREE.PointLight(0x4a6080, 0.5, 25);
        this.tunnelLight.position.set(0, 0, 2);
        this.tunnelGroup.add(this.tunnelLight);

        this.scene.add(this.tunnelGroup);
        this.setVisible(false);
    }

    getFallbackVertexShader() {
        return `
            uniform float uTime;
            uniform float uTunnelDepth;
            uniform float uDistortionStrength;
            uniform vec2 uResolution;

            varying vec2 vUv;
            varying float vDepth;
            varying vec3 vWorldPosition;
            varying float vDistortion;

            float easeInQuad(float t) {
                return t * t;
            }

            float easeInOutCubic(float t) {
                return t < 0.5
                    ? 4.0 * t * t * t
                    : 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0;
            }

            void main() {
                vUv = uv;
                vec3 pos = position;
                vec2 centerOffset = pos.xy;
                float distFromCenter = length(centerOffset);
                vec2 screenPos = pos.xy;
                float zNorm = (pos.z + uTunnelDepth * 0.5) / uTunnelDepth;
                zNorm = clamp(zNorm, 0.0, 1.0);
                float depthEasing = easeInQuad(zNorm);
                vDepth = depthEasing;
                float pullStrength = depthEasing * uDistortionStrength;
                vec2 pullDir = normalize(-screenPos + 0.001);
                float radialFalloff = smoothstep(0.0, 1.0, distFromCenter);
                pos.xy += pullDir * pullStrength * radialFalloff * 2.0;
                pos.z = -easeInOutCubic(zNorm) * uTunnelDepth;
                float wave = sin(distFromCenter * 8.0 - uTime * 2.0) * 0.02 * depthEasing;
                pos.xy += normalize(screenPos + 0.001) * wave;
                vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
                vec4 projected = projectionMatrix * mvPosition;
                vWorldPosition = pos;
                vDistortion = pullStrength;
                gl_Position = projected;
            }
        `;
    }

    getFallbackFragmentShader() {
        return `
            uniform float uTime;
            uniform float uTunnelSpeed;
            uniform float uInkIntensity;
            uniform vec3 uInkColor1;
            uniform vec3 uInkColor2;
            uniform vec3 uInkColor3;
            uniform vec2 uResolution;

            varying vec2 vUv;
            varying float vDepth;
            varying vec3 vWorldPosition;
            varying float vDistortion;

            vec4 permute(vec4 x) {
                return mod(((x * 34.0) + 1.0) * x, 289.0);
            }
            vec4 taylorInvSqrt(vec4 r) {
                return 1.79284291400159 - 0.85373472095314 * r;
            }

            float snoise(vec3 v) {
                const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
                const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
                vec3 i = floor(v + dot(v, C.yyy));
                vec3 x0 = v - i + dot(i, C.xxx);
                vec3 g = step(x0.yzx, x0.xyz);
                vec3 l = 1.0 - g;
                vec3 i1 = min(g.xyz, l.zxy);
                vec3 i2 = max(g.xyz, l.zxy);
                vec3 x1 = x0 - i1 + C.xxx;
                vec3 x2 = x0 - i2 + C.yyy;
                vec3 x3 = x0 - D.yyy;
                i = mod(i, 289.0);
                vec4 p = permute(permute(permute(
                    i.z + vec4(0.0, i1.z, i2.z, 1.0))
                    + i.y + vec4(0.0, i1.y, i2.y, 1.0))
                    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
                float n_ = 1.0 / 7.0;
                vec3 ns = n_ * D.wyz - D.xzx;
                vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
                vec4 x_ = floor(j * ns.z);
                vec4 y_ = floor(j - 7.0 * x_);
                vec4 x = x_ * ns.x + ns.yyyy;
                vec4 y = y_ * ns.x + ns.yyyy;
                vec4 h = 1.0 - abs(x) - abs(y);
                vec4 b0 = vec4(x.xy, y.xy);
                vec4 b1 = vec4(x.zw, y.zw);
                vec4 s0 = floor(b0) * 2.0 + 1.0;
                vec4 s1 = floor(b1) * 2.0 + 1.0;
                vec4 sh = -step(h, vec4(0.0));
                vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
                vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
                vec3 p0 = vec3(a0.xy, h.x);
                vec3 p1 = vec3(a0.zw, h.y);
                vec3 p2 = vec3(a1.xy, h.z);
                vec3 p3 = vec3(a1.zw, h.w);
                vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
                p0 *= norm.x;
                p1 *= norm.y;
                p2 *= norm.z;
                p3 *= norm.w;
                vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
                m = m * m;
                return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
            }

            float fbm(vec3 p, int octaves) {
                float value = 0.0;
                float amplitude = 0.5;
                float frequency = 1.0;
                for (int i = 0; i < 6; i++) {
                    if (i >= octaves) break;
                    value += amplitude * snoise(p * frequency);
                    amplitude *= 0.5;
                    frequency *= 2.0;
                }
                return value;
            }

            mat2 rotate(float angle) {
                float c = cos(angle);
                float s = sin(angle);
                return mat2(c, -s, s, c);
            }

            void main() {
                vec2 uv = vUv;
                float t = uTime;
                vec2 centerDir = normalize(uv - 0.5 + 0.001);
                float distFromCenter = length(uv - 0.5);
                float flowSpeed = t * uTunnelSpeed;
                vec3 flowPos = vec3(uv.x * 2.0, uv.y * 2.0, flowSpeed + vDepth * 5.0);
                vec2 swirlUv = (uv - 0.5) * rotate(t * 0.1 + vDepth * 2.0) + 0.5;
                vec3 swirlPos = vec3(swirlUv * 3.0, flowSpeed * 0.7);
                float ink1 = fbm(flowPos + swirlPos * 0.5, 4);
                float ink2 = fbm(flowPos * 1.5 + vec3(t * 0.2, t * 0.15, 0.0), 3);
                float ink3 = fbm(vec3(
                    centerDir.x * distFromCenter * 4.0 + t * 0.3,
                    centerDir.y * distFromCenter * 4.0,
                    vDepth * 3.0 + t * 0.5
                ), 3);
                float veins = smoothstep(0.3, 0.6, abs(ink1));
                veins *= smoothstep(0.2, 0.5, abs(ink2));
                float flowLines = sin(distFromCenter * 20.0 - t * 3.0 - vDepth * 10.0) * 0.5 + 0.5;
                flowLines = smoothstep(0.4, 0.6, flowLines) * (1.0 - vDepth * 0.5);
                float inkPattern = veins * 0.5 + abs(ink3) * 0.3 + flowLines * 0.2;
                inkPattern = smoothstep(0.2, 0.8, inkPattern);
                vec3 color = mix(uInkColor1, uInkColor2, ink1 * 0.5 + 0.5);
                color = mix(color, uInkColor3, ink2 * 0.5 + 0.5);
                float depthFade = 1.0 - vDepth * 0.7;
                color *= depthFade;
                color *= 1.0 + inkPattern * uInkIntensity;
                float edgeDist = length(uv - 0.5) * 1.5;
                float vignette = 1.0 - smoothstep(0.3, 0.8, edgeDist);
                color *= vignette * 0.3 + 0.7;
                float glow = flowLines * 0.15 * (1.0 - vDepth);
                color += uInkColor2 * glow;
                float alpha = 0.85 + inkPattern * 0.15;
                alpha *= (1.0 - vDepth * 0.3);
                gl_FragColor = vec4(color, alpha);
            }
        `;
    }

    createDepthLayers() {
        // Create multiple layered planes for depth
        this.depthLayers = [];
        const layerCount = 5;

        for (let i = 0; i < layerCount; i++) {
            const progress = (i + 1) / (layerCount + 1);
            const scale = 1.0 - progress * 0.6;
            const layerGeometry = new THREE.PlaneGeometry(20 * scale, 15 * scale, 40, 30);

            const layerMaterial = new THREE.ShaderMaterial({
                uniforms: {
                    uTime: this.tunnelMaterial.uniforms.uTime,
                    uTunnelDepth: this.tunnelMaterial.uniforms.uTunnelDepth,
                    uDistortionStrength: { value: 3.5 * (1.0 - progress * 0.5) },
                    uTunnelSpeed: this.tunnelMaterial.uniforms.uTunnelSpeed,
                    uInkIntensity: { value: 0.6 * (1.0 - progress * 0.3) },
                    uInkColor1: this.tunnelMaterial.uniforms.uInkColor1,
                    uInkColor2: this.tunnelMaterial.uniforms.uInkColor2,
                    uInkColor3: this.tunnelMaterial.uniforms.uInkColor3,
                    uResolution: this.tunnelMaterial.uniforms.uResolution
                },
                vertexShader: this.tunnelMaterial.vertexShader,
                fragmentShader: this.tunnelMaterial.fragmentShader,
                transparent: true,
                side: THREE.DoubleSide,
                depthWrite: false,
                depthTest: true,
                blending: THREE.AdditiveBlending
            });

            const layerMesh = new THREE.Mesh(layerGeometry, layerMaterial);
            layerMesh.position.z = -progress * this.tunnelDepth * 0.3;
            layerMesh.material.opacity = 0.3 * (1.0 - progress);

            this.tunnelGroup.add(layerMesh);
            this.depthLayers.push(layerMesh);
        }
    }

    createFlowParticles() {
        const particleCount = 200;
        const positions = new Float32Array(particleCount * 3);
        const velocities = [];

        for (let i = 0; i < particleCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const radius = 0.5 + Math.random() * 8;
            positions[i * 3] = Math.cos(angle) * radius;
            positions[i * 3 + 1] = Math.sin(angle) * radius;
            positions[i * 3 + 2] = -Math.random() * this.tunnelDepth * 0.5;

            velocities.push({
                speed: 0.5 + Math.random() * 2.0,
                angle: angle,
                radius: radius,
                wobble: Math.random() * Math.PI * 2
            });
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

        const material = new THREE.PointsMaterial({
            color: 0x8a9ba8,
            size: 0.04,
            transparent: true,
            opacity: 0.5,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            sizeAttenuation: true
        });

        this.particleSystem = new THREE.Points(geometry, material);
        this.particleVelocities = velocities;
        this.tunnelGroup.add(this.particleSystem);
    }

    createFlowLines() {
        // Create perspective lines converging to center
        const lineCount = 12;
        this.flowLines = [];

        for (let i = 0; i < lineCount; i++) {
            const angle = (i / lineCount) * Math.PI * 2;
            const points = [];
            const segments = 30;

            for (let j = 0; j < segments; j++) {
                const t = j / (segments - 1);
                const radius = t * 10;
                const x = Math.cos(angle) * radius;
                const y = Math.sin(angle) * radius;
                const z = -t * this.tunnelDepth * 0.4;
                points.push(new THREE.Vector3(x, y, z));
            }

            const geometry = new THREE.BufferGeometry().setFromPoints(points);
            const material = new THREE.LineBasicMaterial({
                color: 0x4a6080,
                transparent: true,
                opacity: 0.08,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });

            const line = new THREE.Line(geometry, material);
            this.tunnelGroup.add(line);
            this.flowLines.push({
                mesh: line,
                angle: angle,
                material: material
            });
        }
    }

    setVisible(visible) {
        if (this.tunnelGroup) {
            this.tunnelGroup.visible = visible;
        }

        const overlay = document.getElementById('liminal-overlay');
        if (overlay) {
            if (visible) {
                overlay.classList.remove('hidden');
                overlay.classList.add('fade-in');
            } else {
                overlay.classList.add('hidden');
                overlay.classList.remove('fade-in');
            }
        }
    }

    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        // Reset tunnel rotation
        this.tunnelRotation = 0;
        if (this.tunnelGroup) {
            this.tunnelGroup.rotation.z = 0;
        }

        // Entrance animation
        this.isEntering = true;
        this.entranceStartTime = this.threeScene.getElapsedTime();

        // Disable CRT post-processing in liminal state
        this.threeScene.enablePostProcessing(false);
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        this.isExiting = true;
        this.exitStartTime = this.threeScene.getElapsedTime();

        setTimeout(() => {
            this.setVisible(false);
            this.isExiting = false;
        }, 600);
    }

    update(deltaTime) {
        if (!this.isActive && !this.isEntering && !this.isExiting) return;
        if (!this.tunnelMaterial) return;

        const time = this.threeScene.getElapsedTime();

        // Update shader uniforms
        this.tunnelMaterial.uniforms.uTime.value = time;

        // Entrance animation - fade in
        if (this.isEntering) {
            const elapsed = time - this.entranceStartTime;
            const progress = Math.min(elapsed / 1.0, 1.0);
            const eased = 1 - Math.pow(1 - progress, 2);

            if (this.tunnelMaterial) {
                this.tunnelMaterial.opacity = eased;
            }
            if (this.particleSystem) {
                this.particleSystem.material.opacity = eased * 0.5;
            }
            this.flowLines.forEach(line => {
                line.material.opacity = eased * 0.08;
            });

            if (progress >= 1.0) {
                this.isEntering = false;
            }
        }

        // Exit animation
        if (this.isExiting) {
            const elapsed = time - this.exitStartTime;
            const progress = Math.min(elapsed / 0.6, 1.0);
            const fadeOut = 1.0 - progress;

            if (this.tunnelMaterial) {
                this.tunnelMaterial.opacity = fadeOut;
            }
            if (this.particleSystem) {
                this.particleSystem.material.opacity = fadeOut * 0.5;
            }
        }

        if (!this.isActive) return;

        // Rotate tunnel slowly
        this.tunnelRotation += deltaTime * 0.05;
        if (this.tunnelGroup) {
            this.tunnelGroup.rotation.z = this.tunnelRotation * 0.3;
        }

        // Update flow particles
        if (this.particleSystem) {
            this.updateParticles(deltaTime, time);
        }

        // Pulse flow lines
        this.flowLines.forEach((line, i) => {
            const pulse = Math.sin(time * 2 + i * 0.5) * 0.5 + 0.5;
            line.material.opacity = 0.05 + pulse * 0.06;
        });

        // Pulsing tunnel light
        if (this.tunnelLight) {
            this.tunnelLight.intensity = 0.5 + Math.sin(time * 1.5) * 0.2;
        }
    }

    updateParticles(deltaTime, time) {
        const positions = this.particleSystem.geometry.attributes.position.array;
        const particleCount = this.particleVelocities.length;

        for (let i = 0; i < particleCount; i++) {
            const vel = this.particleVelocities[i];

            // Move particles along tunnel (toward camera / deeper in)
            positions[i * 3 + 2] += vel.speed * deltaTime * 2.0;

            // Spiral motion
            vel.angle += deltaTime * 0.3;
            const wobbleAmount = Math.sin(time + vel.wobble) * 0.3;
            positions[i * 3] = Math.cos(vel.angle) * (vel.radius + wobbleAmount);
            positions[i * 3 + 1] = Math.sin(vel.angle) * (vel.radius + wobbleAmount);

            // Reset particle if it passes the camera
            if (positions[i * 3 + 2] > 2) {
                positions[i * 3 + 2] = -this.tunnelDepth * 0.5;
                vel.radius = 0.5 + Math.random() * 8;
            }
        }

        this.particleSystem.geometry.attributes.position.needsUpdate = true;
    }

    dispose() {
        if (this.tunnelMesh) {
            this.tunnelMesh.geometry.dispose();
        }
        if (this.tunnelMaterial) {
            this.tunnelMaterial.dispose();
        }
        if (this.depthLayers) {
            this.depthLayers.forEach(layer => {
                layer.geometry.dispose();
                layer.material.dispose();
            });
        }
        if (this.particleSystem) {
            this.particleSystem.geometry.dispose();
            this.particleSystem.material.dispose();
        }
        if (this.flowLines) {
            this.flowLines.forEach(line => {
                line.mesh.geometry.dispose();
                line.material.dispose();
            });
        }
        if (this.tunnelGroup) {
            this.scene.remove(this.tunnelGroup);
        }
    }
}

window.LiminalState = LiminalState;
