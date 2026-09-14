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
import type { Bundle, TierView } from '../types';
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
  render(
    bundles: readonly Bundle[],
    tiers: TierView | null,
    tierGaps: readonly string[],
    popover: 'feed' | 'settings' | null,
  ): void;
}

export interface DockCallbacks {
  onSend(text: string): void;
  onTogglePopover(which: 'feed' | 'settings'): void;
  onToggleBundle(key: Bundle['key']): void;
  /** 打开那 332 个键的细调面。这个按钮从前不接任何东西 —— 一个死键。 */
  onOpenAllSettings(): void;
  /** 换本机模型档位。**不是开关** —— 见下面那一行的说明。 */
  onPickTier(key: string): void;
  /**
   * 用户挑好了文件。
   *
   * 从前这里是 `void platform().pickFiles(accept)` —— 拿到 File[] 之后**什么都
   * 不做**。选完文件、浮层收起、界面毫无变化,而用户以为喂进去了。这是这个仓库
   * 反复要躲的那类失效里最难察觉的一种:操作有反馈(浮层关了),结果没有。
   */
  onFeed(files: readonly File[]): void;
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
  /**
   * 输入条右侧那两小块:**现在用的是什么**。
   *
   * 借的是 Gemini 桌面版把 `Flash  Extended thinking` 低对比地摆在输入框里
   * 那个做法 —— 不是下拉、不是徽章,就是**当前事实**,点得动。
   *
   * 为什么值得搬:`renderTiers` 那段注释里写着「档位是唯一定义处」。既然是
   * 唯一定义处,它就该出现在**你即将用到它的那一行**,而不是要先点开设置浮层
   * 才看得见。你正要说话,而"这句话会被谁接住"就写在旁边。
   *
   * 两块分开而不是拼成一句:左边是档(A/B/C/D,你选的),右边是这一档**实际
   * 加载的型号**(后端给的)。拼成一句的话,"我选了 C 档"和"C 档现在真的在跑
   * 这两个型号"就分不开了 —— 而这个仓库栽过的正是这种。
   */
  const now = document.createElement('button');
  now.className = 'now';
  now.type = 'button';
  now.setAttribute('aria-label', '当前本机模型档位，点开设置');
  const nowTier = document.createElement('span');
  nowTier.className = 'now-tier';
  const nowModel = document.createElement('span');
  nowModel.className = 'now-model';
  now.append(nowTier, nowModel);
  now.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onTogglePopover('settings');
  });

  const send = document.createElement('button');
  send.className = 'send';
  send.type = 'button';
  send.setAttribute('aria-label', '发送');
  send.append(icon(ICONS.send, 15, 2));
  field.append(input, now, send);

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
  /**
   * 每一条:**标题是你想干什么,副行是它实际会做什么。**
   *
   * 借的是 Gemini 桌面版 Trending 那几张卡的写法 ——
   * 「Organize my connected folders / Find unorganized files…, group by type,
   * archive the clutter」。标题用人的意图,副行说清机制。
   *
   * 上一版这里是四个光秃秃的词:图片 / 文件 / 圈一块屏幕 / 网页链接。它们是
   * **分类名**,不是"它会做什么" —— 点"图片"之后发生什么、喂进去之后它被当成
   * 什么用,一个字都没有。而后两条根本还没接上,光看四个并排的词完全看不出来。
   *
   * 副行同时承担一件更要紧的事:**没接上的那两条,就在副行里说出来。** 藏起来
   * 的话,"没这个功能"和"有但还没接"在界面上一模一样。
   */
  const FEED_ITEMS = [
    {
      title: '喂一张图进去',
      how: '选中的图直接进这轮对话，并按记忆门存下来（原图留在 media_store）',
      accept: 'image/*',
    },
    {
      title: '喂一份文件进去',
      how: '读成文字进这轮对话；存进记忆时带上来源，不以第一人称写入',
      accept: '*/*',
    },
    {
      title: '圈一块屏幕',
      how: '还没接上 —— 圈选这条路径尚未接到感知侧，点了不会有反应',
      accept: '',
    },
    {
      title: '给一个网页链接',
      how: '还没接上 —— 抓取与正文提取尚未接进喂入口，点了不会有反应',
      accept: '',
    },
  ] as const;

  for (const spec of FEED_ITEMS) {
    const item = document.createElement('button');
    item.className = 'pop-item pop-card';
    item.type = 'button';
    const t = document.createElement('span');
    t.className = 'pop-card-t';
    t.textContent = spec.title;
    const h = document.createElement('span');
    h.className = 'pop-card-h';
    h.textContent = spec.how;
    item.append(t, h);
    if (spec.accept) {
      item.addEventListener('click', () => {
        void platform()
          .pickFiles(spec.accept)
          .then((files) => {
            // 用户按了取消 —— 什么都不做是对的,但也不该假装发生了什么。
            if (files.length) cb.onFeed(files);
          });
      });
    } else {
      // 没接上的:**照画、照显示,但明说点不动。** 藏起来的话人只会反复去点。
      item.dataset['unwired'] = 'true';
      item.disabled = true;
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
  more.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onOpenAllSettings();
  });
  const tierHost = document.createElement('div');
  tierHost.className = 'tier-row';
  settings.append(bundleHost, tierHost, more);

  wrap.append(dock, feed, settings);

  /**
   * 第五行:本机模型档位。
   *
   * **它长得和上面那四档不一样,因为它不是一回事。** 上面是开关:一个开关问
   * 「这项能力开不开」。这里是四选一:A 轻量本地 / B 全模态单模型 / C 双模型·
   * 35B 推理位 / D 双模型·9B 推理位 —— 问的是「用哪一套」。
   *
   * 三种做不得的画法,以及为什么:
   *
   * 1. **压成一个循环按钮**(点一下 A→B→C→D)。那样人看不见一共有几档,更看不见
   *    自己这台机器跑不动哪几档 —— 而后者恰恰是选档时唯一重要的信息。上面那四档
   *    里 GALAXY_AUTONOMY 用了循环,是因为它只有三档且每一档都随时能用;档位不是。
   * 2. **把跑不动的档藏起来。** 藏了之后「这台机器没有 C 档」和「C 档在那儿但你
   *    的显卡带不动」在界面上一模一样,而这两件事的下一步完全不同(一个是没救,
   *    一个是换显卡/换量化)。所以跑不动的档照画,写清楚为什么。
   * 3. **硬件没探到时当成能跑。** 那是把「不知道」画成「能跑」。unknown 单独一种
   *    样子,点得动(人可能就是知道自己机器行),但不假装评估过。
   *
   * 细调的逃生口在「全部设置 → 思考与执行 → GALAXY_MODEL_TIER」:那里能把档位
   * 钉死成一个固定值,也能留空让系统按能力自己判。这一行是常用路径,那里是兜底。
   */
  function renderTiers(view: TierView | null, gaps: readonly string[]): void {
    tierHost.replaceChildren();

    const head = document.createElement('div');
    head.className = 'tier-head';
    const name = document.createElement('span');
    name.className = 'bundle-name';
    name.textContent = '本机模型';
    const note = document.createElement('span');
    note.className = 'bundle-note';
    head.append(name, note);
    tierHost.append(head);

    if (view === null) {
      // **说清楚是「没拉到」。** 空着的话,和「这台机器没有本机档位」分不开。
      note.textContent = '读不到档位目录 —— 后端没接上，不是没有档位';
      note.dataset['unwired'] = 'true';
      return;
    }

    const cur = view.tiers.find((t) => t.key === view.current);
    // 当前档的两位(感知位 / 推理位)如实报出来 —— 「C 档」三个字说不出实际在跑
    // 哪两个型号,而那才是人想确认的东西。
    const slots = view.slots.filter((s) => s.model).map((s) => `${s.role} ${s.model}`);
    note.textContent = cur
      ? slots.length
        ? `${cur.label} · ${slots.join(' + ')}`
        : cur.label
      : view.current
        ? `当前 ${view.current} 档（目录里没有这一档）`
        : '还没选定档位';

    const chips = document.createElement('div');
    chips.className = 'sf-stages tier-stages';
    // **四选一,要说出来是四选一。** 这四个钮此前只有 data-picked(给 CSS 用),
    // 无障碍上就是四个分别叫 "A" "B" "C" "D" 的光秃秃按钮 —— 读屏读不出一共几档、
    // 更读不出现在在哪一档。上面那几行 bundle 早就分了"两态用 aria-pressed、
    // 多态用 data-state",这一行是漏网的。单选组的正确形状是 radiogroup/radio。
    chips.setAttribute('role', 'radiogroup');
    chips.setAttribute('aria-label', '本机模型档位');
    // **按档位名排,不按后端给的顺序。** core/model_catalog.py 的 _TIERS 是个 dict,
    // 迭代出来是定义顺序(A B D C)—— 那是后端的内部次序,不是给人看的次序,D 排在
    // C 前面读起来就是错的。「有哪几档」归后端,「按什么顺序摆」归这里。
    const ordered = [...view.tiers].sort((a, b) => a.key.localeCompare(b.key));
    for (const t of ordered) {
      const chip = document.createElement('button');
      chip.className = 'stage';
      chip.type = 'button';
      chip.textContent = t.key;
      const picked = t.key === view.current;
      chip.dataset['picked'] = String(picked);
      chip.dataset['fit'] = t.fit;
      chip.setAttribute('role', 'radio');
      chip.setAttribute('aria-checked', String(picked));
      // 光一个 "A" 读不出是什么档 —— 把档名也给读屏。跑不动的那几档在这里就说清楚,
      // 因为它们照样点得动(见上面的说明),看不见 title 的人更需要这句。
      chip.setAttribute(
        'aria-label',
        t.fit === 'ok' ? t.label : `${t.label}（装不下:${t.fitReason}）`,
      );
      // 跑不动的照画、照点得动 —— 拦住的话,人连"为什么"都看不到。
      // 但要在标题上把原因说全:装不下哪几个型号,后端的原话是什么。
      chip.title =
        t.fit === 'ok'
          ? `${t.label}\n${t.desc}`
          : `${t.label}\n${t.desc}\n\n装不下:${t.fitReason}` +
            (t.blockedBy.length ? `（${t.blockedBy.join('、')}）` : '');
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        cb.onPickTier(t.key);
      });
      chips.append(chip);
    }
    tierHost.append(chips);

    // 换档后后端报回来的缺依赖。**只写日志等于没说** —— 用户会以为换成了,
    // 而那一档其实跑不起来。
    for (const g of gaps) {
      const warn = document.createElement('div');
      warn.className = 'bundle-note';
      warn.dataset['unwired'] = 'true';
      warn.textContent = g;
      tierHost.append(warn);
    }
  }

  function render(
    bundles: readonly Bundle[],
    tiers: TierView | null,
    tierGaps: readonly string[],
    popover: 'feed' | 'settings' | null,
  ): void {
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
      // 「管 N 个键」拿掉了:那个数字不影响任何决定,却占着本该说清这一档管什么的
      // 位置。**有键被手改过仍然要说** —— 那条是真会影响判断的:档位显示「开」而
      // 底下某个键被人改成了关,不说出来就是同一个事实两处各存、且没人看得见。
      // 副标题可以是空的(名字已经说完了这一档管什么,比如「声字同文」;或者右边
      // 那枚牌子已经把当前档写出来了,比如「自主」)。**但留痕不能跟着一起没**:
      // 空副标题时那两句照打,只是别带前导的「 · 」。
      const tail = b.unwired
        ? `没接上(主键 ${b.primary || '未知'} 不存在)`
        : b.overrides > 0
          ? `有 ${b.overrides} 项手改过`
          : '';
      note.textContent = tail ? (b.note ? `${b.note} · ${tail}` : tail) : b.note;
      // 什么都没有就别占位 —— 空的 note 仍是 display:block,会给行凭空撑出一截。
      note.hidden = note.textContent === '';
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

    renderTiers(tiers, tierGaps);
    renderNow(tiers);
  }

  /**
   * 输入条里那两小块的取值。
   *
   * 四种处境各说各的 —— 这一行**最容易**被写成"没值就空着",而空着的时候
   * 「读不到目录」「还没选档」「选了个目录里没有的档」三件事长得一模一样。
   */
  function renderNow(view: TierView | null): void {
    if (view === null) {
      // 拉不到目录。空着的话,和"这台机器没有本机档位"分不开。
      nowTier.textContent = '档位读不到';
      nowModel.textContent = '';
      now.dataset['state'] = 'unwired';
      now.title = '读不到档位目录 —— 后端没接上，不是没有档位';
      return;
    }
    const cur = view.tiers.find((t) => t.key === view.current);
    if (!cur) {
      now.dataset['state'] = view.current ? 'unwired' : 'none';
      nowTier.textContent = view.current ? `${view.current} 档` : '未选档';
      nowModel.textContent = '';
      now.title = view.current
        ? `当前 ${view.current} 档，但目录里没有这一档`
        : '还没选定档位，点开设置里的「本机模型」';
      return;
    }
    now.dataset['state'] = 'ok';
    nowTier.textContent = `${cur.key} 档`;
    // 右边只放**实际加载的型号**,而且只放一个 —— 这是一行内联标签,不是清单。
    // 两位都有时取推理位那个(它决定这句话由谁想出来);详细的两位在设置里那行。
    const models = view.slots.filter((sl) => sl.model);
    nowModel.textContent = models.length ? models[models.length - 1]!.model : '';
    now.title = models.length
      ? `${cur.label}\n现在跑的是：${models.map((sl) => `${sl.role} ${sl.model}`).join(' + ')}`
      : `${cur.label}\n这一档还没报出在跑哪个型号`;
  }

  return { root: wrap, render };
}
