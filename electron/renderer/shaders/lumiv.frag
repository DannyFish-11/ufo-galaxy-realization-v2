#version 300 es
precision highp float;

in vec2 v_uv;
out vec4 fragColor;

uniform float u_time;
uniform vec2 u_resolution;
uniform float u_depth;     // 0.0 = Silent, 0.5 = Liminal, 1.0 = Manifest
uniform float u_intent;
uniform float u_speaking;

// ── 工具函数 ─────────────────────────────────────

float breathe(float t) {
  float bt = mod(t, 6.28318530718);
  return 0.82 + 0.18 * sin(bt);
}

float sdSegment(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}

bool inQuad(vec2 p, vec2 a, vec2 b, vec2 c, vec2 d) {
  vec2 ab = b - a, ap = p - a;
  vec2 bc = c - b, bp = p - b;
  vec2 cd = d - c, cp = p - c;
  vec2 da = a - d, dp = p - d;
  float c1 = ab.x * ap.y - ab.y * ap.x;
  float c2 = bc.x * bp.y - bc.y * bp.x;
  float c3 = cd.x * cp.y - cd.y * cp.x;
  float c4 = da.x * dp.y - da.y * dp.x;
  return (c1 >= 0.0 && c2 >= 0.0 && c3 >= 0.0 && c4 >= 0.0) ||
         (c1 <= 0.0 && c2 <= 0.0 && c3 <= 0.0 && c4 <= 0.0);
}

// ── Silent: 暖香槟边缘辉光 ─────────────────────────
// 宽而柔的暖光把屏幕温柔框起来；中心透明、桌面可见。开销极低（每像素一个 smoothstep），
// 软件渲染也能流畅。保留"收回"过渡语义：底边先消失、顶边最后消失。

vec4 renderSilent(vec2 pixel, float t, float weight, float retract) {
  if (weight < 0.001) return vec4(0);

  float W = u_resolution.x;
  float H = u_resolution.y;

  // 到最近屏幕边缘的距离 → 宽柔暖辉光带（短边的 ~18%）
  float dEdge = min(min(pixel.x, W - pixel.x), min(pixel.y, H - pixel.y));
  float band = min(W, H) * 0.18;
  float g = 1.0 - smoothstep(0.0, band, dEdge);
  g = pow(g, 1.7);                       // 更柔的内收拖尾

  // 收回动画：随 retract「从下往上」把整圈辉光抹去（底先消失、顶最后），即原来的
  // “一整个收回”。抹除前沿 cut 从底(1.0)升到顶(0.0)；收回完成后第二态(liminal)展开，
  // 由 main() 的分阶段曲线无缝衔接。
  float yNorm = pixel.y / H;             // 0=顶 1=底
  // 收回前沿 cut：retract=0 时 =1.12(整圈完整、底边不被预削)，retract=1 时 =-0.12(全部收回到顶)
  float cut = 1.12 - 1.24 * retract;
  float retractMask = 1.0 - smoothstep(cut - 0.07, cut + 0.07, yNorm);

  float intensity = g * breathe(t) * weight * 0.62 * retractMask;
  vec3 warm = vec3(1.0, 0.82, 0.60);     // 暖香槟金 (255,209,153)
  return vec4(warm, intensity);
}

// ── Liminal: 鎏金透视空间（桌面安全区）───────────

#define NUM_Z_LAYERS 9
const float Z_LAYERS[NUM_Z_LAYERS] = float[](1.0, 1.6, 2.4, 3.5, 5.0, 7.0, 10.0, 15.0, 25.0);

vec4 renderLiminal(vec2 pixel, float t, float weight, float expand) {
  if (expand < 0.01) return vec4(0);

  float W = u_resolution.x;
  float H = u_resolution.y;
  float cx = W * 0.5;
  float cy = H * 0.5;
  float zNear = 0.8;

  // ── 桌面安全区：中央区域不渲染空间 ──
  // 桌面图标始终可见，空间只出现在边缘区域
  float safeZoneX = W * 0.35;  // 水平安全区半宽
  float safeZoneY = H * 0.30;  // 垂直安全区半高
  float dx = abs(pixel.x - cx);
  float dy = abs(pixel.y - cy);
  // 安全区内alpha衰减（不是硬裁剪，是柔和过渡）
  float safeFade = 1.0;
  if (dx < safeZoneX && dy < safeZoneY) {
    float fx = max(0.0, 1.0 - (safeZoneX - dx) / (safeZoneX * 0.3));
    float fy = max(0.0, 1.0 - (safeZoneY - dy) / (safeZoneY * 0.3));
    safeFade = max(0.0, 1.0 - fx * fy);
  }
  if (safeFade < 0.01) return vec4(0);

  #define PJY(y, z) (cy + ((y) - cy) * zNear / max((z), 0.3))
  #define PJX(x, z) (cx + ((x) - cx) * zNear / max((z), 0.3))

  vec3 accumRGB = vec3(0);
  float accumA = 0;

  // ── z 层墙面 ──
  for (int li = 0; li < NUM_Z_LAYERS - 1; li++) {
    float z1 = Z_LAYERS[li];
    float z2 = Z_LAYERS[li + 1];
    float lp = float(li) / 7.0;

    // 从外往里展开：远处(z大)先出现，近处后出现
    // 这样用户看到的是空间"扑面而来"的感觉
    float expandMap = lp;  // 0=近处, 1=远处
    if (expandMap > expand * 1.3) continue;

    float fade = expandMap < expand ? 1.0 : max(0.0, 1.0 - (expandMap - expand) * 5.0);
    float layerAlpha = 0.14 * (1.0 - lp * 0.5) * fade * expand * weight * safeFade;
    if (layerAlpha < 0.004) continue;

    float yt1 = PJY(0.0, z1), yt2 = PJY(0.0, z2);
    float yb1 = PJY(H,   z1), yb2 = PJY(H,   z2);
    float xl1 = PJX(0.0, z1), xl2 = PJX(0.0, z2);
    float xr1 = PJX(W,   z1), xr2 = PJX(W,   z2);

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
    // 左墙面 — rgba(178,142,67)
    vec2 lA = vec2(xl1, yt1);
    vec2 lB = vec2(max(lIn1, xl1 + 5.0), (yt1 + yb1) * 0.5);
    vec2 lC = vec2(max(lIn2, xl2 + 5.0), (yt2 + yb2) * 0.5);
    vec2 lD = vec2(xl2, yt2);
    if (inQuad(pixel, lA, lB, lC, lD)) {
      vec3 c = vec3(178.0, 142.0, 67.0) / 255.0;
      accumRGB += c * layerAlpha * 1.2 * (1.0 - accumA);
      accumA = min(1.0, accumA + layerAlpha * 1.2);
    }
    // 右墙面 — rgba(178,142,67)
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
    float lineAlpha = max(0.03, (100.0 / 255.0) * (1.0 - float(li) / 8.0) * expand);
    float lw = 1.5;

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
    // 从外往里展开
    if (lp > expand * 1.1) break;
    float tp = lp * lp;
    float yTop = cy * tp * 0.95;
    float yBot = H - (H - cy) * tp * 0.95;
    float spread = W * 0.5 * (1.0 - tp * 0.8);
    float lineAlpha = max(0.016, (75.0 / 255.0) * (1.0 - lp) * expand);
    float lw = max(1.0, 2.2 * (1.0 - lp));

    float dT = abs(sdSegment(pixel, vec2(cx - spread, yTop), vec2(cx + spread, yTop)));
    if (dT < lw) {
      float aa = 1.0 - smoothstep(0.0, lw, dT);
      // 安全区衰减
      aa *= safeFade;
      vec3 c = vec3(255.0, 248.0, 235.0) / 255.0;
      accumRGB += c * lineAlpha * aa * (1.0 - accumA);
      accumA = min(1.0, accumA + lineAlpha * aa);
    }
    float dB = abs(sdSegment(pixel, vec2(cx - spread, yBot), vec2(cx + spread, yBot)));
    if (dB < lw) {
      float aa = 1.0 - smoothstep(0.0, lw, dB);
      aa *= safeFade;
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
      if (lp > expand * 1.1) break;
      float ySt = float(i) * (H / 14.0);
      float lineAlpha2 = max(0.012, (50.0 / 255.0) * (1.0 - lp * 0.6) * expand);
      float d = sdSegment(pixel, vec2(s < 0.0 ? 0.0 : W, ySt), vec2(cx + s * 4.0, cy));
      if (d < 1.0) {
        float aa = 1.0 - smoothstep(0.0, 1.0, d);
        aa *= safeFade;
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
    if (wt > expand) continue;
    float wd = wt;
    float yTop = cy * wd * wd * 0.95;
    float yBot = H - (H - cy) * wd * wd * 0.95;
    float spread = W * 0.5 * (1.0 - wd * wd * 0.8);
    float wa = max(0.0, (65.0 / 255.0) * (1.0 - wt) * expand);
    if (wa < 0.012) continue;
    float lw2 = 2.0;
    float dT = sdSegment(pixel, vec2(cx - spread, yTop), vec2(cx + spread, yTop));
    if (dT < lw2) {
      float aa = 1.0 - smoothstep(0.0, lw2, dT);
      aa *= safeFade;
      vec3 c = vec3(255.0, 248.0, 235.0) / 255.0;
      accumRGB += c * wa * aa * (1.0 - accumA);
      accumA = min(1.0, accumA + wa * aa);
    }
    float dB = sdSegment(pixel, vec2(cx - spread, yBot), vec2(cx + spread, yBot));
    if (dB < lw2) {
      float aa = 1.0 - smoothstep(0.0, lw2, dB);
      aa *= safeFade;
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
  vec2 pixel = vec2(
    v_uv.x * u_resolution.x,
    (1.0 - v_uv.y) * u_resolution.y
  );
  float t = u_time;
  float d = u_depth;

  // ═══════════════════════════════════════════════
  // 分阶段动画曲线
  // ═══════════════════════════════════════════════
  //
  // Phase 0.00-0.25: 纯Silent（边缘光环呼吸）
  // Phase 0.25-0.40: 边缘光向上收回 → 消失
  // Phase 0.40-0.85: 空间从外往里延伸（Liminal主体）
  // Phase 0.85-0.95: 空间收回 + 灵动岛消失
  // Phase 0.95-1.00: Manifest（透明执行）

  // 边缘光收回程度 (0→1在0.25-0.40)
  float edgeRetract = smoothstep(0.25, 0.40, d);

  // 空间展开程度 (0→1在0.40-0.85)
  float spaceExpand = smoothstep(0.40, 0.85, d);

  // 空间收回 (1→0在0.85-0.95)
  float spaceRetract = 1.0 - smoothstep(0.85, 0.95, d);

  // 空间实际可见度 = 展开 × 收回
  float liminalVisible = spaceExpand * spaceRetract;

  // Silent权重：纯Silent阶段 + 收回过渡
  float silentW = max(0.0, 1.0 - d / 0.30) * (1.0 - edgeRetract * 0.3);

  // Liminal权重
  float liminalW = liminalVisible;

  // ── 分别渲染 ──
  vec4 silentRGBA  = renderSilent(pixel, t, silentW, edgeRetract);
  vec4 liminalRGBA = renderLiminal(pixel, t, liminalW, liminalVisible);

  // ── source-over 合成 ──
  vec3 outRGB = silentRGBA.rgb + liminalRGBA.rgb * (1.0 - silentRGBA.a);
  float outA = min(1.0, silentRGBA.a + liminalRGBA.a * (1.0 - silentRGBA.a));

  fragColor = vec4(outRGB, outA);
}
