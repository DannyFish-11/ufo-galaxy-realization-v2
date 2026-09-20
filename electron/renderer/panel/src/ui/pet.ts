/**
 * 「自发注意力」那一栏右边坐着的一只小东西。
 *
 * ## 它替代了什么
 *
 * 这一位原先是两行字:一行写「上一拍:忍住没说」,一行写后端给的理由。字是准的,
 * 但它讲的是**一只在旁边待着的东西此刻什么心思** —— 那种事人天生会从一张脸上读,
 * 不会从一行状语里读。所以换成一只脸:同样的事实,换一种人本来就会的读法。
 *
 * ## 它不是装饰:每一样都**接着每拍都在变的那份帧**
 *
 * 这一位原先只认 `ambient_action`,而那是**上一拍的决策** —— 一个已经发生完的
 * 事实。拿它当常驻姿势,它就会一直卡在「忍住没说」那个样子不动,下一次决策可能
 * 是几分钟以后。看着像死了。
 *
 * 所以拆成两层:
 *
 *   **底子是实时的** —— 每一帧都在变的那几位:
 *     phase              静 / 阈限 / 显形    它此刻整个人的状态
 *     liminal_activity   懂 → 想 → 排演      阈限态里它在干嘛(有序递进)
 *     is_sensing         在不在收             眼睛睁多开
 *     privacy_paused     你按没按「别看了」    眼睛闭不闭
 *
 *   **上面叠一次性的反应** —— `ambient_action` 变了就演一遍,演完回到实时那一层。
 *   一个已经过去的决策不该是一个永久的姿势:它是「刚才」,不是「一直」。
 *
 * 再加眨眼。眨眼不接任何数据 —— 它不声称任何事,只是**活的东西会眨眼**;
 * 没有它,上面那些状态再准,看着也像一张贴纸。
 *
 * ## 颜色与呼吸
 *
 * 身子用面板自己那支紫(`--m-2`),眼睛用近白那一档(`--m-6`),不引第二种色相。
 * 平时极慢地呼吸一下,周期 5.2 秒 —— 刻意避开 0.2 Hz 那一带(那一带最容易被
 * 余光当成"有事发生"而反复拽走注意力)。
 */
import type { AmbientAction } from '../types';

const svgNS = 'http://www.w3.org/2000/svg';

/** 上一拍的决策 → 演哪一种反应。**四档各一种**,少一种那一档就没演。 */
const POSE: Record<AmbientAction, string> = {
  none: 'rest',
  speak: 'lean',
  silent: 'tuck',
  delegate: 'aside',
};

/**
 * 阈限态里它在干嘛 → 呼吸多快。
 *
 * 后端这一位是**有序递进**的(none → understanding → thinking → rehearsing),
 * 所以节奏也该是递进的:越往后越快。这不是装饰 —— 它让「它在使劲」这件事
 * 在余光里看得见,而不用去读那一行字。
 *
 * 四档**都刻意不落在 0.18~0.22 Hz 那一带**:那一带最容易被余光当成「有事发生」
 * 而反复把注意力拽走。
 *
 *   none          6.0s ≈ 0.167 Hz   (慢于那一带)
 *   understanding 4.3s ≈ 0.233 Hz   (快于那一带)
 *   thinking      3.5s ≈ 0.286 Hz
 *   rehearsing    2.9s ≈ 0.345 Hz
 *
 * 最慢那一档原先写的是 5.2 秒,而 5.2 秒 = 0.192 Hz **正好在带子里** —— 注释却写着
 * 「刻意都不落在那一带」。说的和现实相反,是判据算出来才发现的。
 */
const BREATH: Record<string, string> = {
  none: '6s',
  understanding: '4.3s',
  thinking: '3.5s',
  rehearsing: '2.9s',
};

/** 此刻这只东西周围正在发生什么。**全部来自同一帧。** */
export interface PetLive {
  /** 主轴:静 / 阈限 / 显形 */
  readonly phase: 'silent' | 'liminal' | 'manifest';
  /** 阈限态里正在干嘛。非阈限态时后端给 none */
  readonly activity: string;
  /** 此刻在不在收。null = 还没收到过帧 */
  readonly sensing: boolean | null;
  /** 你按没按「别看了」。**三态** —— null = 还没收到过帧,不能塌进 false */
  readonly paused: boolean | null;
  /** 上一拍的决策。变了就演一遍 */
  readonly act: AmbientAction | null;
}

/** 展开态那一行仍然要写话 —— 脸讲得出情绪,讲不出「为什么」。 */
export const POSE_WORD: Record<AmbientAction, string> = {
  none: '还没决策过',
  speak: '上一拍：开口了',
  silent: '上一拍：忍住没说',
  delegate: '上一拍：交给别人',
};

function el(tag: string, attrs: Record<string, string>): SVGElement {
  const n = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

export interface PetHandles {
  readonly root: SVGElement;
  /** 喂一帧。**每一帧都喂** —— 底子那几位就是靠这个动起来的。 */
  render(live: PetLive): void;
}

export function createPet(): PetHandles {
  const svg = el('svg', {
    class: 'pet',
    viewBox: '0 0 40 40',
    'aria-hidden': 'true',
  });

  // 身子。圆角方块偏一点不规则 —— 正圆看着像个按钮,这个看着像只东西。
  //
  // **呼吸和姿势必须分两层。** 同挂一层的话,动画那条 `transform` 的优先级压过
  // 普通声明,姿势就永远推不动 —— 而且屏幕上看着"有在动",最难查。
  const body = el('g', { class: 'pet-body' });
  const breath = el('g', { class: 'pet-breath' });
  body.append(breath);
  breath.append(
    el('path', {
      class: 'pet-skin',
      // **一颗圆润的卵石**,不是圆角方块 —— 方块那四条直边会让它看着像个图标;
      // 边全收成弧、只在腰上略宽一点,才像一只待着的东西。
      //
      // 也不用正圆:正圆没有上下之分,呼吸起伏时看不出是在起伏还是在整体缩放。
      d: 'M20 4.6c8 0 13.6 4.2 15 11 .6 2.9.6 5.9 0 8.8-1.4 7.2-6.8 11.6-15 11.6S6.4 31.6 5 24.4a22 22 0 0 1 0-8.8c1.4-6.8 7-11 15-11z',
    }),
  );

  // 眼睛。两道竖着的窄缝 —— 睁着是缝,闭上就压扁成一横。
  //
  // 眨眼**单独一层**。眨眼是 transform(压扁),眼睛的开合是几何量(y / height) ——
  // 挂同一层的话动画会把数据那一层整个压住,于是「按了急停」就闭不上了。
  // 这跟姿势/呼吸那一处是同一个坑,已经踩过一次。
  const blink = el('g', { class: 'pet-blink' });
  const eyes = el('g', { class: 'pet-eyes' });
  // 眼睛也跟着圆一档:rx 给到半宽,两头就是整圆而不是倒角。
  const left = el('rect', { class: 'pet-eye', x: '13.2', y: '14.4', width: '4', height: '9.6', rx: '2' });
  const right = el('rect', { class: 'pet-eye', x: '22.8', y: '14.4', width: '4', height: '9.6', rx: '2' });
  eyes.append(left, right);
  blink.append(eyes);
  breath.append(blink);
  svg.append(body);

  /**
   * 上一次演过的是哪一拍。
   *
   * `ambient_action` 是**驻留位**:同一个决策会跟着之后每一帧一遍遍发回来。照帧演的话
   * 它每 0.4 秒抽一下 —— 既刺眼,又把「刚才」说成了「一直」。所以只在它变了的时候演。
   */
  let lastAct = '';
  let reactTimer = 0;

  function render(live: PetLive): void {
    // ── 底子:实时 ────────────────────────────────────────────────
    svg.dataset['phase'] = live.phase;
    // 非阈限态时后端给 none,节奏就回到最慢那一档。
    svg.style.setProperty('--pet-rate', BREATH[live.activity] ?? BREATH['none']!);
    svg.dataset['activity'] = live.activity;
    // 眼睛:闭 / 睁 / 虚。**三档**,不是布尔。
    svg.dataset['eyes'] =
      live.paused === null ? 'unknown' : live.paused ? 'shut' : 'open';
    // 在收的时候睁得开一点。不知道就不动它 —— 那不是「没在收」。
    svg.dataset['sensing'] = live.sensing === null ? 'unknown' : String(live.sensing);

    // ── 上面叠一次性的反应 ───────────────────────────────────────
    // 演完就撤,回到实时那一层。一个已经过去的决策不该留成一个永久的姿势。
    const key = live.act === null ? '' : live.act;
    if (key !== lastAct) {
      lastAct = key;
      window.clearTimeout(reactTimer);
      if (live.act && live.act !== 'none') {
        svg.dataset['react'] = POSE[live.act] ?? 'rest';
        reactTimer = window.setTimeout(() => {
          delete svg.dataset['react'];
        }, 1600);
      } else {
        delete svg.dataset['react'];
      }
    }
  }

  return { root: svg, render };
}
