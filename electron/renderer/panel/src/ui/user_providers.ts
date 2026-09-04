/**
 * 「我的模型服务」—— 不改仓库就能加一家。
 *
 * ## 这一段和上面那 335 个键的分工
 *
 * 上面是**键值**:一个键一行,回答"这个开关调到多少"。这里是**对象**:一条端点
 * 有地址、协议、密钥、型号表、以及"它到底通不通"。塞不进键值那套里 —— 硬塞的
 * 结果是四五个键之间有隐含关系,而键值界面表达不了关系。
 *
 * ## 状态是三件事,不准画成两件
 *
 * · live       两步都过,型号表是**网关自己报的**
 * · declared   网关不开放 /models(有意的也常见),型号是**人手填的**,但试调过了
 * · unverified 没过 —— 并且必须说出**卡在哪一步**
 *
 * 把 live 和 declared 画成同一个绿点,就等于告诉用户"这份型号表是网关认的",
 * 而实际上那是他自己敲进去的。哪天敲错一个字,他会以为是系统坏了。
 *
 * ## 为什么每张卡片都带「重新验证」
 *
 * 验证结论是**某一刻**的快照:Key 会过期,网关会挂,型号会下线。没有这个按钮,
 * 用户唯一能做的就是"改点什么再存一次"来逼它重验 —— 那会顺手改坏别的东西。
 */
import type { UserProvider } from '../transport';

export interface UserProviderDraft {
  id: string;
  label: string;
  base_url: string;
  protocol: string;
  models: readonly string[];
  api_key?: string;
}

export interface UserProviderCallbacks {
  onSave(draft: UserProviderDraft): void;
  onVerify(id: string): void;
  onDelete(id: string): void;
}

export interface UserProviderHandles {
  readonly root: HTMLElement;
  render(rows: readonly UserProvider[] | null, busy: boolean, notice: string): void;
  /**
   * 清空新增表单。存成功之后由调用方来调。
   *
   * 不清的话:卡片列表里已经有 my-gw 了,下面表单还留着同一份 —— 人会以为没存上,
   * 再点一次「加进来」,而那一次会把刚才存好的**覆盖掉**(同 id 是更新语义),
   * 并且因为密码框里还是原来那串,覆盖得悄无声息。
   *
   * 失败时**不清** —— 那时表单里是他刚填的东西,清掉等于让他重打一遍。
   */
  clearForm(): void;
}

const STATE_TEXT: Record<string, string> = {
  live: '通了',
  declared: '通了（型号是你自己填的）',
  unverified: '没验过',
};

function ago(ts: number | null): string {
  if (!ts) return '还没验证过';
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s} 秒前验过`;
  if (s < 3600) return `${Math.round(s / 60)} 分钟前验过`;
  if (s < 86400) return `${Math.round(s / 3600)} 小时前验过`;
  return `${Math.round(s / 86400)} 天前验过`;
}

export function createUserProviders(cb: UserProviderCallbacks): UserProviderHandles {
  const root = document.createElement('section');
  root.className = 'sf-sec up-sec';

  const head = document.createElement('h3');
  head.className = 'sf-sec-head';
  head.textContent = '🔌 我的模型服务';
  const n = document.createElement('b');
  head.append(n);

  const hint = document.createElement('p');
  hint.className = 'up-hint';
  hint.textContent =
    '任何 OpenAI 兼容的地址都能加进来（one-api / new-api / 自建 vLLM / 公司内网网关）。加完会真发一次一个 token 的试调 —— 通了才让它参与选路。';

  const list = document.createElement('div');
  list.className = 'up-list';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  // ── 新增表单 ──────────────────────────────────────────────────────────────
  const form = document.createElement('div');
  form.className = 'up-form';

  function field(placeholder: string, type = 'text'): HTMLInputElement {
    const i = document.createElement('input');
    i.className = 'sf-input';
    i.type = type;
    i.placeholder = placeholder;
    i.addEventListener('click', (e) => e.stopPropagation());
    return i;
  }

  const fId = field('短名字，如 my-gw（小写字母数字-_）');
  const fLabel = field('显示名，如 公司内网网关');
  const fUrl = field('https://…/v1');
  const fKey = field('API Key（没有鉴权就留空）', 'password');
  const fModels = field('型号，逗号隔开。留空=让网关自己报');
  const add = document.createElement('button');
  add.className = 'sf-save';
  add.type = 'button';
  add.textContent = '加进来';

  add.addEventListener('click', (e) => {
    e.stopPropagation();
    const models = fModels.value
      .split(',')
      .map((m) => m.trim())
      .filter(Boolean);
    cb.onSave({
      id: fId.value.trim(),
      label: fLabel.value.trim() || fId.value.trim(),
      base_url: fUrl.value.trim(),
      protocol: 'openai',
      models,
      // 空串表示「不改」,新增时也一样 —— 无鉴权的自建服务就是没有 Key。
      ...(fKey.value ? { api_key: fKey.value } : {}),
    });
  });

  form.append(fId, fLabel, fUrl, fKey, fModels, add);
  root.append(head, hint, notice, list, form);
  root.addEventListener('click', (e) => e.stopPropagation());

  function card(p: UserProvider): HTMLElement {
    const el = document.createElement('div');
    el.className = 'up-card';
    el.dataset['state'] = p.state;

    const top = document.createElement('div');
    top.className = 'up-top';
    const name = document.createElement('b');
    name.textContent = p.label || p.id;
    const dot = document.createElement('span');
    dot.className = 'up-dot';
    const state = document.createElement('span');
    state.className = 'up-state';
    state.textContent = STATE_TEXT[p.state] ?? p.state;
    top.append(dot, name, state);

    const addr = document.createElement('code');
    addr.className = 'up-addr';
    addr.textContent = p.base_url;

    const meta = document.createElement('span');
    meta.className = 'up-meta';
    if (p.state === 'unverified') {
      // 没过的时候,**卡在哪一步**比什么都重要 —— 这就是用户要拿去排查的那句话。
      meta.textContent = p.state_reason || '还没验证过';
    } else {
      const src = p.discovered_models.length ? '网关报的' : '你自己填的';
      meta.textContent = `${p.models.length} 个型号（${src}）· ${ago(p.verified_at)}`;
    }

    const models = document.createElement('div');
    models.className = 'up-models';
    for (const m of p.models.slice(0, 8)) {
      const chip = document.createElement('code');
      chip.textContent = m;
      models.append(chip);
    }
    if (p.models.length > 8) {
      const more = document.createElement('span');
      more.className = 'up-more';
      more.textContent = `还有 ${p.models.length - 8} 个`;
      models.append(more);
    }

    const acts = document.createElement('div');
    acts.className = 'up-acts';
    const reverify = document.createElement('button');
    reverify.className = 'up-btn';
    reverify.type = 'button';
    reverify.textContent = '重新验证';
    reverify.addEventListener('click', (e) => {
      e.stopPropagation();
      cb.onVerify(p.id);
    });
    const del = document.createElement('button');
    del.className = 'up-btn up-danger';
    del.type = 'button';
    del.textContent = '删除';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      cb.onDelete(p.id);
    });
    if (!p.has_key) {
      const nokey = document.createElement('span');
      nokey.className = 'up-nokey';
      nokey.textContent = '没填 Key';
      acts.append(nokey);
    }
    acts.append(reverify, del);

    el.append(top, addr, meta, models, acts);
    return el;
  }

  function render(rows: readonly UserProvider[] | null, busy: boolean, msg: string): void {
    root.dataset['busy'] = String(busy);
    notice.hidden = !msg;
    notice.textContent = msg;

    list.replaceChildren();
    if (rows === null) {
      // 「没拉到」不是「一条都没有」。空白会让人以为自己加的端点丢了。
      const e = document.createElement('div');
      e.className = 'sf-empty';
      e.textContent = '拉不到已加的服务 —— 后端没接上，不是你没加过';
      list.append(e);
      n.textContent = '';
      return;
    }
    n.textContent = String(rows.length);
    if (!rows.length) {
      const e = document.createElement('div');
      e.className = 'sf-empty';
      e.textContent = '还没加过。下面填一个地址就行 —— 不用改代码，也不用重启。';
      list.append(e);
      return;
    }
    for (const p of rows) list.append(card(p));
  }

  function clearForm(): void {
    for (const i of [fId, fLabel, fUrl, fKey, fModels]) i.value = '';
  }

  return { root, render, clearForm };
}
