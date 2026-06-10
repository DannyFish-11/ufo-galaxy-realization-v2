/**
 * 灵动岛 UI 控制器
 * 负责：显示/隐藏灵动岛、更新状态文字、动画控制
 */

class IslandController {
  constructor() {
    this.el = document.getElementById('island');
    this.textEl = document.getElementById('islandText');
    this.visible = false;
  }

  // ── 更新 ────────────────────────────────────────

  update(currentDepth, backendState) {
    let progress = 0;
    let text = 'Galaxy';

    if (currentDepth > 0.10 && currentDepth < 0.90) {
      if (currentDepth < 0.35) {
        // 出现阶段
        progress = Math.min(1, (currentDepth - 0.10) / 0.18);
        text = 'Galaxy';
      } else if (currentDepth < 0.65) {
        // 完全展开
        progress = 1;
        text = backendState.speaking ? '倾听中...' : 'Galaxy';
      } else {
        // 消失阶段
        progress = Math.max(0, 1 - (currentDepth - 0.65) / 0.18);
        text = backendState.activeTask || '执行中...';
      }
    }

    if (progress > 0.01) {
      this.el.classList.add('visible');
      this.textEl.textContent = text;
      this.el.style.opacity = Math.min(1, progress).toFixed(2);
      this.visible = true;
    } else {
      this.el.classList.remove('visible');
      this.visible = false;
    }
  }

  // ── 强制显示/隐藏 ───────────────────────────────

  show(text = 'Galaxy') {
    this.el.classList.add('visible');
    this.textEl.textContent = text;
    this.visible = true;
  }

  hide() {
    this.el.classList.remove('visible');
    this.visible = false;
  }

  // ── 状态点动画 ──────────────────────────────────

  setSpeaking(isSpeaking) {
    const dot = this.el.querySelector('.dot');
    if (dot) {
      dot.style.animation = isSpeaking ? 'pulse 0.8s ease-in-out infinite' : 'none';
    }
  }
}

if (typeof module !== 'undefined') module.exports = { IslandController };
