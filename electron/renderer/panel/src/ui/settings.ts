/**
 * 全部设置 —— 那 332 个键的细调面。
 *
 * ## 它和设置浮层里那四档的分工
 *
 * 浮层里是**整档开关**:一个开关管一整片键,回答「这项能力开不开」。这里是
 * **细调**:一个键一行,回答「具体调到多少」。人绝大多数时候只需要前者;来到
 * 这一页,说明他要改的是档位表达不了的那种东西。
 *
 * 所以这一页**不重复档位** —— 档位管的那些键照样在各自分类里列着,但这一页
 * 不再摆一遍四个大开关。同一个事实两处各存一份,迟早一处说开另一处说关。
 *
 * ## 分组不在这里定义
 *
 * 每个键属于哪一类由后端 `/api/config/all` 的 `category` **现算**;
 * `settings_inventory.ts` 里那份 `KEY_ORDER_HINT` 只是同类内的**顺序提示**,
 * 未列到的按字母序跟在后面。
 *
 * 这条区分是这个仓库栽过一次的地方:从前分组写在前端一份手写清单里,漏一个键
 * 的后果是最坏那种 —— **它在设置页上完全看不见,后端却明明有它,还不报错**。
 * 改成现算之后,最坏情况从「新键看不见」变成「新键排在最后」。
 *
 * ## 控件按 type 决定,不按名字猜
 *
 * boolean 给推拉开关(与浮层里那四档同一个 `.knob`,全面板只有一种开关);
 * select 给一排可点的档位牌;其余给输入框。**名字里带 KEY / TOKEN / SECRET 的
 * 用密码框**,并且永远不把已有值回填到 DOM 里 —— 那等于把密钥又摊开一次。
 */
import type { ConfigItem } from '../transport';
import { CATEGORIES, KEY_ORDER_HINT } from '../settings_inventory';

/** 哪些键的值不该以明文出现在界面上。 */
const SECRET_RE = /(_KEY|_TOKEN|_SECRET|PASSWORD|_CREDENTIAL)$/;

function isSecret(item: ConfigItem): boolean {
  return item.type === 'password' || SECRET_RE.test(item.key);
}

/**
 * 按后端给的 category 分组,同类内按顺序提示排,未列到的按字母序跟在后面。
 *
 * 返回的顺序以 `CATEGORIES` 为准;出现了 CATEGORIES 里没有的类别时**不丢掉**,
 * 追加在最后 —— 丢掉就等于那一整类键在设置页上消失了。
 */
export function groupByCategory(
  items: readonly ConfigItem[],
): ReadonlyArray<{ key: string; label: string; icon: string; items: ConfigItem[] }> {
  const buckets = new Map<string, ConfigItem[]>();
  for (const it of items) {
    const list = buckets.get(it.category);
    if (list) list.push(it);
    else buckets.set(it.category, [it]);
  }

  for (const [cat, list] of buckets) {
    const hint = KEY_ORDER_HINT[cat] ?? [];
    const rank = new Map(hint.map((k, i) => [k, i]));
    list.sort((a, b) => {
      const ra = rank.get(a.key) ?? Number.MAX_SAFE_INTEGER;
      const rb = rank.get(b.key) ?? Number.MAX_SAFE_INTEGER;
      return ra !== rb ? ra - rb : a.key.localeCompare(b.key);
    });
  }

  const out: Array<{ key: string; label: string; icon: string; items: ConfigItem[] }> = [];
  for (const c of CATEGORIES) {
    const list = buckets.get(c.key);
    if (list && list.length) {
      out.push({ key: c.key, label: c.label, icon: c.icon, items: list });
      buckets.delete(c.key);
    }
  }
  // 剩下的是 CATEGORIES 里没声明的类别。**不丢** —— 丢了那一整类就没人看得见。
  for (const [cat, list] of buckets) {
    out.push({ key: cat, label: `${cat}（未分类）`, icon: '·', items: list });
  }
  return out;
}

export interface SettingsHandles {
  readonly root: HTMLElement;
  render(items: readonly ConfigItem[] | null, open: boolean, busy: boolean): void;
}

export interface SettingsCallbacks {
  onClose(): void;
  /** 攒够一批一起写 —— 一个键一次请求的话,改十个键就是十次落盘。 */
  onSave(changes: Readonly<Record<string, string>>): void;
}

export function createSettings(cb: SettingsCallbacks): SettingsHandles {
  const root = document.createElement('div');
  root.className = 'settings-full';
  root.dataset['open'] = 'false';

  const head = document.createElement('div');
  head.className = 'sf-head';
  const title = document.createElement('span');
  title.className = 'sf-title';
  title.textContent = '全部设置';
  const count = document.createElement('span');
  count.className = 'sf-count';
  const save = document.createElement('button');
  save.className = 'sf-save';
  save.type = 'button';
  save.textContent = '保存';
  save.disabled = true;
  const close = document.createElement('button');
  close.className = 'sf-close';
  close.type = 'button';
  close.setAttribute('aria-label', '关闭');
  head.append(title, count, save, close);

  const body = document.createElement('div');
  body.className = 'sf-body';
  root.append(head, body);

  /** 尚未写回的改动。键 → 新值。 */
  let pending: Record<string, string> = {};

  function markDirty(): void {
    const n = Object.keys(pending).length;
    save.disabled = n === 0;
    save.textContent = n === 0 ? '保存' : `保存 ${n} 项`;
  }

  function stage(key: string, value: string, original: string): void {
    if (value === original) delete pending[key];
    else pending[key] = value;
    markDirty();
  }

  close.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onClose();
  });
  save.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!Object.keys(pending).length) return;
    cb.onSave({ ...pending });
  });
  // 这一片自己吃掉点击 —— 否则 document 上那个「点别处收起」会把它关掉。
  root.addEventListener('click', (e) => e.stopPropagation());

  function control(item: ConfigItem): HTMLElement {
    if (item.type === 'boolean') {
      const btn = document.createElement('button');
      btn.className = 'bundle';
      btn.type = 'button';
      let on = item.value === 'true';
      btn.setAttribute('aria-pressed', String(on));
      const knob = document.createElement('span');
      knob.className = 'knob';
      btn.append(knob);
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        on = !on;
        btn.setAttribute('aria-pressed', String(on));
        stage(item.key, String(on), item.value);
      });
      return btn;
    }

    if (item.options && item.options.length) {
      // 一排可点的档位牌。**不用下拉** —— 下拉把「有几档」藏起来了,而档数正是
      // 这类键最该让人一眼看见的东西(GALAXY_AUTONOMY 三档、档位四档)。
      const row = document.createElement('span');
      row.className = 'sf-stages';
      let picked = item.value;
      for (const opt of item.options) {
        const chip = document.createElement('button');
        chip.className = 'stage';
        chip.type = 'button';
        // 空串是一个真选项(「不钉死」),但它画不出字 —— 给它一个说得出口的名字。
        chip.textContent = opt === '' ? '自动' : opt;
        chip.dataset['picked'] = String(opt === picked);
        chip.addEventListener('click', (e) => {
          e.stopPropagation();
          picked = opt;
          for (const sib of row.children) {
            (sib as HTMLElement).dataset['picked'] = String(
              (sib as HTMLElement).textContent === (opt === '' ? '自动' : opt),
            );
          }
          stage(item.key, opt, item.value);
        });
        row.append(chip);
      }
      return row;
    }

    const input = document.createElement('input');
    input.className = 'sf-input';
    if (isSecret(item)) {
      input.type = 'password';
      // **不回填已有值。** 把密钥重新摊到 DOM 上没有任何好处 —— 想看的人本来
      // 就看得到,不想泄露的场合(录屏、截图、远程桌面)它会跟着一起走。
      input.value = '';
      input.placeholder = item.value ? '已配置（留空=不改）' : '未配置';
    } else {
      input.type = item.type === 'number' ? 'number' : 'text';
      input.value = item.value;
      input.placeholder = item.defaultValue ? `默认 ${item.defaultValue}` : '';
    }
    input.addEventListener('input', () => {
      if (isSecret(item) && input.value === '') {
        delete pending[item.key];
        markDirty();
        return;
      }
      stage(item.key, input.value, item.value);
    });
    input.addEventListener('click', (e) => e.stopPropagation());
    return input;
  }

  function row(item: ConfigItem): HTMLElement {
    const r = document.createElement('div');
    r.className = 'sf-row';
    if (item.overridden) r.dataset['overridden'] = 'true';

    const text = document.createElement('span');
    text.className = 'sf-text';
    const name = document.createElement('code');
    name.className = 'sf-key';
    name.textContent = item.key;
    const desc = document.createElement('span');
    desc.className = 'sf-desc';
    // 改过默认的**说出来**。只显示当前值的话,「这是默认」和「有人改过」看不出
    // 区别 —— 而排障时那正是第一个要问的问题。
    desc.textContent = item.overridden
      ? `${item.description}（已改过，默认 ${item.defaultValue || '空'}）`
      : item.description;
    text.append(name, desc);

    r.append(text, control(item));
    return r;
  }

  function render(items: readonly ConfigItem[] | null, open: boolean, busy: boolean): void {
    root.dataset['open'] = String(open);
    root.dataset['busy'] = String(busy);
    if (!open) return;

    // 拿到后端新返回的一批值,就意味着上一批待写的已经落地(或者被拒了、后端给回
    // 了它自己认下的值)。两种情况下队列都该归零 —— 留着的话,界面显示的是后端的
    // 值、待写的却还是旧那份,再点一次保存就把旧值又写回去了。
    pending = {};
    markDirty();

    if (items === null) {
      // **说清楚是「没拉到」而不是「一个键都没有」。** 空白页会让人以为
      // 这台机器真的没有可配的东西。
      body.replaceChildren();
      const empty = document.createElement('div');
      empty.className = 'sf-empty';
      empty.textContent = '拉不到配置 —— 后端没接上，不是没有可配的东西';
      body.append(empty);
      count.textContent = '';
      return;
    }

    const groups = groupByCategory(items);
    const changed = items.filter((i) => i.overridden).length;
    count.textContent = changed
      ? `${items.length} 项 · ${changed} 项改过默认`
      : `${items.length} 项`;

    body.replaceChildren();
    for (const g of groups) {
      const sec = document.createElement('section');
      sec.className = 'sf-sec';
      const h = document.createElement('h3');
      h.className = 'sf-sec-head';
      h.textContent = `${g.icon} ${g.label}`;
      const n = document.createElement('b');
      n.textContent = String(g.items.length);
      h.append(n);
      sec.append(h);
      for (const item of g.items) sec.append(row(item));
      body.append(sec);
    }
  }

  return {
    root,
    render,
  };
}
