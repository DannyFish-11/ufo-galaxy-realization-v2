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
export interface Bundle {
  readonly key: 'omnimodal' | 'crossDevice' | 'voice' | 'autonomy';
  readonly name: string;
  readonly note: string;
  readonly on: boolean;
  /** 这一档管着多少个键 —— 从后端 category 现算,不写死 */
  readonly keyCount: number;
  /** 有几个键被手动改得偏离了这一档 —— >0 时档位显示为「开 · 有偏离」 */
  readonly overrides: number;
}
