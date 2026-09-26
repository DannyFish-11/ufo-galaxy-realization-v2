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
  // 停:一个实心的方块。线框方块在 15px 上读起来像一个空的复选框。
  stop: 'M8 8h8v8H8z',
  // 喂入口那三块。图要认得出是什么,字就不用解释它是什么。
  image: 'M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6M8.5 9.5h.01',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5',
  link: 'M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1',
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
    stoppable: boolean,
  ): void;
}

export interface DockCallbacks {
  onSend(text: string): void;
  /** 让它现在住手。只在发送键变成停止键的时候按得到(见 render 的 stoppable)。 */
  onStop(): void;
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
  // 输入条上不再重复一遍"现在用的是哪个模型"。
  //
  // 上一版在这儿放了「A 档 · Gemma 4 · E4B」。所有者的原话:「对话栏没有必要
  // 再放一遍,它是什么模型,有一个地方能让他知道,还有一个地方能让他再调整,
  // 能确保意思被准确传达就可以了,不需要通篇什么地方都要放一下」。
  //
  // 而且这台机器上它已经有两个归宿了:左栏「接上了什么」里的那一行(知道),
  // 设置浮层里的「本机模型」(调整)。第三处只是让整面更厚,不多说一件事。
  /**
   * 液态玻璃:**光跟着手走。**
   *
   * Apple 那份材质说明里的一句话是关键 —— 这层材质"不会完全遮蔽底层内容",
   * 并且"在响应直接触摸时会强调动效"。前半句这条输入条已经做到了(它是透的,
   * 底下那道坡照样透上来);后半句还没有:它此刻是一块**不动的**玻璃。
   *
   * 所以加一道高光,位置跟着指针。这不是装饰 —— 玻璃之所以看起来是玻璃,
   * 靠的就是"光在它表面的位置随视角变"。不动的高光是印上去的,动的才是反射。
   *
   * 只记位置,不记时间:CSS 那边用 transition 把它追过去,所以手停下来光会
   * **跟过去再停住**,而不是死跟着指针。那一点点滞后就是"液态"的来源。
   */
  field.addEventListener('pointermove', (e) => {
    const r = field.getBoundingClientRect();
    field.style.setProperty('--lx', `${((e.clientX - r.left) / r.width) * 100}%`);
    field.style.setProperty('--ly', `${((e.clientY - r.top) / r.height) * 100}%`);
    field.dataset['lit'] = 'true';
  });
  field.addEventListener('pointerleave', () => {
    delete field.dataset['lit'];
  });

  /**
   * 发送键,在它忙的时候就是停止键。
   *
   * **同一个位置,不另加一个键。** 它在回答、在念、在动你的鼠标键盘的时候,人要找的
   * 就是「怎么让它停」—— 而手本来就在这儿。另开一个位置的话,那一刻人得先找到它。
   *
   * 回车照旧是发送:忙的时候接着打字、接着说,是正当的;按停止只能是有意的那一下。
   */
  const send = document.createElement('button');
  send.className = 'send';
  send.type = 'button';
  const sendIcon = icon(ICONS.send, 15, 2);
  const stopIcon = icon(ICONS.stop, 13, 2);
  let stoppable = false;
  function paintSend(): void {
    send.dataset['mode'] = stoppable ? 'stop' : 'send';
    send.setAttribute('aria-label', stoppable ? '停止' : '发送');
    send.title = stoppable ? '让它现在停下' : '';
    send.replaceChildren(stoppable ? stopIcon : sendIcon);
  }
  paintSend();
  field.append(input, send);

  function submit(): void {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    cb.onSend(text);
  }
  send.addEventListener('click', () => {
    if (stoppable) cb.onStop();
    else submit();
  });
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
   * 三块图标格,**一个词,不解释。**
   *
   * 上一版是四张带副行的卡,每张底下一句机制说明。所有者看了之后的原话:
   * 「用很明显的图片什么的,然后上面写就是……这种就够了,犯不着解释这么一大通」。
   * 对 —— 这是 HUD,不是说明书。图认得出是什么,字就不用再说一遍它是什么。
   *
   * 「圈一块屏幕」整条去掉了。所有者:「到时候面板一整个好了,直接在上面一圈
   * 就行了,不需要刻意把它放在那块再解释」。一个本该在画面上直接做的动作,
   * 塞进菜单里当一个条目,本身就是绕路。
   *
   * **没接上的那块仍然不许装作能用。** 但也不再占三行字去说:格子压暗、点不动,
   * 底下一个「还没接」,完整的那句话进 title。屏幕上短,事实一个字没少。
   */
  const FEED_ITEMS = [
    { key: 'image', label: '图片', accept: 'image/*', why: '' },
    { key: 'file', label: '文件', accept: '*/*', why: '' },
    {
      key: 'link',
      label: '链接',
      accept: '',
      why: '还没接上 —— 抓取与正文提取尚未接进喂入口，点了不会有反应',
    },
  ] as const;

  for (const spec of FEED_ITEMS) {
    const item = document.createElement('button');
    item.className = 'pop-tile';
    item.type = 'button';
    item.append(icon(ICONS[spec.key], 21, 1.5));
    const t = document.createElement('span');
    t.className = 'pop-tile-t';
    t.textContent = spec.label;
    item.append(t);
    if (spec.accept) {
      item.title = spec.label;
      item.addEventListener('click', () => {
        void platform()
          .pickFiles(spec.accept)
          .then((files) => {
            // 用户按了取消 —— 什么都不做是对的,但也不该假装发生了什么。
            if (files.length) cb.onFeed(files);
          });
      });
    } else {
      // 没接上的:照画、照显示,但点不动,并且说得出为什么。
      item.dataset['unwired'] = 'true';
      item.disabled = true;
      item.title = spec.why;
      const n = document.createElement('span');
      n.className = 'pop-tile-n';
      n.textContent = '还没接';
      item.append(n);
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
    canStop: boolean,
  ): void {
    if (canStop !== stoppable) {
      stoppable = canStop;
      paintSend();
    }
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
  }


  return { root: wrap, render };
}
