/**
 * 收起态那枚药丸里的**一座微缩星系**。
 *
 * ## 为什么是星系,不是一排小方块
 *
 * 这块面板要在余光里回答一件事:**还有多少东西连着**。小方块能数,但数东西
 * 是要用中央视觉的 —— 得看清楚每一格是浮着还是沉着,才数得出来。星系不用数:
 * 一片星海**亮不亮**是周边视觉直接给的,不经过「读」这一步。
 *
 * 所以这里的映射只有两条,都不需要图例:
 *
 *   连接浓度  →  整座星系**有多亮**。连着的少,它就暗;连着的多,它就亮起来。
 *   每台连着的设备  →  星海里**一颗明显更亮的星**。灭一台,那颗星自己淡回星海。
 *
 * 药丸的比例是**跟着星系改的**,不是反过来。它原先 186 × 40(4.6 : 1),那个宽度
 * 是给八格小方块留的;方块撤了,宽度就没有理由了。而 4.6 : 1 意味着盘得倾到 78°
 * ——那么平的角度下旋臂会压成一片糊,只剩「一堆星」,正是不该有的样子。
 *
 * 所以药丸收到 112 × 40(2.8 : 1),盘倾 66°。这个角度旋臂还认得出是两道反向甩
 * 出去的弧,核球也还在中间立得住。**投影是真投的**:盘面坐标先转再按 cos(i) 压,
 * 旋臂因此是近大远小的椭圆弧,不是把一张圆图拉扁。
 *
 * ## 结构照着银河系搭
 *
 * 银河系是一个**有棒的旋涡星系**(SBbc):中间一根棒、两条主旋臂从棒的两端甩
 * 出去、两条次旋臂、再加上盘上的散星和一圈很稀的晕。这几件都画了 —— 只撒一把
 * 星点是撒不出星系的,星系之所以认得出来,靠的是**旋臂、核球、尘埃带**这三样。
 * 旋臂走的是对数螺线 r = r0·e^(bθ),取 13° 的缠绕角(银河系实测约 12°)。
 *
 * ## 颜色
 *
 * 只有白光。星是白的,核球是白的,尘埃带用的是这块面板本来就在用的那一种灰紫
 * (阴影色)。**不引第二种色相** —— 星系在莫兰迪底子上本来就该是这样。
 *
 * ## 星位是定死的
 *
 * 星表在模块加载时用一个**定种子**的伪随机数算一次,之后不再变。每帧重算的话
 * 整片星海会跟着帧闪 —— 那不是星系,那是噪点。设备变了只改**亮度**,不改星位:
 * 于是同一台设备永远是同一颗星,灭了就是那一颗淡下去,而不是整片重排。
 */
import type { DeviceRow } from '../types';

const svgNS = 'http://www.w3.org/2000/svg';

/** 画布。宽高比跟着药丸(112 × 40),上下多留一点给晕。 */
const W = 140;
const H = 54;
const CX = W / 2;
const CY = H / 2;

/**
 * 盘的倾角。cos(i) 就是投影之后的扁率 —— 这个数定下来,盘有多高就定下来了。
 * 66° 对应扁率 0.407:盘半径 54 时半高 22 —— 旋臂最外圈连上厚度约 24,落在
 * 画布半高 27 里面。**这一条不能松**:药丸是 overflow:hidden 的,盘只要比画布
 * 大一点,外圈旋臂就被直接切掉,星系看着像被咬了一口。
 */
const INCLINATION = (66 * Math.PI) / 180;
const COS_I = Math.cos(INCLINATION);
const SIN_I = Math.sin(INCLINATION);
/** 盘在画面上转一点,不是正着摆 —— 正着摆像个仪表,斜着才像在天上。 */
const ROLL = (-7 * Math.PI) / 180;
const COS_R = Math.cos(ROLL);
const SIN_R = Math.sin(ROLL);
/** 盘半径 → 画布像素。 */
const SCALE = 54;

/** 对数螺线的缠绕角。银河系实测约 12°,取 13°。 */
const PITCH = Math.tan((13 * Math.PI) / 180);

/** 定种子的伪随机数(mulberry32)。**必须定种子** —— 见文件头。 */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 两个均匀数 → 一个正态数。撒星要的是聚在中间、边上渐稀,不是一片均匀。 */
function gauss(r: () => number): number {
  const u = Math.max(1e-9, r());
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

export interface Star {
  /** 画布坐标 */
  readonly x: number;
  readonly y: number;
  /** 半径 */
  readonly r: number;
  /** 本来有多亮,0..1 */
  readonly b: number;
  /** 盘面上离心多远。排「哪几颗显眼」时用得着 —— 太靠核球的挑出来看不见 */
  readonly rad: number;
}

/**
 * 盘面坐标 → 画布坐标。
 *
 * 先在盘面里转 ROLL,再按倾角压扁;盘的厚度 z 在倾斜之后**贴到竖直方向上**,
 * 所以盘不是一条线,而是一条有厚度的带 —— 边缘那点厚度正是它看着像「盘」而
 * 不像「一道杠」的原因。
 */
function project(x: number, y: number, z: number): { x: number; y: number } {
  const px = x * COS_R - y * SIN_R;
  const py = x * SIN_R + y * COS_R;
  return { x: CX + px * SCALE, y: CY + (py * COS_I + z * SIN_I) * SCALE };
}

/** 一条旋臂上撒星。`arm` 定这条臂从棒的哪一端甩出去。 */
function armStars(out: Star[], r: () => number, phase: number, count: number, weight: number): void {
  for (let k = 0; k < count; k += 1) {
    // 沿臂走。t 偏向外侧一点 —— 旋臂外段本来就比内段长
    const t = Math.pow(r(), 0.78);
    const theta = phase + t * 4.9;
    const rad = 0.26 * Math.exp(PITCH * (theta - phase) * 1.02);
    if (rad > 1.02) continue;
    // 臂有宽度:越往外越散。零宽度的臂是一根线,不是旋臂
    const spread = (0.022 + rad * 0.034) * gauss(r);
    const ang = theta + spread / Math.max(0.2, rad);
    const rr = rad + spread * 0.5;
    const z = gauss(r) * 0.018 * (1 + rad);
    const p = project(rr * Math.cos(ang), rr * Math.sin(ang), z);
    // 旋臂上是新星,最亮的那一档在这儿。越往外越淡:盘本来就是外面稀
    const b = weight * (0.5 + 0.5 * r()) * (1 - 0.24 * rad);
    out.push({ x: p.x, y: p.y, r: 0.26 + r() * (0.34 + weight * 0.26), b, rad: rr });
  }
}

/** 撒一次星表。定种子,只跑一次。 */
function buildStars(): Star[] {
  const r = rng(0x9a17c3);
  const out: Star[] = [];

  // ── 棒 ──────────────────────────────────────────────────────────
  // 银河系是有棒的。没有这根棒,两条主旋臂就没有根,看着像凭空缠上去的。
  for (let k = 0; k < 130; k += 1) {
    const t = gauss(r) * 0.4;
    const x = Math.max(-0.42, Math.min(0.42, t));
    const y = gauss(r) * 0.055;
    const z = gauss(r) * 0.035;
    const p = project(x, y, z);
    out.push({ x: p.x, y: p.y, r: 0.23 + r() * 0.25, b: 0.42 + 0.4 * r(), rad: Math.abs(x) });
  }

  // ── 核球 ────────────────────────────────────────────────────────
  // 又密又厚的一团。它是这座星系的重心,画面上也是 —— 眼睛先落在这儿。
  for (let k = 0; k < 150; k += 1) {
    const rad = Math.abs(gauss(r)) * 0.085;
    const ang = r() * Math.PI * 2;
    const z = gauss(r) * 0.075;
    const p = project(rad * Math.cos(ang), rad * Math.sin(ang), z);
    out.push({ x: p.x, y: p.y, r: 0.2 + r() * 0.23, b: 0.5 + 0.45 * r(), rad });
  }

  // ── 旋臂 ────────────────────────────────────────────────────────
  // 两条主臂从棒的两端(相位 0 与 π)甩出去,两条次臂夹在中间、暗一档。
  armStars(out, r, 0, 330, 1);
  armStars(out, r, Math.PI, 330, 1);
  armStars(out, r, Math.PI * 0.52, 120, 0.5);
  armStars(out, r, Math.PI * 1.52, 120, 0.5);

  // ── 盘上的散星 ──────────────────────────────────────────────────
  // 臂与臂之间不是空的,只是稀。全空的话旋臂就成了四条独立的带子。
  for (let k = 0; k < 150; k += 1) {
    const rad = Math.pow(r(), 0.55) * 1.0;
    const ang = r() * Math.PI * 2;
    const z = gauss(r) * 0.026 * (1 + rad);
    const p = project(rad * Math.cos(ang), rad * Math.sin(ang), z);
    out.push({ x: p.x, y: p.y, r: 0.15 + r() * 0.17, b: (0.12 + 0.2 * r()) * (1 - 0.18 * rad), rad });
  }

  // ── 晕 ──────────────────────────────────────────────────────────
  // 很稀、很淡、接近球形。它管的是**轮廓**:没有晕,盘的边就是一刀切下去的。
  for (let k = 0; k < 190; k += 1) {
    const rad = 0.5 + Math.pow(r(), 0.5) * 0.9;
    const ang = r() * Math.PI * 2;
    const z = gauss(r) * 0.42;
    const p = project(rad * Math.cos(ang), rad * Math.sin(ang), z);
    if (p.x < -4 || p.x > W + 4 || p.y < -4 || p.y > H + 4) continue;
    out.push({ x: p.x, y: p.y, r: 0.16 + r() * 0.18, b: 0.08 + 0.12 * r(), rad });
  }

  return out;
}

const STARS = buildStars();

/**
 * 能被「点亮」的那几颗 —— 一台连着的设备占一颗。
 *
 * 挑的规矩:**离核球远一点**(挤在核球里点亮了看不出来,那一团本来就亮)、
 * 本身就在亮的那一档、彼此**不要挨着**(挨着的两颗亮起来会糊成一颗,于是两台
 * 设备在画面上变成一台)。挑完按定序排好,所以第 n 台设备永远是同一颗星。
 */
function pickLit(): Star[] {
  const cand = STARS.filter((s) => s.rad > 0.2 && s.rad < 0.98 && s.b > 0.45)
    .slice()
    .sort((a, b) => b.b - a.b);
  const out: Star[] = [];
  for (const s of cand) {
    if (out.every((o) => (o.x - s.x) ** 2 + (o.y - s.y) ** 2 > 52)) out.push(s);
    if (out.length >= 24) break;
  }
  // ── 排序:让**前 n 颗**总是摊得开 ──────────────────────────────
  //
  // 挑完直接按左右排的话,只连着三台时点亮的就是最左边那三颗 —— 一簇挤在盘的
  // 一边,看着像星系那头坏了,而不是「有三台连着」。
  //
  // 改成最远点遍历:先要最亮的那颗,之后每次要**离已选那些最远**的一颗。这样
  // 任取前 n 个都是铺开的,而且序列是定死的 —— 第 n 台设备仍旧永远是同一颗星。
  const order: Star[] = [out[0]!];
  const left = out.slice(1);
  while (left.length) {
    let best = 0;
    let far = -1;
    for (const [i, s] of left.entries()) {
      const d = Math.min(...order.map((o) => (o.x - s.x) ** 2 + ((o.y - s.y) * 2.2) ** 2));
      if (d > far) {
        far = d;
        best = i;
      }
    }
    order.push(left.splice(best, 1)[0]!);
  }
  return order;
}

const LIT = pickLit();

/** 一台连着的设备能占到一颗星的上限。超过了得留痕 —— 见 render()。 */
export const LIT_CAPACITY = LIT.length;

function el(tag: string, attrs: Record<string, string>): SVGElement {
  const n = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

export interface GalaxyHandles {
  readonly root: SVGElement;
  /**
   * 设备名册变了。**这里只改亮度,不改星位。**
   *
   * `devices` 为空 = 名册还没接上,与「接上了、一台都不在线」是两件事 ——
   * 前者面板什么都不知道,后者是一条结论。两者长得不一样。
   */
  render(devices: readonly DeviceRow[]): void;
}

export function createGalaxy(): GalaxyHandles {
  const svg = el('svg', {
    class: 'galaxy',
    viewBox: `0 0 ${W} ${H}`,
    preserveAspectRatio: 'xMidYMid meet',
    'aria-hidden': 'true',
  });

  const defs = el('defs', {});
  // 核球的光。盘面上那一团弥散的亮,不是一颗大星
  const core = el('radialGradient', { id: 'gx-core', cx: '50%', cy: '50%', r: '50%' });
  core.append(
    el('stop', { offset: '0%', 'stop-color': '#ffffff', 'stop-opacity': '0.85' }),
    el('stop', { offset: '38%', 'stop-color': '#ffffff', 'stop-opacity': '0.32' }),
    el('stop', { offset: '100%', 'stop-color': '#ffffff', 'stop-opacity': '0' }),
  );
  // 盘的辉光。铺在星底下,没有它整片星点是浮在药丸上的,不像一座星系
  const disc = el('radialGradient', { id: 'gx-disc', cx: '50%', cy: '50%', r: '50%' });
  disc.append(
    el('stop', { offset: '0%', 'stop-color': '#ffffff', 'stop-opacity': '0.3' }),
    el('stop', { offset: '55%', 'stop-color': '#ffffff', 'stop-opacity': '0.11' }),
    el('stop', { offset: '100%', 'stop-color': '#ffffff', 'stop-opacity': '0' }),
  );
  /**
   * 被点亮那几颗星身上的光。
   *
   * **必须是渐变,不能是一个半透明的圆。** 半透明的圆是一块饼,边是硬的;
   * 星的光是往外化开的。这一处是「有设备连着」唯一的说法,读不成一颗星就白做。
   */
  const glow = el('radialGradient', { id: 'gx-glow', cx: '50%', cy: '50%', r: '50%' });
  glow.append(
    el('stop', { offset: '0%', 'stop-color': '#ffffff', 'stop-opacity': '1' }),
    el('stop', { offset: '26%', 'stop-color': '#ffffff', 'stop-opacity': '0.62' }),
    el('stop', { offset: '100%', 'stop-color': '#ffffff', 'stop-opacity': '0' }),
  );
  defs.append(core, disc, glow);

  const tilt = `rotate(${(ROLL * 180) / Math.PI} ${CX} ${CY})`;
  const discGlow = el('ellipse', {
    class: 'gx-disc', cx: String(CX), cy: String(CY),
    rx: String(SCALE * 1.1), ry: String(SCALE * COS_I * 1.45),
    fill: 'url(#gx-disc)', transform: tilt,
  });
  const coreGlow = el('ellipse', {
    class: 'gx-core', cx: String(CX), cy: String(CY),
    rx: String(SCALE * 0.26), ry: String(SCALE * COS_I * 0.82),
    fill: 'url(#gx-core)', transform: tilt,
  });

  // ── 尘埃带 ──────────────────────────────────────────────────────
  // 旋臂内侧那一道暗。**这一道才是星系认得出来的地方** —— 没有它,亮的地方
  // 挨着亮的地方,整盘糊成一片雾。用的是面板本来的阴影色,不是新颜色。
  const dust = el('g', { class: 'gx-dust' });
  for (const phase of [0.12, Math.PI + 0.12]) {
    const pts: string[] = [];
    for (let k = 0; k <= 34; k += 1) {
      const theta = phase + (k / 34) * 4.7;
      const rad = 0.245 * Math.exp(PITCH * (theta - phase) * 1.02);
      if (rad > 1.0) break;
      const p = project(rad * Math.cos(theta), rad * Math.sin(theta), 0);
      pts.push(`${p.x.toFixed(2)},${p.y.toFixed(2)}`);
    }
    dust.append(el('polyline', { points: pts.join(' '), fill: 'none' }));
  }

  const field = el('g', { class: 'gx-field' });
  for (const s of STARS) {
    field.append(
      el('circle', {
        cx: s.x.toFixed(2), cy: s.y.toFixed(2), r: s.r.toFixed(2),
        opacity: s.b.toFixed(3),
      }),
    );
  }

  // ── 被点亮的那几颗 = 接着的设备 ──────────────────────────────────
  // 每一颗都先建好摆在那儿,亮度由 data-lit 控制 —— 于是一台设备上线/掉线是
  // **那一颗自己亮起来或淡回去**,不是整片星海重画。
  const litG = el('g', { class: 'gx-lit' });
  const litNodes: SVGElement[] = LIT.map((s) => {
    const g = el('g', { class: 'gx-star', transform: `translate(${s.x.toFixed(2)} ${s.y.toFixed(2)})` });
    g.append(
      el('circle', { class: 'gx-halo-c', r: '4.6', fill: 'url(#gx-glow)' }),
      el('circle', { class: 'gx-core-c', r: '1.05' }),
    );
    g.setAttribute('data-lit', 'off');
    litG.append(g);
    return g;
  });

  svg.append(defs, discGlow, dust, field, coreGlow, litG);

  function render(devices: readonly DeviceRow[]): void {
    // 名册没接上:只剩轮廓。**一颗都不点亮,核球也不亮** —— 点亮等于替后端
    // 断言「有这些设备连着」,而面板此刻一台都不知道。
    const wired = devices.length > 0;
    svg.dataset['wired'] = String(wired);

    const live = devices.filter((d) => d.state !== 'offline').length;
    // 连接浓度 → 整座星系有多亮。**连着一台就该看得出来**,所以起点不是 0:
    // 底下那一档是「接上了,但没有谁在线」,它跟「没接上」已经由 data-wired 分开。
    const lum = wired ? Math.min(1, 0.22 + 0.78 * (1 - Math.exp(-live / 3.1))) : 0;
    svg.style.setProperty('--gx-lum', lum.toFixed(3));

    for (const [i, g] of litNodes.entries()) {
      const d = devices[i];
      // 三档,不是布尔。降级的那台亮一半 —— 顶着「在线」那一档的亮度,
      // 等于在余光里把降级说成了在线。
      g.setAttribute(
        'data-lit',
        !d || d.state === 'offline' ? 'off' : d.state === 'degraded' ? 'half' : 'on',
      );
    }
  }

  return { root: svg, render };
}
