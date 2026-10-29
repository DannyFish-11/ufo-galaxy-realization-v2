/**
 * 「等你批准」—— 对话区下面、输入条上面，只在有操作等人点头时出现。
 *
 * 所有者的决定（docs/GROUNDED_AGENT_DESIGN.md §0）：电脑这边发起、要人点头的操作在电脑面板上批；
 * 批一次默认记「同一个动作 + 同一个对象」到这段对话结束；「一直允许」要人明确选，之后在面板上能撤。
 * 所以主键就是「批准」（= 本会话），旁边两个次要的：「只这一次」「一直允许」，最后是「不要」。
 *
 * 写在脸上的两件事：
 *
 * - **点了才执行，不点不执行。** 智能体那一轮正等着这一条时会写还剩多久；超时就当没批。
 * - **结论由后端说。** 没成（多半是已经超时）就照实说，不先把卡片抹掉。
 *
 * 一条都没有时整段不占地方。拉不到时只在刚操作过（有话要说）时露出来。
 */
import type { ApprovalScope, PendingApproval } from '../transport';

export interface PendingApprovalsCallbacks {
  onDecide(requestId: string, approve: boolean, scope: ApprovalScope): void;
}

export interface PendingApprovalsHandles {
  readonly root: HTMLElement;
  render(rows: readonly PendingApproval[] | null, busy: boolean, notice: string): void;
}

/** 风险等级 → 人话 */
const RISK_TEXT: Record<string, string> = {
  critical: '高风险',
  high: '会改动东西',
  medium: '要你点头',
  low: '要你点头',
};

/** 谁在等、最多等多久。不画倒计时：卡片只在清单变了时重画，倒计时会停在某个数上，比不写更误导。 */
function left(a: PendingApproval): string {
  if (!a.waiting) return '排着队，批了之后重试就会执行';
  return a.waitS === null ? '它在等你' : `它在等你（最多等 ${Math.round(a.waitS)} 秒）`;
}

export function createPendingApprovals(cb: PendingApprovalsCallbacks): PendingApprovalsHandles {
  const root = document.createElement('section');
  root.className = 'approvals';
  root.hidden = true;
  root.setAttribute('aria-live', 'polite');

  const head = document.createElement('div');
  head.className = 'ap-head';
  head.textContent = '等你批准';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  const list = document.createElement('div');
  list.className = 'up-list';

  root.append(head, notice, list);

  function card(a: PendingApproval, busy: boolean): HTMLElement {
    const el = document.createElement('div');
    el.className = 'up-card';
    el.dataset['state'] = 'unverified';

    const top = document.createElement('div');
    top.className = 'up-top';
    const dot = document.createElement('span');
    dot.className = 'up-dot';
    const what = document.createElement('b');
    what.textContent = a.what;
    const state = document.createElement('span');
    state.className = 'up-state';
    state.textContent = [RISK_TEXT[a.risk] ?? a.risk, left(a)].filter(Boolean).join(' · ');
    top.append(dot, what, state);
    el.append(top);

    if (a.target && !a.what.includes(a.target)) {
      const meta = document.createElement('span');
      meta.className = 'up-meta';
      meta.textContent = `对象：${a.target}`;
      el.append(meta);
    }

    const acts = document.createElement('div');
    acts.className = 'up-acts';
    const btn = (text: string, approve: boolean, scope: ApprovalScope, cls = ''): HTMLButtonElement => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `up-btn ${cls}`.trim();
      b.textContent = text;
      b.disabled = busy;
      b.addEventListener('click', () => cb.onDecide(a.requestId, approve, scope));
      return b;
    };
    acts.append(
      btn('批准', true, 'session', 'ap-primary'),
      btn('只这一次', true, 'once'),
      btn('一直允许', true, 'always'),
      btn('不要', false, 'once', 'up-danger'),
    );
    el.append(acts);
    return el;
  }

  function render(rows: readonly PendingApproval[] | null, busy: boolean, text: string): void {
    notice.hidden = !text;
    notice.textContent = text;
    if (rows === null) {
      root.hidden = !text;
      list.replaceChildren();
      return;
    }
    root.hidden = rows.length === 0 && !text;
    list.replaceChildren(...rows.map((a) => card(a, busy)));
  }

  return { root, render };
}
