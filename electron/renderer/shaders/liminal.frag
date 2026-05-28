// Liminal State Fragment Shader
// Liquid ink flow along perspective lines with Simplex noise

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

// Simplex 3D Noise
vec4 permute(vec4 x) {
    return mod(((x * 34.0) + 1.0) * x, 289.0);
}
vec4 taylorInvSqrt(vec4 r) {
    return 1.79284291400159 - 0.85373472095314 * r;
}

float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

    // First corner
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);

    // Other corners
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);

    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;

    // Permutations
    i = mod(i, 289.0);
    vec4 p = permute(permute(permute(
        i.z + vec4(0.0, i1.z, i2.z, 1.0))
        + i.y + vec4(0.0, i1.y, i2.y, 1.0))
        + i.x + vec4(0.0, i1.x, i2.x, 1.0));

    // Gradients
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

    // Normalise gradients
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x;
    p1 *= norm.y;
    p2 *= norm.z;
    p3 *= norm.w;

    // Mix contributions
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

// Fractional Brownian Motion for layered noise
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

// Rotation matrix for swirling ink
mat2 rotate(float angle) {
    float c = cos(angle);
    float s = sin(angle);
    return mat2(c, -s, s, c);
}

void main() {
    vec2 uv = vUv;
    float t = uTime;

    // Flow direction: along the tunnel (perspective lines converge to center)
    vec2 centerDir = normalize(uv - 0.5 + 0.001);
    float distFromCenter = length(uv - 0.5);

    // Tunnel flow coordinate - moves along perspective lines
    float flowSpeed = t * uTunnelSpeed;
    vec3 flowPos = vec3(
        uv.x * 2.0,
        uv.y * 2.0,
        flowSpeed + vDepth * 5.0
    );

    // Swirling ink motion
    vec2 swirlUv = (uv - 0.5) * rotate(t * 0.1 + vDepth * 2.0) + 0.5;
    vec3 swirlPos = vec3(swirlUv * 3.0, flowSpeed * 0.7);

    // Layered noise for ink veins
    float ink1 = fbm(flowPos + swirlPos * 0.5, 4);
    float ink2 = fbm(flowPos * 1.5 + vec3(t * 0.2, t * 0.15, 0.0), 3);
    float ink3 = fbm(vec3(
        centerDir.x * distFromCenter * 4.0 + t * 0.3,
        centerDir.y * distFromCenter * 4.0,
        vDepth * 3.0 + t * 0.5
    ), 3);

    // Create vein-like structures
    float veins = smoothstep(0.3, 0.6, abs(ink1));
    veins *= smoothstep(0.2, 0.5, abs(ink2));

    // Flow lines along perspective
    float flowLines = sin(distFromCenter * 20.0 - t * 3.0 - vDepth * 10.0) * 0.5 + 0.5;
    flowLines = smoothstep(0.4, 0.6, flowLines) * (1.0 - vDepth * 0.5);

    // Combine ink layers
    float inkPattern = veins * 0.5 + abs(ink3) * 0.3 + flowLines * 0.2;
    inkPattern = smoothstep(0.2, 0.8, inkPattern);

    // Color mixing based on depth and ink flow
    vec3 color = mix(uInkColor1, uInkColor2, ink1 * 0.5 + 0.5);
    color = mix(color, uInkColor3, ink2 * 0.5 + 0.5);

    // Depth-based darkness (tunnel gets darker deeper in)
    float depthFade = 1.0 - vDepth * 0.7;
    color *= depthFade;

    // Ink intensity boost
    color *= 1.0 + inkPattern * uInkIntensity;

    // Vignette along tunnel edges
    float edgeDist = length(uv - 0.5) * 1.5;
    float vignette = 1.0 - smoothstep(0.3, 0.8, edgeDist);
    color *= vignette * 0.3 + 0.7;

    // Add subtle glow along flow lines
    float glow = flowLines * 0.15 * (1.0 - vDepth);
    color += uInkColor2 * glow;

    // Output with depth-based alpha
    float alpha = 0.85 + inkPattern * 0.15;
    alpha *= (1.0 - vDepth * 0.3);

    gl_FragColor = vec4(color, alpha);
}
