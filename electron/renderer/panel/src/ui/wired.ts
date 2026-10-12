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
 * 3. **写实际的那个东西,不写一个形容词。** 本体写正在答话的 Agent 叫什么,容器写是 docker 还是
 *    podman,服务写验过几个 / 一共几个,感知写此刻是不是正在感知 —— 都是后端说的,面板不编。
 *    没有就写「无」(所有者要求),原委进悬停那一句。
 */
import type { DeviceRow, PerceptionView, TierView } from '../types';
import type { PanelSelf, UserProvider } from '../transport';
import { modelLabel } from './model_name';

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
  /**
   * 右边那几个字:**现在到底是什么情况**。不许为空。
   *
   * 要**短**。这是 HUD 上常驻的一列,不是一份报告 —— 所有者看了上一版的原话是
   * 「文字信息密度还是太厚了,你这不有些脱离 HUD 的设计」。一眼扫过去要能扫完,
   * 扫不完就等于没人看。完整的那句话进 `why`,鼠标停一下才出来。
   */
  readonly detail: string;
  /**
   * 补一句原委。左栏那一列窄,`detail` 长了会被切掉 —— 被切掉的那半句正好是
   * 「那下一步该看哪儿」,而那是最有用的一半。所以短的那句摆在屏幕上,
   * 长的那句进 `title`,一个字都不丢。
   */
  readonly why?: string;
}

/** 六行的名字,自上而下。名字短:这一列窄,所有者要的是一眼扫完。 */
const NAMES = ['本体', '模型', '服务', '设备', '感知', '容器'] as const;

/** 后端设备名册里这台电脑自己那一条的编号(core/routes/panel.py::build_panel_feed 总会插这一条)。 */
const LOCAL_DEVICE_ID = 'desktop_local';

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
  /** 本体是谁、容器用的哪个(``/api/v1/panel/self``)。null = 还没问到 */
  readonly self: PanelSelf | null;
}): readonly WiredRow[] {
  const rows: WiredRow[] = [];

  // ── 本体(后端)没连上:六行**全部写「无」**(所有者要求)。底下几行本来就问不到,
  //    与其显示上一次的样子,不如一眼看出「现在什么都没有」。原委进悬停那一句。──
  if (!input.connected) {
    for (const name of NAMES) {
      rows.push({
        name,
        state: 'off',
        detail: '无',
        why: name === '本体' ? '本体（后端）没连上' : '本体（后端）没连上 —— 这一条问不到',
      });
    }
    return rows;
  }

  // ── 本体:写**正在答话的那个 Agent 的名字**(后端实例的类名,比如 OpenClawd),不写「连着」 ──
  if (input.self === null) {
    rows.push({ name: '本体', state: 'unknown', detail: '没拉到', why: '连上了，但还没问到在答话的是哪个 Agent' });
  } else {
    rows.push({
      name: '本体',
      state: input.self.agent ? 'on' : 'off',
      detail: input.self.agent || '无',
      why: '后端连着，答话的是这个 Agent',
    });
  }

  // ── 本机模型:看**实际加载的型号**,不看选了哪一档。型号首字母大写只是显示 ──
  if (input.tiers === null) {
    rows.push({
      name: '模型',
      state: 'unknown',
      detail: '没拉到',
      why: '档位目录没拉到 —— 不是没有档位，是这次没问到',
    });
  } else {
    const models = input.tiers.slots.filter((s) => s.model);
    if (models.length) {
      rows.push({
        name: '模型',
        state: 'on',
        detail: models.map((s) => modelLabel(s.model)).join(' + '),
        why: `标签原文 ${models.map((s) => s.model).join(' + ')}`,
      });
    } else if (input.tiers.current) {
      // 选了档,但这一档没报出在跑哪个型号 —— 不是"没有模型",是"没报"。
      rows.push({
        name: '模型',
        state: 'part',
        detail: `${input.tiers.current} 档`,
        why: `选了 ${input.tiers.current} 档，但这一档没报出在跑哪个型号`,
      });
    } else {
      rows.push({ name: '模型', state: 'off', detail: '无', why: '还没选档' });
    }
  }

  // ── 我的模型服务:写「验过的 / 一共」(比如 1/1)。`live` 才算通,**没验过的不算** ──
  if (input.providers === null) {
    rows.push({
      name: '服务',
      state: 'unknown',
      detail: '没拉到',
      why: '端点列表没拉到 —— 不是一个都没加，是这次没问到',
    });
  } else if (input.providers.length === 0) {
    rows.push({ name: '服务', state: 'off', detail: '无', why: '一个端点都没加过' });
  } else {
    const live = input.providers.filter((p) => p.state === 'live');
    const rest = input.providers.length - live.length;
    rows.push({
      name: '服务',
      state: live.length === 0 ? 'off' : rest === 0 ? 'on' : 'part',
      detail: `${live.length}/${input.providers.length}`,
      why:
        live.length === 0
          ? `加了 ${input.providers.length} 个端点，一个都还没验过 —— 没验过的不参与选路`
          : `${input.providers.length} 个端点里 ${live.length} 个验过了` + (rest ? `，${rest} 个还没验` : ''),
    });
  }

  // ── 设备:**只写实时的设备数**(所有者要求)= 这台电脑 + 别的在线设备;
  //    在线才算,降级的单独记进悬停那一句 —— 降级和离线是两件事,别并成一个数。
  //    名册里**有**这台电脑自己那一条(后端 build_panel_feed 总会插一条 `desktop_local`「本机 Desktop」)——
  //    以前这里当它不在、再 +1,只有一台电脑时写成「2 台」(所有者:「为啥只有一个设备会显示两个」)。
  //    所以先把本机那条剔掉,再 +1:名册里有没有它,数都对。────────
  const others = input.devices.filter((d) => d.id !== LOCAL_DEVICE_ID);
  const online = others.filter((d) => d.state === 'online').length;
  const degraded = others.filter((d) => d.state === 'degraded').length;
  rows.push({
    name: '设备',
    state: degraded ? 'part' : 'on',
    detail: `${online + 1} 台`,
    why:
      others.length === 0
        ? '只有这台电脑 —— 名册上没有别的设备'
        : `这台电脑 + ${online} 台在线` + (degraded ? `，另有 ${degraded} 台降级` : ''),
  });

  // ── 感知:**实时的** —— 此刻正在感知就写「正在感知」,否则写「无」(所有者要求)。
  //    「正在」= 后端契约里的 `is_sensing`(任一模态此刻 live),隐私暂停时一律不算。为什么不在,进悬停那一句。──
  if (input.perception === null) {
    rows.push({ name: '感知', state: 'unknown', detail: '没收到', why: '还没收到感知状态' });
  } else if (input.perception.is_sensing && !input.perception.privacy_paused) {
    const live = input.perception.modalities.filter((m) => m.state === 'live').length;
    rows.push({
      name: '感知',
      state: 'on',
      detail: '正在感知',
      why: `${input.perception.modalities.length} 条模态里 ${live} 条正在收`,
    });
  } else {
    rows.push({
      name: '感知',
      state: 'off',
      detail: '无',
      why:
        input.perception.source === 'unwired'
          ? '这个进程里没有感知库 —— 看、听这几条都不在'
          : input.perception.privacy_paused
            ? '你按了隐私暂停 —— 这是你要的，不是故障'
            : '此刻没有一条模态在收',
    });
  }

  // ── 容器:写**实际用的那个运行时**(docker / podman),一个都没有就写「无」 ──────
  if (input.self === null) {
    rows.push({ name: '容器', state: 'unknown', detail: '没拉到', why: '还没问到用的是哪个容器运行时' });
  } else if (input.self.containerRuntime) {
    rows.push({
      name: '容器',
      state: 'on',
      detail: input.self.containerRuntime,
      why: `容器运行时是 ${input.self.containerRuntime}`,
    });
  } else {
    rows.push({
      name: '容器',
      state: 'off',
      detail: '无',
      why: '这台机器上没找到 docker 或 podman（两个都装了而还没选过的，也先算没有）',
    });
  }

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
