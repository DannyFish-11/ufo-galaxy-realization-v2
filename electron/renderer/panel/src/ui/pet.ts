/**
 * 「自发注意力」那一栏右边坐着的一只小东西。
 *
 * ## 它替代了什么
 *
 * 这一位原先是两行字:一行写「上一拍:忍住没说」,一行写后端给的理由。字是准的,
 * 但它讲的是**一只在旁边待着的东西此刻什么心思** —— 那种事人天生会从一张脸上读,
 * 不会从一行状语里读。所以换成一只脸:同样的事实,换一种人本来就会的读法。
 *
 * ## 它不是装饰:每一种样子都**接着真数据**
 *
 * 眼睛管**看不看**(隐私急停),身子管**上一拍想了什么**(自发注意力的决策):
 *
 *   眼睛闭上   privacy_paused = true    你按了「别看了」,它就真的不看
 *   眼睛虚着   还没收到过感知帧          面板不知道 —— 不能画成「睁着」也不能画成「闭着」
 *   眼睛睁开   在采
 *
 *   身子不动   none      还没自己动过念头
 *   往前探     speak     它开口了
 *   缩一下     silent    忍住没说
 *   偏向一边   delegate  交给别人了
 *
 * **眼睛那一条是顺带补上的一个洞。** 收起态看不见隐私急停(药丸上只放星系,
 * 那是所有者定的);展开态这儿至少有一双眼睛会闭上 —— 那比一行「感知已暂停」
 * 更快被看见,因为人不需要去读它。
 *
 * ## 颜色与呼吸
 *
 * 身子用面板自己那支紫(`--m-2`),眼睛用近白那一档(`--m-6`),不引第二种色相。
 * 平时极慢地呼吸一下,周期 5.2 秒 —— 刻意避开 0.2 Hz 那一带(那一带最容易被
 * 余光当成"有事发生"而反复拽走注意力)。
 */
import type { AmbientAction } from '../types';

const svgNS = 'http://www.w3.org/2000/svg';

/** 上一拍的决策 → 身子摆成什么样。**四档各一种**,少一种那一档就没画。 */
const POSE: Record<AmbientAction, string> = {
  none: 'rest',
  speak: 'lean',
  silent: 'tuck',
  delegate: 'aside',
};

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
  /**
   * `paused` 三态:true = 你按了急停,false = 在采,null = **还没收到过帧**。
   * null 不能塌进 false —— 那等于替后端断言「它正看着」。
   */
  render(act: AmbientAction | null, paused: boolean | null): void;
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
  const eyes = el('g', { class: 'pet-eyes' });
  // 眼睛也跟着圆一档:rx 给到半宽,两头就是整圆而不是倒角。
  const left = el('rect', { class: 'pet-eye', x: '13.2', y: '14.4', width: '4', height: '9.6', rx: '2' });
  const right = el('rect', { class: 'pet-eye', x: '22.8', y: '14.4', width: '4', height: '9.6', rx: '2' });
  eyes.append(left, right);
  breath.append(eyes);
  svg.append(body);

  function render(act: AmbientAction | null, paused: boolean | null): void {
    // 身子:上一拍想了什么。null = 还没收到过帧,那就连姿势都不摆。
    svg.dataset['pose'] = act === null ? 'unknown' : POSE[act] ?? 'rest';
    // 眼睛:看不看。**三档**,不是布尔。
    svg.dataset['eyes'] = paused === null ? 'unknown' : paused ? 'shut' : 'open';
  }

  return { root: svg, render };
}
