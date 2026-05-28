// CRT Post-Processing Fragment Shader
// Scanlines + chromatic aberration + vignette + film grain

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

// Pseudo-random function for grain
float rand(vec2 co) {
    return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
}

// 2D noise for grain
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

    // Apply screen curvature (barrel distortion)
    vec2 centered = uv - 0.5;
    float dist = length(centered);
    float curvature = 1.0 + uCurvature * dist * dist;
    vec2 curvedUv = centered * curvature + 0.5;

    // Discard pixels outside curved bounds
    if (curvedUv.x < 0.0 || curvedUv.x > 1.0 || curvedUv.y < 0.0 || curvedUv.y > 1.0) {
        gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // --- Chromatic Aberration ---
    float chromOffset = uChromaticStrength * dist * 0.02;
    vec2 chromDir = normalize(centered + 0.001);

    float r = texture2D(uSceneTexture, curvedUv + chromDir * chromOffset * 1.5).r;
    float g = texture2D(uSceneTexture, curvedUv + chromDir * chromOffset * 0.5).g;
    float b = texture2D(uSceneTexture, curvedUv - chromDir * chromOffset * 0.8).b;
    vec3 color = vec3(r, g, b);

    // --- Scanlines ---
    float scanlineY = gl_FragCoord.y;
    float scanlineFreq = uResolution.y / 2.0; // Every 2 pixels
    float scanline = sin(scanlineY * 3.14159265 / 1.0) * 0.5 + 0.5;
    scanline = 1.0 - (scanline * uScanlineIntensity);
    color *= scanline;

    // --- Moving scan band (retro feel) ---
    float scanBand = sin(curvedUv.y * 20.0 + uTime * 0.5) * 0.5 + 0.5;
    scanBand = smoothstep(0.48, 0.52, scanBand) * 0.08;
    color += vec3(scanBand * 0.3, scanBand * 0.5, scanBand * 0.7);

    // --- Horizontal hold lines ---
    float holdLine = step(0.98, rand(vec2(floor(curvedUv.y * 300.0), floor(uTime * 10.0))));
    color *= 1.0 - holdLine * 0.3;

    // --- Vignette ---
    float vignetteDist = length(centered * 1.5);
    float vignette = 1.0 - smoothstep(0.4, 1.2, vignetteDist);
    vignette = mix(1.0, vignette, uVignetteStrength);
    color *= vignette;

    // --- Film Grain ---
    float grain = noise(gl_FragCoord.xy * 0.5 + uTime * 100.0);
    grain = (grain - 0.5) * uGrainIntensity;
    color += grain;

    // --- Screen flicker ---
    float flicker = 1.0 + (rand(vec2(uTime * 60.0, 0.0)) - 0.5) * uFlickerIntensity;
    color *= flicker;

    // --- Screen tint (greenish phosphor) ---
    vec3 phosphorTint = vec3(0.85, 0.95, 0.90);
    color *= phosphorTint;

    // --- Brightness boost in center ---
    float centerGlow = 1.0 - dist * 0.3;
    color *= centerGlow;

    // --- Clip and output ---
    color = clamp(color, 0.0, 1.0);
    gl_FragColor = vec4(color, 1.0);
}
