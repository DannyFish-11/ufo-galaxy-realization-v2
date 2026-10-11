/**
 * 型号串怎么**显示**:每一段名字的首字母大写 —— `gemma4:e2b` → `Gemma4:e2b`,
 * `openbmb/minicpm-o4.5` → `Openbmb/Minicpm-o4.5`(斜杠前是发布者、后是型号,两段各是一个名字)。
 *
 * 只改显示。存进设置、发给后端的仍是原串:Ollama 的标签按原样认,改了大小写就找不到那个型号。
 * 所以凡是画型号的地方都过这一道,凡是传型号的地方都不过。
 */
export function modelLabel(tag: string): string {
  return tag.replace(/(^|\/)([a-z])/g, (_m: string, lead: string, ch: string) => lead + ch.toUpperCase());
}
