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
 * ## 接入形态是三档,而且是**并列**的三档
 *
 * · MCP 工具    根上有 mcp_tool.json,注册成了一个 MCP 工具
 * · Skill       根上有 skill.json 或 SKILL.md,注册成了一个 Skill
 * · 项目完整形式  哪个契约都没有 —— 代码落盘,没注册成任何可调用的工具
 *
 * **第三档不是失败。** MCP / Skill 是 GitHub 项目的**交集**,不是它的定义:
 * 接一个仓库可能是为了拿它跑实验、读它、拿它当素材。把它画成"降级"或"没接上",
 * 等于规定了"接项目 = 接工具",而那不是这个功能的全集。
 *
 * 形态之外还有一个**正交**的位:这次接入到底成没成(``ok``)。它只对前两档有意义
 * —— 项目形态没有"注册"这一步,也就无所谓成败。没成的时候必须说出**卡在哪一步**,
 * 那句话就是他要拿去排查的东西;画成绿点等于告诉用户"这个工具能用",而模型
 * 调它的时候才会报错。这和隔壁 live/declared 不许共用一个绿点是同一条理由。
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

/** 接入形态。三档并列 —— 每一档都是一句完整的话,不是"成功/降级"的两个程度。 */
const FORM_TEXT: Record<string, string> = {
  mcp: '以 MCP 工具形式接入',
  skill: '以 Skill 形式接入',
  project: '以项目完整形式接入',
};

/** 三个接入槽的名字。顺序就是安装器的判定顺序:mcp → skill → SKILL.md。 */
const CONTRACT_TEXT: Record<GitHubContractKey, string> = {
  mcp: 'MCP 工具',
  skill: 'Skill',
  skill_md: 'SKILL.md',
};

/**
 * 一个槽位的四态。**和左栏底下那块「接上了什么」同一套话** —— 用深度,不用颜色。
 *
 * on    这份契约在,而且就是它接上的
 * part  这份契约在,但没走通(被另一份抢了先,或者注册失败)
 * off   根上没有这份契约
 */
function slotState(a: GitHubAddon, key: GitHubContractKey): 'on' | 'part' | 'off' {
  const c = a.contracts[key];
  if (!c.present) return 'off';
  if (c.chosen && a.ok) return 'on';
  return 'part';
}

/** 没接上的时候说什么。只有前两档会走到这儿 —— 项目形态没有"注册"这一步。 */
const FAILED_TEXT: Record<string, string> = {
  mcp: '本该接成 MCP 工具，没接上',
  skill: '本该接成 Skill，没接上',
  project: '拿下来了，但没接上',
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
    el.dataset['form'] = a.form;
    el.dataset['ok'] = String(a.ok);

    // ── 左:项目本体 ────────────────────────────────────────────────────
    //
    // 这一侧**只说这个仓库本身**:叫什么、从哪儿来的哪一次提交、依赖装在哪、
    // 落在磁盘的什么位置。它接没接成工具是右边那一侧的事。
    //
    // 分成左右两栏,是因为这两件事本来就是两件事:一个 GitHub 项目接进来是完整的
    // 一件事,"它顺带填上了哪个接入槽"是另一件。挤成一列的时候,项目本身的信息
    // 会被接入状态的措辞盖过去 —— 而多数时候人是来找项目的。
    const left = document.createElement('div');
    left.className = 'ga-left';

    const name = document.createElement('b');
    name.className = 'ga-name';
    name.textContent = a.name;

    const repo = document.createElement('code');
    repo.className = 'ga-repo';
    // commit 截到 8 位:够认人,又不会把一行挤爆。ref 和 commit 都要有 ——
    // 「装的是 main」和「装的是 main 上的哪一次提交」是两件事。
    repo.textContent = `${a.owner}/${a.repo}@${a.ref}${a.commit ? ` · ${a.commit.slice(0, 8)}` : ''}`;

    const meta = document.createElement('span');
    meta.className = 'ga-meta';
    meta.textContent = [DEPS_TEXT[a.depsScope] ?? a.depsScope, when(a.installedAt)].filter(Boolean).join(' · ');

    left.append(name, repo, meta);

    // 依赖没装成是**另一件事**:它可能注册成功了,但依赖被整份拒了。
    // 合进上面那行会让人以为"接上了"就等于"依赖也齐了"。
    if (a.depsError) {
      const deps = document.createElement('span');
      deps.className = 'ga-deps';
      deps.textContent = `依赖：${a.depsError}`;
      left.append(deps);
    }

    const where = document.createElement('code');
    where.className = 'ga-where';
    where.textContent = a.installPath;
    left.append(where);

    // ── 右:三个接入槽 ──────────────────────────────────────────────────
    //
    // 三个**都摆出来**,不是只画命中的那一个。摆出来才说得清"这个仓库根上有
    // 什么、没有什么" —— 只画命中的那一个,另外两个就成了一片说不清的空白。
    const right = document.createElement('div');
    right.className = 'ga-right';

    const slots = document.createElement('div');
    slots.className = 'ga-slots';
    for (const key of GITHUB_CONTRACT_KEYS) {
      const row = document.createElement('div');
      row.className = 'ga-slot';
      row.dataset['state'] = slotState(a, key);
      const dot = document.createElement('span');
      dot.className = 'ga-dot';
      const label = document.createElement('span');
      label.className = 'ga-slot-name';
      label.textContent = CONTRACT_TEXT[key];
      row.append(dot, label);
      slots.append(row);
    }

    // 一句结论。三个槽位说的是"根上有什么",这一句说的是"于是它以什么身份接进来了"
    // —— 两者都要有:光看槽位看不出注册到底成没成。
    const verdict = document.createElement('span');
    verdict.className = 'ga-verdict';
    verdict.textContent = a.ok ? (FORM_TEXT[a.form] ?? a.form) : (FAILED_TEXT[a.form] ?? '没接上');

    right.append(slots, verdict);

    if (!a.ok) {
      // 没接上的时候,**卡在哪一步**比什么都重要 —— 这就是他要拿去排查的那句话。
      const why = document.createElement('span');
      why.className = 'ga-why';
      why.textContent = a.formDetail || '注册或自证没通过';
      right.append(why);
    } else if (a.form === 'project') {
      // 项目形态:必须**说出**它没注册成工具。不说的话,这张卡片看起来和一个
      // 真能调用的工具没有任何区别 —— 那就从"把成功说成失败"翻到了另一头。
      const why = document.createElement('span');
      why.className = 'ga-why';
      why.textContent = '三份契约一份都没有，所以没有注册成可调用的工具';
      right.append(why);
    }

    const del = document.createElement('button');
    del.className = 'ga-btn ga-danger';
    del.type = 'button';
    del.textContent = '移除';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      cb.onUninstall(a.name);
    });
    right.append(del);

    el.append(left, right);
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
