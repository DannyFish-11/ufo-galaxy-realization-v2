/**
 * perception-capture.js
 * 第一态（silent 待机）下的【连续原生多模态一体化采集】：摄像头 + 麦克风 + 屏幕。
 *
 * 默认关闭（隐私优先）。仅当壳层通过 GALAXY_DESKTOP_PERCEPTION=1 启用时才采集。
 * 采集生命周期【贴合第一态】：覆盖层进入第一态(silent)即开启三路连续采集，作为环境
 * 基线常驻感知（一旦开启便持续，进入二/三态也不中断，保证 AI 始终“在场感知”）。
 *
 * - 摄像头：getUserMedia({video}) → 每 intervalMs 抓一帧 JPEG → 后端(source=desktop_camera)
 * - 麦克风：getUserMedia({audio}) → MediaRecorder 周期切片 → 后端
 * - 屏幕：  getDisplayMedia({video}) → 每 intervalMs 抓一帧 JPEG → 后端(source=desktop_screen)
 *           ★ 仅在 Electron 走此路；Tauri 下屏幕由 Rust 壳【原生截屏】采集（更稳、免选择器），
 *             故 Tauri 时此处跳过 getDisplayMedia，避免重复抓屏。
 *
 * 三路最终在后端 DesktopPerceptionStore 合并为单个 MultiModalContext（摄像头+屏幕+音频
 * 一体化），由 OpenClawd 在下一次请求时按 TTL 一并注入——模型同时看到摄像头、看到屏幕、
 * 听到麦克风。全程容错：任一模态拿不到权限/设备就降级关闭该路，绝不影响主覆盖层渲染。
 */
(function () {
  'use strict';

  const isTauri = () => !!(window.__TAURI__);

  async function getConfig() {
    try {
      if (window.galaxyAPI && window.galaxyAPI.getPerceptionConfig) {
        return await window.galaxyAPI.getPerceptionConfig();
      }
    } catch (e) { /* ignore */ }
    return { enabled: false, intervalMs: 2000, audio: true, video: true };
  }

  function send(payload) {
    try {
      if (window.galaxyAPI && window.galaxyAPI.sendDesktopPerception) {
        window.galaxyAPI.sendDesktopPerception(payload);
      }
    } catch (e) { /* non-fatal */ }
  }

  // 通用：把一个 MediaStream 的视频轨周期性抓帧成 JPEG 发往后端（摄像头/屏幕共用）。
  async function pumpVideoFrames(stream, intervalMs, source, label) {
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play().catch(() => {});
    const canvas = document.createElement('canvas');
    setInterval(() => {
      try {
        const w = video.videoWidth, h = video.videoHeight;
        if (!w || !h) return;
        canvas.width = w; canvas.height = h;
        canvas.getContext('2d').drawImage(video, 0, 0, w, h);
        const b64 = (canvas.toDataURL('image/jpeg', 0.6).split(',')[1]) || '';
        if (b64) send({ type: 'frame', image_base64: b64, mime: 'image/jpeg', source });
      } catch (e) { /* skip this frame */ }
    }, Math.max(500, intervalMs));
    console.log(`[Perception] ${label} capture started`);
  }

  async function startCamera(intervalMs) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    } catch (e) {
      console.warn('[Perception] camera unavailable:', e && e.message);
      return;
    }
    await pumpVideoFrames(stream, intervalMs, 'desktop_camera', 'camera');
  }

  async function startScreen(intervalMs) {
    // Tauri：屏幕由 Rust 原生截屏负责，前端不再 getDisplayMedia（免选择器、免重复）。
    if (isTauri()) {
      console.log('[Perception] screen capture handled natively by Tauri shell; skipping getDisplayMedia');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      console.warn('[Perception] getDisplayMedia unavailable; screen capture skipped');
      return;
    }
    let stream;
    try {
      // Electron 侧需 main.js 的 setDisplayMediaRequestHandler 自动提供主屏（无选择器弹窗）。
      stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 1 }, audio: false });
    } catch (e) {
      console.warn('[Perception] screen unavailable:', e && e.message);
      return;
    }
    await pumpVideoFrames(stream, intervalMs, 'desktop_screen', 'screen');
  }

  async function startAudio(intervalMs) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      console.warn('[Perception] microphone unavailable:', e && e.message);
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      console.warn('[Perception] MediaRecorder unavailable; audio capture skipped');
      return;
    }
    try {
      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      rec.ondataavailable = (ev) => {
        if (!ev.data || ev.data.size === 0) return;
        const reader = new FileReader();
        reader.onloadend = () => {
          const b64 = (reader.result || '').toString().split(',')[1] || '';
          if (b64) send({ type: 'audio', audio_base64: b64, mime: 'audio/webm' });
        };
        reader.readAsDataURL(ev.data);
      };
      rec.start();
      setInterval(() => {
        try { if (rec.state === 'recording') rec.requestData(); } catch (e) { /* ignore */ }
      }, Math.max(1000, intervalMs * 2));
      console.log('[Perception] microphone capture started');
    } catch (e) {
      console.warn('[Perception] audio recorder failed:', e && e.message);
    }
  }

  // 一体化启动：三路一起拉起（幂等，只启动一次）。
  let _started = false;
  function startAll(cfg) {
    if (_started) return;
    _started = true;
    const interval = cfg.intervalMs || 2000;
    if (cfg.video !== false) startCamera(interval);
    if (cfg.video !== false) startScreen(interval);   // 屏幕（Tauri 下内部自动跳过）
    if (cfg.audio !== false) startAudio(interval);
    console.log('[Perception] 第一态连续原生多模态一体化采集已开启（摄像头+屏幕+麦克风）');
  }

  async function init() {
    const cfg = await getConfig();
    if (!cfg || !cfg.enabled) {
      console.log('[Perception] disabled (set GALAXY_DESKTOP_PERCEPTION=1 to enable)');
      return;
    }
    // 【贴合第一态】：进入第一态(silent) 即开启采集。覆盖层默认就启动在第一态，
    // 故这里既订阅状态事件（首次 silent 触发），也在 init 时直接拉起一次（默认即第一态）。
    try {
      if (window.galaxyAPI && window.galaxyAPI.onBackendState) {
        window.galaxyAPI.onBackendState((payload) => {
          if (payload && (payload.phase === 'silent' || payload.phase === undefined)) startAll(cfg);
        });
      }
    } catch (e) { /* ignore */ }
    startAll(cfg);   // 默认启动态即第一态 → 立即开启
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
