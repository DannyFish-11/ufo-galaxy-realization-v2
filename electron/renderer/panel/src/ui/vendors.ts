/**
 * 「模型服务商」—— 每家厂商一张卡:填 Key、配没配、通没通、参与哪些任务。
 *
 * ## 为什么有这一段
 *
 * 各家厂商的 API Key 原来只躺在「全部设置」第 12 段、35 行裸环境变量名里
 * (`ANTHROPIC_API_KEY` …):没有厂商名、没有「配了没有」、没有「能不能通」。
 * 人打开设置只看得到「我的模型服务」(自定义端点),就以为各家厂商没法填 ——
 * 旧面板里那份带中文名的厂商目录,在新面板重写时被整个删掉了,这里把它建回来。
 *
 * ## 它和「我的模型服务」的分工
 *
 * · 这里:**我们核实过的直连厂商**(型号、地址、脾气后端都知道)+ 聚合/自建/识屏这几类入口。
 *   事实全由后端给(`core/provider_catalog.py`),这里只画。
 * · 「我的模型服务」:你自己加的、后端不认识的网关。两者永不合并。
 *
 * ## 三条不肯让步的
 *
 * 一、**密钥不回填、不下发。** 输入框永远是空的;配没配只由后端一个布尔说了算。
 * 二、**存了就验。** 保存之后立刻真发一次 1 token 试调 —— 否则用户看到的是「已配置」,
 *    却要等到第一次对话失败才知道 Key 是错的。(由 main.ts 串起来,这里只画结果。)
 * 三、**输入框不能因为别处的刷新被清掉。** 这个面板每秒都在重画(姿态帧),卡片的 DOM
 *    按厂商 id 留着、只更新文字;输入到一半的 Key 不会没。
 */
import type { Vendor, VendorCheck, VendorPage } from '../transport';

export interface VendorCallbacks {
  /** 写这个 Key 名。value 非空。 */
  onSaveKey(v: Vendor, env: string, value: string): void;
  /** 把这家配过的 Key(含别名)全部清掉。 */
  onClearKey(v: Vendor): void;
  onSaveUrl(v: Vendor, env: string, value: string): void;
  onVerify(v: Vendor): void;
}

export interface VendorHandles {
  readonly root: HTMLElement;
  render(
    page: VendorPage | null,
    busy: boolean,
    notice: string,
    checks: Readonly<Record<string, VendorCheck>>,
    checking: string,
  ): void;
}

const ROLE_TEXT: Record<string, string> = {
  reasoning: '推理',
  fast_response: '快速响应',
  coding: '代码',
  creative: '创作',
  analysis: '分析',
  planning: '规划',
  agent_control: '操控',
  general: '通用',
};

/** 卡片上最多列几个型号。列全的话 OpenAI 一家就是一整屏。 */
const MODELS_SHOWN = 10;

interface CardRefs {
  /** 这张卡当前对应的厂商。按钮回调读它而不是建卡那一刻的闭包 —— 后者会过期(配了 Key 之后「清除」还以为没配)。 */
  readonly box: { v: Vendor };
  readonly el: HTMLElement;
  readonly state: HTMLElement;
  readonly meta: HTMLElement;
  readonly verdict: HTMLElement;
  readonly keyRows: Map<string, { input: HTMLInputElement; save: HTMLButtonElement }>;
  readonly verify: HTMLButtonElement;
  readonly clear: HTMLButtonElement;
  readonly detail: HTMLElement;
  readonly more: HTMLButtonElement;
  readonly urlInputs: Map<string, HTMLInputElement>;
}

function btn(label: string, cls: string, on: () => void): HTMLButtonElement {
  const b = document.createElement('button');
  b.className = cls;
  b.type = 'button';
  b.textContent = label;
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    on();
  });
  return b;
}

function chips(items: readonly string[], cap: number): HTMLElement {
  const box = document.createElement('div');
  box.className = 'up-models';
  for (const m of items.slice(0, cap)) {
    const c = document.createElement('code');
    c.textContent = m;
    box.append(c);
  }
  if (items.length > cap) {
    const more = document.createElement('span');
    more.className = 'up-more';
    more.textContent = `还有 ${items.length - cap} 个`;
    box.append(more);
  }
  return box;
}

export function createVendors(cb: VendorCallbacks): VendorHandles {
  const root = document.createElement('section');
  root.className = 'sf-sec up-sec vd-sec';

  const head = document.createElement('h3');
  head.className = 'sf-sec-head';
  head.textContent = '模型服务商';
  const count = document.createElement('b');
  head.append(count);

  const hint = document.createElement('p');
  hint.className = 'up-hint';
  hint.textContent =
    '各家的 API Key 填在这里:保存后会立刻真发一次 1 token 的试调,通了才算数。Key 只写进本机密钥库,这里永远不会显示它。';

  const notice = document.createElement('div');
  notice.className = 'up-notice';
  notice.hidden = true;

  const body = document.createElement('div');
  body.className = 'vd-body';

  root.append(head, hint, notice, body);
  root.addEventListener('click', (e) => e.stopPropagation());

  const cards = new Map<string, CardRefs>();
  /** 分组标题的节点也留着:每次新建的话,顺序比对永远不等,DOM 会被整个替换、输入框丢焦点。 */
  const headings = new Map<string, HTMLElement>();
  /** 展开了「型号与选路」的厂商。留在这里而不是 DOM 上,重画不会收回去。 */
  const opened = new Set<string>();

  function build(first: Vendor): CardRefs {
    const box = { v: first };
    const v = first; // 只用来决定「建哪些行」(结构随厂商种类定,不随状态变)
    const el = document.createElement('div');
    el.className = 'up-card vd-card';

    const top = document.createElement('div');
    top.className = 'up-top';
    const dot = document.createElement('span');
    dot.className = 'up-dot';
    const name = document.createElement('b');
    name.textContent = v.label;
    const state = document.createElement('span');
    state.className = 'up-state';
    top.append(dot, name, state);

    const meta = document.createElement('span');
    meta.className = 'up-meta';
    // 试调的结论单独一行:它可能很长(「连接失败(ConnectError)——检查网络…」),
    // 挤在标题旁边会把名字顶成竖排。
    const verdict = document.createElement('span');
    verdict.className = 'up-meta vd-verdict';

    el.append(top, meta, verdict);

    // 密钥输入。registry 厂商只写规范名(第一个);别名只是「填过也认」。
    // extra 入口(识屏 OCR 有两把 Key)每把一行 —— 各写各的,不替人决定填哪把。
    const keyRows = new Map<string, { input: HTMLInputElement; save: HTMLButtonElement }>();
    const inputEnvs = v.kind === 'registry' ? v.keyEnvs.slice(0, 1) : v.keyEnvs;
    for (const env of inputEnvs) {
      const row = document.createElement('div');
      row.className = 'vd-key';
      const input = document.createElement('input');
      input.className = 'sf-input vd-input';
      input.type = 'password';
      input.autocomplete = 'off';
      input.spellcheck = false;
      input.addEventListener('click', (e) => e.stopPropagation());
      const save = btn('保存', 'sf-save', () => {
        const val = input.value.trim();
        if (!val) return;
        cb.onSaveKey(box.v, env, val);
        // 提交就清掉:留着的话,密钥会一直躺在 DOM 里,直到有人关页面。
        input.value = '';
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') save.click();
      });
      const label = document.createElement('code');
      label.className = 'vd-env';
      label.textContent = env;
      row.append(label, input, save);
      el.append(row);
      keyRows.set(env, { input, save });
    }

    // 地址:本机/自建那几类就是主角(没有它根本不通),直接摆;直连厂商的「换中转」放进详情。
    const urlInputs = new Map<string, HTMLInputElement>();
    const urlHost = document.createElement('div');
    urlHost.className = 'vd-urls';
    for (const u of v.urlEnvs) {
      const row = document.createElement('div');
      row.className = 'vd-key';
      const input = document.createElement('input');
      input.className = 'sf-input vd-input';
      input.type = 'text';
      input.spellcheck = false;
      input.addEventListener('click', (e) => e.stopPropagation());
      const save = btn('保存地址', 'sf-save', () => cb.onSaveUrl(box.v, u.env, input.value.trim()));
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') save.click();
      });
      const label = document.createElement('code');
      label.className = 'vd-env';
      label.textContent = u.env;
      row.append(label, input, save);
      urlHost.append(row);
      urlInputs.set(u.env, input);
    }

    const acts = document.createElement('div');
    acts.className = 'up-acts';
    const verify = btn('验证', 'up-btn', () => cb.onVerify(box.v));
    const clear = btn('清除密钥', 'up-btn up-danger', () => cb.onClearKey(box.v));
    const more = btn('', 'up-btn vd-more', () => {
      if (opened.has(first.id)) opened.delete(first.id);
      else opened.add(first.id);
      applyOpen(first.id);
    });
    acts.append(verify, clear, more);

    const detail = document.createElement('div');
    detail.className = 'vd-detail';
    detail.hidden = true;

    if (v.kind === 'registry') {
      // 直连厂商:地址属于「高级」(多数人不用换),跟详情一起收着。
      detail.append(urlHost);
    } else {
      el.append(urlHost);
    }
    el.append(acts, detail);

    const refs: CardRefs = { box, el, state, meta, verdict, keyRows, verify, clear, detail, more, urlInputs };
    fillDetail(v, refs);
    return refs;
  }

  /** 详情里的静态部分(型号、选路)。厂商数据变了才重填,不碰输入框。 */
  function fillDetail(v: Vendor, r: CardRefs): void {
    // 先摘掉旧的静态块,保留 urlHost(带着输入框)。
    for (const child of Array.from(r.detail.children)) {
      if (!(child as HTMLElement).classList.contains('vd-urls')) child.remove();
    }
    const line = (text: string): HTMLElement => {
      const p = document.createElement('p');
      p.className = 'up-meta';
      p.textContent = text;
      return p;
    };
    if (v.kind === 'registry') {
      if (v.defaultModel) r.detail.append(line(`默认型号:${v.defaultModel}`));
      if (v.models.length) r.detail.append(chips(v.models, MODELS_SHOWN));
      if (v.realtimeModels.length) {
        r.detail.append(line('语音实时型号:'));
        r.detail.append(chips(v.realtimeModels, MODELS_SHOWN));
      }
      r.detail.append(
        line(
          v.optIn
            ? '这家不自动参与选路(有意如此):配了 Key 也只在你明确指定时才用。'
            : `参与选路的任务:${v.roles.map((x) => ROLE_TEXT[x] ?? x).join(' · ') || '无'}。其余任务它也是最后的备选。`,
        ),
      );
    }
    if (v.keyEnvs.length > 1 && v.kind === 'registry') {
      r.detail.append(line(`也认这些名字:${v.keyEnvs.slice(1).join('、')}`));
    }
  }

  function applyOpen(id: string): void {
    const r = cards.get(id);
    if (!r) return;
    const open = opened.has(id);
    r.detail.hidden = !open;
    r.more.textContent = open ? '收起' : '型号与选路';
  }

  function update(v: Vendor, r: CardRefs, check: VendorCheck | undefined, checking: boolean): void {
    r.box.v = v;
    // 状态:试过的以试调结论为准(通 / 没通);没试过的只说「配了/没配」。
    // 标题旁只放一个短词,结论的原话(可能很长)放到下面一行。
    let state = 'off';
    let text = '未配置';
    let verdict = '';
    if (checking) {
      state = 'declared';
      text = '验证中…';
    } else if (check) {
      state = check.ok ? 'live' : 'unverified';
      text = check.ok ? '通了' : '没通';
      verdict = check.text;
    } else if (v.configured) {
      state = 'declared';
      text = v.kind === 'registry' ? '已配置 · 还没验证' : '已填';
    }
    r.el.dataset['state'] = state;
    r.state.textContent = text;
    r.verdict.textContent = verdict;
    r.verdict.hidden = !verdict;

    r.meta.textContent = v.note;
    r.meta.hidden = !v.note;

    for (const [env, row] of r.keyRows) {
      const set = v.keyState[env] === true;
      row.input.placeholder = set ? '已配置 · 输入新密钥可替换' : '粘贴 API Key';
    }
    // 别名填过也算配了:清除按钮要在「任何一个 Key 名有值」时出现。
    const anySet = Object.values(v.keyState).some(Boolean);
    r.clear.hidden = !anySet;
    // 没有 Key 可验的入口(本机/自建地址)不画验证键,除非路由器里真有它。
    r.verify.hidden = v.kind !== 'registry' && v.registered !== true;

    for (const u of v.urlEnvs) {
      const input = r.urlInputs.get(u.env);
      if (!input) continue;
      input.placeholder = u.default ? `默认 ${u.default}` : '地址';
      // 正在输入的时候不覆盖:只在输入框没被聚焦且值与后端不同才同步。
      if (document.activeElement !== input && input.value !== u.value) input.value = u.value;
    }
    applyOpen(v.id);
  }

  let last: { page: VendorPage | null; busy: boolean; notice: string; checks: unknown; checking: string } | null =
    null;

  function render(
    page: VendorPage | null,
    busy: boolean,
    msg: string,
    checks: Readonly<Record<string, VendorCheck>>,
    checking: string,
  ): void {
    // 面板每一帧都会调用到这里;输入没变就什么都不做(也就不会打断正在打字的人)。
    if (
      last &&
      last.page === page &&
      last.busy === busy &&
      last.notice === msg &&
      last.checks === checks &&
      last.checking === checking
    ) {
      return;
    }
    last = { page, busy, notice: msg, checks, checking };

    root.dataset['busy'] = String(busy);
    notice.hidden = !msg;
    notice.textContent = msg;

    if (page === null) {
      // 「没拉到」不是「一家都没有」。
      count.textContent = '';
      const e = document.createElement('div');
      e.className = 'sf-empty';
      e.textContent = '拉不到厂商目录 —— 后端没接上，不是没有可填的厂商';
      body.replaceChildren(e);
      return;
    }

    const set = page.vendors.filter((v) => v.configured).length;
    count.textContent = `已配 ${set} / 共 ${page.vendors.length}`;

    const desired: HTMLElement[] = [];
    const known = new Set(page.groups.map((g) => g.id));
    const sections = [
      ...page.groups,
      // 后端出现了面板不认识的分组也不丢 —— 丢了那一整组厂商就无处可填。
      ...Array.from(new Set(page.vendors.map((v) => v.group).filter((g) => !known.has(g)))).map((id) => ({
        id,
        label: id || '其他',
      })),
    ];
    for (const g of sections) {
      const list = page.vendors.filter((v) => v.group === g.id);
      if (!list.length) continue;
      let h = headings.get(g.id);
      if (!h) {
        h = document.createElement('div');
        h.className = 'vd-group';
        headings.set(g.id, h);
      }
      h.textContent = g.label;
      desired.push(h);
      for (const v of list) {
        let r = cards.get(v.id);
        if (!r) {
          r = build(v);
          cards.set(v.id, r);
        } else {
          fillDetail(v, r);
        }
        update(v, r, checks[v.id], checking === v.id);
        desired.push(r.el);
      }
    }

    // 顺序没变就不动 DOM —— 重新插入会让输入框失去焦点。
    const cur = Array.from(body.children);
    const same = cur.length === desired.length && cur.every((n, i) => n === desired[i]);
    if (!same) body.replaceChildren(...desired);
  }

  return { root, render };
}
