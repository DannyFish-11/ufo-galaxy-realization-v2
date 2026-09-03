/**
 * 面板自己的类型。
 *
 * 相位契约**不在这里重新定义** —— 它的唯一定义处是 core/phase_contract.py,
 * 由 scripts/gen_ts_types.py 生成 TS。这里只 re-export,让面板代码有一个
 * 统一的入口,而不是每个文件各自去找那份生成文件。
 */
export type {
  Lifecycle,
  RenderPhase,
  RenderPosture,
  PerceptionModality,
  ModalityState,
  ModalityView,
  PerceptionView,
  ExecutionChainView,
  HybridExecutionView,
  ThinkingLocusView,
  LiminalActivity,
  RuntimeDomain,
} from '@contract';

/** 三态在面板上的展示词汇。后端线上传的是 static,展示上叫 silent。 */
export type Phase = 'silent' | 'liminal' | 'manifest';

/** SSE 的锁步状态。取值域与 core/routes/chat.py 的 LOCKSTEP_STATES 一致。 */
export type LockstepState = 'engaged' | 'off' | 'degraded';

/** 为什么是这个锁步状态。与 LOCKSTEP_REASONS 一致。 */
export type LockstepReason =
  | 'no_speaker'
  | 'disabled_by_config'
  | 'no_first_sentence'
  | 'mid_stall'
  | '';

/** 设备在名册上的状态。三档,不是布尔 —— 降级和离线是两件事。 */
export type DeviceState = 'online' | 'degraded' | 'offline';

/** 这台设备此刻忙不忙。null = 不知道(离线时就是不知道,不是"闲")。 */
export type DeviceLoad = 'busy' | 'idle' | null;

export interface DeviceRow {
  readonly id: string;
  readonly name: string;
  /** controller / participant / gateway / wearable —— 决定画多宽的小方 */
  readonly role: string;
  readonly state: DeviceState;
  readonly load: DeviceLoad;
  /** 它在跑什么;空串 = 没在跑 */
  readonly doing: string;
  /** 距上次心跳多少秒;null = 从没有过心跳(与 0 是两件事) */
  readonly lastSeenS: number | null;
}

/**
 * 一张记忆卡片 = 一个根上连续三天的切片。
 *
 * `weight` 是这三天的浓淡 [0,1]。**0 与 null 必须分开**:
 * 0 = 确实什么都没发生;null = 这三天没有留下可读的记录(不知道)。
 * 卡面上前者是空,后者是虚线空心。
 */
export interface MemoryCard {
  readonly id: string;
  /** 用户起的名字;空串 = 没起名,显示时段本身 */
  readonly title: string;
  readonly from: string;
  readonly to: string;
  readonly weight: number | null;
  readonly turns: number;
  /** 这三天进来过哪些模态 */
  readonly modalities: readonly string[];
  /** 逐段浓度,画卡面中段那条「图」;weight 为 null 时是空数组 */
  readonly profile: readonly number[];
}

/** 一条对话消息。 */
export interface Turn {
  readonly id: string;
  readonly role: 'user' | 'agent';
  readonly text: string;
  /** 还没被念出来、因此还没上屏的那一截(锁步) */
  readonly pending: string;
  readonly attachments: readonly Attachment[];
  readonly streaming: boolean;
}

export interface Attachment {
  readonly kind: 'image' | 'file' | 'screen' | 'link';
  readonly name: string;
  readonly note: string;
}

/** 一个整档开关。它管着一片配置键,而不是一个键。 */
/**
 * 一档整档开关。
 *
 * **这个形状由后端说了算** —— `GET /api/config/bundles` 现算出来什么就是什么。
 * 面板不许自己再存一份「哪一档管哪些键」:那样同一个事实两处各存,迟早一处说开、
 * 另一处说关,而且没人看得见。这四档之前确实在面板里写死过,连 keyCount 都是
 * 手抄的数字,点一下只翻一个本地变量、不发任何请求。
 */
export interface Bundle {
  readonly key: string;
  readonly name: string;
  readonly note: string;
  /** 这一档的主键 —— 开合由它说了算,写回也写它 */
  readonly primary: string;
  /**
   * 主键当前的值(字符串,后端原样给)。
   *
   * **不预先压成布尔。** `GALAXY_AUTONOMY` 是 safe / guided / autonomous 三档,
   * 压成布尔会把中间那档吞掉 —— 这个仓库为「三态被当成布尔」栽过一次。
   */
  readonly value: string;
  readonly type: string;
  /** select 型才有。有它就说明这一档不是两态的。 */
  readonly options?: readonly string[];
  /** 这一档管着多少个键 —— 后端按 category 现算,不写死 */
  readonly keyCount: number;
  /** 有几个键被手动改得偏离了默认 —— >0 时档位显示为「有 N 项手改过」 */
  readonly overrides: number;
  /**
   * 这一档的主键在后端不存在。
   *
   * 出现它就说明档位接到了一个不存在的东西上。**必须画得出来** ——
   * 否则界面上是一个永远关着、点了也没反应的开关。
   */
  readonly unwired: boolean;
}


/**
 * 本机模型档位(A/B/C/D)在面板上的样子。
 *
 * **档位不是开关,是四选一。** 它和上面那四档整档开关放在同一个浮层里,但形状
 * 不同:开关问「开不开」,档位问「用哪一套」。压成一个循环按钮(点一下 A→B→C→D)
 * 也不行 —— 那样人看不见有几档,更看不见哪几档这台机器根本跑不动。
 *
 * 唯一定义处是 core/model_catalog.py 的 `_TIERS`,经 `GET /api/v1/models/catalog`
 * 出来。面板不许自己再存一份档位表。
 */
export interface ModelTier {
  /** 'A' | 'B' | 'C' | 'D' —— 不写死成联合类型:目录里加一档,面板要跟着显示出来 */
  readonly key: string;
  readonly label: string;
  readonly desc: string;
  /** single = 一个模型全包;composite = 感知位 + 推理位两个模型 */
  readonly kind: string;
  /** 这一档真正会加载的型号 */
  readonly activeTags: readonly string[];
  /**
   * 这台机器装不装得下这一档。
   *
   * **`unknown` 与 `ok` 必须分开**:硬件没探到时是 unknown。当成 ok 的话,面板
   * 把「不知道」画成「能跑」,而人是照着这个画面选档的。聚合规则在后端
   * (core/routes/models.py::_tier_fit),不在这里 —— 判据跟着渲染代码走的话,
   * 换个界面就得重写一遍,两处迟早给出不同答案。
   */
  readonly fit: 'ok' | 'no_gpu' | 'insufficient_vram' | 'unknown';
  /** 为什么装不下,后端给的原话;fit 为 ok 时是空串 */
  readonly fitReason: string;
  /** 是哪几个型号卡住的 */
  readonly blockedBy: readonly string[];
}

/** 档位这一栏的整体状态。current 为空串 = **还没拉到**,不是「没有档位」。 */
export interface TierView {
  readonly current: string;
  readonly tiers: readonly ModelTier[];
  /** 感知位/推理位当前各是哪个型号,从当前档的 slots 里取,只读展示 */
  readonly slots: readonly { readonly role: string; readonly model: string }[];
}
