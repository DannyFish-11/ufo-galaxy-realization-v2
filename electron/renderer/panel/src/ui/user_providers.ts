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
  /** 把这条填回表单去改。密钥不回填 —— 留空表示不改。 */
  onEdit(row: UserProvider): void;
  onVerify(id: string): void;
  onDelete(id: string): void;
}

export interface UserProviderHandles {
  readonly root: HTMLElement;
  render(
    rows: readonly UserProvider[] | null,
    protocols: readonly string[],
    busy: boolean,
    notice: string,
  ): void;
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
  /** 把一条端点填回表单（供「编辑」用）。 */
  fillForm(row: UserProvider): void;
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
  head.textContent = '我的模型服务';
  const n = document.createElement('b');
  head.append(n);

  const hint = document.createElement('p');
  hint.className = 'up-hint';
  hint.textContent =
    '任何 OpenAI 兼容的地址都能加进来（one-api / new-api / 自建 vLLM / 自定义网关）。加完会真发一次一个 token 的试调 —— 通了才让它参与选路。';

  const list = document.createElement('div');
  list.className = 'up-list';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  // ── 新增表单 ──────────────────────────────────────────────────────────────
  const form = document.createElement('div');
  form.className = 'up-form';

  /**
   * 表单的一行。**用和那 335 个键完全一样的排版** —— 左边一句话说这是什么,
   * 右边一个控件。
   *
   * 第一版是五个等宽的圆角白条竖着摞起来,看着像一个弹出对话框掉进了设置页:
   * 同一个页面上两套排版,人会觉得这块东西是从别处贴过来的。而且五条一样宽、
   * 一样圆、一样白的横条本身就是那种"生成出来的界面"最典型的样子。
   *
   * 现在它和上下文用同一个节奏,不需要任何边框就自己归位了。
   */
  function field(
    label: string,
    hint: string,
    placeholder: string,
    type = 'text',
    wide = false,
  ): HTMLInputElement {
    const row = document.createElement('div');
    row.className = 'sf-row up-row';
    const text = document.createElement('span');
    text.className = 'sf-text';
    const name = document.createElement('span');
    name.className = 'up-label';
    name.textContent = label;
    const desc = document.createElement('span');
    desc.className = 'sf-desc';
    desc.textContent = hint;
    text.append(name, desc);

    const i = document.createElement('input');
    i.className = wide ? 'sf-input up-input up-wide' : 'sf-input up-input';
    i.type = type;
    i.placeholder = placeholder;
    i.addEventListener('click', (e) => e.stopPropagation());

    row.append(text, i);
    formRows.push(row);
    return i;
  }

  const formRows: HTMLElement[] = [];

  /**
   * 协议。**一排可点的档位牌,名单由后端给。**
   *
   * 此前这里写死成 'openai' —— 而后端一直支持 anthropic。那不是"少做了一个
   * 功能",是**后端有能力、界面上够不着**:一个 Claude 兼容的网关加不进来,
   * 而且从界面上完全看不出为什么。这正是本仓最怕那种缺陷的镜像。
   *
   * 名单从 /api/v1/providers/user 一起返回,不在这里写第二份 —— 写死的名单
   * 会在后端增减协议时悄悄错开,而且不报错。
   */
  const protoLine = document.createElement('div');
  protoLine.className = 'sf-row up-row';
  const protoText = document.createElement('span');
  protoText.className = 'sf-text';
  const protoName = document.createElement('span');
  protoName.className = 'up-label';
  protoName.textContent = '协议';
  const protoHint = document.createElement('span');
  protoHint.className = 'sf-desc';
  protoHint.textContent = '这家网关讲哪一套。名单由后端给，不是这里写死的';
  protoText.append(protoName, protoHint);
  const protoRow = document.createElement('span');
  protoRow.className = 'sf-stages up-proto';
  protoLine.append(protoText, protoRow);
  let picked = '';

  function renderProtocols(list: readonly string[]): void {
    if (!picked && list.length) picked = list[0] ?? '';
    protoRow.replaceChildren();
    for (const proto of list) {
      const chip = document.createElement('button');
      chip.className = 'stage';
      chip.type = 'button';
      chip.textContent = proto;
      chip.dataset['picked'] = String(proto === picked);
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        picked = proto;
        for (const sib of protoRow.children) {
          (sib as HTMLElement).dataset['picked'] = String((sib as HTMLElement).textContent === proto);
        }
      });
      protoRow.append(chip);
    }
  }

  const fId = field('名字', '这条端点在系统里的标识，小写字母数字与 - _', 'my-gw');
  const fLabel = field('显示名', '你自己看的名字，留空就用上面那个', '我的自定义服务');
  const fUrl = field('地址', '这家网关的 base URL，通常以 /v1 结尾', 'https://…/v1', 'text', true);
  const fKey = field('API Key', '没有鉴权的自建服务就留空', '', 'password');
  const fModels = field('型号', '逗号隔开。留空 = 让网关自己报', '留空即可', 'text', true);
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
      protocol: picked || 'openai',
      models,
      // 空串表示「不改」,新增时也一样 —— 无鉴权的自建服务就是没有 Key。
      ...(fKey.value ? { api_key: fKey.value } : {}),
    });
  });

  // 顺序:名字 → 显示名 → 地址 → 协议 → Key → 型号 → 按钮。
  // 协议插在地址后面,因为"这个地址讲哪套协议"是紧接着地址要回答的问题。
  form.append(formRows[0]!, formRows[1]!, formRows[2]!, protoLine, formRows[3]!, formRows[4]!, add);
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
    // 改一条端点从前只能整份重打(同 id 是更新语义,但表单是空的)。
    // 「编辑」把这条的字段填回表单 —— **密钥不回填**,那等于把它重新摊到 DOM 上。
    const edit = document.createElement('button');
    edit.className = 'up-btn';
    edit.type = 'button';
    edit.textContent = '编辑';
    edit.addEventListener('click', (e) => {
      e.stopPropagation();
      cb.onEdit(p);
    });
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
    acts.append(edit, reverify, del);

    el.append(top, addr, meta, models, acts);
    return el;
  }

  function render(
    rows: readonly UserProvider[] | null,
    protocols: readonly string[],
    busy: boolean,
    msg: string,
  ): void {
    root.dataset['busy'] = String(busy);
    renderProtocols(protocols);
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

  function fillForm(row: UserProvider): void {
    fId.value = row.id;
    fLabel.value = row.label;
    fUrl.value = row.base_url;
    // **密钥不回填。** 留空 = 不改,后端保留原来那份。把它重新摊到 DOM 上
    // 没有任何好处 —— 录屏、截图、远程桌面都会把它一起带走。
    fKey.value = '';
    fKey.placeholder = row.has_key ? '已存过（留空=不改）' : 'API Key（没有鉴权就留空）';
    fModels.value = row.declared_models.join(', ');
    picked = row.protocol;
    for (const sib of protoRow.children) {
      (sib as HTMLElement).dataset['picked'] = String((sib as HTMLElement).textContent === row.protocol);
    }
    fId.scrollIntoView({ block: 'nearest' });
  }

  return { root, render, clearForm, fillForm };
}
