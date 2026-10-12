/**
 * 面板与覆盖层**共用**的两份原生 JS（electron/renderer/ 下，覆盖层用 <script> 直接加载，
 * 面板 import 进来打包）。它们挂在全局上，这里给全局补类型。
 *
 *   pet_state.js    三只桌宠（面板 / 覆盖层 / 托盘）共用的那一份推导
 *   live_socket.js  面板与覆盖层共用的那条长连接（保活、断线重连）
 *   panel_stage.js  面板画布的尺寸与等比缩放（主进程锁窗口宽高比用的也是它）
 */
export {};

declare global {
  /** 桌宠此刻该是哪一档（pet_state.js 的 derive 的返回）。 */
  interface PetDerived {
    readonly phase: 'silent' | 'liminal' | 'manifest';
    readonly activity: string;
    readonly rate: string;
    readonly eyes: 'open' | 'shut' | 'unknown';
    readonly sensing: 'true' | 'false' | 'unknown';
    /** 上一拍的决策；null = 不知道（没收到帧，或进程里根本没有感知库） */
    readonly act: string | null;
  }

  interface PetStateApi {
    readonly BREATH: Readonly<Record<string, string>>;
    readonly POSE: Readonly<Record<string, string>>;
    readonly REACT_MS: number;
    derive(input: {
      readonly lifecycle?: string;
      readonly liminal_activity?: string;
      readonly perception?: unknown;
    }): PetDerived;
    reactionFor(act: string | null): string | null;
  }

  interface LiveSocketHandlers {
    onOpen?(): void;
    onClose?(): void;
    /** 已经 JSON.parse 过的一帧（保活的 pong 不会到这里） */
    onMessage?(msg: unknown): void;
  }

  interface LiveSocketOptions {
    readonly pingMs?: number;
    readonly staleMs?: number;
    readonly connectTimeoutMs?: number;
    readonly baseDelayMs?: number;
    readonly maxDelayMs?: number;
  }

  interface LiveSocketInstance {
    start(): void;
    stop(): void;
    /** 没连着就立刻重连（不等退避）；连着就立刻探一下活着没有。 */
    kick(): void;
    readonly connected: boolean;
  }

  interface LiveSocketCtor {
    new (url: string, handlers: LiveSocketHandlers, options?: LiveSocketOptions): LiveSocketInstance;
  }

  interface PanelStageApi {
    readonly STAGE: { readonly width: number; readonly height: number };
    readonly MIN_SCALE: number;
    /** 能拖的八个方位：四条边、四个角。 */
    readonly EDGES: readonly string[];
    ratio(): number;
    fit(view: { readonly width: number; readonly height: number }): { k: number; dx: number; dy: number };
  }

  // eslint-disable-next-line no-var
  var PetState: PetStateApi;
  // eslint-disable-next-line no-var
  var PanelStage: PanelStageApi;
  // eslint-disable-next-line no-var
  var LiveSocket: LiveSocketCtor;
}
