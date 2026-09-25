/**
 * 「接进来的 GitHub 项目」—— 填一个仓库地址就把它接进来，随时能换掉。
 *
 * ## 两栏是一次**分流**,不是一张卡片的左右
 *
 * 左栏是**项目本身**:根上没有任何集成契约的那些 —— 代码落盘,不注册成任何工具。
 * 右栏是**从项目里接出来的能力**,按形态分组:一个带 ``mcp_tool.json`` 的仓库
 * 接进来之后就是一个 MCP 工具,它不出现在左栏,直接进右栏 MCP 那一组。
 *
 * 为什么要分流,而不是一列里按状态排:这一段里其实混着两种东西。
 * "我接了一个项目"和"我多了一个模型能调的工具"是两件事,人来这一页找的往往
 * 只是其中一件。混成一列时,想找项目的人要在一堆工具里扒,反之亦然。
 *
 * MCP / Skill 是 GitHub 项目的**交集**,不是它的定义:接一个仓库可能是为了拿它
 * 跑实验、读它、拿它当素材。所以左栏那一档不是"降级",是并列的一档。
 *
 * ## 右栏第三组 MHS:画出来,但把它**现在是什么**写清楚
 *
 * MHS = Model Hardware Standard,Anthropic 2026-08-27 的研究预览,定位是 MCP 的
 * 硬件侧对应物。``docs/EXTERNAL_AGENT_FRAMEWORK_EVALUATION.md`` 第 ④ 节判过一次:
 * 它至今没有公开规范、没有 SDK、没有 schema、没有一致性测试,所以**协议这一层
 * 不实现**,也不放占位模块。那条判断没有变。
 *
 * 但"界面上有没有这一档"和"协议实不实现"是两件事。这一格画出来,并且如实写明:
 * 规范还没开源,现在没有任何仓库能落进这一档;真到那天,MHS 的接入路径之一
 * **就是 MCP**,它会从 MCP 那条路进来。
 *
 * 一个空格子本身不骗人;**一个不说明自己为什么空的空格子**才骗人 —— 它看起来像
 * "你还没装",而实际是"这条路还不存在"。所以这一格的空态文案不是"还没有",
 * 是把上面那两句说全。
 *
 * ## 「会不会先问我一句」必须写在脸上
 *
 * 装一个第三方仓库是有后果的动作。准入闸有三档(名单内免确认 / 每次问 /
 * 显式声明无人值守),这三档**必须由后端报**,不能让面板自己按环境变量推 ——
 * 那会成为第二处权威,判定规则改一次两边就分家,而"界面说会问我、实际没问"
 * 是最坏的那种不一致。
 *
 * ## 为什么这里没有「重新验证」按钮(隔壁「我的模型服务」有)
 *
 * 后端没有这个端点。唯一能"再验一次"的办法是拿同一个地址再装一遍,而那会
 * **重新克隆并覆盖**已经装好的那份 —— 一个写着"重新验证"的按钮干的是"重装",
 * 这正是这个仓最怕的那种不一致。缺的是后端能力,就照实缺着。
 */
import { GITHUB_CONTRACT_KEYS } from '../transport';
import type { GitHubAddon, GitHubAddonStatus, GitHubContractKey } from '../transport';

export interface GitHubAddonDraft {
  url: string;
  ref?: string;
}

export interface GitHubAddonCallbacks {
  /** 真的装。 */
  onInstall(draft: GitHubAddonDraft): void;
  /** 只校验地址、不落盘（后端的 dry_run）。 */
  onDryRun(draft: GitHubAddonDraft): void;
  onUninstall(name: string): void;
}

export interface GitHubAddonHandles {
  readonly root: HTMLElement;
  render(
    rows: readonly GitHubAddon[] | null,
    status: GitHubAddonStatus | null,
    busy: boolean,
    notice: string,
  ): void;
  /**
   * 清空表单。装成功之后由调用方来调。
   *
   * 不清的话:列表里已经有这条了,下面表单还留着同一个地址 —— 人会以为没接上,
   * 再点一次「接进来」,而那一次会把刚装好的重新克隆一遍。
   *
   * 失败时**不清** —— 那时表单里是他刚填的东西,清掉等于让他重打一遍。
   */
  clearForm(): void;
}

/** 三份契约的名字。顺序就是安装器的判定顺序:mcp → skill → SKILL.md。 */
const CONTRACT_TEXT: Record<GitHubContractKey, string> = {
  mcp: 'mcp_tool.json',
  skill: 'skill.json',
  skill_md: 'SKILL.md',
};

const ICON_NS = 'http://www.w3.org/2000/svg';

/**
 * 一枚线条图标。形状与画法都照 ``ui/dock.ts`` 那个 helper —— 24 格、
 * ``currentColor`` 描边、圆头圆角。全面板只有一种图标画法,多一种就要多认一次。
 */
function icon(path: string, size = 14, width = 1.6): SVGSVGElement {
  const svg = document.createElementNS(ICON_NS, 'svg');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', String(width));
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(ICON_NS, 'path');
  p.setAttribute('d', path);
  svg.append(p);
  return svg;
}

/**
 * 分流出来的几栏。
 *
 * ``project`` 单独在左边,两组工具在右边 —— 见文件头那一段。
 * 没有 MHS 这一组,理由也写在那儿(仓里已经判过:没有规范可实现,而且不放占位)。
 */
const GROUPS = [
  {
    form: 'project',
    label: '项目',
    side: 'left',
    // 文件夹:它就是一份代码,不是一个能调用的东西。
    path: 'M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
    desc: '根上没有集成契约 —— 代码落盘，不注册成可调用的工具',
    empty: '还没接过项目',
  },
  {
    form: 'mcp',
    label: 'MCP 工具',
    side: 'right',
    // 插头:接进网关,模型调得到。
    path: 'M9 3v5M15 3v5M6.5 8h11v4a5.5 5.5 0 0 1-11 0zM12 17.5V21',
    desc: '根上有 mcp_tool.json，注册进了全系统共用的 MCP 网关',
    empty: '还没有从 GitHub 接进来的 MCP 工具',
  },
  {
    form: 'skill',
    label: 'Skill',
    side: 'right',
    // 一本册子:一段写好的做法。
    path: 'M5 4.5A1.5 1.5 0 0 1 6.5 3H18v18H6.5A1.5 1.5 0 0 1 5 19.5zM5 17h13M9 7.5h5',
    desc: '根上有 skill.json 或 SKILL.md，注册进了 SkillLoader',
    empty: '还没有从 GitHub 接进来的 Skill',
  },
  {
    form: 'mhs',
    label: 'MHS',
    side: 'right',
    // 芯片:它管的是物理设备,不是软件工具。
    path: 'M8 8h8v8H8zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3',
    desc: 'Model Hardware Standard —— 让 agent 操作物理设备的规范，MCP 的硬件侧对应物',
    // 空态**必须说清为什么空**。只写"还没有"会被读成"你还没装",
    // 而实际是"这条路还不存在"。详见文件头那一节。
    empty:
      '规范还没开源（没有 schema / SDK / 一致性测试），现在没有任何仓库能落进这一档。真开源之后它的接入路径之一就是 MCP —— 会从 MCP 那条路进来，不需要另起一套传输。判断见 docs/EXTERNAL_AGENT_FRAMEWORK_EVALUATION.md 第 ④ 节。',
  },
] as const;

/** 依赖装到哪。后端的 scope 原样翻译,不合并 —— 每一档的后果都不一样。 */
const DEPS_TEXT: Record<string, string> = {
  venv: '依赖在它自己的 venv 里',
  host: '依赖装进了宿主环境',
  none: '没有依赖要装',
  rejected: '依赖被拒了',
  venv_unavailable: 'venv 建不出来，依赖没装',
};

/**
 * 三档准入策略各一句人话。
 *
 * 分三句而不是「会/不会问」两句:`allowlist` 和 `unattended` 都不问,但一个是
 * "只有名单里的能进",另一个是"谁都能进"。合成一句,后者会被读成前者。
 */
const MODE_TEXT: Record<string, string> = {
  ask: '装之前会先问你一句',
  allowlist: '名单内直接装，名单外直接拒',
  unattended: '一律不问 —— 这台机器声明了无人值守',
};

function when(iso: string): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s} 秒前接进来`;
  if (s < 3600) return `${Math.round(s / 60)} 分钟前接进来`;
  if (s < 86400) return `${Math.round(s / 3600)} 小时前接进来`;
  return `${Math.round(s / 86400)} 天前接进来`;
}

export function createGitHubAddons(cb: GitHubAddonCallbacks): GitHubAddonHandles {
  const root = document.createElement('section');
  root.className = 'sf-sec ga-sec';

  const head = document.createElement('h3');
  head.className = 'sf-sec-head';
  head.textContent = '接进来的 GitHub 项目';
  const n = document.createElement('b');
  head.append(n);

  const hint = document.createElement('p');
  hint.className = 'ga-hint';
  hint.textContent =
    '接一个仓库不一定要让它变成工具。根上有 mcp_tool.json / skill.json / SKILL.md 的，会顺带注册成一个 MCP 工具或一个 Skill（进的是全系统共用的那套 MCP 网关与 SkillLoader）；没有的，就以项目完整形式接进来 —— 代码落盘，不注册任何工具，这同样是一次成功的接入。这份清单只列从 GitHub 接进来的；系统自带的 MCP 工具和 Skill 不在这里。';

  /** 准入策略那一行。**内容全部来自后端**,这里不按环境变量推第二份。 */
  const policy = document.createElement('div');
  policy.className = 'ga-policy';
  const policyDot = document.createElement('span');
  policyDot.className = 'ga-dot';
  const policyText = document.createElement('span');
  policyText.className = 'ga-policy-text';
  const policyMeta = document.createElement('span');
  policyMeta.className = 'ga-policy-meta';
  policy.append(policyDot, policyText, policyMeta);

  /**
   * 分流出来的两栏。左边一栏(项目),右边一栏(接出来的工具,再分两组)。
   *
   * ``ga-split`` 在窄处会塌成一列 —— 设置页本来就不宽,硬撑两栏会把每张卡片
   * 挤到读不了。塌成一列时分组的标题还在,分流这件事不丢。
   */
  const split = document.createElement('div');
  split.className = 'ga-split';

  const colLeft = document.createElement('div');
  colLeft.className = 'ga-col';
  const colRight = document.createElement('div');
  colRight.className = 'ga-col';
  split.append(colLeft, colRight);

  /** 拉不到 / 一条都没有时,那句话摆在两栏上面,而不是塞进某一组里。 */
  const wholeNote = document.createElement('div');
  wholeNote.className = 'sf-empty';
  wholeNote.hidden = true;

  const notice = document.createElement('div');
  notice.className = 'ga-notice';
  notice.hidden = true;

  // ── 表单 ──────────────────────────────────────────────────────────────────
  const form = document.createElement('div');
  form.className = 'ga-form';
  const formRows: HTMLElement[] = [];

  /** 表单的一行。和那 335 个键完全一样的排版:左边一句话,右边一个控件。 */
  function field(label: string, desc: string, placeholder: string, wide = false): HTMLInputElement {
    const row = document.createElement('div');
    row.className = 'sf-row ga-row';
    const text = document.createElement('span');
    text.className = 'sf-text';
    const name = document.createElement('span');
    name.className = 'ga-label';
    name.textContent = label;
    const d = document.createElement('span');
    d.className = 'sf-desc';
    d.textContent = desc;
    text.append(name, d);

    const i = document.createElement('input');
    i.className = wide ? 'sf-input ga-input ga-wide' : 'sf-input ga-input';
    i.type = 'text';
    i.placeholder = placeholder;
    i.addEventListener('click', (e) => e.stopPropagation());

    row.append(text, i);
    formRows.push(row);
    return i;
  }

  const fUrl = field(
    '仓库地址',
    'https://github.com/owner/repo，带 /tree/分支 也认',
    'https://github.com/…',
    true,
  );
  const fRef = field('分支或标签', '留空就用仓库的默认分支', 'main');

  /**
   * **这里刻意没有「类型」选择器。**
   *
   * 后端的 type 是 `mcp | skill | skill_md | null(按清单自动判)`,而这份名单
   * 后端并不通过任何接口报出来。在前端写死它,就会在后端增减类型的那天悄悄错开,
   * 而且不报错 —— 和协议牌当初写死成 'openai' 是同一个坑。
   *
   * 更重要的是:强制指定类型本来就该是排查手段,不是日常路径。仓库自己的清单
   * 就是权威,让人在界面上"猜"一个类型去覆盖它,只会做出装上了却调不通的东西。
   */
  const acts = document.createElement('div');
  acts.className = 'ga-form-acts';
  const dry = document.createElement('button');
  dry.className = 'ga-btn';
  dry.type = 'button';
  dry.textContent = '先验一下';
  const add = document.createElement('button');
  add.className = 'sf-save';
  add.type = 'button';
  add.textContent = '接进来';
  acts.append(dry, add);

  function draft(): GitHubAddonDraft {
    const ref = fRef.value.trim();
    return { url: fUrl.value.trim(), ...(ref ? { ref } : {}) };
  }

  dry.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onDryRun(draft());
  });
  add.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onInstall(draft());
  });

  form.append(formRows[0]!, formRows[1]!, acts);
  root.append(head, hint, policy, notice, wholeNote, split, form);
  root.addEventListener('click', (e) => e.stopPropagation());

  /**
   * 一条。**压成一行**:图标带头、名字、状态点、移除。
   *
   * 完整的那几句话(仓库坐标、落盘路径、卡在哪一步)进 ``title``,鼠标停一下才出来。
   * 这是左栏底下那块「接上了什么」用过的同一招,它那条 ``why`` 的注释写着理由:
   * 「短的那句摆在屏幕上,长的那句进 title,一个字都不丢」。
   *
   * 改成一行是因为上一版每条占了五六行 —— 四个框摞起来,一屏放不下两条,
   * 而这一页本来就是拿来**扫**的:先看有哪些,再点开看某一个。
   */
  function row(a: GitHubAddon, def: (typeof GROUPS)[number]): HTMLElement {
    const el = document.createElement('div');
    el.className = 'ga-row-item';
    el.dataset['ok'] = String(a.ok);

    // 一条条目也带图标:横着扫的时候,图标比一行等宽小字先被认出来。
    // 用它所在那一组的图标 —— 同一种东西在界面上只有一个样子。
    const glyph = icon(def.path, 13, 1.5);
    glyph.classList.add('ga-row-icon');

    const name = document.createElement('span');
    name.className = 'ga-row-name';
    name.textContent = a.name;

    const dot = document.createElement('span');
    dot.className = 'ga-dot';

    const del = document.createElement('button');
    del.className = 'ga-btn ga-danger ga-row-del';
    del.type = 'button';
    del.textContent = '移除';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      cb.onUninstall(a.name);
    });

    // title 里一个字都不丢。顺序按排障时会用到的先后:坐标 → 出了什么事 → 在哪儿。
    const lines = [`${a.owner}/${a.repo}@${a.ref}`];
    if (a.commit) lines.push(`commit ${a.commit.slice(0, 12)}`);
    if (!a.ok) lines.push(a.formDetail || '注册或自证没通过');
    if (!GROUPS.some((g) => g.form === a.form)) {
      // 后端报了一个这里还不认识的形态。不能让它悄悄躺在「项目」组里装成普通项目。
      lines.push(`后端报的接入形态「${a.form}」这个面板还不认识，先按项目摆着`);
    }
    const ignored = GITHUB_CONTRACT_KEYS.filter((k) => a.contracts[k].present && !a.contracts[k].chosen);
    if (ignored.length) {
      lines.push(`根上还有 ${ignored.map((k) => CONTRACT_TEXT[k]).join('、')}（判定顺序在前的那份已命中）`);
    }
    lines.push(DEPS_TEXT[a.depsScope] ?? a.depsScope);
    if (a.depsError) lines.push(`依赖：${a.depsError}`);
    lines.push(when(a.installedAt), a.installPath);
    el.title = lines.filter(Boolean).join('\n');

    el.append(glyph, name, dot, del);

    // **没接上、或者依赖被拒**这两件事不许只躺在 title 里:它们要人去做点什么。
    // 其余的(坐标、路径、时间)是查的时候才要,留在 title 就够。
    const alert = !a.ok ? a.formDetail || '注册或自证没通过' : a.depsError ? `依赖：${a.depsError}` : '';
    if (!alert) return el;

    const wrap = document.createElement('div');
    wrap.className = 'ga-row-wrap';
    const why = document.createElement('span');
    why.className = 'ga-why';
    why.textContent = alert;
    wrap.append(el, why);
    wrap.title = el.title;
    return wrap;
  }

  /**
   * 一个框。四个框**同一套做法** —— 左边那个大的和右边三个小的只是尺寸不同。
   *
   * 框里自己滚(``max-height`` + ``overflow-y``),不是让整页跟着长:四个框各装各的,
   * 某一组装了二十条时,不该把另外三组顶到屏幕外面去。
   */
  function frame(def: (typeof GROUPS)[number], rows: readonly GitHubAddon[]): HTMLElement {
    const box = document.createElement('section');
    box.className = 'ga-frame';
    box.dataset['form'] = def.form;

    const head = document.createElement('div');
    head.className = 'ga-frame-head';
    const label = document.createElement('span');
    label.className = 'ga-frame-name';
    label.textContent = def.label;
    const n = document.createElement('b');
    n.textContent = String(rows.length);
    head.append(icon(def.path, 15, 1.6), label, n);
    head.title = def.desc;

    const body = document.createElement('div');
    body.className = 'ga-frame-body';
    if (!rows.length) {
      const e = document.createElement('div');
      e.className = 'ga-frame-empty';
      // 空态**必须说清为什么空**。省掉的话,这一栏看起来就是完整的,而它并不完整
      // ——「一个都没接过」和「这条路还不存在」是两件事。
      e.textContent = def.empty;
      body.append(e);
    } else {
      for (const a of rows) body.append(row(a, def));
    }

    box.append(head, body);
    return box;
  }

  function renderPolicy(status: GitHubAddonStatus | null): void {
    if (status === null) {
      // 「拉不到策略」不能画成任何一档。画成"会问你"而实际不问,是最坏的那种谎。
      policy.dataset['mode'] = 'unknown';
      policyText.textContent = '拉不到安装策略 —— 后端没接上';
      policyMeta.textContent = '';
      return;
    }
    const mode = status.approvalMode || 'unknown';
    policy.dataset['mode'] = mode;
    policyText.textContent = MODE_TEXT[mode] ?? `安装策略：${mode}`;

    const bits: string[] = [];
    if (status.allowlist.length) bits.push(`名单 ${status.allowlist.join('、')}`);
    if (status.blocklist.length) bits.push(`黑名单 ${status.blocklist.join('、')}`);
    // 没配 token 不是"坏了",但私有仓和高频调用会失败 —— 说出来,别等装的时候才炸。
    if (!status.tokenConfigured) bits.push('没配 GITHUB_TOKEN（私有仓和高频调用会失败）');
    if (status.installDir) bits.push(`装在 ${status.installDir}`);
    policyMeta.textContent = bits.join(' · ');
  }

  function render(
    rows: readonly GitHubAddon[] | null,
    status: GitHubAddonStatus | null,
    busy: boolean,
    msg: string,
  ): void {
    root.dataset['busy'] = String(busy);
    renderPolicy(status);
    notice.hidden = !msg;
    notice.textContent = msg;

    colLeft.replaceChildren();
    colRight.replaceChildren();

    if (rows === null) {
      // 「没拉到」不是「一个都没装」。空白会让人以为自己接过的项目丢了。
      wholeNote.hidden = false;
      wholeNote.textContent = '拉不到已接进来的项目 —— 后端没接上，不是你没接过';
      split.hidden = true;
      n.textContent = '';
      return;
    }
    split.hidden = false;
    n.textContent = String(rows.length);
    wholeNote.hidden = rows.length > 0;
    if (!rows.length) {
      wholeNote.textContent = '还没接过。下面填一个仓库地址就行 —— 不用改代码，也不用重启。';
    }

    // 分流:一张卡片按它的形态进它该进的那一组,一个都不许落在两边之外。
    // ``form`` 是后端给的唯一判定,认不出的一律归到「项目」—— 认不出的东西
    // 少说一句话是安全的,悄悄消失不是。
    const byForm = new Map<string, GitHubAddon[]>(GROUPS.map((g) => [g.form, []]));
    for (const a of rows) (byForm.get(a.form) ?? byForm.get('project')!).push(a);

    for (const def of GROUPS) {
      // 去向由 ``side`` 说,不由"是不是 project"反推 —— 加第四档(MHS)的时候
      // 那种反推就会悄悄把它送错栏,而且不报错。
      const target = def.side === 'left' ? colLeft : colRight;
      target.append(frame(def, byForm.get(def.form) ?? []));
    }
  }

  function clearForm(): void {
    fUrl.value = '';
    fRef.value = '';
  }

  return { root, render, clearForm };
}
