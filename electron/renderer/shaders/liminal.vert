// Liminal State Vertex Shader
// FOV perspective distortion with vanishing point at screen center

uniform float uTime;
uniform float uTunnelDepth;
uniform float uDistortionStrength;
uniform vec2 uResolution;

varying vec2 vUv;
varying float vDepth;
varying vec3 vWorldPosition;
varying float vDistortion;

// Smooth easing function for non-linear Z stretching
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

    // Vanishing point at screen center (0, 0 in NDC)
    vec2 centerOffset = pos.xy;
    float distFromCenter = length(centerOffset);

    // Normalize position to screen coordinates
    vec2 screenPos = pos.xy;

    // Calculate perspective pull toward vanishing point
    // The deeper into the tunnel (Z), the more points converge to center
    float zNorm = (pos.z + uTunnelDepth * 0.5) / uTunnelDepth;
    zNorm = clamp(zNorm, 0.0, 1.0);

    // Non-linear Z stretching - deeper layers compress more
    float depthEasing = easeInQuad(zNorm);
    vDepth = depthEasing;

    // Pull vertices toward center based on depth
    // Creates the tearing/stretching effect
    float pullStrength = depthEasing * uDistortionStrength;

    // Apply radial pull toward vanishing point
    vec2 pullDir = normalize(-screenPos + 0.001);
    float radialFalloff = smoothstep(0.0, 1.0, distFromCenter);

    // Distort X/Y position - desktop image tearing backward
    pos.xy += pullDir * pullStrength * radialFalloff * 2.0;

    // Non-linear Z compression for tunnel depth
    pos.z = -easeInOutCubic(zNorm) * uTunnelDepth;

    // Add subtle wave distortion for organic feel
    float wave = sin(distFromCenter * 8.0 - uTime * 2.0) * 0.02 * depthEasing;
    pos.xy += normalize(screenPos + 0.001) * wave;

    // Apply perspective projection
    vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
    vec4 projected = projectionMatrix * mvPosition;

    vWorldPosition = pos;
    vDistortion = pullStrength;

    gl_Position = projected;
}
