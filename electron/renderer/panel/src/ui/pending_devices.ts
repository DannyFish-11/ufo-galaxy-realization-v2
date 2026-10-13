/**
 * 「等你同意的设备」—— 「全部设置」最上面一段。
 *
 * 设备自己从 REST 来登记（`POST /api/v1/devices/register`），不带任何凭据。原先后端照单全收、直接写进设备表：
 * 同一局域网谁都能登记一台假设备、接到派过去的任务。所有者的决定是**在面板上确认**：后端只把它记成接入候选，
 * 这里点「接入」就是那一下确认，点「不接入」以后它再来登记也会被拒。
 *
 * 写在脸上的两件事：
 *
 * - **它是自己找上门来的。** 名字、类型都是那台设备自己报的 —— 只凭这些没法证明它是谁，所以要人看一眼。
 * - **点了之后的结论由后端说。** 没成就说没成（以及后端给的原因），不先把卡片抹掉。
 *
 * 一台都没有时整段不占地方；拉不到时说拉不到，不说「没有设备在等」—— 那是两件事。
 */
import type { PendingDevice } from '../transport';

export interface PendingDevicesCallbacks {
  onDecide(candidateId: string, accept: boolean): void;
}

export interface PendingDevicesHandles {
  readonly root: HTMLElement;
  render(rows: readonly PendingDevice[] | null, busy: boolean, notice: string): void;
}

/** 设备自己报的类型 → 人话。认不出的照原样显示 */
const TYPE_TEXT: Record<string, string> = {
  android: '安卓手机',
  ios: '苹果手机',
  wearos: '手表',
  windows: 'Windows 电脑',
  windows_laptop: '笔记本',
  windows_desktop: '电脑',
  linux: 'Linux 机器',
  macos: 'Mac',
};

function since(ts: number): string {
  if (!ts) return '';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return '刚刚来的';
  if (s < 3600) return `${Math.round(s / 60)} 分钟前来的`;
  if (s < 86400) return `${Math.round(s / 3600)} 小时前来的`;
  return `${Math.round(s / 86400)} 天前来的`;
}

export function createPendingDevices(cb: PendingDevicesCallbacks): PendingDevicesHandles {
  const root = document.createElement('section');
  root.className = 'sf-sec up-sec';
  root.hidden = true;

  const head = document.createElement('h3');
  head.className = 'sf-sec-head';
  const title = document.createElement('span');
  title.textContent = '等你同意的设备';
  const count = document.createElement('b');
  head.append(title, count);

  const hint = document.createElement('p');
  hint.className = 'up-hint';
  hint.textContent =
    '这些设备自己找上门来登记，没带任何凭据。名字和类型是它自己报的 —— 认得就点「接入」，不认得就点「不接入」，以后它再来也会被拒。';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  const list = document.createElement('div');
  list.className = 'up-list';

  root.append(head, hint, notice, list);

  function card(d: PendingDevice, busy: boolean): HTMLElement {
    const el = document.createElement('div');
    el.className = 'up-card';
    el.dataset['state'] = 'unverified';

    const top = document.createElement('div');
    top.className = 'up-top';
    const dot = document.createElement('span');
    dot.className = 'up-dot';
    const name = document.createElement('b');
    name.textContent = d.name || d.deviceId;
    const state = document.createElement('span');
    state.className = 'up-state';
    state.textContent = [TYPE_TEXT[d.deviceType] ?? d.deviceType, since(d.firstSeen)].filter(Boolean).join(' · ');
    top.append(dot, name, state);

    const meta = document.createElement('span');
    meta.className = 'up-meta';
    const where = d.address ? ` · 从 ${d.address}` : '';
    meta.textContent = d.error ? `设备号 ${d.deviceId}${where} · 上次没接成：${d.error}` : `设备号 ${d.deviceId}${where}`;

    const acts = document.createElement('div');
    acts.className = 'up-acts';
    const accept = document.createElement('button');
    accept.type = 'button';
    accept.className = 'up-btn';
    accept.textContent = '接入';
    accept.disabled = busy;
    accept.addEventListener('click', () => cb.onDecide(d.candidateId, true));
    const refuse = document.createElement('button');
    refuse.type = 'button';
    refuse.className = 'up-btn';
    refuse.textContent = '不接入';
    refuse.disabled = busy;
    refuse.addEventListener('click', () => cb.onDecide(d.candidateId, false));
    acts.append(accept, refuse);

    el.append(top, meta, acts);
    return el;
  }

  function render(rows: readonly PendingDevice[] | null, busy: boolean, text: string): void {
    notice.hidden = !text;
    notice.textContent = text;
    if (rows === null) {
      // 拉不到:只在刚操作过(有话要说)时露出来 —— 开机拉一次没拉到,不该凭空多出一段「后端没接上」。
      root.hidden = !text;
      count.textContent = '';
      list.replaceChildren();
      return;
    }
    root.hidden = rows.length === 0 && !text;
    count.textContent = String(rows.length);
    list.replaceChildren(...rows.map((d) => card(d, busy)));
  }

  return { root, render };
}
