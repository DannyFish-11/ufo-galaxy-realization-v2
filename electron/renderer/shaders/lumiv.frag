#version 300 es
precision highp float;

/**
 * Lumiv 三态统一渲染着色器 — GLSL 300 es
 *
 * 1:1 复刻 Canvas 2D 版本视觉效果
 * - Silent: 四边缘呼吸光环 (2.2% 宽度)
 * - Liminal: 鎏金色透视空间 (从近到远展开)
 * - Manifest: 透明
 *
 * 注意：GLSL ES 3.0 不支持函数嵌套，投影使用宏内联
 */

in vec2 v_uv;
out vec4 fragColor;

uniform float u_time;
uniform vec2 u_resolution;
uniform float u_depth;
uniform float u_intent;
uniform float u_speaking;

#define PI 3.14159265
#define NUM_Z_LAYERS 8

const float Z_LAYERS[NUM_Z_LAYERS] = float[](
  1.0, 1.5, 2.2, 3.2, 4.8, 7.2, 11.0, 18.0
);

// ── 工具函数 ─────────────────────────────────────

float breathe(float t) {
  return 0.65 + 0.35 * (0.5 + 0.5 * sin(t * 0.785 - PI * 0.5));
}

float cross2(vec2 a, vec2 b) {
  return a.x * b.y - a.y * b.x;
}

bool inQuad(vec2 p, vec2 a, vec2 b, vec2 c, vec2 d) {
  float c1 = cross2(b - a, p - a);
  float c2 = cross2(c - b, p - b);
  float c3 = cross2(d - c, p - c);
  float c4 = cross2(a - d, p - d);
  bool pos = (c1 >= 0.0) && (c2 >= 0.0) && (c3 >= 0.0) && (c4 >= 0.0);
  bool neg = (c1 <= 0.0) && (c2 <= 0.0) && (c3 <= 0.0) && (c4 <= 0.0);
  return pos || neg;
}

float sdSegment(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}

// ── Silent: 边缘光环 ─────────────────────────────

vec4 renderSilent(vec2 pixel, float t, float weight) {
  if (weight < 0.001) return vec4(0);

  float bt = breathe(t) * weight;
  float W = u_resolution.x;
  float H = u_resolution.y;
  float edgeH = H * 0.022;
  float edgeW = W * 0.022;
  float peakA = 55.0 / 255.0;

  float px = pixel.x;
  float py = pixel.y;
  float a = 0.0;

  // 上边缘 — rgba(255,248,235)
  if (py < edgeH) {
    a = max(a, peakA * bt * (1.0 - py / edgeH));
  }
  // 下边缘 — rgba(232,205,165)
  if (H - py < edgeH) {
    a = max(a, peakA * 0.85 * bt * (1.0 - (H - py) / edgeH));
  }
  // 左边缘 — rgba(250,244,230)
  if (px < edgeW) {
    a = max(a, peakA * 0.8 * bt * (1.0 - px / edgeW));
  }
  // 右边缘 — rgba(250,244,230)
  if (W - px < edgeW) {
    a = max(a, peakA * 0.8 * bt * (1.0 - (W - px) / edgeW));
  }

  if (a < 0.002) return vec4(0);

  vec3 topCol  = vec3(255.0, 248.0, 235.0) / 255.0;
  vec3 botCol  = vec3(232.0, 205.0, 165.0) / 255.0;
  vec3 sideCol = vec3(250.0, 244.0, 230.0) / 255.0;

  float dTop = py;
  float dBot = H - py;
  float dLeft = px;
  float dRight = W - px;
  float minD = min(min(dTop, dBot), min(dLeft, dRight));

  vec3 col = sideCol;
  if (minD == dTop)  col = topCol;
  if (minD == dBot)  col = botCol;

  return vec4(col * a, a);
}

// ── Liminal: 鎏金透视空间 ────────────────────────

vec4 renderLiminal(vec2 pixel, float t, float weight) {
  float spring = clamp((u_depth - 0.18) / 0.35, 0.0, 1.0);
  if (spring < 0.01) return vec4(0);

  float W = u_resolution.x;
  float H = u_resolution.y;
  float cx = W * 0.5;
  float cy = H * 0.5;
  float zNear = 0.8;

  // 投影宏（GLSL 不支持嵌套函数）
  #define PJY(y, z) (cy + ((y) - cy) * zNear / max((z), 0.3))
  #define PJX(x, z) (cx + ((x) - cx) * zNear / max((z), 0.3))

  vec3 accumRGB = vec3(0);
  float accumA = 0;

  // ── z 层墙面 ──
  for (int li = 0; li < NUM_Z_LAYERS - 1; li++) {
    float z1 = Z_LAYERS[li];
    float z2 = Z_LAYERS[li + 1];
    float lp = float(li) / 7.0;

    if (lp > spring * 1.3) break;

    float fade = lp < spring ? 1.0 : max(0.0, 1.0 - (lp - spring) * 5.0);
    float layerAlpha = 0.14 * (1.0 - lp * 0.5) * fade * spring * weight;
    if (layerAlpha < 0.004) continue;

    float yt1 = PJY(0.0, z1), yt2 = PJY(0.0, z2);
    float yb1 = PJY(H,   z1), yb2 = PJY(H,   z2);
    float xl1 = PJX(0.0, z1), xl2 = PJX(0.0, z2);
    float xr1 = PJX(W,   z1), xr2 = PJX(W,   z2);

    // 墙面展开因子 — 控制左右墙面的横向宽度
    float wallSpread = 0.35;
    float lIn1 = cx - cx * wallSpread * zNear / z1;
    float lIn2 = cx - cx * wallSpread * zNear / z2;
    float rIn1 = cx + (W - cx) * wallSpread * zNear / z1;
    float rIn2 = cx + (W - cx) * wallSpread * zNear / z2;

    // 上墙面（天花板）— rgba(255,250,240)
    if (inQuad(pixel, vec2(xl1,yt1), vec2(xr1,yt1), vec2(xr2,yt2), vec2(xl2,yt2))) {
      vec3 c = vec3(255.0, 250.0, 240.0) / 255.0;
      accumRGB += c * layerAlpha * (1.0 - accumA);
      accumA = min(1.0, accumA + layerAlpha);
    }
    // 下墙面（地板）— rgba(228,200,160)
    if (inQuad(pixel, vec2(xl1,yb1), vec2(xr1,yb1), vec2(xr2,yb2), vec2(xl2,yb2))) {
      vec3 c = vec3(228.0, 200.0, 160.0) / 255.0;
      accumRGB += c * layerAlpha * 0.85 * (1.0 - accumA);
      accumA = min(1.0, accumA + layerAlpha * 0.85);
    }
    // 左墙面 — rgba(178,142,67) — 增强alpha到1.2，更宽的梯形
    vec2 lA = vec2(xl1, yt1);
    vec2 lB = vec2(max(lIn1, xl1 + 5.0), (yt1 + yb1) * 0.5);
    vec2 lC = vec2(max(lIn2, xl2 + 5.0), (yt2 + yb2) * 0.5);
    vec2 lD = vec2(xl2, yt2);
    if (inQuad(pixel, lA, lB, lC, lD)) {
      vec3 c = vec3(178.0, 142.0, 67.0) / 255.0;
      accumRGB += c * layerAlpha * 1.2 * (1.0 - accumA);
      accumA = min(1.0, accumA + layerAlpha * 1.2);
    }
    // 右墙面 — rgba(178,142,67) — 增强alpha到1.2，更宽的梯形
    vec2 rA = vec2(xr1, yt1);
    vec2 rB = vec2(min(rIn1, xr1 - 5.0), (yt1 + yb1) * 0.5);
    vec2 rC = vec2(min(rIn2, xr2 - 5.0), (yt2 + yb2) * 0.5);
    vec2 rD = vec2(xr2, yt2);
    if (inQuad(pixel, rA, rB, rC, rD)) {
      vec3 c = vec3(178.0, 142.0, 67.0) / 255.0;
      accumRGB += c * layerAlpha * 1.2 * (1.0 - accumA);
      accumA = min(1.0, accumA + layerAlpha * 1.2);
    }

    // ── 墙面轮廓线 ──
    float lineAlpha = max(0.03, (100.0 / 255.0) * (1.0 - float(li) / 8.0) * spring);
    float lw = 1.5;

    // 外轮廓（上下墙面边界）
    if (sdSegment(pixel, vec2(xl1,yt1), vec2(xl2,yt2)) < lw) {
      vec3 c = vec3(255.0, 245.0, 230.0) / 255.0;
      accumRGB += c * lineAlpha * (1.0 - accumA); accumA = min(1.0, accumA + lineAlpha);
    }
    if (sdSegment(pixel, vec2(xr1,yt1), vec2(xr2,yt2)) < lw) {
      vec3 c = vec3(255.0, 245.0, 230.0) / 255.0;
      accumRGB += c * lineAlpha * (1.0 - accumA); accumA = min(1.0, accumA + lineAlpha);
    }
    if (sdSegment(pixel, vec2(xl1,yb1), vec2(xl2,yb2)) < lw) {
      vec3 c = vec3(225.0, 195.0, 155.0) / 255.0;
      accumRGB += c * lineAlpha * (1.0 - accumA); accumA = min(1.0, accumA + lineAlpha);
    }
    if (sdSegment(pixel, vec2(xr1,yb1), vec2(xr2,yb2)) < lw) {
      vec3 c = vec3(225.0, 195.0, 155.0) / 255.0;
      accumRGB += c * lineAlpha * (1.0 - accumA); accumA = min(1.0, accumA + lineAlpha);
    }

    // 左右墙面内轮廓线（鎏金色）
    float goldLineA = lineAlpha * 0.8;
    if (sdSegment(pixel, lB, lC) < lw) {
      vec3 c = vec3(212.0, 175.0, 55.0) / 255.0;
      accumRGB += c * goldLineA * (1.0 - accumA); accumA = min(1.0, accumA + goldLineA);
    }
    if (sdSegment(pixel, rB, rC) < lw) {
      vec3 c = vec3(212.0, 175.0, 55.0) / 255.0;
      accumRGB += c * goldLineA * (1.0 - accumA); accumA = min(1.0, accumA + goldLineA);
    }
  }

  // ── 水平线 ──
  for (int i = 0; i < 22; i++) {
    float lp = float(i) / 22.0;
    if (lp > spring * 1.1) break;
    float tp = lp * lp;
    float yTop = cy * tp * 0.95;
    float yBot = H - (H - cy) * tp * 0.95;
    float spread = W * 0.5 * (1.0 - tp * 0.8);
    float lineAlpha = max(0.016, (75.0 / 255.0) * (1.0 - lp) * spring);
    float lw = max(1.0, 2.2 * (1.0 - lp));

    float dT = abs(sdSegment(pixel, vec2(cx - spread, yTop), vec2(cx + spread, yTop)));
    if (dT < lw) {
      float aa = 1.0 - smoothstep(0.0, lw, dT);
      vec3 c = vec3(255.0, 248.0, 235.0) / 255.0;
      accumRGB += c * lineAlpha * aa * (1.0 - accumA);
      accumA = min(1.0, accumA + lineAlpha * aa);
    }
    float dB = abs(sdSegment(pixel, vec2(cx - spread, yBot), vec2(cx + spread, yBot)));
    if (dB < lw) {
      float aa = 1.0 - smoothstep(0.0, lw, dB);
      vec3 c = vec3(228.0, 200.0, 160.0) / 255.0;
      accumRGB += c * lineAlpha * aa * (1.0 - accumA);
      accumA = min(1.0, accumA + lineAlpha * aa);
    }
  }

  // ── 斜线 ──
  for (int side = 0; side < 2; side++) {
    float s = side == 0 ? -1.0 : 1.0;
    for (int i = 0; i < 14; i++) {
      float lp = float(i) / 14.0;
      if (lp > spring * 1.1) break;
      float ySt = float(i) * (H / 14.0);
      float lineAlpha2 = max(0.012, (50.0 / 255.0) * (1.0 - lp * 0.6) * spring);
      float d = sdSegment(pixel, vec2(s < 0.0 ? 0.0 : W, ySt), vec2(cx + s * 4.0, cy));
      if (d < 1.0) {
        float aa = 1.0 - smoothstep(0.0, 1.0, d);
        vec3 c = vec3(255.0, 248.0, 235.0) / 255.0;
        accumRGB += c * lineAlpha2 * aa * (1.0 - accumA);
        accumA = min(1.0, accumA + lineAlpha2 * aa);
      }
    }
  }

  // ── 扫描波 ──
  float waveSpeed = u_speaking > 0.5 ? 0.5 : 0.3;
  for (int wi = 0; wi < 3; wi++) {
    float wt = mod(t * waveSpeed + float(wi) * 0.33, 1.0);
    if (wt > spring) continue;
    float wd = wt;
    float yTop = cy * wd * wd * 0.95;
    float yBot = H - (H - cy) * wd * wd * 0.95;
    float spread = W * 0.5 * (1.0 - wd * wd * 0.8);
    float wa = max(0.0, (65.0 / 255.0) * (1.0 - wt) * spring);
    if (wa < 0.012) continue;
    float lw2 = 2.0;
    float dT = sdSegment(pixel, vec2(cx - spread, yTop), vec2(cx + spread, yTop));
    if (dT < lw2) {
      float aa = 1.0 - smoothstep(0.0, lw2, dT);
      vec3 c = vec3(255.0, 248.0, 235.0) / 255.0;
      accumRGB += c * wa * aa * (1.0 - accumA);
      accumA = min(1.0, accumA + wa * aa);
    }
    float dB = sdSegment(pixel, vec2(cx - spread, yBot), vec2(cx + spread, yBot));
    if (dB < lw2) {
      float aa = 1.0 - smoothstep(0.0, lw2, dB);
      vec3 c = vec3(228.0, 200.0, 160.0) / 255.0;
      accumRGB += c * wa * aa * (1.0 - accumA);
      accumA = min(1.0, accumA + wa * aa);
    }
  }

  #undef PJY
  #undef PJX

  return vec4(accumRGB, accumA);
}

// ── Main ─────────────────────────────────────────

void main() {
  // 像素坐标（Canvas 2D 风格：原点在左上角，y 向下）
  vec2 pixel = vec2(
    v_uv.x * u_resolution.x,
    (1.0 - v_uv.y) * u_resolution.y
  );

  float t = u_time;

  // ── 三态权重（与 Canvas 2D 版本完全一致） ──
  float silentW  = max(0.0, 1.0 - u_depth / 0.30);
  float liminalW = max(0.0, min(1.0, (u_depth - 0.15) / 0.40) * min(1.0, (0.95 - u_depth) / 0.35));

  // ── 分别渲染两态 ──
  vec4 silentRGBA  = renderSilent(pixel, t, silentW);
  vec4 liminalRGBA = renderLiminal(pixel, t, liminalW);

  // ── source-over 合成 ──
  vec3 outRGB = silentRGBA.rgb + liminalRGBA.rgb * (1.0 - silentRGBA.a);
  float outA = min(1.0, silentRGBA.a + liminalRGBA.a * (1.0 - silentRGBA.a));

  fragColor = vec4(outRGB, outA);
}
