/**
 * 对话区。
 *
 * 锁步这件事在这里落地:一句话只有在 TTS **真的开始念它之后**才上屏,
 * 所以未念的那一截是灰的(`turn-pending`)。而一旦脱钩 —— 引擎挂了、首句
 * 超时、中途卡住 —— 文字会转成逐字直出。
 *
 * **那一刻必须留痕。** 声音和文字已经错开了,界面上一声不吭的话,人只会
 * 觉得"节奏怪怪的",查不出所以然。所以脱钩时在流里插一条明确的记号。
 */
import type { LockstepReason, LockstepState, Revision, Turn } from '../types';

const REASON_TEXT: Record<Exclude<LockstepReason, ''>, string> = {
  no_speaker: '本轮没走语音',
  disabled_by_config: '你关掉了锁步',
  no_first_sentence: '首句宽限内一句都没念出来',
  mid_stall: '念到一半卡住了',
};

export interface ThreadHandles {
  readonly root: HTMLElement;
  render(turns: readonly Turn[], lockstep: LockstepState, reason: LockstepReason): void;
}

/**
 * 画一段回答,把核出来的修订落上去(core/live_check.py):
 *
 * - 驳倒的:**原句留着、划掉**(所有者的决定),后面跟一句「更正」;
 * - 查不到的:原句照常,后面一个小小的「未核实」,悬停看为什么。
 *
 * 按原句文字在气泡里找,从上一处往后找、只认第一次出现 —— 不靠偏移,done 的全文经过边界过滤。
 * 还没流到的那一句先不画,等它上屏再落。
 */
function paintText(node: HTMLElement, text: string, revisions: readonly Revision[]): void {
  let at = 0;
  const hits = revisions
    .map((r) => ({ r, i: text.indexOf(r.original.trim()) }))
    .filter((h) => h.i >= 0)
    .sort((a, b) => a.i - b.i);
  for (const { r, i } of hits) {
    if (i < at) continue;
    const orig = r.original.trim();
    node.append(document.createTextNode(text.slice(at, i)));
    if (r.verdict === 'refuted') {
      const struck = document.createElement('s');
      struck.className = 'rv-orig';
      struck.textContent = orig;
      const fix = document.createElement('span');
      fix.className = 'rv-note';
      fix.textContent = `更正：${r.note}`;
      node.append(struck, fix);
    } else {
      node.append(document.createTextNode(orig));
      const mark = document.createElement('span');
      const ok = r.verdict === 'supported'; // 事后联网核实了的猜想
      mark.className = ok ? 'rv-mark rv-ok' : 'rv-mark';
      mark.textContent = ok ? '已核实' : '未核实';
      mark.title = r.source.startsWith('web:') ? `${r.note} · ${r.source.slice(4)}` : r.note;
      node.append(mark);
    }
    at = i + orig.length;
  }
  node.append(document.createTextNode(text.slice(at)));
}

export function createThread(): ThreadHandles {
  const root = document.createElement('div');
  root.className = 'thread';
  // 上一次画了几句。**只有比它多出来的才播进场** —— 这里每次都整组重画(流式时每来一个字就画一遍),
  // 旧的也跟着重放的话,每个字都会让整屏闪一次。第一次(载入历史)也不播:那不是「新来的」。
  let drawn = -1;

  function render(
    turns: readonly Turn[],
    lockstep: LockstepState,
    reason: LockstepReason,
  ): void {
    root.replaceChildren();

    turns.forEach((t, i) => {
      const node = document.createElement('div');
      node.className = 'turn';
      node.dataset['role'] = t.role === 'user' ? 'user' : 'agent';
      if (drawn >= 0 && i >= drawn) node.dataset['new'] = 'true';
      if (t.streaming && t.role !== 'user') node.dataset['streaming'] = 'true';

      if (t.text) paintText(node, t.text, t.revisions ?? []);
      if (t.pending) {
        const pending = document.createElement('span');
        pending.className = 'turn-pending';
        pending.textContent = t.pending;
        node.append(pending);
      }
      if (t.streaming) {
        const caret = document.createElement('span');
        caret.className = 'turn-caret';
        node.append(caret);
      }
      root.append(node);

      for (const a of t.attachments) {
        const box = document.createElement('div');
        box.className = 'attach';
        const thumb = document.createElement('div');
        thumb.className = 'attach-thumb';
        const text = document.createElement('div');
        const name = document.createElement('b');
        name.className = 'attach-name';
        name.textContent = a.name;
        const note = document.createElement('span');
        note.className = 'attach-note';
        note.textContent = a.note;
        text.append(name, note);
        box.append(thumb, text);
        root.append(box);
      }
    });
    drawn = turns.length;

    // 降级必须留痕。只在真脱钩时出现,平时不占位。
    if (lockstep === 'degraded') {
      const mark = document.createElement('div');
      mark.className = 'lockstep-mark';
      const why = reason && reason in REASON_TEXT ? REASON_TEXT[reason as Exclude<LockstepReason, ''>] : '';
      mark.textContent = why
        ? `声音跟不上了，文字改为直出 · ${why}`
        : '声音跟不上了，文字改为直出';
      root.append(mark);
    }

    root.scrollTop = root.scrollHeight;
  }

  return { root, render };
}
