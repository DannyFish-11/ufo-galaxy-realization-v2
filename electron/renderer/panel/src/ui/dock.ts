/**
 * 底下那条:左边一个 + 收文件和图片,右下角是设置。
 *
 * 两端分工:**左边是往里喂东西,右边是调这台机器。**
 *
 * 设置里放的是**整档开关** —— 一个开关管一整片配置键,不是一个键。
 * 全模态不该是四个模态各自一个勾,跨设备也不该让人分别去开发现、联邦、
 * 主脑、安卓通道。散键退到「全部设置」里当细调。
 *
 * 一条规矩写在这里,因为它是这个设计能不能成立的关键:
 * **档位是唯一定义处。** 有键被手动改得偏离了这一档时,档位必须显示成
 * 「开 · 有偏离」而不是「开」—— 否则档位说开、底下某个键说关,就是同一个
 * 事实两处各存一份,而且没人看得见。
 */
import type { Bundle } from '../types';
import { platform } from '../platform';

const ICONS = {
  plus: 'M12 5v14M5 12h14',
  send: 'M12 19V5M5 12l7-7 7 7',
} as const;

function icon(path: string, size = 17, width = 1.7): SVGSVGElement {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', String(width));
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  const p = document.createElementNS(ns, 'path');
  p.setAttribute('d', path);
  svg.append(p);
  return svg;
}

function gearIcon(): SVGSVGElement {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', '17');
  svg.setAttribute('height', '17');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.5');
  svg.setAttribute('stroke-linecap', 'round');
  const c = document.createElementNS(ns, 'circle');
  c.setAttribute('cx', '12'); c.setAttribute('cy', '12'); c.setAttribute('r', '3');
  const p = document.createElementNS(ns, 'path');
  p.setAttribute('d', 'M12 2.4v2m0 15.2v2M5 5l1.4 1.4m11.2 11.2L19 19M2.4 12h2m15.2 0h2M5 19l1.4-1.4M17.6 6.4 19 5');
  svg.append(c, p);
  return svg;
}

export interface DockHandles {
  readonly root: HTMLElement;
  render(bundles: readonly Bundle[], popover: 'feed' | 'settings' | null): void;
}

export interface DockCallbacks {
  onSend(text: string): void;
  onTogglePopover(which: 'feed' | 'settings'): void;
  onToggleBundle(key: Bundle['key']): void;
}

export function createDock(cb: DockCallbacks): DockHandles {
  const wrap = document.createElement('div');
  wrap.style.position = 'relative';

  const dock = document.createElement('div');
  dock.className = 'dock';

  const plus = document.createElement('button');
  plus.className = 'round';
  plus.type = 'button';
  plus.dataset['kind'] = 'plus';
  plus.setAttribute('aria-label', '添加文件、图片');
  plus.append(icon(ICONS.plus));
  plus.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onTogglePopover('feed');
  });

  const field = document.createElement('div');
  field.className = 'field';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = '说点什么，或者直接说话';
  const send = document.createElement('button');
  send.className = 'send';
  send.type = 'button';
  send.setAttribute('aria-label', '发送');
  send.append(icon(ICONS.send, 15, 2));
  field.append(input, send);

  function submit(): void {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    cb.onSend(text);
  }
  send.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) submit();
  });

  const gear = document.createElement('button');
  gear.className = 'round';
  gear.type = 'button';
  gear.dataset['kind'] = 'gear';
  gear.setAttribute('aria-label', '设置');
  gear.append(gearIcon());
  gear.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onTogglePopover('settings');
  });

  dock.append(plus, field, gear);

  // 左边:往里喂东西
  const feed = document.createElement('div');
  feed.className = 'pop';
  feed.dataset['side'] = 'left';
  for (const [label, accept] of [
    ['图片', 'image/*'],
    ['文件', '*/*'],
    ['圈一块屏幕', ''],
    ['网页链接', ''],
  ] as const) {
    const item = document.createElement('button');
    item.className = 'pop-item';
    item.type = 'button';
    item.textContent = label;
    if (accept) {
      item.addEventListener('click', () => void platform().pickFiles(accept));
    }
    feed.append(item);
  }

  // 右边:调这台机器
  const settings = document.createElement('div');
  settings.className = 'pop';
  settings.dataset['side'] = 'right';
  const bundleHost = document.createElement('div');
  const more = document.createElement('button');
  more.className = 'pop-item pop-more';
  more.type = 'button';
  more.textContent = '全部设置';
  settings.append(bundleHost, more);

  wrap.append(dock, feed, settings);

  function render(bundles: readonly Bundle[], popover: 'feed' | 'settings' | null): void {
    feed.dataset['open'] = String(popover === 'feed');
    settings.dataset['open'] = String(popover === 'settings');
    plus.setAttribute('aria-expanded', String(popover === 'feed'));
    gear.setAttribute('aria-expanded', String(popover === 'settings'));

    bundleHost.replaceChildren();
    for (const b of bundles) {
      const row = document.createElement('button');
      row.className = 'bundle';
      row.type = 'button';
      // **不是所有档都是两态的。** GALAXY_AUTONOMY 是 safe / guided / autonomous
      // 三档,压成 aria-pressed 的真假会把中间那档吞掉 —— 这个仓库为「三态被当成
      // 布尔」栽过一次。两态的用 aria-pressed,多态的用 data-state 出档位名。
      const twoState = b.type === 'boolean';
      const on = b.value === 'true';
      if (b.unwired) {
        row.dataset['unwired'] = 'true';
        row.disabled = true;
      } else if (twoState) {
        row.setAttribute('aria-pressed', String(on));
      } else {
        row.dataset['state'] = b.value;
        row.setAttribute('aria-label', `${b.name}:${b.value}`);
      }
      const text = document.createElement('span');
      const name = document.createElement('span');
      name.className = 'bundle-name';
      name.textContent = b.name;
      const note = document.createElement('span');
      note.className = 'bundle-note';
      // 有偏离就说出来。只显示"开"等于把不一致藏起来。
      note.textContent = b.unwired
        ? `${b.note} · 没接上(主键 ${b.primary || '未知'} 不存在)`
        : b.overrides > 0
          ? `${b.note} · 有 ${b.overrides} 项手改过`
          : `${b.note} · 管 ${b.keyCount} 个键`;
      if (b.overrides > 0) note.dataset['drift'] = 'true';
      if (b.unwired) note.dataset['unwired'] = 'true';
      text.append(name, note);

      // 两态给推拉开关;多态给一枚写着当前档位的小牌子 —— 一个开关表达不了三档。
      const control = document.createElement('span');
      if (twoState || b.unwired) {
        control.className = 'knob';
      } else {
        control.className = 'stage';
        control.textContent = b.value;
      }
      row.append(text, control);
      row.addEventListener('click', (e) => {
        e.stopPropagation();
        cb.onToggleBundle(b.key);
      });
      bundleHost.append(row);
    }
  }

  return { root: wrap, render };
}
