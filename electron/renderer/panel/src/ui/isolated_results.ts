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
 */
import type { IsolatedResult } from '../transport';

/** 四步的中文名。后端的步骤名见 core/task_result_canonical_truth_chain.py 的 TRUTH_CHAIN_STEPS */
const STEP_TEXT: Record<string, string> = {
  truth_ingress: '真相入账',
  reconcile: '对账',
  authority_update: '推进任务状态',
  completion_linkage: '唤醒等待方',
};

export interface IsolatedResultsCallbacks {
  onRetry(key: string): void;
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
    '回答当时已经交给你了；这里是结果没能完整写回任务记录的那几条。后台已经自动补过一次，仍没补上的才在这儿。';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  const list = document.createElement('div');
  list.className = 'up-list';

  root.append(head, hint, notice, list);

  function card(r: IsolatedResult, busy: boolean): HTMLElement {
    const el = document.createElement('div');
    el.className = 'up-card';
    el.dataset['state'] = 'unverified';

    const top = document.createElement('div');
    top.className = 'up-top';
    const dot = document.createElement('span');
    dot.className = 'up-dot';
    const name = document.createElement('b');
    name.textContent = r.taskId || r.key;
    const state = document.createElement('span');
    state.className = 'up-state';
    state.textContent = r.resultStatus ? `结果 ${r.resultStatus} · 试了 ${r.attempts} 次` : `试了 ${r.attempts} 次`;
    top.append(dot, name, state);

    const meta = document.createElement('span');
    meta.className = 'up-meta';
    const steps = r.failedSteps.map((s) => STEP_TEXT[s] ?? s).join('、') || '（后端没说是哪一步）';
    meta.textContent = r.deviceId ? `没走通：${steps} · 来自 ${r.deviceId}` : `没走通：${steps}`;

    const acts = document.createElement('div');
    acts.className = 'up-acts';
    if (r.retryable) {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'up-btn';
      retry.textContent = '再试一次';
      retry.disabled = busy;
      retry.addEventListener('click', () => cb.onRetry(r.key));
      acts.append(retry);
    } else {
      const why = document.createElement('span');
      why.className = 'up-nokey';
      why.textContent = '原始结果太大没留存，不能再试';
      acts.append(why);
    }
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'up-btn';
    dismiss.textContent = '知道了';
    dismiss.disabled = busy;
    dismiss.addEventListener('click', () => cb.onDismiss(r.key));
    acts.append(dismiss);

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
