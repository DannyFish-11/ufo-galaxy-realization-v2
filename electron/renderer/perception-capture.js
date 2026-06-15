/**
 * perception-capture.js
 * 电脑端连续感知采集：摄像头 / 麦克风 / 屏幕 → 周期性发往后端。
 *
 * 默认关闭（隐私优先）。仅当 main.js 通过 GALAXY_DESKTOP_PERCEPTION=1 启用时才采集。
 * - 摄像头：getUserMedia({video}) → 每 intervalMs 抓一帧 → JPEG base64 → 后端
 * - 麦克风：getUserMedia({audio}) → MediaRecorder 周期切片 → base64 → 后端
 * 这些帧只更新后端的「最新帧」存储；模型在下一次普通请求时按 TTL 取用（原生看到）。
 *
 * 全程容错：拿不到权限/设备就降级关闭对应模态，绝不影响主覆盖层渲染。
 */
(function () {
  'use strict';

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

  async function startVideo(intervalMs) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    } catch (e) {
      console.warn('[Perception] camera unavailable:', e && e.message);
      return;
    }
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
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, w, h);
        // JPEG ~0.6 质量，控制体积
        const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
        const b64 = dataUrl.split(',')[1] || '';
        if (b64) send({ type: 'frame', image_base64: b64, mime: 'image/jpeg', source: 'desktop_camera' });
      } catch (e) { /* skip this frame */ }
    }, Math.max(500, intervalMs));
    console.log('[Perception] camera capture started');
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
      // 每 intervalMs 产出一个切片
      rec.start();
      setInterval(() => {
        try { if (rec.state === 'recording') rec.requestData(); } catch (e) { /* ignore */ }
      }, Math.max(1000, intervalMs * 2));
      console.log('[Perception] microphone capture started');
    } catch (e) {
      console.warn('[Perception] audio recorder failed:', e && e.message);
    }
  }

  async function init() {
    const cfg = await getConfig();
    if (!cfg || !cfg.enabled) {
      console.log('[Perception] disabled (set GALAXY_DESKTOP_PERCEPTION=1 to enable)');
      return;
    }
    const interval = cfg.intervalMs || 2000;
    if (cfg.video !== false) startVideo(interval);
    if (cfg.audio !== false) startAudio(interval);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
