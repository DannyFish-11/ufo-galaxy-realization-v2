/**
 * 左栏底下那一小块:**现在真的接上了什么。**
 *
 * 借的是 Gemini 桌面版侧栏那段 `Connected folders` —— 它把"当前实际连着的东西"
 * 直接列出来,而不是塞进设置里的一个开关。
 *
 * 为什么这个仓库特别需要它
 * ------------------------
 * 这一整轮真机排查里反复出现的那类缺陷,只有一个形状:**看起来接上了,其实没有。**
 * 托盘说"右下角常驻"而图标根本没出现;档位说"C 档"而目录压根没拉到;探测超时
 * 却被渲染成"未安装"。每一次的修法都一样 —— 把"到底接没接上"摆到明面上。
 *
 * 这块就是那件事的常驻形态:一眼扫过去,哪条通、哪条降级、哪条不通、哪条**根本
 * 还不知道**。
 *
 * 三条规矩
 * --------
 * 1. **不新增权威。** 每一行都是从 store 里已有的状态**推**出来的,一个字段都不
 *    自己存。同一个事实两处各存一份,迟早一处说通、另一处说不通,而且没人看得见。
 * 2. **四态,不是布尔。** 通 / 降级 / 不通 / **不知道**。第四种最要紧:后端没拉到
 *    (`null`)和后端说"一个都没有"(空数组)是两件事,画成同一个样子就是把"不知道"
 *    说成了"没有"。
 * 3. **缺的那条也列出来。** 容器运行时现在**没有**面板能问的接口 —— 那就如实写成
 *    "面板还没接这条",而不是从清单里省掉。省掉的话,这张清单看起来就是完整的,
 *    而它并不完整。
 */
import type { DeviceRow, PerceptionView, TierView } from '../types';
import type { UserProvider } from '../transport';

/**
 * 一行的状态。**四态**,理由见文件头第 2 条。
 *
 * - `on`      通了,而且是问过之后确认的
 * - `part`    接上了但不完整(有几条降级 / 没验过)
 * - `off`     确实没有 —— 问过了,答案是没有
 * - `unknown` **没问到**。不是没有,是这条路还没接上,或者后端没答
 */
export type WiredState = 'on' | 'part' | 'off' | 'unknown';

export interface WiredRow {
  /** 这一条叫什么 */
  readonly name: string;
  readonly state: WiredState;
  /** 右边那句:**现在到底是什么情况**,一句人话。不许为空。 */
  readonly detail: string;
  /**
   * 补一句原委。左栏那一列窄,`detail` 长了会被切掉 —— 被切掉的那半句正好是
   * 「那下一步该看哪儿」,而那是最有用的一半。所以短的那句摆在屏幕上,
   * 长的那句进 `title`,一个字都不丢。
   */
  readonly why?: string;
}

const LABEL: Record<WiredState, string> = {
  on: '通',
  part: '部分',
  off: '不通',
  unknown: '不知道',
};

/**
 * 把 store 的状态推成几行。**纯函数** —— 好让判据能直接喂状态、比结果,
 * 不用去碰 DOM。
 */
export function deriveWired(input: {
  readonly tiers: TierView | null;
  readonly providers: readonly UserProvider[] | null;
  readonly devices: readonly DeviceRow[];
  readonly perception: PerceptionView | null;
  readonly connected: boolean;
}): readonly WiredRow[] {
  const rows: WiredRow[] = [];

  // ── 后端本身。它不通的话,底下几行全是"不知道",得先说清这一条 ──────────
  rows.push(
    input.connected
      ? { name: '后端', state: 'on', detail: '连着' }
      : { name: '后端', state: 'off', detail: '没连上 —— 底下几行都问不到' },
  );

  // ── 本机模型:看**实际加载的型号**,不看选了哪一档 ─────────────────────
  if (input.tiers === null) {
    rows.push({ name: '本机模型', state: 'unknown', detail: '档位目录没拉到' });
  } else {
    const models = input.tiers.slots.filter((s) => s.model);
    if (models.length) {
      rows.push({
        name: '本机模型',
        state: 'on',
        detail: models.map((s) => s.model).join(' + '),
      });
    } else if (input.tiers.current) {
      // 选了档,但这一档没报出在跑哪个型号 —— 不是"没有模型",是"没报"。
      rows.push({
        name: '本机模型',
        state: 'part',
        detail: `${input.tiers.current} 档，但没报出在跑哪个型号`,
      });
    } else {
      rows.push({ name: '本机模型', state: 'off', detail: '还没选定档位' });
    }
  }

  // ── 我的模型服务:`live` 才算通。**没验过的不算** ──────────────────────
  if (input.providers === null) {
    rows.push({ name: '模型服务', state: 'unknown', detail: '端点列表没拉到' });
  } else if (input.providers.length === 0) {
    rows.push({ name: '模型服务', state: 'off', detail: '一个都没加' });
  } else {
    const live = input.providers.filter((p) => p.state === 'live');
    const rest = input.providers.length - live.length;
    rows.push({
      name: '模型服务',
      state: live.length === 0 ? 'off' : rest === 0 ? 'on' : 'part',
      detail:
        live.length === 0
          ? `${input.providers.length} 个都没验过`
          : rest === 0
            ? `${live.length} 个验过了`
            : `${live.length} 个验过，${rest} 个没验过`,
    });
  }

  // ── 设备:在线才算。降级和离线是两件事,别并成一个数 ────────────────────
  const online = input.devices.filter((d) => d.state === 'online').length;
  const degraded = input.devices.filter((d) => d.state === 'degraded').length;
  if (input.devices.length === 0) {
    // 名册是空的。这台机器自己不进名册,所以空是正常的 —— 但也别说成"通"。
    rows.push({ name: '其他设备', state: 'off', detail: '名册上没有别的设备' });
  } else {
    rows.push({
      name: '其他设备',
      state: online === 0 ? 'off' : degraded ? 'part' : 'on',
      detail: degraded ? `${online} 台在线，${degraded} 台降级` : `${online} 台在线`,
    });
  }

  // ── 感知:四条模态。`source === 'unwired'` = 进程里根本没有感知库 ────────
  if (input.perception === null) {
    rows.push({ name: '感知', state: 'unknown', detail: '还没收到感知状态' });
  } else if (input.perception.source === 'unwired') {
    rows.push({ name: '感知', state: 'off', detail: '这个进程里没有感知库' });
  } else if (input.perception.privacy_paused) {
    // 按了隐私暂停 —— 这是**你要的**,不是故障。单独说。
    rows.push({ name: '感知', state: 'part', detail: '你按了隐私暂停' });
  } else {
    const on = input.perception.modalities.filter(
      (m) => m.state === 'live' || m.state === 'idle',
    ).length;
    const total = input.perception.modalities.length;
    rows.push({
      name: '感知',
      state: on === 0 ? 'off' : on === total ? 'on' : 'part',
      detail: `${on}/${total} 条在`,
    });
  }

  // ── 容器运行时:**面板问不到。** ───────────────────────────────────────
  //
  // 启动器那边是知道的(屏幕上会打「基础设施 · Podman」),但那条事实没有任何
  // 面板能调的接口。省掉这一行的话,这张清单看起来就是完整的 —— 而它不是。
  // 写成 unknown 并说明为什么,既不撒谎,也把下一步指出来了。
  rows.push({
    name: '容器运行时',
    state: 'unknown',
    detail: '面板还没接这条',
    why: '启动器屏幕上有（「基础设施 · Podman」那一行），但没有面板能调的接口',
  });

  return rows;
}

export interface WiredHandles {
  readonly root: HTMLElement;
  render(rows: readonly WiredRow[], slim: boolean): void;
}

export function createWired(): WiredHandles {
  const root = document.createElement('div');
  root.className = 'wired';

  const head = document.createElement('div');
  head.className = 'wired-head';
  head.textContent = '接上了什么';

  const list = document.createElement('div');
  list.className = 'wired-list';
  root.append(head, list);

  function render(rows: readonly WiredRow[], slim: boolean): void {
    root.dataset['slim'] = String(slim);
    list.replaceChildren();
    for (const r of rows) {
      const row = document.createElement('div');
      row.className = 'wired-row';
      row.dataset['state'] = r.state;
      // 收起时只剩一列点。**点本身仍带完整的那句话** —— 收起不该让事实消失,
      // 只是让它退到 title 里。
      row.title = r.why
        ? `${r.name}：${LABEL[r.state]} —— ${r.detail}。${r.why}`
        : `${r.name}：${LABEL[r.state]} —— ${r.detail}`;

      const dot = document.createElement('span');
      dot.className = 'wired-dot';

      const name = document.createElement('span');
      name.className = 'wired-name';
      name.textContent = r.name;

      const detail = document.createElement('span');
      detail.className = 'wired-detail';
      detail.textContent = r.detail;

      row.append(dot, name, detail);
      list.append(row);
    }
  }

  return { root, render };
}
