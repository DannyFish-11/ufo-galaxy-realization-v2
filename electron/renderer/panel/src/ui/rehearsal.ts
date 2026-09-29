/**
 * 推演过程。夹在对话区与输入条之间的一小段。
 *
 * 阈限态里,智能体在真正动手之前会先在沙盘里把工具调用走一遍(后端
 * core/liminal_rehearsal.py)。这一段把那几步**照实**摆出来:第几轮、模拟了哪个
 * 工具、哪一步被校验挡下、这一轮通过没有、没通过的原因。
 *
 * **每一行都要说清它是不是真的。** 预演里写状态的工具一律模拟,只读工具会真查一次。
 * 一行写着「调用了 发送邮件」而不说是模拟,人会以为邮件已经发出去了 —— 这比
 * 什么都不显示更糟。所以模拟的写「模拟」,真查的写「真查了」,没有第三种措辞。
 *
 * 只留**最近一次**推演:新的一次从第 1 轮开始时,旧的整段换掉。发下一句话时由
 * 调用方清空(见 main.ts)。空的时候整段不占位置。
 */
import type { RehearsalStep } from '../types';

/** 一次推演最多显示几行。再多就是刷屏,留最后这些。 */
const MAX_LINES = 12;

export interface RehearsalHandles {
  readonly root: HTMLElement;
  render(steps: readonly RehearsalStep[]): void;
}

/** 把一步说成一句人话。措辞里「模拟 / 真查了」必须出现 —— 见文件头。 */
export function describeStep(s: RehearsalStep): string {
  switch (s.step) {
    case 'attempt_start':
      return s.task ? `第 ${s.attempt} 轮推演：${s.task}` : `第 ${s.attempt} 轮推演`;
    case 'tool_simulated':
      return s.simulated ? `模拟 ${s.tool}` : `真查了 ${s.tool}（只读）`;
    case 'validation_reject':
      return `${s.tool} 的参数没过校验，这一步没走`;
    case 'attempt_success':
      return `这一轮走通了（${s.steps} 步）—— 接下来照这个剧本真做`;
    case 'attempt_failed':
      return s.feedback ? `这一轮没走通：${s.feedback}` : '这一轮没走通';
    default:
      return '';
  }
}

/**
 * 合并一步进已有的列表。新的一次推演(第 1 轮开始)换掉整段;其余追加,超长截头。
 * 纯函数 —— 状态只在 store 里存一份。
 */
export function mergeStep(prev: readonly RehearsalStep[], s: RehearsalStep): readonly RehearsalStep[] {
  if (s.step === 'attempt_start' && s.attempt <= 1) return [s];
  const next = [...prev, s];
  return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
}

export function createRehearsal(): RehearsalHandles {
  const root = document.createElement('div');
  root.className = 'rehearsal';
  root.hidden = true;

  function render(steps: readonly RehearsalStep[]): void {
    root.hidden = steps.length === 0;
    if (!steps.length) {
      root.replaceChildren();
      return;
    }
    const head = document.createElement('div');
    head.className = 'rh-head';
    head.textContent = '动手之前的推演 · 模拟的步骤没有碰过真实世界';
    const list = document.createElement('ol');
    list.className = 'rh-list';
    for (const s of steps) {
      const li = document.createElement('li');
      li.className = 'rh-step';
      li.dataset['step'] = s.step;
      li.dataset['real'] = String(s.step === 'tool_simulated' && !s.simulated);
      li.textContent = describeStep(s);
      list.append(li);
    }
    root.replaceChildren(head, list);
  }

  return { root, render };
}
