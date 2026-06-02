/**
 * liminal-state.js
 * Liminal State: Perspective box tunnel — single vanishing point
 * Inspired by UVA "Vanishing Point" laser installation
 * Like The Last Supper's perspective composition
 */

class LiminalState {
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.scene = threeScene.getScene();
        this.camera = threeScene.getCamera();
        this.isActive = false;

        // Perspective room group
        this.roomGroup = null;

        // 12 edge lines of the perspective box
        this.edgeLines = null;       // LineSegments for the 12 edges
        this.edgeMaterial = null;

        // Floor grid lines (perspective)
        this.floorGrid = null;
        this.ceilingGrid = null;

        // Particle system (flowing toward vanishing point)
        this.particleSystem = null;
        this.particlePositions = null;     // Float32Array
        this.particleVelocities = [];      // Array of {speed, angle, depthOffset}
        this.particleMaterial = null;

        // Vanishing point light (deep center glow)
        this.vanishingLight = null;

        // Animation state
        this.opacity = 0;
        this.targetOpacity = 1;
        this.fadeSpeed = 1;
        this.entering = false;
        this.exiting = false;

        // Entrance/exit animation
        this.roomScale = 1;
        this.targetRoomScale = 1;
        this.depthProgress = 1;       // 0=flat, 1=full depth
        this.targetDepthProgress = 1;

        // Rotation
        this.rotationY = 0;

        // Perspective parameters
        this.depth = 20;              // Depth of the room
        this.particleCount = 150;

        // Galaxy palette
        this.colorCyan = new THREE.Color(0x00e1ff);
        this.colorPink = new THREE.Color(0xec4899);
        this.colorBlue = new THREE.Color(0x3b82f6);

        this.build();
    }

    // ============================================
    // Build
    // ============================================
    build() {
        this.roomGroup = new THREE.Group();

        this._buildPerspectiveBox();
        this._buildFloorCeilingGrids();
        this._buildFlowParticles();
        this._buildVanishingLight();

        this.scene.add(this.roomGroup);
        this.setVisible(false);
    }

    /**
     * Build the perspective box: 8 vertices, 12 edges
     * Near plane (screen) is large, far plane (deep) converges to a point
     */
    _buildPerspectiveBox() {
        const d = this.depth;

        // Near plane (at z=0, larger than screen)
        // Will be scaled to match screen in refreshPerspectiveGeometry
        const nearW = 12;
        const nearH = 8;

        // Far plane (deep, nearly a point)
        const farW = 0.05;
        const farH = 0.05;

        // 8 vertices: 4 near + 4 far
        // Order: near BL, near BR, near TR, near TL, far BL, far BR, far TR, far TL
        this.boxVertices = new Float32Array([
            // Near plane (z=0)
            -nearW/2, -nearH/2, 0,   // 0: near bottom-left
             nearW/2, -nearH/2, 0,   // 1: near bottom-right
             nearW/2,  nearH/2, 0,   // 2: near top-right
            -nearW/2,  nearH/2, 0,   // 3: near top-left
            // Far plane (z=-d)
            -farW/2, -farH/2, -d,    // 4: far bottom-left
             farW/2, -farH/2, -d,    // 5: far bottom-right
             farW/2,  farH/2, -d,    // 6: far top-right
            -farW/2,  farH/2, -d,    // 7: far top-left
        ]);

        // 12 edges: 4 near + 4 far + 4 connecting
        const indices = [
            // Near plane edges
            0, 1,  1, 2,  2, 3,  3, 0,
            // Far plane edges
            4, 5,  5, 6,  6, 7,  7, 4,
            // Connecting edges (perspective lines)
            0, 4,  1, 5,  2, 6,  3, 7
        ];

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(this.boxVertices.slice(), 3));
        geometry.setIndex(indices);

        this.edgeMaterial = new THREE.LineBasicMaterial({
            color: this.colorCyan,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });

        this.edgeLines = new THREE.LineSegments(geometry, this.edgeMaterial);
        this.roomGroup.add(this.edgeLines);
    }

    /**
     * Build perspective floor and ceiling grid lines
     * Additional lines for depth perception
     */
    _buildFloorCeilingGrids() {
        const d = this.depth;
        const nearW = 12;
        const nearH = 8;
        const farW = 0.05;
        const farH = 0.05;

        // Floor: 5 lines going from near to far (depth lines)
        const floorPositions = [];
        const ceilPositions = [];
        const numDivisions = 5;

        for (let i = 0; i <= numDivisions; i++) {
            const t = i / numDivisions; // 0 to 1
            const nearX = -nearW/2 + t * nearW;
            const farX = -farW/2 + t * farW;

            // Floor line (y = -nearH/2 at near, y = -farH/2 at far)
            floorPositions.push(
                nearX, -nearH/2, 0,
                farX, -farH/2, -d
            );

            // Ceiling line
            ceilPositions.push(
                nearX, nearH/2, 0,
                farX, farH/2, -d
            );
        }

        // Horizontal cross lines at various depths
        const numDepthSteps = 6;
        for (let i = 0; i < numDepthSteps; i++) {
            const t = (i + 1) / (numDepthSteps + 1); // 0 to 1
            const easeT = t * t; // ease-in for perspective spacing
            const z = -d * easeT;
            const w = nearW + (farW - nearW) * easeT;
            const h = nearH + (farH - nearH) * easeT;

            floorPositions.push(-w/2, -nearH/2 + (farH/2 - nearH/2) * easeT, z,
                                 w/2, -nearH/2 + (farH/2 - nearH/2) * easeT, z);
            ceilPositions.push(-w/2, nearH/2 + (-farH/2 - nearH/2) * easeT, z,
                                w/2, nearH/2 + (-farH/2 - nearH/2) * easeT, z);
        }

        // Floor grid
        const floorGeo = new THREE.BufferGeometry();
        floorGeo.setAttribute('position', new THREE.Float32BufferAttribute(floorPositions, 3));
        this.floorMaterial = new THREE.LineBasicMaterial({
            color: this.colorBlue,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        this.floorGrid = new THREE.LineSegments(floorGeo, this.floorMaterial);
        this.roomGroup.add(this.floorGrid);

        // Ceiling grid
        const ceilGeo = new THREE.BufferGeometry();
        ceilGeo.setAttribute('position', new THREE.Float32BufferAttribute(ceilPositions, 3));
        this.ceilingMaterial = new THREE.LineBasicMaterial({
            color: this.colorBlue,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        this.ceilingGrid = new THREE.LineSegments(ceilGeo, this.ceilingMaterial);
        this.roomGroup.add(this.ceilingGrid);
    }

    /**
     * Build flowing particles: 150 particles drifting along perspective lines
     * From screen edges toward the vanishing point
     */
    _buildFlowParticles() {
        const positions = new Float32Array(this.particleCount * 3);
        const colors = new Float32Array(this.particleCount * 3);
        const velocities = [];

        const colorCyan = this.colorCyan;
        const colorPink = this.colorPink;
        const tempColor = new THREE.Color();

        for (let i = 0; i < this.particleCount; i++) {
            // Random starting position: around the near plane perimeter
            const side = Math.floor(Math.random() * 4); // 0=top,1=right,2=bottom,3=left
            const t = Math.random();
            let x, y, z;

            const margin = 0.3;
            switch (side) {
                case 0: // top
                    x = (t - 0.5) * 14;
                    y = 5 + margin;
                    break;
                case 1: // right
                    x = 7 + margin;
                    y = (t - 0.5) * 10;
                    break;
                case 2: // bottom
                    x = (t - 0.5) * 14;
                    y = -5 - margin;
                    break;
                case 3: // left
                    x = -7 - margin;
                    y = (t - 0.5) * 10;
                    break;
            }
            z = -Math.random() * this.depth * 0.8;

            positions[i * 3] = x;
            positions[i * 3 + 1] = y;
            positions[i * 3 + 2] = z;

            // Velocity: drift toward vanishing point (0,0,-d)
            const speed = 1.5 + Math.random() * 3.0;
            velocities.push({
                speed: speed,
                driftX: (Math.random() - 0.5) * 0.3,
                driftY: (Math.random() - 0.5) * 0.3,
                wobblePhase: Math.random() * Math.PI * 2
            });

            // Color gradient based on depth: cyan near, pink far
            const depthRatio = Math.abs(z) / this.depth;
            tempColor.copy(colorCyan).lerp(colorPink, depthRatio);
            colors[i * 3] = tempColor.r;
            colors[i * 3 + 1] = tempColor.g;
            colors[i * 3 + 2] = tempColor.b;
        }

        this.particlePositions = positions;
        this.particleVelocities = velocities;

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        this.particleMaterial = new THREE.PointsMaterial({
            size: 0.06,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            vertexColors: true,
            sizeAttenuation: true
        });

        this.particleSystem = new THREE.Points(geometry, this.particleMaterial);
        this.roomGroup.add(this.particleSystem);
    }

    /**
     * Vanishing point light: a faint glow at the deep center
     */
    _buildVanishingLight() {
        this.vanishingLight = new THREE.PointLight(this.colorPink, 0, 15);
        this.vanishingLight.position.set(0, 0, -this.depth);
        this.roomGroup.add(this.vanishingLight);

        // Small glow sphere at vanishing point
        const glowGeo = new THREE.SphereGeometry(0.15, 16, 16);
        const glowMat = new THREE.MeshBasicMaterial({
            color: this.colorPink,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        this.vanishingGlow = new THREE.Mesh(glowGeo, glowMat);
        this.vanishingGlow.position.set(0, 0, -this.depth);
        this.roomGroup.add(this.vanishingGlow);
    }

    // ============================================
    // Visibility
    // ============================================

    setVisible(visible) {
        this.roomGroup.visible = visible;

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

    // ============================================
    // State Transitions
    // ============================================

    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        // Entrance: room "opens" from flat to full depth
        this.opacity = 0;
        this.targetOpacity = 1;
        this.fadeSpeed = 1 / 2.0; // 2 seconds
        this.entering = true;
        this.exiting = false;

        this.depthProgress = 0;
        this.targetDepthProgress = 1;

        // Reset rotation
        this.rotationY = 0;
        this.roomGroup.rotation.y = 0;

        // Reset particle positions
        this._resetParticles();

        // Disable post-processing
        this.threeScene.enablePostProcessing(false);
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // Exit: room "closes" — collapses to flat
        this.targetOpacity = 0;
        this.fadeSpeed = 1 / 1.0; // 1 second
        this.entering = false;
        this.exiting = true;

        this.targetDepthProgress = 0;
    }

    /**
     * Reset all particles to starting positions
     */
    _resetParticles() {
        if (!this.particlePositions) return;

        for (let i = 0; i < this.particleCount; i++) {
            const side = Math.floor(Math.random() * 4);
            const t = Math.random();
            let x, y;

            const margin = 0.3;
            switch (side) {
                case 0: x = (t - 0.5) * 14; y = 5 + margin; break;
                case 1: x = 7 + margin; y = (t - 0.5) * 10; break;
                case 2: x = (t - 0.5) * 14; y = -5 - margin; break;
                case 3: x = -7 - margin; y = (t - 0.5) * 10; break;
            }

            this.particlePositions[i * 3] = x;
            this.particlePositions[i * 3 + 1] = y;
            this.particlePositions[i * 3 + 2] = -Math.random() * this.depth * 0.5;
        }

        this.particleSystem.geometry.attributes.position.needsUpdate = true;
    }

    // ============================================
    // Update (called every frame)
    // ============================================

    update(deltaTime) {
        const needsUpdate = this.isActive || this.entering || this.exiting;
        if (!needsUpdate) return;

        const time = this.threeScene.getElapsedTime();

        // --- Opacity fade ---
        if (this.opacity < this.targetOpacity) {
            this.opacity = Math.min(this.opacity + this.fadeSpeed * deltaTime, this.targetOpacity);
        } else if (this.opacity > this.targetOpacity) {
            this.opacity = Math.max(this.opacity - this.fadeSpeed * deltaTime, this.targetOpacity);
        }

        // --- Depth progress (room opening/closing) ---
        const depthSpeed = this.exiting ? 3.0 : 2.0; // Close faster
        if (this.depthProgress < this.targetDepthProgress) {
            this.depthProgress = Math.min(this.depthProgress + depthSpeed * deltaTime, this.targetDepthProgress);
        } else if (this.depthProgress > this.targetDepthProgress) {
            this.depthProgress = Math.max(this.depthProgress - depthSpeed * deltaTime, this.targetDepthProgress);
        }

        // Ease the depth progress
        const easedDepth = this._easeOutCubic(this.depthProgress);

        // --- Entrance/exit state ---
        if (this.entering && this.opacity >= 1.0 && this.depthProgress >= 1.0) {
            this.entering = false;
        }
        if (this.exiting && this.opacity <= 0 && this.depthProgress <= 0) {
            this.exiting = false;
            this.setVisible(false);
        }

        if (this.opacity <= 0.001) return;

        // --- Apply depth animation: scale room from flat to full ---
        // At depthProgress=0: room is flat (z-scale ≈ 0)
        // At depthProgress=1: full depth
        const zScale = Math.max(0.001, easedDepth);
        this.roomGroup.scale.set(1, 1, zScale);

        // --- Opacity for all line materials ---
        const baseLineOpacity = 0.18 * this.opacity; // 0.1-0.25 range base
        if (this.edgeMaterial) {
            this.edgeMaterial.opacity = baseLineOpacity;
        }
        if (this.floorMaterial) {
            this.floorMaterial.opacity = baseLineOpacity * 0.4;
        }
        if (this.ceilingMaterial) {
            this.ceilingMaterial.opacity = baseLineOpacity * 0.4;
        }
        if (this.particleMaterial) {
            this.particleMaterial.opacity = 0.6 * this.opacity;
        }

        // --- Slow Y-axis rotation ---
        if (this.isActive) {
            this.rotationY += deltaTime * 0.02; // 0.02 rad/s
            this.roomGroup.rotation.y = this.rotationY;
        }

        // --- Pulse vanishing point light ---
        const vanishPulse = Math.sin(time * 1.5) * 0.3 + 0.7;
        if (this.vanishingLight) {
            this.vanishingLight.intensity = 0.8 * vanishPulse * this.opacity;
        }
        if (this.vanishingGlow) {
            this.vanishingGlow.material.opacity = 0.3 * vanishPulse * this.opacity;
        }

        // --- Update flow particles ---
        if (this.particleSystem && this.isActive) {
            this._updateParticles(deltaTime, time);
        }
    }

    /**
     * Update particle positions: flow along perspective lines toward vanishing point
     */
    _updateParticles(deltaTime, time) {
        const positions = this.particlePositions;
        const d = this.depth;
        let needsReset = false;

        for (let i = 0; i < this.particleCount; i++) {
            const vel = this.particleVelocities[i];
            const idx = i * 3;

            // Current position
            let x = positions[idx];
            let y = positions[idx + 1];
            let z = positions[idx + 2];

            // Direction toward vanishing point (0, 0, -d)
            const dx = -x;
            const dy = -y;
            const dz = -d - z;
            const dist = Math.sqrt(dx*dx + dy*dy + dz*dz) + 0.001;

            // Normalize + add speed
            const speed = vel.speed * deltaTime;
            x += (dx / dist) * speed;
            y += (dy / dist) * speed;
            z += (dz / dist) * speed;

            // Add wobble
            const wobble = Math.sin(time * 2 + vel.wobblePhase) * 0.003;
            x += vel.driftX * wobble;
            y += vel.driftY * wobble;

            // Reset if reached vanishing point (or passed it)
            if (dist < 0.5 || z < -d + 0.1) {
                // Respawn at edge
                const side = Math.floor(Math.random() * 4);
                const t = Math.random();
                const margin = 0.5;
                switch (side) {
                    case 0: x = (t - 0.5) * 14; y = 5.5 + margin; break;
                    case 1: x = 7.5 + margin; y = (t - 0.5) * 10; break;
                    case 2: x = (t - 0.5) * 14; y = -5.5 - margin; break;
                    case 3: x = -7.5 - margin; y = (t - 0.5) * 10; break;
                }
                z = -Math.random() * 2; // Start near screen
            }

            positions[idx] = x;
            positions[idx + 1] = y;
            positions[idx + 2] = z;
        }

        this.particleSystem.geometry.attributes.position.needsUpdate = true;
    }

    // ============================================
    // Easing
    // ============================================

    _easeOutCubic(t) {
        return 1 - Math.pow(1 - t, 3);
    }

    // ============================================
    // Cleanup
    // ============================================

    dispose() {
        if (this.edgeLines) {
            this.edgeLines.geometry.dispose();
            this.edgeMaterial.dispose();
        }
        if (this.floorGrid) {
            this.floorGrid.geometry.dispose();
            this.floorMaterial.dispose();
        }
        if (this.ceilingGrid) {
            this.ceilingGrid.geometry.dispose();
            this.ceilingMaterial.dispose();
        }
        if (this.particleSystem) {
            this.particleSystem.geometry.dispose();
            this.particleMaterial.dispose();
        }
        if (this.vanishingGlow) {
            this.vanishingGlow.geometry.dispose();
            this.vanishingGlow.material.dispose();
        }
        if (this.roomGroup) {
            this.scene.remove(this.roomGroup);
        }
    }
}

window.LiminalState = LiminalState;
