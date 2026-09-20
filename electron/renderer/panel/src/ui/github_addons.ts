/**
 * 「接进来的 GitHub 项目」—— 填一个仓库地址就把它接进来，随时能换掉。
 *
 * ## 为什么它和「我的模型服务」长得像，而不是像那 335 个键
 *
 * 同一个理由:一条插件不是「一个开关调到多少」,它有地址、有分支、有它到底
 * **注册上没有**、依赖装进了谁的环境。这些塞不进键值那套排版里 —— 硬塞的结果
 * 是四五个键之间有隐含关系,而键值界面表达不了关系。
 *
 * 所以这一段刻意和 `user_providers.ts` 用同一套骨架(`sf-sec` / `sf-row` /
 * `sf-text` / `sf-desc` / `sf-input` / `sf-save` / `sf-empty` 全是共用的),
 * 差别只在它自己那几个 `.ga-*`。**不另起一套排版** —— 同一个页面上两套节奏,
 * 人会觉得这块东西是从别处贴过来的。
 *
 * ## 状态是两件事,不准画成一件
 *
 * · active    克隆、注册、自证都过了,模型**真的调得到**
 * · degraded  代码拿下来了,但注册或自证没过 —— 调它的时候才会报错
 *
 * 把两者画成同一个绿点,等于告诉用户"这个工具能用"。这和隔壁
 * live/declared 不许共用一个绿点是同一条理由。degraded 时必须说出**卡在哪一步**,
 * 那句话就是他要拿去排查的东西。
 *
 * ## 「会不会先问我一句」必须写在脸上
 *
 * 装一个第三方仓库是有后果的动作。准入闸有三档(名单内免确认 / 每次问 /
 * 显式声明无人值守),这三档**必须由后端报**,不能让面板自己按环境变量推 ——
 * 那会成为第二处权威,判定规则改一次两边就分家,而"界面说会问我、实际没问"
 * 是最坏的那种不一致。所以 approvalMode 来自 `/api/v1/github/status`。
 *
 * ## 为什么这里没有「重新验证」按钮(隔壁有)
 *
 * 后端没有这个端点。唯一能"再验一次"的办法是拿同一个地址再装一遍,而那会
 * **重新克隆并覆盖**已经装好的那份 —— 一个写着"重新验证"的按钮干的是"重装",
 * 这正是这个仓最怕的那种不一致。缺的是后端能力,就照实缺着,不拿一个名不副实的
 * 按钮把它盖住。
 */
import type { GitHubAddon, GitHubAddonStatus } from '../transport';

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

const STATE_TEXT: Record<string, string> = {
  active: '接上了',
  degraded: '拿下来了，但没接上',
};

/**
 * 仓库接进来之后变成了什么。
 *
 * 这是一张**显示用**的对照表,不是一份"可选类型名单":表单里没有让人挑类型的
 * 入口(仓库自己的清单才是权威),所以这里不会出现"前端名单和后端名单错开"
 * 那种病。后端将来多一种类型,下面的 ``?? a.type`` 会把原值照样显示出来 ——
 * 认不出的东西要露出来,不能悄悄消失。
 */
const KIND_TEXT: Record<string, string> = {
  mcp: 'MCP 工具',
  skill: 'Skill',
  skill_md: 'Skill（SKILL.md）',
  ordinary_tool_repo: '只克隆了代码',
};

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
    '一个 GitHub 仓库接进来之后，会变成一个 MCP 工具或一个 Skill —— 由它根上的 mcp_tool.json / skill.json 说了算，注册进的是全系统共用的那套 MCP 网关与 SkillLoader。所以卡片上那个类型不是另一类东西，就是这个仓库变成的样子。这份清单只列从 GitHub 接进来的；系统自带的 MCP 工具和 Skill 不在这里。';

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

  const list = document.createElement('div');
  list.className = 'ga-list';

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
  root.append(head, hint, policy, notice, list, form);
  root.addEventListener('click', (e) => e.stopPropagation());

  function card(a: GitHubAddon): HTMLElement {
    const el = document.createElement('div');
    el.className = 'ga-card';
    el.dataset['state'] = a.state;

    const top = document.createElement('div');
    top.className = 'ga-top';
    const dot = document.createElement('span');
    dot.className = 'ga-dot';
    const name = document.createElement('b');
    name.textContent = a.name;
    const state = document.createElement('span');
    state.className = 'ga-state';
    state.textContent = STATE_TEXT[a.state] ?? a.state;
    const kind = document.createElement('span');
    kind.className = 'ga-kind';
    kind.textContent = KIND_TEXT[a.type] ?? a.type;
    top.append(dot, name, state, kind);

    const repo = document.createElement('code');
    repo.className = 'ga-repo';
    // commit 截到 8 位:够认人,又不会把一行挤爆。ref 和 commit 都要有 ——
    // 「装的是 main」和「装的是 main 上的哪一次提交」是两件事。
    repo.textContent = `${a.owner}/${a.repo}@${a.ref}${a.commit ? ` · ${a.commit.slice(0, 8)}` : ''}`;

    const meta = document.createElement('span');
    meta.className = 'ga-meta';
    if (a.state === 'degraded') {
      // 没接上的时候,**卡在哪一步**比什么都重要 —— 这就是他要拿去排查的那句话。
      meta.textContent = a.stateReason || '注册或自证没通过';
    } else {
      meta.textContent = [DEPS_TEXT[a.depsScope] ?? a.depsScope, when(a.installedAt)]
        .filter(Boolean)
        .join(' · ');
    }

    el.append(top, repo, meta);

    // 依赖没装成是**另一件事**:插件可能注册成功了,但它的依赖被整份拒了。
    // 合进上面那行会让人以为"接上了"就等于"依赖也齐了"。
    if (a.depsError) {
      const deps = document.createElement('span');
      deps.className = 'ga-deps';
      deps.textContent = `依赖：${a.depsError}`;
      el.append(deps);
    }

    const where = document.createElement('code');
    where.className = 'ga-where';
    where.textContent = a.installPath;

    const row = document.createElement('div');
    row.className = 'ga-acts';
    const del = document.createElement('button');
    del.className = 'ga-btn ga-danger';
    del.type = 'button';
    del.textContent = '移除';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      cb.onUninstall(a.name);
    });
    row.append(where, del);
    el.append(row);
    return el;
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

    list.replaceChildren();
    if (rows === null) {
      // 「没拉到」不是「一个都没装」。空白会让人以为自己接过的项目丢了。
      const e = document.createElement('div');
      e.className = 'sf-empty';
      e.textContent = '拉不到已接进来的项目 —— 后端没接上，不是你没接过';
      list.append(e);
      n.textContent = '';
      return;
    }
    n.textContent = String(rows.length);
    if (!rows.length) {
      const e = document.createElement('div');
      e.className = 'sf-empty';
      e.textContent = '还没接过。下面填一个仓库地址就行 —— 不用改代码，也不用重启。';
      list.append(e);
      return;
    }
    for (const a of rows) list.append(card(a));
  }

  function clearForm(): void {
    fUrl.value = '';
    fRef.value = '';
  }

  return { root, render, clearForm };
}
