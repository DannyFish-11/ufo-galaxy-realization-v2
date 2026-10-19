'use strict';
/**
 * clipboard_watch.js —— 剪贴板一变，告诉覆盖层「是哪一类」，灵动岛亮 1.5 秒「已复制 · 文字 / 图片 / 文件」。
 *
 * 借的是所有者指的 winsland（github.com/adityasrivastava5098/WinIsland）的剪贴板提示：每 500 毫秒看一眼格式，
 * 格式变了、或文字变了，就算复制过一次。Electron 没有剪贴板的序号可读，只能这样轮询。
 *
 * **内容不离开主进程，也不留在内存里**：发给渲染层的只有 { type }；比对用的是文字的 sha1 摘要，不是原文。
 * 图片不逐张比（解一张截图的位图每 500 毫秒一次太贵）—— 从文字换成图片、从图片换成文件都认得出来，
 * 连着复制两张图片只亮第一次。这与 winsland 同一个取舍。
 *
 * 纯函数模块：clipboard / hash / 定时器都由调用方给，测试（clipboard_watch.test.js）拿假的喂。
 */

const POLL_MS = 500;

/** 格式表 → 一类。与 winsland 同一套判法；island.js 的 COPY_WORD 认这四个。 */
function kindOf(formats) {
  const f = Array.isArray(formats) ? formats : [];
  if (f.includes('image/png') || f.includes('image/jpeg')) return 'image';
  if (f.includes('text/uri-list') || f.some((x) => String(x).toLowerCase().includes('file'))) return 'file';
  if (f.includes('text/plain')) return 'text';
  return 'generic';
}

/**
 * 开始看。返回停下的函数。
 *
 * @param {{availableFormats(): string[], readText(): string}} clipboard  electron 的 clipboard
 * @param {(msg: {type: string}) => void} send  发给覆盖层（只有类别）
 * @param {{hash?: (s: string) => string, every?: (fn: Function, ms: number) => any, cancel?: (h: any) => void, ms?: number}} [opts]
 */
function watchClipboard(clipboard, send, opts = {}) {
  const hash = opts.hash || ((s) => require('crypto').createHash('sha1').update(s).digest('hex'));
  const every = opts.every || setInterval;
  const cancel = opts.cancel || clearInterval;

  const look = () => {
    const formats = clipboard.availableFormats() || [];
    const text = formats.includes('text/plain') ? hash(clipboard.readText() || '') : '';
    return { sig: formats.join('\n'), text, formats };
  };
  // 起点只记下、不报：开机时剪贴板里本来就有的东西不算「刚复制」
  let last = null;
  try { last = look(); } catch (_e) { last = { sig: '', text: '' }; }

  const handle = every(() => {
    let now;
    try { now = look(); } catch (_e) { return; }   // 别的程序正占着剪贴板：这一拍跳过
    if (now.sig === last.sig && now.text === last.text) return;
    last = now;
    try { send({ type: kindOf(now.formats) }); } catch (_e) { /* 覆盖层不在：下一次再说 */ }
  }, opts.ms || POLL_MS);
  if (handle && typeof handle.unref === 'function') handle.unref();
  return () => cancel(handle);
}

module.exports = { watchClipboard, kindOf, POLL_MS };
