/**
 * silent-state.js
 * Silent State: Static transparent window with central particle avatar
 * - Three.js MeshPhysicalMaterial (metalness 0.95, roughness 0.15)
 * - Titanium gray color (0x8a9ba8)
 * - CSS3D ambient shadow + breathing animation (4s cycle)
 */

class SilentState {
    constructor(threeScene) {
        this.threeScene = threeScene;
        this.scene = threeScene.getScene();
        this.isActive = false;

        // Meshes
        this.particleMesh = null;
        this.particleGroup = null;
        this.ambientLight = null;
        this.pointLight1 = null;
        this.pointLight2 = null;

        // Animation
        this.breathPhase = 0;
        this.floatPhase = 0;
        this.originalY = 0;

        // Breathing parameters
        this.breathSpeed = 1.57; // 2*PI / 4 seconds = 1.57 rad/s for 4s cycle
        this.breathAmplitude = 0.08;

        // Build the scene
        this.build();
    }

    build() {
        // Create particle group
        this.particleGroup = new THREE.Group();

        // Main particle sphere - MeshPhysicalMaterial
        const geometry = new THREE.SphereGeometry(0.25, 64, 64);
        const material = new THREE.MeshPhysicalMaterial({
            color: 0x8a9ba8,
            metalness: 0.95,
            roughness: 0.15,
            clearcoat: 0.3,
            clearcoatRoughness: 0.1,
            envMapIntensity: 1.0,
            reflectivity: 0.9
        });
        this.particleMesh = new THREE.Mesh(geometry, material);
        this.originalY = this.particleMesh.position.y;
        this.particleGroup.add(this.particleMesh);

        // Inner glow core (smaller, emissive sphere)
        const coreGeometry = new THREE.SphereGeometry(0.08, 32, 32);
        const coreMaterial = new THREE.MeshBasicMaterial({
            color: 0xb0c4d0,
            transparent: true,
            opacity: 0.15
        });
        this.coreMesh = new THREE.Mesh(coreGeometry, coreMaterial);
        this.particleGroup.add(this.coreMesh);

        // Outer halo ring (torus)
        const ringGeometry = new THREE.TorusGeometry(0.35, 0.003, 16, 64);
        const ringMaterial = new THREE.MeshBasicMaterial({
            color: 0x8a9ba8,
            transparent: true,
            opacity: 0.2,
            side: THREE.DoubleSide
        });
        this.ringMesh = new THREE.Mesh(ringGeometry, ringMaterial);
        this.ringMesh.rotation.x = Math.PI / 2;
        this.particleGroup.add(this.ringMesh);

        // Add lights
        this.ambientLight = new THREE.AmbientLight(0x404040, 0.5);
        this.pointLight1 = new THREE.PointLight(0xa0b0c0, 0.8, 10);
        this.pointLight1.position.set(2, 2, 3);
        this.pointLight2 = new THREE.PointLight(0x607080, 0.4, 10);
        this.pointLight2.position.set(-2, -1, 2);

        this.scene.add(this.ambientLight);
        this.scene.add(this.pointLight1);
        this.scene.add(this.pointLight2);
        this.scene.add(this.particleGroup);

        // Initially hidden
        this.setVisible(false);
    }

    setVisible(visible) {
        if (this.particleGroup) {
            this.particleGroup.visible = visible;
        }
        if (this.ambientLight) {
            this.ambientLight.visible = visible;
        }
        if (this.pointLight1) {
            this.pointLight1.visible = visible;
        }
        if (this.pointLight2) {
            this.pointLight2.visible = visible;
        }

        // DOM overlay
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

    enter() {
        if (this.isActive) return;
        this.isActive = true;
        this.setVisible(true);

        // Reset phases
        this.breathPhase = 0;
        this.floatPhase = 0;

        // Entrance animation - scale up
        this.particleGroup.scale.set(0.1, 0.1, 0.1);
        this.entranceStartTime = this.threeScene.getElapsedTime();
        this.isEntering = true;

        // Disable post-processing in silent state
        this.threeScene.enablePostProcessing(false);
    }

    exit() {
        if (!this.isActive) return;
        this.isActive = false;

        // Exit animation - scale down
        this.isExiting = true;
        this.exitStartTime = this.threeScene.getElapsedTime();

        // Hide after short delay
        setTimeout(() => {
            this.setVisible(false);
            this.isExiting = false;
        }, 500);
    }

    update(deltaTime) {
        if (!this.isActive && !this.isEntering && !this.isExiting) return;

        const time = this.threeScene.getElapsedTime();

        // Entrance animation
        if (this.isEntering) {
            const elapsed = time - this.entranceStartTime;
            const progress = Math.min(elapsed / 0.8, 1.0);
            const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
            const scale = 0.1 + eased * 0.9;
            this.particleGroup.scale.set(scale, scale, scale);
            if (progress >= 1.0) {
                this.isEntering = false;
            }
        }

        // Exit animation
        if (this.isExiting) {
            const elapsed = time - this.exitStartTime;
            const progress = Math.min(elapsed / 0.5, 1.0);
            const eased = progress * progress; // ease-in quadratic
            const scale = 1.0 - eased * 0.9;
            this.particleGroup.scale.set(scale, scale, scale);
        }

        if (!this.isActive) return;

        // Breathing animation (4-second cycle)
        this.breathPhase += deltaTime * this.breathSpeed;
        const breathValue = Math.sin(this.breathPhase) * 0.5 + 0.5; // 0 to 1

        // Scale breathing
        const breathScale = 1.0 + breathValue * this.breathAmplitude;
        this.particleMesh.scale.set(breathScale, breathScale, breathScale);

        // Subtle floating motion
        this.floatPhase += deltaTime * 0.8;
        const floatY = Math.sin(this.floatPhase) * 0.03;
        this.particleGroup.position.y = floatY;

        // Core pulse (synced with breath, slightly offset)
        const corePulse = Math.sin(this.breathPhase + 0.5) * 0.5 + 0.5;
        this.coreMesh.scale.setScalar(1.0 + corePulse * 0.3);
        this.coreMesh.material.opacity = 0.08 + corePulse * 0.12;

        // Ring rotation and pulse
        this.ringMesh.rotation.z += deltaTime * 0.2;
        const ringPulse = Math.sin(this.breathPhase * 0.7) * 0.5 + 0.5;
        this.ringMesh.scale.setScalar(1.0 + ringPulse * 0.05);
        this.ringMesh.material.opacity = 0.1 + ringPulse * 0.15;

        // Light intensity breathing
        this.pointLight1.intensity = 0.8 + breathValue * 0.2;
        this.pointLight2.intensity = 0.4 + (1.0 - breathValue) * 0.15;

        // Subtle particle rotation
        this.particleMesh.rotation.y += deltaTime * 0.3;
        this.particleMesh.rotation.x += deltaTime * 0.15;
    }

    dispose() {
        if (this.particleMesh) {
            this.particleMesh.geometry.dispose();
            this.particleMesh.material.dispose();
        }
        if (this.coreMesh) {
            this.coreMesh.geometry.dispose();
            this.coreMesh.material.dispose();
        }
        if (this.ringMesh) {
            this.ringMesh.geometry.dispose();
            this.ringMesh.material.dispose();
        }
        if (this.particleGroup) {
            this.scene.remove(this.particleGroup);
        }
        if (this.ambientLight) {
            this.scene.remove(this.ambientLight);
        }
        if (this.pointLight1) {
            this.scene.remove(this.pointLight1);
        }
        if (this.pointLight2) {
            this.scene.remove(this.pointLight2);
        }
    }
}

window.SilentState = SilentState;
