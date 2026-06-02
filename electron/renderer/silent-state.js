/**
 * silent-state.js
 * Silent State: Static ambient edge glow + HUD corner brackets
 * Like monitor RGB backlighting (extremely faint) + HUD-style corner markers
 * Core concept: entity is resting, minimal presence, like deep-sea bioluminescence
 */

class SilentState {
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.scene = threeScene.getScene();
        this.camera = threeScene.getCamera();
        this.renderer = threeScene.getRenderer();
        this.isActive = false;

        // Edge glow mesh (fullscreen plane with edge shader)
        this.edgeGlowMesh = null;
        this.edgeMaterial = null;

        // Corner HUD brackets (LineSegments)
        this.cornerGroup = null;
        this.cornerLines = []; // { mesh, material, cornerIndex }

        // Animation state
        this.opacity = 0;          // Current overall opacity (0-1)
        this.targetOpacity = 1;    // Target opacity
        this.fadeSpeed = 1;        // Opacity change per second
        this.entering = false;
        this.exiting = false;

        // Corner bracket config
        this.cornerSize = 40;      // px
        this.cornerOffset = 30;    // px from screen edge

        // Galaxy palette
        this.colorCyan = new THREE.Color(0x00e1ff);
        this.colorPink = new THREE.Color(0xec4899);

        this.build();
    }

    // ============================================
    // Build
    // ============================================
    build() {
        this.group = new THREE.Group();

        this._buildEdgeGlow();
        this._buildCornerBrackets();

        this.scene.add(this.group);
        this.setVisible(false);
    }

    /**
     * Build fullscreen edge glow using ShaderMaterial on PlaneGeometry
     * Edge glow only: brightest at screen edges, decays rapidly inward
     */
    _buildEdgeGlow() {
        const { width, height } = this._getVisibleSizeAtZ0();

        // Slightly larger than visible area to ensure full coverage
        const geometry = new THREE.PlaneGeometry(width * 1.05, height * 1.05);

        this.edgeMaterial = new THREE.ShaderMaterial({
            uniforms: {
                uTime: { value: 0.0 },
                uOpacity: { value: 0.0 },
                uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) }
            },
            vertexShader: `
                varying vec2 vUv;
                void main() {
                    vUv = uv;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                }
            `,
            fragmentShader: `
                uniform float uTime;
                uniform float uOpacity;
                uniform vec2 uResolution;
                varying vec2 vUv;

                void main() {
                    vec2 uv = vUv;

                    // Distance to each edge (0 at edge, 0.5 at center)
                    float distToLeft = uv.x;
                    float distToRight = 1.0 - uv.x;
                    float distToTop = 1.0 - uv.y;
                    float distToBottom = uv.y;

                    // Distance to nearest edge
                    float edgeDist = min(min(distToLeft, distToRight), min(distToTop, distToBottom));

                    // Edge glow: only within ~8% of edge, smooth falloff
                    float edgeGlow = 1.0 - smoothstep(0.0, 0.08, edgeDist);

                    // Horizontal gradient: left=cyan, right=pink
                    vec3 leftColor = vec3(0.0, 0.882, 1.0);   // #00e1ff
                    vec3 rightColor = vec3(0.925, 0.286, 0.6); // #ec4899
                    vec3 color = mix(leftColor, rightColor, uv.x);

                    // Breathing animation: slow 6-second cycle
                    float breath = sin(uTime * 1.047) * 0.3 + 0.7; // 2*PI/6 ≈ 1.047

                    // Final alpha: very faint (0.03-0.08 base)
                    float alpha = edgeGlow * 0.055 * breath * uOpacity;

                    gl_FragColor = vec4(color, alpha);
                }
            `,
            transparent: true,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            side: THREE.DoubleSide
        });

        this.edgeGlowMesh = new THREE.Mesh(geometry, this.edgeMaterial);
        this.edgeGlowMesh.position.z = 0;
        this.group.add(this.edgeGlowMesh);
    }

    /**
     * Build 4 corner HUD brackets using LineSegments
     * Each bracket: ┌ ┐ └ ┘ style, 40x40px, breathing opacity
     */
    _buildCornerBrackets() {
        this.cornerGroup = new THREE.Group();

        // 4 corners: TL, TR, BL, BR
        const cornerConfigs = [
            { id: 'TL', sx: 1, sy: -1 },   // top-left:  ┘  (horizontal right, vertical down)
            { id: 'TR', sx: -1, sy: -1 },  // top-right: └  (horizontal left, vertical down)
            { id: 'BL', sx: 1, sy: 1 },    // bottom-left: ┐ (horizontal right, vertical up)
            { id: 'BR', sx: -1, sy: 1 },   // bottom-right: ┌ (horizontal left, vertical up)
        ];

        cornerConfigs.forEach((cfg, index) => {
            const bracket = this._createBracketGeometry(cfg.sx, cfg.sy);
            const material = new THREE.LineBasicMaterial({
                color: this.colorCyan,
                transparent: true,
                opacity: 0,
                blending: THREE.AdditiveBlending,
                depthWrite: false
            });

            const lineSegments = new THREE.LineSegments(bracket, material);
            this.cornerGroup.add(lineSegments);

            this.cornerLines.push({
                mesh: lineSegments,
                material: material,
                index: index,
                phaseOffset: index * 1.5 // Stagger breathing
            });
        });

        this.group.add(this.cornerGroup);
    }

    /**
     * Create a single bracket geometry (two lines forming an L corner)
     * sx, sy: direction multipliers (-1 or 1)
     */
    _createBracketGeometry(sx, sy) {
        const s = this._pxToWorld(this.cornerSize); // bracket arm length in world units
        const geometry = new THREE.BufferGeometry();
        // Two lines: horizontal + vertical
        const vertices = new Float32Array([
            0, 0, 0,   sx * s, 0, 0,      // horizontal arm
            0, 0, 0,   0, sy * s, 0       // vertical arm
        ]);
        geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
        return geometry;
    }

    /**
     * Position corner brackets at screen corners
     */
    _positionCornerBrackets() {
        const offset = this._pxToWorld(this.cornerOffset);
        const { width, height } = this._getVisibleSizeAtZ0();
        const halfW = width / 2;
        const halfH = height / 2;

        const positions = [
            { x: -halfW + offset, y: halfH - offset },   // TL
            { x: halfW - offset,  y: halfH - offset },   // TR
            { x: -halfW + offset, y: -halfH + offset },  // BL
            { x: halfW - offset,  y: -halfH + offset }   // BR
        ];

        this.cornerLines.forEach((corner, i) => {
            corner.mesh.position.set(positions[i].x, positions[i].y, 0);
        });
    }

    // ============================================
    // Helpers: Screen-space to world-space
    // ============================================

    /**
     * Get the visible world-space dimensions at z=0 plane
     */
    _getVisibleSizeAtZ0() {
        const vFOV = THREE.MathUtils.degToRad(this.camera.fov);
        const dist = this.camera.position.z; // z=5
        const visibleHeight = 2 * Math.tan(vFOV / 2) * dist;
        const visibleWidth = visibleHeight * this.camera.aspect;
        return { width: visibleWidth, height: visibleHeight };
    }

    /**
     * Convert pixel size to world units at z=0
     */
    _pxToWorld(px) {
        const { height } = this._getVisibleSizeAtZ0();
        return (px / window.innerHeight) * height;
    }

    // ============================================
    // Visibility
    // ============================================

    setVisible(visible) {
        this.group.visible = visible;

        const overlay = document.getElementById('silent-overlay');
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

    // ============================================
    // State Transitions
    // ============================================

    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        // Start fade-in
        this.opacity = 0;
        this.targetOpacity = 1;
        this.fadeSpeed = 1 / 1.5; // 1.5 seconds to full
        this.entering = true;
        this.exiting = false;

        // Ensure edge glow plane covers current screen
        this._refreshEdgeGlowSize();
        this._positionCornerBrackets();

        // Disable post-processing in silent state
        this.threeScene.enablePostProcessing(false);
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // Start fade-out
        this.targetOpacity = 0;
        this.fadeSpeed = 1 / 0.5; // 0.5 seconds to fade out
        this.entering = false;
        this.exiting = true;
    }

    // ============================================
    // Update (called every frame)
    // ============================================

    update(deltaTime) {
        const needsUpdate = this.isActive || this.entering || this.exiting;
        if (!needsUpdate) return;

        const time = this.threeScene.getElapsedTime();

        // Update opacity (fade in/out)
        if (this.opacity < this.targetOpacity) {
            this.opacity = Math.min(this.opacity + this.fadeSpeed * deltaTime, this.targetOpacity);
        } else if (this.opacity > this.targetOpacity) {
            this.opacity = Math.max(this.opacity - this.fadeSpeed * deltaTime, this.targetOpacity);
        }

        // Check if entrance complete
        if (this.entering && this.opacity >= 1.0) {
            this.entering = false;
        }

        // Check if exit complete
        if (this.exiting && this.opacity <= 0) {
            this.exiting = false;
            this.setVisible(false);
        }

        // Skip visual updates if fully faded out
        if (this.opacity <= 0.001) return;

        // Update edge glow shader
        if (this.edgeMaterial) {
            this.edgeMaterial.uniforms.uTime.value = time;
            this.edgeMaterial.uniforms.uOpacity.value = this.opacity;
        }

        // Update corner brackets: breathing opacity 0.05-0.15, 6-second cycle
        this.cornerLines.forEach(corner => {
            const breath = Math.sin(time * 1.047 + corner.phaseOffset) * 0.5 + 0.5; // 0 to 1
            const baseOpacity = 0.05 + breath * 0.10; // 0.05 - 0.15
            corner.material.opacity = baseOpacity * this.opacity;
        });
    }

    /**
     * Refresh edge glow plane size on window resize
     */
    onResize() {
        if (!this.isActive && !this.entering && !this.exiting) return;
        this._refreshEdgeGlowSize();
        this._positionCornerBrackets();

        // Update resolution uniform
        if (this.edgeMaterial) {
            this.edgeMaterial.uniforms.uResolution.value.set(window.innerWidth, window.innerHeight);
        }
    }

    _refreshEdgeGlowSize() {
        if (!this.edgeGlowMesh) return;
        const { width, height } = this._getVisibleSizeAtZ0();
        this.edgeGlowMesh.scale.set(width * 1.05 / this.edgeGlowMesh.geometry.parameters.width,
                                     height * 1.05 / this.edgeGlowMesh.geometry.parameters.height,
                                     1);
    }

    // ============================================
    // Cleanup
    // ============================================

    dispose() {
        if (this.edgeGlowMesh) {
            this.edgeGlowMesh.geometry.dispose();
            this.edgeMaterial.dispose();
        }

        this.cornerLines.forEach(corner => {
            corner.mesh.geometry.dispose();
            corner.material.dispose();
        });

        if (this.group) {
            this.scene.remove(this.group);
        }
    }
}

window.SilentState = SilentState;
