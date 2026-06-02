/**
 * manifest-state.js
 * Manifest State: Holographic HUD panel + sci-fi terminal
 * Perspective space collapses, content panel expands from vanishing point
 * NO typing effect — content displays directly with fade-in
 */

class ManifestState {
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.scene = threeScene.getScene();
        this.isActive = false;

        // Three.js elements: a faint glow at center (optional ambient)
        this.glowGroup = null;
        this.centerGlow = null;

        // DOM overlay elements (cached)
        this.overlayEl = null;
        this.panelEl = null;
        this.resultTextEl = null;
        this.phaseDisplayEl = null;
        this.timestampEl = null;
        this.cursorBlinkEl = null;

        // Animation state
        this.opacity = 0;
        this.panelScale = 0.5;
        this.entering = false;
        this.exiting = false;
        this.contentVisible = false;

        // Content
        this.resultText = '';
        this.timestampInterval = null;

        // Timing
        this.enterDuration = 0.6;   // Panel expand: 0.6s
        this.exitDuration = 0.4;    // Panel collapse: 0.4s
        this.contentDelay = 0.3;    // Content fade-in delay: 0.3s

        // Galaxy palette
        this.colorCyan = new THREE.Color(0x00e1ff);

        this.build();
        this._cacheDOMElements();
    }

    // ============================================
    // Build (minimal Three.js — just ambient glow)
    // ============================================
    build() {
        // A subtle center glow behind the panel (Three.js)
        this.glowGroup = new THREE.Group();

        const glowGeo = new THREE.SphereGeometry(0.8, 32, 32);
        const glowMat = new THREE.MeshBasicMaterial({
            color: this.colorCyan,
            transparent: true,
            opacity: 0,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });
        this.centerGlow = new THREE.Mesh(glowGeo, glowMat);
        this.glowGroup.add(this.centerGlow);

        this.scene.add(this.glowGroup);
        this.setVisible(false);
    }

    /**
     * Cache references to DOM overlay elements
     */
    _cacheDOMElements() {
        this.overlayEl = document.getElementById('manifest-overlay');
        this.panelEl = document.getElementById('manifest-panel');
        this.resultTextEl = document.getElementById('manifest-result-text');
        this.phaseDisplayEl = document.getElementById('manifest-phase-display');
        this.timestampEl = document.getElementById('manifest-timestamp');
        this.cursorBlinkEl = document.getElementById('output-cursor-blink');
        this.taskNameEl = document.getElementById('manifest-task-name');
    }

    // ============================================
    // Visibility
    // ============================================

    setVisible(visible) {
        if (this.glowGroup) {
            this.glowGroup.visible = visible;
        }

        if (this.overlayEl) {
            if (visible) {
                this.overlayEl.classList.remove('hidden');
                this.overlayEl.style.opacity = '0';
            } else {
                this.overlayEl.classList.add('hidden');
            }
        }
    }

    // ============================================
    // State Transitions
    // ============================================

    enter(resultText = '') {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        this.resultText = resultText || '';
        this.contentVisible = false;

        // Reset animation state
        this.opacity = 0;
        this.panelScale = 0.5;
        this.entering = true;
        this.exiting = false;
        this.enterStartTime = this.threeScene.getElapsedTime();
        this.contentShownTime = null;

        // Update DOM content immediately
        this._updateDOMContent();
        this._updateTimestamp();

        // Start timestamp updates
        if (this.timestampInterval) clearInterval(this.timestampInterval);
        this.timestampInterval = setInterval(() => this._updateTimestamp(), 1000);

        // Update phase display
        if (this.phaseDisplayEl) {
            this.phaseDisplayEl.textContent = 'MANIFEST';
        }

        // Apply initial CSS for entrance animation
        if (this.panelEl) {
            this.panelEl.style.transition = 'none';
            this.panelEl.style.opacity = '0';
            this.panelEl.style.transform = 'scale(0.5)';

            // Force reflow
            void this.panelEl.offsetHeight;

            // Start entrance transition
            this.panelEl.style.transition = `opacity ${this.enterDuration}s ease-out, transform ${this.enterDuration}s cubic-bezier(0.16, 1, 0.3, 1)`;
            this.panelEl.style.opacity = '1';
            this.panelEl.style.transform = 'scale(1)';
        }

        // Update overlay opacity
        if (this.overlayEl) {
            this.overlayEl.style.transition = `opacity ${this.enterDuration}s ease-out`;
            this.overlayEl.style.opacity = '1';
        }

        // Schedule content fade-in
        setTimeout(() => {
            this.contentVisible = true;
            this._fadeInContent();
        }, this.contentDelay * 1000);

        // Enable subtle post-processing for glow effect
        this.threeScene.enablePostProcessing(true);
        this.threeScene.updateCRTUniforms({
            uScanlineIntensity: 0.15,
            uChromaticStrength: 0.3,
            uVignetteStrength: 0.5,
            uGrainIntensity: 0.06,
            uFlickerIntensity: 0.02,
            uCurvature: 0.04
        });
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // Stop timestamp updates
        if (this.timestampInterval) {
            clearInterval(this.timestampInterval);
            this.timestampInterval = null;
        }

        this.entering = false;
        this.exiting = true;
        this.exitStartTime = this.threeScene.getElapsedTime();

        // CSS exit animation: scale down + fade out
        if (this.panelEl) {
            this.panelEl.style.transition = `opacity ${this.exitDuration}s ease-in, transform ${this.exitDuration}s ease-in`;
            this.panelEl.style.opacity = '0';
            this.panelEl.style.transform = 'scale(0.8)';
        }

        if (this.overlayEl) {
            this.overlayEl.style.transition = `opacity ${this.exitDuration}s ease-in`;
            this.overlayEl.style.opacity = '0';
        }

        // Hide after exit animation completes
        setTimeout(() => {
            this.exiting = false;
            this.setVisible(false);
            this.threeScene.enablePostProcessing(false);
        }, this.exitDuration * 1000 + 50);
    }

    // ============================================
    // Content Management
    // ============================================

    /**
     * Set result text directly (NO typing effect)
     */
    setResult(text) {
        this.resultText = text || '';
        if (this.isActive) {
            this._updateDOMContent();
        }
    }

    /**
     * Update DOM content: display text directly with fade-in
     */
    _updateDOMContent() {
        if (!this.resultTextEl) return;

        // Direct display — no typing
        const escaped = this._escapeHtml(this.resultText);
        // Preserve line breaks
        const withBreaks = escaped.replace(/\n/g, '<br>');
        this.resultTextEl.innerHTML = withBreaks;

        // Start with opacity 0, then fade in
        this.resultTextEl.style.opacity = '0';
        this.resultTextEl.style.transition = 'none';

        // Force reflow
        void this.resultTextEl.offsetHeight;

        // Fade in
        this.resultTextEl.style.transition = 'opacity 0.4s ease-out';
        this.resultTextEl.style.opacity = '1';
    }

    /**
     * Fade in content elements
     */
    _fadeInContent() {
        if (!this.resultTextEl || !this.resultText) return;

        this.resultTextEl.style.opacity = '0';
        this.resultTextEl.style.transition = 'opacity 0.4s ease-out 0.1s';

        requestAnimationFrame(() => {
            this.resultTextEl.style.opacity = '1';
        });
    }

    /**
     * Update timestamp display
     */
    _updateTimestamp() {
        if (!this.timestampEl) return;
        const now = new Date();
        const hh = String(now.getHours()).padStart(2, '0');
        const mm = String(now.getMinutes()).padStart(2, '0');
        const ss = String(now.getSeconds()).padStart(2, '0');
        this.timestampEl.textContent = `${hh}:${mm}:${ss}`;
    }

    /**
     * Escape HTML special characters
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ============================================
    // Update (called every frame)
    // ============================================

    update(deltaTime) {
        const needsUpdate = this.isActive || this.entering || this.exiting;
        if (!needsUpdate) return;

        const time = this.threeScene.getElapsedTime();

        // --- Entrance animation tracking ---
        if (this.entering) {
            const elapsed = time - this.enterStartTime;
            const progress = Math.min(elapsed / this.enterDuration, 1.0);
            this.opacity = progress;
            // Scale: 0.5 → 1.0 with ease-out
            this.panelScale = 0.5 + (1 - Math.pow(1 - progress, 3)) * 0.5;

            if (progress >= 1.0) {
                this.entering = false;
                this.opacity = 1;
                this.panelScale = 1;
            }
        }

        // --- Exit animation tracking ---
        if (this.exiting) {
            const elapsed = time - this.exitStartTime;
            const progress = Math.min(elapsed / this.exitDuration, 1.0);
            this.opacity = 1 - progress;
            this.panelScale = 1 - progress * 0.2; // 1.0 → 0.8

            if (progress >= 1.0) {
                this.exiting = false;
            }
        }

        // --- Three.js glow update ---
        if (this.centerGlow && this.glowGroup.visible) {
            // Pulse glow
            const pulse = Math.sin(time * 2) * 0.2 + 0.8;
            this.centerGlow.material.opacity = 0.06 * pulse * this.opacity;
            this.centerGlow.scale.setScalar(1 + Math.sin(time * 1.5) * 0.1);

            // Slow rotation
            this.glowGroup.rotation.y += deltaTime * 0.3;
            this.glowGroup.rotation.x += deltaTime * 0.15;
        }

        // --- Cursor blink animation ---
        if (this.cursorBlinkEl && this.isActive) {
            const blink = Math.sin(time * 5) > 0 ? '_' : '';
            this.cursorBlinkEl.textContent = blink;
            this.cursorBlinkEl.style.opacity = 0.5 + Math.sin(time * 3) * 0.5;
        }
    }

    // ============================================
    // Cleanup
    // ============================================

    dispose() {
        if (this.timestampInterval) {
            clearInterval(this.timestampInterval);
        }

        if (this.centerGlow) {
            this.centerGlow.geometry.dispose();
            this.centerGlow.material.dispose();
        }
        if (this.glowGroup) {
            this.scene.remove(this.glowGroup);
        }
    }
}

window.ManifestState = ManifestState;
