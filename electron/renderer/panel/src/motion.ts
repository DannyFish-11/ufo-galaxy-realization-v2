/**
 * 动效的两条**全局**规矩。都只写在这里一处。
 *
 * ── 一、要躲开的那个频段 ─────────────────────────────────────────
 * 约 0.17–0.25 Hz。那一带最容易被余光当成「有事发生」,反复把注意力拽走;
 * 持续振荡还容易引起不适(照 Apple 那份动效指引)。
 *
 * 这个判据在这仓库里已经栽过**两次**,两次都是同一种栽法:判据写在注释里。
 *   · line.ts 收窄态原先是常态 × 1.5,阈落到 5.1s = 0.196 Hz,正好在带里,
 *     而注释写着「都避开」;
 *   · pet.ts 最慢那一档原先 5.2s = 0.192 Hz,同样在带里,注释同样写着「都避开」。
 *
 * 第一次的修法是在 line.ts 里加一道载入即跑的检查 —— 有用,但只护住了 line.ts。
 * 于是第三次照样发生了:pet.ts 的 understanding 档 4.3s = 0.233 Hz 在带里,
 * 而 pet.ts 的注释给自己写了**另一条带子**(0.18–0.22),4.3s 在那条带子外面。
 * 同一条感知判据有两份数字,窄的那份放行了宽的那份要拦的值。
 *
 * 所以数字收到这里,检查也收到这里:谁定周期谁调用 `checkPeriods`。
 * CSS 那边的周期在 tokens.css 的 --c-* 上,由
 * tests/test_panel_motion_stops_when_asked.py 用同样的 LO/HI 过一遍。
 *
 * ── 二、关了动效之后 ────────────────────────────────────────────
 * 一次过渡(--t-*)缩到 1ms 就等于没有;一直在转的循环(--c-*)缩到 1ms
 * 只会让它转得更疯。所以循环是**整条停掉**,而且停在一处 —— 见 tokens.css
 * 末尾那条通配规则,以及上面那个测试里的理由。
 */

/** 频段边界,单位 Hz。**唯一的一份。** */
export const AVOID_LO = 0.17;
export const AVOID_HI = 0.25;

/** 周期(秒)→ 落不落在带里。只有这一处换算。 */
export function inAvoidBand(seconds: number): boolean {
  const hz = 1 / seconds;
  return hz >= AVOID_LO && hz <= AVOID_HI;
}

/**
 * 把一组周期过一遍,越界的当场喊出来。
 *
 * 不静默 —— 越界要留痕,否则改坏了没人知道。返回越界的条目,好让调用方
 * (和测试)能拿到结果,而不是只能去读 console。
 */
export function checkPeriods(
  source: string,
  periods: ReadonlyArray<readonly [string, number]>,
): ReadonlyArray<readonly [string, number]> {
  const bad = periods.filter(([, secs]) => inAvoidBand(secs));
  for (const [label, secs] of bad) {
    console.error(
      `[hud/${source}] ${label} 的周期 ${secs}s = ${(1 / secs).toFixed(3)} Hz,` +
        `落在要躲开的 ${AVOID_LO}–${AVOID_HI} Hz 带里。`,
    );
  }
  return bad;
}
