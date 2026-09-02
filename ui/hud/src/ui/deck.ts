/**
 * 左栏:一整根长框。
 *
 * 收起展开都是这一个框自己变宽变窄 —— 卡片和小块都长在框里。
 * 卡片放完之后露出来的就是**框自己的面**,那本来就是留白,不铺底也不描边。
 *
 * 三处刻意的做法,都是为了「像一叠真卡」:
 *
 * 1. **池子建一次就不再增删。** 滚一格换一张时,把退场那张换上新内容、
 *    不带过渡地瞬移到另一端候着,再让所有卡一起滑。每滚一格就重建整组
 *    DOM 的话,增删加重排,画面必顿 —— 那是水车做法与列表做法的分野。
 * 2. **看得见的那一格只有一张卡那么高。** 于是任何一张都不可能被完整
 *    露出来:抽出的那张上面压着已翻过的、下半截被后面几张盖住,最下面
 *    那张被框沿切掉。一叠卡本来就看不全。
 * 3. **抽出不是把整叠推开。** 那一格的位置是固定的,卡片进出那一格。
 *    前者是抽卡,后者只是挪位置。
 */
import type { MemoryCard } from '../types';
import { VISIBLE_CARDS, clampStart, type Store } from '../store';

/** 露出的上沿。也是没抽出任何一张时,整叠的间距。 */
const LIP = 40;
/** 已翻过去的那几张压在顶上,只露这么一线。 */
const TUCK = 13;
/** 池子比可见张数多一张 —— 进场的那张先在视野外候着。 */
const POOL = VISIBLE_CARDS + 1;
/** 滚多少像素算一格。太小会连跳,太大会觉得推不动。 */
const WHEEL_STEP = 90;

const svgNS = 'http://www.w3.org/2000/svg';

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  return node;
}

export interface DeckHandles {
  readonly root: HTMLElement;
  /** 外部改了状态之后重排。窗口尺寸变了也调它。 */
  render(): void;
}

export function createDeck(store: Store): DeckHandles {
  const rail = el('div', 'rail');
  const frame = el('div', 'frame');
  const deck = el('div', 'deck');
  const wheel = el('div', 'wheel');
  const thumb = el('div', 'thumb');
  const slot = el('div', 'slot');
  const stack = el('div', 'stack');
  const blocks = el('div', 'blocks');
  const rest = el('button', 'rest');

  wheel.setAttribute('aria-hidden', 'true');
  wheel.append(thumb);
  slot.append(stack, blocks);
  deck.append(wheel, slot);
  rest.type = 'button';
  rest.setAttribute('aria-label', '收起或展开左栏');
  frame.append(deck, rest);
  rail.append(frame);

  // ── 卡片池 ──────────────────────────────────────────────────────
  const pool: HTMLButtonElement[] = [];
  for (let k = 0; k < POOL; k += 1) {
    const card = el('button', 'card');
    card.type = 'button';
    card.addEventListener('click', () => {
      if (store.state.slim) return;
      const i = Number(card.dataset['index']);
      if (!Number.isInteger(i)) return;
      // 点已经抽出来的那张,它自己收回去 —— 不用跑去点空白。
      store.patch({ drawn: store.state.drawn === i ? -1 : i });
    });
    stack.append(card);
    pool.push(card);
  }

  // ── 收起态的小块。也只放五个,跟卡片同一个窗口 ──────────────────
  const blks: HTMLButtonElement[] = [];
  for (let k = 0; k < VISIBLE_CARDS; k += 1) {
    const b = el('button', 'blk');
    b.type = 'button';
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const i = Number(b.dataset['index']);
      if (Number.isInteger(i)) store.patch({ drawn: i });
    });
    blocks.append(b);
    blks.push(b);
  }

  function fill(node: HTMLButtonElement, card: MemoryCard, index: number): void {
    node.dataset['index'] = String(index);
    const named = card.title.length > 0;
    node.setAttribute('aria-label', `${named ? card.title : '未命名'} ${card.from} 至 ${card.to}`);
    node.replaceChildren();

    const title = el('span', 'card-title');
    title.textContent = named ? card.title : '未命名';
    if (!named) title.dataset['unnamed'] = 'true';

    const span = el('span', 'card-span');
    span.textContent = `${card.from} – ${card.to}`;

    node.append(title, span);

    if (card.profile.length > 0) {
      const plot = el('span', 'card-plot');
      for (const v of card.profile) {
        const bar = el('i');
        bar.style.height = `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
        plot.append(bar);
      }
      node.append(plot);
    }

    const foot = el('span', 'card-foot');
    const meta = el('span');
    meta.textContent =
      card.weight === null
        ? '没有留下可读的记录 · 不是空的，是不知道'
        : `${card.turns} 轮 · ${card.modalities.join(' ')}`;
    const nfc = el('span', 'card-nfc');
    nfc.title = 'NFC 预留位';
    foot.append(meta, nfc);
    node.append(foot);
  }

  /** 一张竖卡的高度 = 框内宽 × 1.586。 */
  function cardHeight(): number {
    const w = stack.clientWidth;
    return w > 40 ? Math.round(w * 1.586) : 280;
  }

  /**
   * 卡片区占多高。
   *
   * 展开时**就是一张卡那么高** —— 那正是「谁都不会被完整露出来」的来源。
   * 剩下多少归下面那片可点的地方,那才是留白,不是先挖一块再说。
   */
  function sizeDeck(): void {
    const avail = frame.clientHeight - 20 - 44;
    if (avail < 80) return;
    if (store.state.slim) {
      const w = blocks.clientWidth || 40;
      const h = VISIBLE_CARDS * blockHeight(w) + (VISIBLE_CARDS - 1) * 6;
      deck.style.height = `${Math.min(h, avail)}px`;
    } else {
      deck.style.height = `${Math.min(cardHeight(), avail)}px`;
    }
  }

  function blockHeight(width: number): number {
    return Math.max(8, Math.round(width * 0.62));
  }

  function layout(): void {
    const { cards, start, drawn, slim } = store.state;
    const height = cardHeight();
    const open = drawn >= 0;
    const rel = open ? drawn - start : -1;
    const bottomY = height - (VISIBLE_CARDS - 1 - rel) * LIP;

    for (const node of pool) {
      const i = Number(node.dataset['index']);
      const v = i - start;
      const isDrawn = open && i === drawn;

      let y: number;
      if (!open) y = v * LIP;
      else if (v < rel) y = v * TUCK;
      else if (v === rel) y = rel * TUCK + 6;
      else y = bottomY + (v - rel - 1) * LIP;

      node.dataset['drawn'] = String(isDrawn);
      // 抽出的那张凑近一点点 —— 分量感的来源之一,不是装饰。
      node.style.transform = `translateY(${y}px)${isDrawn ? ' scale(1.015)' : ''}`;
      // 离被抽的那张越远,落位越晚一点。整叠是「让了一下」,不是齐刷刷弹。
      const away = open ? Math.abs(v - rel) : 0;
      node.style.transitionDelay = `${isDrawn ? 0 : Math.min(3, away) * 22}ms`;
      node.style.zIndex = String(!open ? 20 + v : v <= rel ? 20 + v : 60 - v);
      node.style.opacity = v < 0 || v >= VISIBLE_CARDS ? '0' : '1';
    }

    // 小块
    const w = blocks.clientWidth;
    for (const [k, b] of blks.entries()) {
      const i = start + k;
      const card = cards[i];
      if (!card) {
        b.style.display = 'none';
        continue;
      }
      b.style.display = '';
      b.dataset['index'] = String(i);
      b.dataset['inWindow'] = 'true';
      b.dataset['drawn'] = String(i === drawn);
      b.dataset['unknown'] = String(card.weight === null);
      b.setAttribute('aria-label', `${card.title || '未命名'} ${card.from} 至 ${card.to}`);
      if (slim && w > 12) b.style.height = `${blockHeight(w)}px`;
    }

    // 滑键:长短是「五张占全部的多少」,位置是「翻到哪儿了」
    const total = Math.max(1, cards.length);
    const maxStart = Math.max(0, total - VISIBLE_CARDS);
    const H = wheel.clientHeight || 1;
    const th = Math.max(20, (H * VISIBLE_CARDS) / total);
    thumb.style.height = `${th}px`;
    thumb.style.top = `${maxStart ? (start / maxStart) * (H - th) : 0}px`;
  }

  /** 把池子里的每一张对到正确的下标。只在窗口整体变了时调。 */
  function remap(): void {
    const { cards, start } = store.state;
    for (const [k, node] of pool.entries()) {
      const i = start + k;
      const card = cards[i];
      if (!card) {
        node.style.opacity = '0';
        node.dataset['index'] = String(i);
        continue;
      }
      fill(node, card, i);
    }
  }

  // ── 滚轮:一格一张。水车。 ────────────────────────────────────────
  let acc = 0;
  let locked = false;
  let hideTimer = 0;

  function flashWheel(atEdge: boolean): void {
    wheel.dataset['on'] = 'true';
    wheel.dataset['edge'] = String(atEdge);
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      delete wheel.dataset['on'];
      delete wheel.dataset['edge'];
    }, atEdge ? 1100 : 800);
  }

  function turn(dir: 1 | -1): void {
    const s = store.state;
    const next = clampStart(s.start + dir, s.cards.length);
    if (next === s.start) {
      flashWheel(true); // 到头了
      return;
    }
    flashWheel(false);

    // 退场那张换上新内容,瞬移到另一端候着,再跟大家一起滑 —— 水车。
    const leaving = dir > 0 ? s.start : s.start + VISIBLE_CARDS;
    const entering = dir > 0 ? next + VISIBLE_CARDS : next;
    const node = pool.find((n) => Number(n.dataset['index']) === leaving) ?? pool[0];
    const card = store.state.cards[entering];
    if (node && card) {
      node.dataset['warp'] = 'true';
      fill(node, card, entering);
      node.style.transform = `translateY(${dir > 0 ? cardHeight() + LIP : -cardHeight()}px)`;
      node.style.opacity = '0';
      void node.offsetWidth; // 逼一次重排,让上面那步不带过渡
      delete node.dataset['warp'];
    }

    let drawn = s.drawn;
    if (drawn >= 0) {
      drawn = Math.min(Math.max(drawn, next), next + VISIBLE_CARDS - 1);
    }
    store.patch({ start: next, drawn });
  }

  frame.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      if (locked) return;
      acc += e.deltaY;
      if (Math.abs(acc) < WHEEL_STEP) return;
      const dir: 1 | -1 = acc > 0 ? 1 : -1;
      acc = 0;
      locked = true;
      window.setTimeout(() => (locked = false), 170); // 一格一格来,不连跳
      turn(dir);
    },
    { passive: false },
  );

  rest.addEventListener('click', () => store.patch({ slim: !store.state.slim }));

  function render(): void {
    rail.dataset['slim'] = String(store.state.slim);
    remap();
    sizeDeck();
    layout();
  }

  return { root: rail, render };
}

export { LIP, TUCK, svgNS };
