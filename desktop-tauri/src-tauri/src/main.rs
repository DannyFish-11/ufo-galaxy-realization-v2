// Galaxy 三态桌面覆盖层 — Tauri 主进程
// =====================================================================
// 这是对 electron/main.js 的等价重写（Rust + 系统 WebView，替代 Electron/Chromium）。
// 设计目标：renderer/ 那套前端（lumiv 着色器、三态、感知、WebSocket、React 面板）
// **完全不动**，由本进程复刻 Electron 侧的全部契约：
//   - 两个窗口：overlay（透明/置顶/点击穿透/覆盖主屏 bounds）+ panel（控制面板，热键开关）
//   - preload 的 window.galaxyAPI（11 个方法）→ 注入脚本 + Rust command 复刻
//   - IPC HTTP 接收端（127.0.0.1:GALAXY_IPC_PORT，默认 9231）：/ipc/presence-state|wake|
//     toggle-panel|toggle-overlay —— 托盘与后端 bridge 照原样 POST，无需改动 Python 侧
//   - 全局快捷键：唤醒/隐藏/面板（与 Electron 同一组候选键）
//   - 桌面感知：摄像头/麦克风帧 → 转发网关 /api/perception/desktop/*（含首启授权 + 持久化）
//   - 配置读写：转发网关 /api/config，写后广播 galaxy:config-update
// 关键修复延续：用主屏 bounds 覆盖、不开 OS 独占全屏（透明置顶覆盖层的稳健做法）。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, State, WebviewUrl,
    WebviewWindow, WebviewWindowBuilder,
};

// ── 全局运行期状态（Tauri manage）──
struct AppState {
    gateway_base: String,         // http://localhost:{GALAXY_GATEWAY_PORT|PORT|9000}
    ipc_port: u16,                // GALAXY_IPC_PORT，默认 9231
    perception_interval_ms: u64,  // 采集间隔（注入给 renderer）
    perception_enabled: AtomicBool,
    overlay_awake: AtomicBool,
    http: reqwest::Client,
    config_cache: Mutex<Value>,
    settings_cache: Mutex<Value>,                 // /api/config/all 完整明细（设置 tab）
    config_refresh_inflight: AtomicBool,          // 去重：同一时间只跑一条配置刷新链
    settings_refresh_inflight: AtomicBool,
}

// preload 注入脚本：在每个窗口里重建 window.galaxyAPI（指向 Tauri invoke/event）。
// 懒解析 window.__TAURI__（注入脚本早于页面脚本执行，故在【调用时】才取，避免时序问题）。
// __PLATFORM__ 在窗口创建时按真实 OS 替换为 win32/darwin/linux（对齐 process.platform）。
const GALAXY_API_SHIM: &str = r#"
(function () {
  function T() { return window.__TAURI__; }
  function invoke(cmd, args) { return T().core.invoke(cmd, args); }
  function listen(ev, cb) { return T().event.listen(ev, function (e) { cb(e.payload); }); }
  window.galaxyAPI = {
    onBackendState: function (cb) { var un = null; listen('presence-state', cb).then(function (f) { un = f; }); return function () { if (un) un(); }; },
    getBackendUrl: function () { return invoke('get_backend_url'); },
    getWindowSize: function () { return invoke('get_window_size'); },
    setIgnoreMouse: function (ignore) { return invoke('set_ignore_mouse', { ignore: !!ignore }); },
    getPerceptionConfig: function () { return invoke('get_perception_config'); },
    sendDesktopPerception: function (payload) { return invoke('send_desktop_perception', { payload: payload }); },
    platform: '__PLATFORM__',
    getConfig: function () { return invoke('get_config'); },
    getSettings: function () { return invoke('get_settings'); },
    getBackendStatus: function () { return invoke('get_backend_status'); },
    startBackend: function () { return invoke('start_backend'); },
    getRuntimeStatus: function () { return invoke('get_runtime_status'); },
    testRuntime: function (runtime) { return invoke('test_runtime', { runtime: String(runtime || '') }); },
    saveRuntime: function (runtime) { return invoke('save_runtime', { runtime: String(runtime || '') }); },
    getConfigSaveTimeoutMs: function () { return invoke('get_config_save_timeout_ms'); },
    setConfig: function (config) { return invoke('set_config', { config: config }); },
    onConfigUpdate: function (cb) { var un = null; listen('galaxy:config-update', cb).then(function (f) { un = f; }); return function () { if (un) un(); }; },
    onConfigReady: function (cb) { var un = null; listen('galaxy:config-ready', cb).then(function (f) { un = f; }); return function () { if (un) un(); }; },
    saveConfig: function () { return invoke('save_config'); }
  };
  // 窗口级 F12/F10 兜底(第二层)：等价 electron 的 before-input-event。globalShortcut(OS 级)
  // 在 RDP/虚拟机/全屏下常被上层截走收不到；覆盖层/面板 webview 恰好持键盘焦点时这里兜底。
  // key 或 code 任一命中即可（兼容只回报 code 的远程/虚拟键盘）。
  window.addEventListener('keydown', function (e) {
    if (e.key === 'F12' || e.code === 'F12' || e.key === 'F10' || e.code === 'F10') {
      e.preventDefault();
      invoke('toggle_panel_cmd');
    }
  }, true);
  console.log('[Tauri-Preload] galaxyAPI shim ready');
})();
"#;

fn platform_tag() -> &'static str {
    match std::env::consts::OS {
        "windows" => "win32",
        "macos" => "darwin",
        _ => "linux",
    }
}

fn shim_script() -> String {
    GALAXY_API_SHIM.replace("__PLATFORM__", platform_tag())
}

// ─────────────────────────────── 窗口构建 ───────────────────────────────

fn build_overlay(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    let win = WebviewWindowBuilder::new(app, "overlay", WebviewUrl::App("index.html".into()))
        .title("Galaxy")
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .resizable(false)
        .focused(false)
        .visible(false)
        .inner_size(1920.0, 1080.0)
        .initialization_script(shim_script())
        .build()?;
    Ok(win)
}

fn build_panel(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    // 优先 Vite 构建产物 panel/dist/index.html；renderer/panel/index.html 是构建入口，不能直接加载。
    let url = WebviewUrl::App("panel/dist/index.html".into());
    let win = WebviewWindowBuilder::new(app, "panel", url)
        .title("Galaxy 控制面板")
        .inner_size(1200.0, 700.0)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .resizable(true)
        .focused(true)
        .visible(false)
        .initialization_script(shim_script())
        .build()?;
    Ok(win)
}

// 把覆盖层重定位/缩放到主显示器 bounds（DIP→物理像素），等价 Electron 的 setBounds(primary)。
// 用窗口自身的 primary_monitor()（Tauri v2 上窗口对象的显示器查询最稳）。
fn position_overlay_to_primary(_app: &AppHandle, win: &WebviewWindow) {
    if let Ok(Some(m)) = win.primary_monitor() {
        let pos = m.position();
        let size = m.size();
        let _ = win.set_position(PhysicalPosition::new(pos.x, pos.y));
        let _ = win.set_size(PhysicalSize::new(size.width, size.height));
    }
}

// ─────────────────────────────── 三态唤醒/隐藏 ───────────────────────────────
// 「唤醒」= 显示整套外壳并停在第一态(silent 暖金辉光)；三态切换交给后端按 AI 实际活动驱动。
// 「隐藏」= 收起外壳（hide）。覆盖层始终鼠标穿透，绝不接管鼠标。

fn set_overlay_phase(app: &AppHandle, awake: bool) {
    let state = app.state::<AppState>();
    state.overlay_awake.store(awake, Ordering::Relaxed);
    let Some(win) = app.get_webview_window("overlay") else { return };
    if awake {
        // 停第一态：不强制后续态（早期把唤醒强设 manifest/liminal 都错）。
        let _ = app.emit_to(
            "overlay",
            "presence-state",
            json!({
                "phase": "silent",
                "depth_factor": 0.05,
                "intent": "manual_wake",
                "speaking": false,
                "source": "hotkey"
            }),
        );
        position_overlay_to_primary(app, &win);
        let _ = win.show();
        let _ = win.set_always_on_top(true);
        // 鼠标穿透必须在窗口【已显示/realize 之后】再设：Linux(GTK) 上过早调用会让
        // tao 取 GDK window 时 unwrap None 而 panic；Windows 无此问题，但统一放在 show 后最稳。
        let _ = win.set_ignore_cursor_events(true);
    } else {
        let _ = win.hide();
    }
    println!(
        "[Overlay] {}",
        if awake {
            "已唤醒(第一态 暖金辉光；三态随 AI 实际活动自行切换)"
        } else {
            "已隐藏(收起外壳)"
        }
    );
}

fn toggle_overlay_wake(app: &AppHandle) {
    let cur = app.state::<AppState>().overlay_awake.load(Ordering::Relaxed);
    set_overlay_phase(app, !cur);
}

fn toggle_panel(app: &AppHandle) {
    use tauri_plugin_notification::NotificationExt;
    // 非阻塞提示（等价 electron 的 Notification）：面板可能开在别的屏/被挡，给用户一个可见回执。
    let notify = |body: &str| {
        let _ = app
            .notification()
            .builder()
            .title("Galaxy 控制面板")
            .body(body)
            .show();
    };
    if let Some(win) = app.get_webview_window("panel") {
        let visible = win.is_visible().unwrap_or(false);
        if visible {
            let _ = win.hide();
            println!("[Panel] Hidden");
            notify("已隐藏");
        } else {
            let _ = win.show();
            let _ = win.set_focus();
            println!("[Panel] Shown");
            notify("已显示");
        }
        return;
    }
    match build_panel(app) {
        Ok(win) => {
            let _ = win.show();
            let _ = win.set_focus();
            println!("[Panel] Created & Shown");
            notify("已显示");
        }
        Err(e) => eprintln!("[Panel] 创建失败: {e}"),
    }
}

// 在主线程上执行窗口相关操作（从 IPC HTTP 线程进来时必须切回主线程再建窗/显示）。
fn on_main<F: FnOnce(&AppHandle) + Send + 'static>(app: &AppHandle, f: F) {
    let a = app.clone();
    let _ = app.run_on_main_thread(move || f(&a));
}

// ─────────────────────────────── 感知授权（首启询问 + 持久化）───────────────────────────────

fn consent_file(app: &AppHandle) -> Option<std::path::PathBuf> {
    app.path()
        .app_data_dir()
        .ok()
        .map(|d| d.join("perception_consent.json"))
}

fn read_consent(app: &AppHandle) -> Option<bool> {
    let f = consent_file(app)?;
    let s = std::fs::read_to_string(f).ok()?;
    let v: Value = serde_json::from_str(&s).ok()?;
    v.get("granted").and_then(|x| x.as_bool())
}

fn write_consent(app: &AppHandle, granted: bool) {
    if let Some(f) = consent_file(app) {
        if let Some(parent) = f.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(f, json!({ "granted": granted }).to_string());
    }
}

// env 强制 > 已持久化 > 首启弹框。返回最终是否启用感知。
fn resolve_perception_consent(app: &AppHandle) -> bool {
    let env = std::env::var("GALAXY_DESKTOP_PERCEPTION")
        .unwrap_or_default()
        .trim()
        .to_lowercase();
    if ["1", "true", "yes", "on"].contains(&env.as_str()) {
        return true;
    }
    if ["0", "false", "no", "off"].contains(&env.as_str()) {
        return false;
    }
    if let Some(saved) = read_consent(app) {
        return saved;
    }
    // 首启：弹一次授权框（阻塞）。
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
    let granted = app
        .dialog()
        .message(
            "允许 Galaxy 使用摄像头、麦克风与屏幕画面？\n\n\
             授权后，Galaxy 在第一态(待机)会连续原生采集【摄像头+麦克风+屏幕】，由本地多模态\
             模型(Gemma4 / MiniCPM-o)一体化理解，提供更自然的在场助理体验。\
             采集仅在本机处理；可随时在设置中关闭。",
        )
        .title("Galaxy 多模态感知授权")
        .buttons(MessageDialogButtons::OkCancelCustom(
            "授权".to_string(),
            "暂不".to_string(),
        ))
        .blocking_show();
    write_consent(app, granted);
    granted
}

// ─────────────────────────────── IPC HTTP 接收端 ───────────────────────────────
// 复刻 electron/main.js 的 http.createServer：托盘与 core.lumiv_websocket_bridge 照原样 POST。

fn start_ipc_http(app: AppHandle, port: u16) {
    std::thread::spawn(move || {
        let server = match tiny_http::Server::http(("127.0.0.1", port)) {
            Ok(s) => s,
            Err(e) => {
                eprintln!(
                    "[IPC] 端口 {port} 绑定失败（presence 推送禁用，不影响窗口/快捷键）: {e}"
                );
                return;
            }
        };
        println!("[IPC] HTTP receiver on 127.0.0.1:{port}");
        for mut req in server.incoming_requests() {
            let is_post = *req.method() == tiny_http::Method::Post;
            let url = req.url().to_string();
            let (code, body): (u32, String) = if is_post && url == "/ipc/toggle-panel" {
                on_main(&app, toggle_panel);
                (200, r#"{"success":true,"action":"toggle-panel"}"#.into())
            } else if is_post && url == "/ipc/wake" {
                on_main(&app, |a| set_overlay_phase(a, true));
                (200, r#"{"success":true,"action":"wake"}"#.into())
            } else if is_post && url == "/ipc/toggle-overlay" {
                on_main(&app, toggle_overlay_wake);
                (200, r#"{"success":true,"action":"toggle-overlay"}"#.into())
            } else if is_post && url == "/ipc/hide-overlay" {
                // 始终【隐藏】覆盖层（幂等，永不显示）——托盘「收起覆盖层」走这条。
                on_main(&app, |a| set_overlay_phase(a, false));
                (200, r#"{"success":true,"action":"hide-overlay"}"#.into())
            } else if is_post && url == "/ipc/presence-state" {
                let mut buf = String::new();
                let _ = req.as_reader().read_to_string(&mut buf);
                match serde_json::from_str::<Value>(&buf) {
                    Ok(v) => {
                        let payload = v.get("payload").cloned().unwrap_or(v);
                        let _ = app.emit_to("overlay", "presence-state", payload.clone());
                        let _ = app.emit_to("panel", "presence-state", payload);
                        (200, r#"{"success":true,"via":"ipc"}"#.into())
                    }
                    Err(_) => (400, r#"{"error":"invalid json"}"#.into()),
                }
            } else {
                (404, r#"{"error":"not found"}"#.into())
            };
            let header =
                tiny_http::Header::from_bytes(&b"Content-Type"[..], &b"application/json"[..])
                    .unwrap();
            let resp = tiny_http::Response::from_string(body)
                .with_status_code(code)
                .with_header(header);
            let _ = req.respond(resp);
        }
    });
}

// ─────────────────────────────── 第一态原生连续屏幕采集 ───────────────────────────────
// Tauri 下屏幕由本进程【原生截屏】采集（Win32/X11，免 getDisplayMedia 选择器、更稳），
// 与渲染层的摄像头/麦克风一起，构成第一态的连续原生多模态一体化感知。
// 仅当感知启用时运行；每 interval 截一次主屏 → JPEG → POST 后端(source=desktop_screen)。

fn capture_primary_jpeg() -> Option<Vec<u8>> {
    // 用 xcap re-export 的 image（与 xcap 同版本 0.24，避免版本冲突）。
    use xcap::image::{codecs::jpeg::JpegEncoder, ColorType, DynamicImage};
    use xcap::Monitor;

    let monitors = Monitor::all().ok()?;
    // 优先主屏；取不到就退而取第一个。is_primary() 返回 bool。
    let monitor = monitors
        .iter()
        .find(|m| m.is_primary())
        .or_else(|| monitors.first())?;
    let img = monitor.capture_image().ok()?; // xcap::image::RgbaImage
    let (w, h) = (img.width(), img.height());
    // JPEG 无 alpha：转 RGB8 再编码，质量 60 控体积。
    let rgb = DynamicImage::ImageRgba8(img).to_rgb8();
    let mut out: Vec<u8> = Vec::new();
    // image 0.24 的 encode 签名用 ColorType（非 ExtendedColorType）。
    JpegEncoder::new_with_quality(&mut out, 60)
        .encode(rgb.as_raw(), w, h, ColorType::Rgb8)
        .ok()?;
    Some(out)
}

fn start_native_screen_capture(app: AppHandle) {
    let st = app.state::<AppState>();
    if !st.perception_enabled.load(Ordering::Relaxed) {
        return; // 感知未启用：不抓屏
    }
    let base = st.gateway_base.clone();
    let interval_ms = st.perception_interval_ms.max(500);
    let client = st.http.clone();
    println!("[Perception] 原生屏幕采集已开启（每 {interval_ms}ms 一帧 → desktop_screen）");
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_millis(interval_ms)).await;
            // 截屏是阻塞 CPU 活，放 blocking 线程，避免卡住异步运行时。
            let jpeg = tauri::async_runtime::spawn_blocking(capture_primary_jpeg)
                .await
                .ok()
                .flatten();
            if let Some(bytes) = jpeg {
                use base64::Engine;
                let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
                let body = json!({
                    "image_base64": b64,
                    "mime": "image/jpeg",
                    "source": "desktop_screen"
                });
                // 失败非致命（后端未就绪/网络抖动），丢弃本帧即可。
                let _ = client
                    .post(format!("{base}/api/perception/desktop/frame"))
                    .json(&body)
                    .send()
                    .await;
            }
        }
    });
}

// ─────────────────────────────── 面板数据轮询（5s）───────────────────────────────
// 等价 main.js 的 setInterval：从网关拉真实聚合数据并推给可见的面板窗口。

fn start_panel_feed_poll(app: AppHandle) {
    let base = app.state::<AppState>().gateway_base.clone();
    let client = app.state::<AppState>().http.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(5)).await;
            let visible = app
                .get_webview_window("panel")
                .map(|w| w.is_visible().unwrap_or(false))
                .unwrap_or(false);
            if !visible {
                continue;
            }
            let url = format!("{base}/api/v1/panel/feed");
            if let Ok(resp) = client.get(&url).send().await {
                if let Ok(data) = resp.json::<Value>().await {
                    if let Some(feed) = data.get("feed") {
                        if feed.is_object() && !feed.as_object().map(|o| o.is_empty()).unwrap_or(true)
                        {
                            let _ = app.emit_to("panel", "presence-state", feed.clone());
                        }
                    }
                }
            }
        }
    });
}

// ─────────────────────────────── Tauri commands（对应 preload 的 11 个方法）───────────────────────────────

#[tauri::command]
fn get_backend_url(state: State<'_, AppState>) -> String {
    state.gateway_base.clone()
}

#[tauri::command]
fn get_window_size(window: WebviewWindow) -> Value {
    let (w, h) = window
        .inner_size()
        .map(|s| (s.width, s.height))
        .unwrap_or((1920, 1080));
    json!({ "width": w, "height": h })
}

#[tauri::command]
fn set_ignore_mouse(window: WebviewWindow, ignore: bool) {
    let _ = window.set_ignore_cursor_events(ignore);
}

#[tauri::command]
fn get_perception_config(state: State<'_, AppState>) -> Value {
    json!({
        "enabled": state.perception_enabled.load(Ordering::Relaxed),
        "intervalMs": state.perception_interval_ms,
        "video": true,
        "audio": true
    })
}

#[tauri::command]
async fn send_desktop_perception(state: State<'_, AppState>, payload: Value) -> Result<(), String> {
    if !state.perception_enabled.load(Ordering::Relaxed) {
        return Ok(());
    }
    let base = state.gateway_base.clone();
    let typ = payload.get("type").and_then(|v| v.as_str()).unwrap_or("");
    if typ == "frame" {
        if let Some(img) = payload.get("image_base64").and_then(|v| v.as_str()) {
            let body = json!({
                "image_base64": img,
                "mime": payload.get("mime").and_then(|v| v.as_str()).unwrap_or("image/jpeg"),
                "source": payload.get("source").and_then(|v| v.as_str()).unwrap_or("desktop_camera")
            });
            // 失败非致命（后端未就绪/网络抖动），丢弃本帧即可。
            let _ = state
                .http
                .post(format!("{base}/api/perception/desktop/frame"))
                .json(&body)
                .send()
                .await;
        }
    } else if typ == "audio" {
        if let Some(audio) = payload.get("audio_base64").and_then(|v| v.as_str()) {
            let body = json!({
                "audio_base64": audio,
                "mime": payload.get("mime").and_then(|v| v.as_str()).unwrap_or("audio/webm")
            });
            let _ = state
                .http
                .post(format!("{base}/api/perception/desktop/audio"))
                .json(&body)
                .send()
                .await;
        }
    }
    Ok(())
}

// 配置/设置后台刷新 + config-ready 广播（等价 electron scheduleConfigRefresh/scheduleSettingsRefresh）。
// 立即返回缓存、后台异步刷新，刷到手后广播 galaxy:config-ready(kind)，渲染层(useConfigCache)就地重取。
fn schedule_config_refresh(app: AppHandle) {
    let st = app.state::<AppState>();
    if st.config_refresh_inflight.swap(true, Ordering::SeqCst) {
        return; // 已有刷新在飞，去重
    }
    let base = st.gateway_base.clone();
    let http = st.http.clone();
    tauri::async_runtime::spawn(async move {
        if let Ok(resp) = http.get(format!("{base}/api/config")).send().await {
            if resp.status().is_success() {
                if let Ok(v) = resp.json::<Value>().await {
                    *app.state::<AppState>().config_cache.lock().unwrap() = v;
                    let _ = app.emit("galaxy:config-ready", "config");
                }
            }
        }
        app.state::<AppState>().config_refresh_inflight.store(false, Ordering::SeqCst);
    });
}

fn schedule_settings_refresh(app: AppHandle) {
    let st = app.state::<AppState>();
    if st.settings_refresh_inflight.swap(true, Ordering::SeqCst) {
        return;
    }
    let base = st.gateway_base.clone();
    let http = st.http.clone();
    tauri::async_runtime::spawn(async move {
        if let Ok(resp) = http.get(format!("{base}/api/config/all")).send().await {
            if resp.status().is_success() {
                if let Ok(v) = resp.json::<Value>().await {
                    *app.state::<AppState>().settings_cache.lock().unwrap() = v;
                    let _ = app.emit("galaxy:config-ready", "settings");
                }
            }
        }
        app.state::<AppState>().settings_refresh_inflight.store(false, Ordering::SeqCst);
    });
}

// GET 配置(精简版 — 模型 tab)：立即返回缓存，后台异步刷新并广播 config-ready。
#[tauri::command]
fn get_config(app: AppHandle, state: State<'_, AppState>) -> Value {
    let cached = state.config_cache.lock().unwrap().clone();
    schedule_config_refresh(app);
    cached
}

// GET 配置(完整明细 — 设置 tab)：立即返回缓存，后台异步刷新并广播 config-ready。
#[tauri::command]
fn get_settings(app: AppHandle, state: State<'_, AppState>) -> Value {
    let cached = state.settings_cache.lock().unwrap().clone();
    schedule_settings_refresh(app);
    cached
}

// 窗口级按键兜底调用（shim 的 keydown → 切换面板；等价 electron before-input-event → togglePanel）。
#[tauri::command]
fn toggle_panel_cmd(app: AppHandle) {
    toggle_panel(&app);
}

#[tauri::command]
async fn set_config(app: AppHandle, state: State<'_, AppState>, config: Value) -> Result<Value, String> {
    let base = state.gateway_base.clone();
    // 后端 ConfigUpdateRequest 的体格式是 {"config": {KEY: VALUE}}(见
    // core/routes/config.py)——此前这里直接 .json(&config) 发裸 {KEY: VALUE},
    // FastAPI 校验必 422,Tauri 壳下保存 API Key 100% 失败("Backend rejected
    // config")。Electron 的 IPC 层(main.js galaxy:set-config)一直是包壳发送的。
    match state
        .http
        .post(format!("{base}/api/config"))
        .json(&json!({ "config": config }))
        .send()
        .await
    {
        Ok(resp) if resp.status().is_success() => {
            // 合并进缓存并广播 config-update（对齐 Electron 的 BrowserWindow.getAllWindows().send）。
            let merged = {
                let mut cache = state.config_cache.lock().unwrap();
                if let (Some(obj), Some(patch)) = (cache.as_object_mut(), config.as_object()) {
                    for (k, v) in patch {
                        obj.insert(k.clone(), v.clone());
                    }
                } else {
                    *cache = config.clone();
                }
                cache.clone()
            };
            // 同步更新完整明细缓存里对应项的 value（保持 ConfigItem 形状，等价 electron），
            // 否则设置 tab 下次读缓存会拿到旧值/undefined。
            {
                let mut sc = state.settings_cache.lock().unwrap();
                if let (Some(sobj), Some(patch)) = (sc.as_object_mut(), config.as_object()) {
                    for (k, v) in patch {
                        if let Some(item) = sobj.get_mut(k).and_then(|it| it.as_object_mut()) {
                            item.insert("value".to_string(), v.clone());
                        }
                    }
                }
            }
            let _ = app.emit("galaxy:config-update", merged);
            Ok(json!({ "success": true }))
        }
        Ok(_) => Ok(json!({ "success": false, "error": "Backend rejected config" })),
        Err(e) => Ok(json!({ "success": false, "error": e.to_string() })),
    }
}

#[tauri::command]
async fn save_config(state: State<'_, AppState>) -> Result<Value, String> {
    let base = state.gateway_base.clone();
    match state.http.post(format!("{base}/api/config/save")).send().await {
        Ok(resp) => Ok(json!({ "success": resp.status().is_success() })),
        Err(e) => Ok(json!({ "success": false, "error": e.to_string() })),
    }
}

// ─────────────── Electron 对齐补全:后端状态 / 拉起 / 容器运行时桥 ───────────────
// 此前 Tauri 壳缺 6 个 galaxyAPI 方法(getBackendStatus/startBackend/
// getRuntimeStatus/testRuntime/saveRuntime/getConfigSaveTimeoutMs),面板对应
// 功能(网关离线横幅/重试启动网关/容器运行时选择)在 Tauri 下静默降级或失效。
// 逐一按 electron/main.js 的语义补齐。

/// 与 electron/main.js 对齐:CONFIG_FETCH_BUDGET_MS(60s)+ATTEMPT(8s)+MARGIN(10s)。
#[tauri::command]
fn get_config_save_timeout_ms() -> u64 {
    78000
}

#[tauri::command]
async fn get_backend_status(state: State<'_, AppState>) -> Result<Value, String> {
    let base = state.gateway_base.clone();
    let healthy = matches!(
        state
            .http
            .get(format!("{base}/health"))
            .timeout(std::time::Duration::from_millis(2500))
            .send()
            .await,
        Ok(resp) if resp.status().is_success()
    );
    Ok(json!({ "ok": true, "healthy": healthy }))
}

/// 仓库根定位:从可执行文件路径向上找 main.py(开发态 target/{debug,release} 深四层),
/// 兜底当前目录。
fn project_root() -> std::path::PathBuf {
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        let mut p = exe.as_path();
        while let Some(parent) = p.parent() {
            candidates.push(parent.to_path_buf());
            p = parent;
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }
    for c in &candidates {
        if c.join("main.py").is_file() && c.join("electron").is_dir() {
            return c.clone();
        }
    }
    std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
}

fn python_exec() -> String {
    for var in ["GALAXY_PYTHON_EXECUTABLE", "PYTHON"] {
        if let Ok(v) = std::env::var(var) {
            if !v.trim().is_empty() {
                return v.trim().to_string();
            }
        }
    }
    if cfg!(windows) { "python".into() } else { "python3".into() }
}

/// 拉起后端(等价 electron ensureGatewayOnline 的 spawn 部分)并轮询 /health
/// 直至就绪或超时(90s,对齐 BACKEND_START_TIMEOUT_MS)。
#[tauri::command]
async fn start_backend(state: State<'_, AppState>) -> Result<Value, String> {
    let base = state.gateway_base.clone();
    let probe = |client: reqwest::Client, base: String| async move {
        matches!(
            client
                .get(format!("{base}/health"))
                .timeout(std::time::Duration::from_millis(2500))
                .send()
                .await,
            Ok(r) if r.status().is_success()
        )
    };
    if probe(state.http.clone(), base.clone()).await {
        return Ok(json!({ "ok": true, "healthy": true, "already_running": true }));
    }

    let root = project_root();
    let port = base.rsplit(':').next().unwrap_or("9000").to_string();
    // 唯一入口 main.py。原来拉的是 `launch_desktop.py --backend --skip-check
    // --skip-model-download --no-interactive`，那个文件已随启动器统一删除
    // (docs/LAUNCHER_UNIFICATION_PLAN.md 第 8 步)——照着老路径拉只会 spawn 失败,
    // 而 stdout/stderr 都被 null 掉了,失败信息一个字都看不到,表现就是
    // "backend did not become healthy within 90s"。
    //
    // 另外三个 flag 不需要等价物,逐条核过:
    //   --skip-model-download  main.py 的模型拉取是 background_pull,本来就不阻塞启动
    //   --no-interactive       选型提示已由 core/model_selection.rs 侧的
    //                          `sys.stdin.isatty()` 闸挡住,这里既无 tty 也无 stdin
    //   --skip-check           main.py 的 Phase 0 只做本地探测,不联网、不阻塞
    let spawn_res = std::process::Command::new(python_exec())
        .args(["main.py", "--backend"])
        .current_dir(&root)
        .env("GALAXY_GATEWAY_PORT", &port)
        .env("PORT", &port)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
    if let Err(e) = spawn_res {
        return Ok(json!({ "ok": false, "error": format!("spawn failed: {e}") }));
    }

    // 轮询至 90s(1.5s 间隔),与 Electron 的启动预算一致。
    for _ in 0..60 {
        tokio::time::sleep(std::time::Duration::from_millis(1500)).await;
        if probe(state.http.clone(), base.clone()).await {
            return Ok(json!({ "ok": true, "healthy": true }));
        }
    }
    Ok(json!({ "ok": false, "healthy": false, "error": "backend did not become healthy within 90s" }))
}

/// 与 electron/main.js 的 _RUNTIME_BRIDGE_SCRIPT 逐字一致(共享 core.container_runtime)。
const RUNTIME_BRIDGE_SCRIPT: &str = r#"
import json, sys
from core import container_runtime as cr
action = sys.argv[1] if len(sys.argv) > 1 else "status"
payload = {}
if len(sys.argv) > 2:
    try:
        payload = json.loads(sys.argv[2])
    except Exception:
        payload = {}
if action == "status":
    out = cr.inspect_runtime_state()
elif action == "test":
    out = cr.test_runtime(str(payload.get("runtime", "")))
elif action == "save":
    out = cr.set_runtime_choice(str(payload.get("runtime", "")), source="tauri-panel")
else:
    out = {"ok": False, "error": f"unknown action: {action}"}
print(json.dumps(out, ensure_ascii=False))
"#;

fn run_runtime_bridge(action: &str, payload: Value) -> Value {
    let out = std::process::Command::new(python_exec())
        .args(["-c", RUNTIME_BRIDGE_SCRIPT, action, &payload.to_string()])
        .current_dir(project_root())
        .output();
    match out {
        Err(e) => json!({ "ok": false, "error": e.to_string() }),
        Ok(o) if !o.status.success() => {
            let err = String::from_utf8_lossy(&o.stderr).trim().to_string();
            json!({ "ok": false, "error": if err.is_empty() { format!("python exited with {:?}", o.status.code()) } else { err } })
        }
        Ok(o) => {
            let stdout = String::from_utf8_lossy(&o.stdout);
            let tail = stdout.lines().map(str::trim).filter(|l| !l.is_empty()).last().unwrap_or("{}");
            serde_json::from_str(tail)
                .unwrap_or_else(|_| json!({ "ok": false, "error": "runtime bridge output parse failed" }))
        }
    }
}

#[tauri::command]
async fn get_runtime_status() -> Result<Value, String> {
    Ok(tauri::async_runtime::spawn_blocking(|| run_runtime_bridge("status", json!({})))
        .await
        .unwrap_or_else(|e| json!({ "ok": false, "error": e.to_string() })))
}

#[tauri::command]
async fn test_runtime(runtime: String) -> Result<Value, String> {
    if !["docker", "podman"].contains(&runtime.as_str()) {
        return Ok(json!({ "ok": false, "error": "invalid runtime" }));
    }
    Ok(tauri::async_runtime::spawn_blocking(move || {
        run_runtime_bridge("test", json!({ "runtime": runtime }))
    })
    .await
    .unwrap_or_else(|e| json!({ "ok": false, "error": e.to_string() })))
}

#[tauri::command]
async fn save_runtime(runtime: String) -> Result<Value, String> {
    if !["docker", "podman"].contains(&runtime.as_str()) {
        return Ok(json!({ "ok": false, "error": "invalid runtime" }));
    }
    Ok(tauri::async_runtime::spawn_blocking(move || {
        run_runtime_bridge("save", json!({ "runtime": runtime }))
    })
    .await
    .unwrap_or_else(|e| json!({ "ok": false, "error": e.to_string() })))
}

// ─────────────────────────────── 入口 ───────────────────────────────

fn main() {
    // WebView2（Windows）附加参数：
    //  - --use-fake-ui-for-media-stream：让 getUserMedia 自动放行（采集是否真的发生由 App 的
    //    感知开关控制；这里只是免去系统级权限弹窗，等价 Electron 的 setPermissionRequestHandler）。
    //  - GALAXY_ELECTRON_GPU=0 → --disable-gpu（软件渲染兜底，对齐 main.js 的自适应策略）。
    {
        let mut args = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").unwrap_or_default();
        if !args.contains("use-fake-ui-for-media-stream") {
            args.push_str(" --use-fake-ui-for-media-stream");
        }
        let gpu = std::env::var("GALAXY_ELECTRON_GPU")
            .unwrap_or_default()
            .trim()
            .to_lowercase();
        if ["0", "false", "no", "off"].contains(&gpu.as_str()) && !args.contains("disable-gpu") {
            args.push_str(" --disable-gpu");
        }
        std::env::set_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", args.trim());
    }

    let port = std::env::var("GALAXY_GATEWAY_PORT")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .or_else(|| std::env::var("PORT").ok().filter(|s| !s.trim().is_empty()))
        .unwrap_or_else(|| "9000".to_string());
    let gateway_base = format!("http://localhost:{}", port.trim());
    let ipc_port: u16 = std::env::var("GALAXY_IPC_PORT")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(9231);
    let perception_interval_ms: u64 = std::env::var("GALAXY_DESKTOP_PERCEPTION_INTERVAL_MS")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(2000);

    let state = AppState {
        gateway_base,
        ipc_port,
        perception_interval_ms,
        perception_enabled: AtomicBool::new(false),
        overlay_awake: AtomicBool::new(false),
        http: reqwest::Client::new(),
        config_cache: Mutex::new(json!({})),
        settings_cache: Mutex::new(json!({})),
        config_refresh_inflight: AtomicBool::new(false),
        settings_refresh_inflight: AtomicBool::new(false),
    };

    tauri::Builder::default()
        // 单实例锁（对齐 Electron requestSingleInstanceLock）：后来者唤起已存在窗口后退出。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(win) = app.get_webview_window("overlay") {
                let _ = win.show();
                let _ = win.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            get_window_size,
            set_ignore_mouse,
            get_perception_config,
            send_desktop_perception,
            get_config,
            get_settings,
            set_config,
            save_config,
            get_backend_status,
            start_backend,
            get_runtime_status,
            test_runtime,
            save_runtime,
            get_config_save_timeout_ms,
            toggle_panel_cmd
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            // 1) 感知授权（env > 持久化 > 首启弹框）。
            let granted = resolve_perception_consent(&handle);
            handle
                .state::<AppState>()
                .perception_enabled
                .store(granted, Ordering::Relaxed);

            // 2) 覆盖层窗口：创建 → 覆盖主屏 bounds → 点击穿透 → 显示并置顶。
            //    多重保险：即便加载较慢，也在 setup 即定位+显示，绝不把外壳卡在不可见。
            match build_overlay(&handle) {
                Ok(win) => {
                    position_overlay_to_primary(&handle, &win);
                    let _ = win.show();
                    let _ = win.set_always_on_top(true);
                    // 鼠标穿透放在 show 之后（Linux/GTK 上过早调用会 panic；见 set_overlay_phase 注释）。
                    let _ = win.set_ignore_cursor_events(true);
                    handle
                        .state::<AppState>()
                        .overlay_awake
                        .store(true, Ordering::Relaxed);
                }
                Err(e) => eprintln!("[Main] 覆盖层创建失败: {e}"),
            }

            // 3) 全局快捷键（与 Electron 同一组候选键；任一注册成功即可用）。
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
            let gs = handle.global_shortcut();
            let wake = ["Ctrl+Alt+Space", "Ctrl+Shift+Space", "Ctrl+Alt+G", "Ctrl+Shift+G"];
            let hide = ["Ctrl+Alt+H", "Ctrl+Shift+H"];
            let panel = ["F12", "Ctrl+F12", "Ctrl+Shift+P"];
            for acc in wake {
                let _ = gs.on_shortcut(acc, move |app, _sc, ev| {
                    if ev.state == ShortcutState::Pressed {
                        toggle_overlay_wake(app);
                    }
                });
            }
            for acc in hide {
                let _ = gs.on_shortcut(acc, move |app, _sc, ev| {
                    if ev.state == ShortcutState::Pressed {
                        set_overlay_phase(app, false);
                    }
                });
            }
            for acc in panel {
                let _ = gs.on_shortcut(acc, move |app, _sc, ev| {
                    if ev.state == ShortcutState::Pressed {
                        toggle_panel(app);
                    }
                });
            }

            // 4) IPC HTTP 接收端 + 面板数据轮询。
            let ipc_port = handle.state::<AppState>().ipc_port;
            start_ipc_http(handle.clone(), ipc_port);
            start_panel_feed_poll(handle.clone());
            // 第一态原生连续屏幕采集（与渲染层摄像头/麦克风共同构成一体化感知）。
            start_native_screen_capture(handle.clone());

            // 5) 启动即预载配置/设置缓存（等价 electron 启动期 schedule*Refresh）：
            //    后端就绪后广播 galaxy:config-ready，面板打开时缓存已暖、tab 就地刷新。
            schedule_config_refresh(handle.clone());
            schedule_settings_refresh(handle.clone());

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Galaxy overlay (Tauri)");
}
