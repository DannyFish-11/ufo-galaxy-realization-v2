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
import type { LockstepReason, LockstepState, Turn } from '../types';

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

export function createThread(): ThreadHandles {
  const root = document.createElement('div');
  root.className = 'thread';

  function render(
    turns: readonly Turn[],
    lockstep: LockstepState,
    reason: LockstepReason,
  ): void {
    root.replaceChildren();

    for (const t of turns) {
      const node = document.createElement('div');
      node.className = 'turn';
      node.dataset['role'] = t.role === 'user' ? 'user' : 'agent';

      if (t.text) node.append(document.createTextNode(t.text));
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
    }

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
