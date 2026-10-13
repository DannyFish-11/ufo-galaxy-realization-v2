/**
 * 「没收口的结果」—— 「全部设置」最上面一段。
 *
 * 设备交回的结果要走四步才算写进了任务的真相(真相入账、对账、推进任务状态、
 * 唤醒等待方)。没走完时,后端已经**自动在后台补跑过一次**,只补失败的那几步
 * (所有者的决定:自动重试,失败再隔离)。补跑之后仍没收口的,才落到这里。
 *
 * 两件事要写在脸上:
 *
 * - **回答当时已经给出去了。** 这里不是「用户没拿到答案」的清单,是「系统的账
 *   对不上」的清单。措辞照这个写,不吓人,也不轻描淡写。
 * - **能不能再试,由后端说。** 原始消息太大时后端不留,那一条就不能再试 —— 按钮
 *   不画,而不是画一个注定失败的按钮。
 *
 * 一条都没有时整段不占地方:这是一个只在出事时才该出现的东西。拉不到时说拉不到,
 * 不说「一切正常」—— 那是两件事。
 *
 * 两类条目(`kind`):
 *
 * - `task_result` —— 设备交回的结果没走完上面那四步。
 * - `computer_use` —— 桌面操作「说做完了」,但另起一张屏幕、交给只看任务与屏幕的核对员,核对没通过
 *   (core/computer_use_verdict.py)。后台已经把没做完的部分再做过一次,仍不行才在这里。它的「再试一次」
 *   要几十秒,后端先回「在做」,卡片显示「正在再做一次」、不再画按钮,做完这一条自己更新。
 *
 * 三个动作,与运维面板的结案动作是同一处:「再试一次」= 重开、「认可」= 确认(人看过、认它做完了)、
 * 「知道了」= 驳回(判它没做成)。后两种记录都保留,只是不再列出来。
 */
import type { IsolatedResult } from '../transport';

/** 四步的中文名。后端的步骤名见 core/task_result_canonical_truth_chain.py 的 TRUTH_CHAIN_STEPS */
const STEP_TEXT: Record<string, string> = {
  truth_ingress: '真相入账',
  reconcile: '对账',
  authority_update: '推进任务状态',
  completion_linkage: '唤醒等待方',
};

/** 每类条目的称呼与「没成在哪」的说法 */
const KIND_TEXT: Record<string, string> = {
  task_result: '设备结果',
  computer_use: '桌面操作',
};

export interface IsolatedResultsCallbacks {
  onRetry(key: string): void;
  /** 认可:人看过了,它确实做完了 */
  onAccept(key: string): void;
  /** 知道了:判它没做成 */
  onDismiss(key: string): void;
}

export interface IsolatedResultsHandles {
  readonly root: HTMLElement;
  render(rows: readonly IsolatedResult[] | null, pendingRetry: number, busy: boolean, notice: string): void;
}

export function createIsolatedResults(cb: IsolatedResultsCallbacks): IsolatedResultsHandles {
  const root = document.createElement('section');
  root.className = 'sf-sec up-sec';

  const head = document.createElement('h3');
  head.className = 'sf-sec-head';
  const title = document.createElement('span');
  title.textContent = '没收口的结果';
  const count = document.createElement('b');
  head.append(title, count);

  const hint = document.createElement('p');
  hint.className = 'up-hint';
  hint.textContent =
    '回答当时已经交给你了；这里是结果没能核实的那几条 —— 设备交回的结果没写回任务记录，或桌面操作说做完了、对着屏幕核对没通过。后台已经自动补过一次，仍不行的才在这儿。';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  const list = document.createElement('div');
  list.className = 'up-list';

  root.append(head, hint, notice, list);

  function button(text: string, tip: string, busy: boolean, onClick: () => void): HTMLButtonElement {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'up-btn';
    b.textContent = text;
    b.title = tip;
    b.disabled = busy;
    b.addEventListener('click', onClick);
    return b;
  }

  /** 「没成在哪」那一行。设备结果说哪几步没走通;桌面操作说核对员看到了什么。 */
  function whatWentWrong(r: IsolatedResult): string {
    if (r.kind === 'computer_use') {
      const now = r.reason || '（后端没说核对员看到了什么）';
      const first = r.firstReason && r.firstReason !== r.reason ? ` · 第一次：${r.firstReason}` : '';
      return `说做完了，对着屏幕核对没通过：${now}${first}`;
    }
    const steps = r.failedSteps.map((s) => STEP_TEXT[s] ?? s).join('、') || '（后端没说是哪一步）';
    return r.deviceId ? `没走通：${steps} · 来自 ${r.deviceId}` : `没走通：${steps}`;
  }

  function card(r: IsolatedResult, busy: boolean): HTMLElement {
    const el = document.createElement('div');
    el.className = 'up-card';
    el.dataset['state'] = r.retrying ? 'retrying' : 'unverified';
    el.dataset['kind'] = r.kind;

    const top = document.createElement('div');
    top.className = 'up-top';
    const dot = document.createElement('span');
    dot.className = 'up-dot';
    const name = document.createElement('b');
    name.textContent = r.taskId || r.key;
    const kind = document.createElement('span');
    kind.className = 'up-kind';
    kind.textContent = KIND_TEXT[r.kind] ?? r.kind;
    const state = document.createElement('span');
    state.className = 'up-state';
    const tries = r.retrying ? `试了 ${r.attempts} 次 · 正在再做一次` : `试了 ${r.attempts} 次`;
    state.textContent = r.kind === 'task_result' && r.resultStatus ? `结果 ${r.resultStatus} · ${tries}` : tries;
    top.append(dot, name, kind, state);

    const meta = document.createElement('span');
    meta.className = 'up-meta';
    meta.textContent = whatWentWrong(r);

    const acts = document.createElement('div');
    acts.className = 'up-acts';
    if (r.retrying) {
      const why = document.createElement('span');
      why.className = 'up-nokey';
      why.textContent = '后台正在再做一次，做完这里会更新';
      acts.append(why);
    } else if (r.retryable) {
      const tip = r.kind === 'computer_use' ? '把没做完的部分交给桌面操作再做一次，做完再核对一次' : '只重跑没走通的那几步';
      acts.append(button('再试一次', tip, busy, () => cb.onRetry(r.key)));
    } else {
      const why = document.createElement('span');
      why.className = 'up-nokey';
      why.textContent = '原始结果太大没留存，不能再试';
      acts.append(why);
    }
    acts.append(
      button('认可', '我看过了，它确实做完了（记录保留）', busy || r.retrying, () => cb.onAccept(r.key)),
      button('知道了', '它没做成，我知道了（记录保留）', busy || r.retrying, () => cb.onDismiss(r.key)),
    );

    el.append(top, meta, acts);
    return el;
  }

  function render(rows: readonly IsolatedResult[] | null, pendingRetry: number, busy: boolean, text: string): void {
    notice.hidden = !text;
    notice.textContent = text;
    if (rows === null) {
      root.hidden = false;
      count.textContent = '';
      list.replaceChildren();
      const e = document.createElement('p');
      e.className = 'up-hint';
      e.textContent = '拉不到这份清单 —— 后端没接上，不是没有问题';
      list.append(e);
      return;
    }
    // 没有隔离项、也没有排队补跑的:整段不占位置(但刚操作完的那句话要留着给人看)。
    root.hidden = rows.length === 0 && pendingRetry === 0 && !text;
    count.textContent = pendingRetry ? `${rows.length} · 另有 ${pendingRetry} 条等补跑` : String(rows.length);
    list.replaceChildren(...rows.map((r) => card(r, busy)));
  }

  return { root, render };
}
