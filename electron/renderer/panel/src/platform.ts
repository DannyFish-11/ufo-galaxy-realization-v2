/**
 * 外壳适配层。
 *
 * 面板本身**不认识 Electron,也不认识 Tauri** —— 它只知道自己需要外壳提供
 * 这几件事。浏览器里跑就是下面这份空实现,一样能开。
 *
 * 这样做的实际好处:外壳选型可以往后放,而不是现在把 UI 焊死在某个框架上。
 * Electron / Tauri 各写一份 `HudPlatform` 塞进 `setPlatform()` 即可,
 * UI 一行不用改。
 */

/** 唤醒键。两个相邻、平时不用、且不跟输入法打架的键。 */
export interface WakeChord {
  /** 人看的写法,例如「右 Ctrl + 右 Alt」 */
  readonly label: string;
  /** 外壳自己的写法(Electron accelerator / Tauri shortcut) */
  readonly accelerator: string;
}

export interface HudPlatform {
  /** 收起面板。浏览器里没有"收起"这回事,所以默认是空操作。 */
  hide(): void;
  /**
   * 注册唤醒键,返回**真正生效**的那一个。
   *
   * 注意返回值可能与请求的不同,甚至是 null:注册"成功"不等于按得到 ——
   * 键可能在到达本进程之前就被输入法 / 远程桌面 / 浏览器开发者工具截走。
   * 所以这里如实返回外壳认为生效的那个,由界面显示出来给人确认。
   */
  registerWake(candidates: readonly WakeChord[]): Promise<WakeChord | null>;
  /** 打开系统的文件选择。浏览器里回落到 <input type=file>。 */
  pickFiles(accept: string): Promise<readonly File[]>;
  /** 外壳的名字,只用于显示与排障 */
  readonly name: string;
}

const browserPlatform: HudPlatform = {
  name: 'browser',
  hide() {
    /* 浏览器里没有外壳可收 */
  },
  async registerWake() {
    // 网页拿不到全局热键 —— 如实返回 null,而不是假装注册上了。
    return null;
  },
  async pickFiles(accept: string) {
    return new Promise((resolve) => {
      const el = document.createElement('input');
      el.type = 'file';
      el.multiple = true;
      el.accept = accept;
      el.addEventListener('change', () => resolve(Array.from(el.files ?? [])), {
        once: true,
      });
      el.click();
    });
  },
};

let current: HudPlatform = browserPlatform;

export function setPlatform(p: HudPlatform): void {
  current = p;
}

export function platform(): HudPlatform {
  return current;
}

/**
 * 唤醒键的候选,按优先级。
 *
 * 首选**右 Ctrl + 右 Alt**:两个键在右下角紧挨着,单独按都不产生任何
 * 字符和动作,笔记本与台式都有;而且不占中文输入法用的 Ctrl+Space(中英切换)
 * 和 Ctrl+Shift(切输入法)。
 *
 * 刻意避开的:任何 Ctrl+Shift 组合(输入法必冲突)、Ctrl+Space(同上)、
 * F12 / F10(实测会被远程桌面与开发者工具截走)、Ctrl+Shift+P
 * (浏览器与 VSCode 的命令面板)。
 */
export const WAKE_CANDIDATES: readonly WakeChord[] = [
  { label: '右 Ctrl + 右 Alt', accelerator: 'Right Control+Right Alt' },
  { label: '右 Ctrl + 应用程序键', accelerator: 'Right Control+ContextMenu' },
  { label: 'Ctrl + Alt + 空格', accelerator: 'CommandOrControl+Alt+Space' },
];
