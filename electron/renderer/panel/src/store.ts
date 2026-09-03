/**
 * 面板的状态。
 *
 * 一份状态,一处改,订阅者收通知 —— 没有框架,也不需要框架。
 * 刻意做成**不可变替换**:每次 patch 产生新对象,于是"这一帧和上一帧
 * 有没有变"是可判定的,不必靠深比较猜。
 */
import type {
  Bundle,
  DeviceRow,
  LockstepReason,
  LockstepState,
  MemoryCard,
  Phase,
  RenderPosture,
  TierView,
  Turn,
} from './types';
import type { ConfigItem } from './transport';

export interface HudState {
  /** 连上后端了没有。false 时下面的东西全是上一次的残值或空态 */
  readonly connected: boolean;
  /**
   * 后端每帧算好的双轴渲染契约。**这是"此刻"的唯一权威**。
   *
   * null = 从没收到过。**不要拿它和"全零"混为一谈** —— 没收到过和
   * 收到了一份全零的姿态是两件事,前者不该画任何东西。
   */
  readonly posture: RenderPosture | null;
  /** 契约里这一帧缺了哪些字段。非空 = 后端漂了,不是正常降级 */
  readonly postureDrift: readonly string[];
  /** 展示用的三态。由 posture.lifecycle 推,posture 缺席时是 silent */
  readonly phase: Phase;

  readonly lockstep: LockstepState;
  readonly lockstepReason: LockstepReason;

  readonly cards: readonly MemoryCard[];
  /** 窗口起点:眼前那五张是 cards[start .. start+VISIBLE) */
  readonly start: number;
  /** 抽出来的那张的下标;-1 = 没有抽出任何一张,整叠归位 */
  readonly drawn: number;
  /** 左栏收窄了没有 */
  readonly slim: boolean;

  readonly turns: readonly Turn[];
  readonly devices: readonly DeviceRow[];
  readonly bundles: readonly Bundle[];
  /**
   * 本机模型档位(A/B/C/D)。null = **还没拉到**,与「没有档位」是两件事 ——
   * 前者浮层里那一行画成「读取中」,后者才该说「这台机器没有本机档位」。
   */
  readonly tiers: TierView | null;
  /** 换档时后端报回来的「这一档缺什么依赖」。空数组 = 不缺;必须画出来。 */
  readonly tierGaps: readonly string[];
  /** 全部设置那 332 个键。null = **还没拉到**,与「一个键都没有」是两件事。 */
  readonly config: readonly ConfigItem[] | null;
  readonly settingsOpen: boolean;
  /** 正在拉或正在写。用来把保存按钮压住,免得连点写两遍。 */
  readonly configBusy: boolean;

  /** 右上那块岛展开了没有 */
  readonly islandOpen: boolean;
  /** 底下两个浮层,同一时刻最多开一个 */
  readonly popover: 'feed' | 'settings' | null;
}

export const VISIBLE_CARDS = 5;

export const initialState: HudState = {
  connected: false,
  posture: null,
  postureDrift: [],
  phase: 'silent',
  lockstep: 'off',
  lockstepReason: '',
  cards: [],
  start: 0,
  drawn: -1,
  slim: false,
  turns: [],
  devices: [],
  bundles: [],
  tiers: null,
  tierGaps: [],
  config: null,
  settingsOpen: false,
  configBusy: false,
  islandOpen: false,
  popover: null,
};

type Listener = (next: HudState, prev: HudState) => void;

export class Store {
  #state: HudState;
  #listeners = new Set<Listener>();

  constructor(initial: HudState = initialState) {
    this.#state = initial;
  }

  get state(): HudState {
    return this.#state;
  }

  /** 打一个补丁。返回是否真的变了 —— 没变就不通知,省掉一整轮重绘。 */
  patch(part: Partial<HudState>): boolean {
    const prev = this.#state;
    let changed = false;
    for (const k of Object.keys(part) as (keyof HudState)[]) {
      if (!Object.is(prev[k], part[k])) {
        changed = true;
        break;
      }
    }
    if (!changed) return false;
    this.#state = { ...prev, ...part };
    for (const fn of this.#listeners) fn(this.#state, prev);
    return true;
  }

  subscribe(fn: Listener): () => void {
    this.#listeners.add(fn);
    return () => this.#listeners.delete(fn);
  }
}

/** 窗口起点夹到合法范围。卡少于一屏时恒为 0。 */
export function clampStart(start: number, total: number): number {
  const max = Math.max(0, total - VISIBLE_CARDS);
  return Math.min(Math.max(0, start), max);
}
