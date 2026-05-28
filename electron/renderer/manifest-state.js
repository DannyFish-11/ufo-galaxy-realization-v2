/**
 * manifest-state.js
 * Manifest State: CRT monitor effect with scanlines, chromatic aberration, vignette, grain
 * - Full-screen industrial execution grid
 * - Result display with typing animation
 */

class ManifestState {
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.scene = threeScene.getScene();
        this.isActive = false;

        // CRT scene elements
        this.crtGroup = null;
        this.screenMesh = null;
        this.screenMaterial = null;
        this.frameMesh = null;
        this.glowMesh = null;

        // Result content
        this.resultText = '';
        this.isTyping = false;
        this.typedLength = 0;
        this.typingSpeed = 30; // ms per character
        this.typingInterval = null;

        // Boot animation
        this.bootPhase = 0;

        this.build();
    }

    build() {
        this.crtGroup = new THREE.Group();

        // Screen plane for CRT display area
        const screenGeometry = new THREE.PlaneGeometry(16, 10, 1, 1);
        const screenMaterial = new THREE.MeshBasicMaterial({
            color: 0x0a0f14,
            transparent: true,
            opacity: 0.95,
            side: THREE.DoubleSide
        });
        this.screenMesh = new THREE.Mesh(screenGeometry, screenMaterial);
        this.screenMesh.position.z = 0;
        this.crtGroup.add(this.screenMesh);

        // Outer frame (bezel)
        const frameGeometry = new THREE.PlaneGeometry(17, 11, 1, 1);
        const frameMaterial = new THREE.MeshBasicMaterial({
            color: 0x1a2028,
            transparent: true,
            opacity: 0.8,
            side: THREE.DoubleSide
        });
        this.frameMesh = new THREE.Mesh(frameGeometry, frameMaterial);
        this.frameMesh.position.z = -0.1;
        this.crtGroup.add(this.frameMesh);

        // Screen glow
        const glowGeometry = new THREE.PlaneGeometry(16.5, 10.5, 1, 1);
        const glowMaterial = new THREE.MeshBasicMaterial({
            color: 0x4a6080,
            transparent: true,
            opacity: 0.1,
            side: THREE.BackSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        this.glowMesh = new THREE.Mesh(glowGeometry, glowMaterial);
        this.glowMesh.position.z = -0.2;
        this.crtGroup.add(this.glowMesh);

        // Corner accents (4 small markers at corners)
        this.cornerAccents = [];
        const cornerSize = 0.3;
        const cornerPositions = [
            [-8, 5, 0.1], [8, 5, 0.1],
            [-8, -5, 0.1], [8, -5, 0.1]
        ];
        cornerPositions.forEach(pos => {
            const geo = new THREE.PlaneGeometry(cornerSize, 0.03);
            const mat = new THREE.MeshBasicMaterial({
                color: 0x8a9ba8,
                transparent: true,
                opacity: 0.5
            });
            const meshH = new THREE.Mesh(geo, mat);
            meshH.position.set(pos[0], pos[1], pos[2]);
            this.crtGroup.add(meshH);

            const geoV = new THREE.PlaneGeometry(0.03, cornerSize);
            const meshV = new THREE.Mesh(geoV, mat.clone());
            meshV.position.set(pos[0], pos[1], pos[2]);
            this.crtGroup.add(meshV);
            this.cornerAccents.push(meshH, meshV);
        });

        // Status LEDs
        this.ledMesh = new THREE.Mesh(
            new THREE.CircleGeometry(0.06, 16),
            new THREE.MeshBasicMaterial({
                color: 0x50c878,
                transparent: true,
                opacity: 0.8
            })
        );
        this.ledMesh.position.set(7.8, -5.3, 0.1);
        this.crtGroup.add(this.ledMesh);

        // Add CRT lighting
        this.crtLight = new THREE.PointLight(0x4a6080, 0.6, 20);
        this.crtLight.position.set(0, 0, 3);
        this.crtGroup.add(this.crtLight);

        this.scene.add(this.crtGroup);
        this.setVisible(false);
    }

    setVisible(visible) {
        if (this.crtGroup) {
            this.crtGroup.visible = visible;
        }

        const overlay = document.getElementById('crt-overlay');
        if (overlay) {
            if (visible) {
                overlay.classList.remove('hidden');
                overlay.classList.add('crt-boot');
            } else {
                overlay.classList.add('hidden');
                overlay.classList.remove('crt-boot');
                overlay.classList.add('crt-shutdown');
                setTimeout(() => {
                    overlay.classList.remove('crt-shutdown');
                }, 400);
            }
        }

        // Update CRT phase indicator
        const phaseEl = document.getElementById('crt-phase');
        if (phaseEl) {
            phaseEl.textContent = 'MANIFEST';
        }
    }

    enter(resultText = '') {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        this.resultText = resultText || '';
        this.typedLength = 0;
        this.bootPhase = 0;
        this.isTyping = false;

        // Boot animation sequence
        this.isBooting = true;
        this.bootStartTime = this.threeScene.getElapsedTime();

        // Enable CRT post-processing
        this.threeScene.enablePostProcessing(true);
        this.threeScene.updateCRTUniforms({
            uScanlineIntensity: 0.35,
            uChromaticStrength: 1.0,
            uVignetteStrength: 0.7,
            uGrainIntensity: 0.15,
            uFlickerIntensity: 0.06,
            uCurvature: 0.1
        });

        // Update DOM content
        this.updateTimestamp();
        this.timestampInterval = setInterval(() => this.updateTimestamp(), 1000);

        // Start typing if result provided
        if (this.resultText) {
            setTimeout(() => {
                this.startTyping();
            }, 800);
        }
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // Stop typing
        this.stopTyping();

        // Stop timestamp updates
        if (this.timestampInterval) {
            clearInterval(this.timestampInterval);
            this.timestampInterval = null;
        }

        // Shutdown animation
        this.setVisible(false);

        // Disable post-processing
        this.threeScene.enablePostProcessing(false);
    }

    startTyping() {
        if (this.isTyping) return;
        this.isTyping = true;
        this.typedLength = 0;

        const resultEl = document.getElementById('crt-result');
        if (!resultEl) return;

        resultEl.innerHTML = '<span class="typing-cursor"></span>';

        this.typingInterval = setInterval(() => {
            if (this.typedLength < this.resultText.length) {
                this.typedLength++;
                const text = this.resultText.substring(0, this.typedLength);
                // Add occasional line styling
                const lines = text.split('\n');
                let html = '';
                lines.forEach((line, i) => {
                    if (i > 0) html += '\n';
                    html += `<span class="crt-result-line" style="animation-delay: ${i * 0.05}s">${this.escapeHtml(line)}</span>`;
                });
                html += '<span class="typing-cursor"></span>';
                resultEl.innerHTML = html;
            } else {
                // Done typing - keep cursor blinking
                const text = this.resultText;
                const lines = text.split('\n');
                let html = '';
                lines.forEach((line, i) => {
                    if (i > 0) html += '\n';
                    html += `<span class="crt-result-line">${this.escapeHtml(line)}</span>`;
                });
                html += '<span class="typing-cursor"></span>';
                resultEl.innerHTML = html;
                this.stopTyping();
            }
        }, this.typingSpeed);
    }

    stopTyping() {
        this.isTyping = false;
        if (this.typingInterval) {
            clearInterval(this.typingInterval);
            this.typingInterval = null;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    updateTimestamp() {
        const el = document.getElementById('crt-timestamp');
        if (el) {
            const now = new Date();
            const hh = String(now.getHours()).padStart(2, '0');
            const mm = String(now.getMinutes()).padStart(2, '0');
            const ss = String(now.getSeconds()).padStart(2, '0');
            el.textContent = `${hh}:${mm}:${ss}`;
        }
    }

    setResult(text) {
        this.resultText = text;
        this.typedLength = 0;
        if (this.isActive) {
            this.stopTyping();
            this.startTyping();
        }
    }

    update(deltaTime) {
        if (!this.isActive && !this.isBooting) return;

        const time = this.threeScene.getElapsedTime();

        // Boot animation
        if (this.isBooting) {
            const elapsed = time - this.bootStartTime;
            const progress = Math.min(elapsed / 1.2, 1.0);

            // Flicker effect during boot
            const flicker = progress < 0.3
                ? Math.random() * 0.5 + 0.5
                : 1.0;

            if (this.screenMesh) {
                this.screenMesh.material.opacity = progress * 0.95 * flicker;
            }
            if (this.glowMesh) {
                this.glowMesh.material.opacity = progress * 0.15;
            }
            if (this.frameMesh) {
                this.frameMesh.material.opacity = progress * 0.8;
            }

            if (progress >= 1.0) {
                this.isBooting = false;
            }
        }

        if (!this.isActive) return;

        // LED pulse
        if (this.ledMesh) {
            const ledPulse = Math.sin(time * 3) * 0.3 + 0.7;
            this.ledMesh.material.opacity = ledPulse;
        }

        // Glow breathing
        if (this.glowMesh) {
            const glowBreath = Math.sin(time * 1.5) * 0.05 + 0.15;
            this.glowMesh.material.opacity = glowBreath;
        }

        // Corner accent pulse
        this.cornerAccents.forEach((accent, i) => {
            const pulse = Math.sin(time * 2 + i * 0.5) * 0.3 + 0.5;
            accent.material.opacity = pulse * 0.5;
        });

        // CRT light flicker
        if (this.crtLight) {
            this.crtLight.intensity = 0.6 + Math.sin(time * 4) * 0.1;
        }

        // Update post-processing uniforms
        const flickerIntensity = 0.04 + Math.sin(time * 8) * 0.02;
        this.threeScene.updateCRTUniforms({
            uFlickerIntensity: flickerIntensity,
            uTime: time
        });
    }

    dispose() {
        this.stopTyping();
        if (this.timestampInterval) {
            clearInterval(this.timestampInterval);
        }

        if (this.screenMesh) {
            this.screenMesh.geometry.dispose();
            this.screenMesh.material.dispose();
        }
        if (this.frameMesh) {
            this.frameMesh.geometry.dispose();
            this.frameMesh.material.dispose();
        }
        if (this.glowMesh) {
            this.glowMesh.geometry.dispose();
            this.glowMesh.material.dispose();
        }
        if (this.ledMesh) {
            this.ledMesh.geometry.dispose();
            this.ledMesh.material.dispose();
        }
        this.cornerAccents.forEach(accent => {
            accent.geometry.dispose();
            accent.material.dispose();
        });
        if (this.crtGroup) {
            this.scene.remove(this.crtGroup);
        }
    }
}

window.ManifestState = ManifestState;
