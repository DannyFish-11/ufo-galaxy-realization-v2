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
    setConfig: function (config) { return invoke('set_config', { config: config }); },
    onConfigUpdate: function (cb) { var un = null; listen('galaxy:config-update', cb).then(function (f) { un = f; }); return function () { if (un) un(); }; },
    saveConfig: function () { return invoke('save_config'); }
  };
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
    if let Some(win) = app.get_webview_window("panel") {
        let visible = win.is_visible().unwrap_or(false);
        if visible {
            let _ = win.hide();
            println!("[Panel] Hidden");
        } else {
            let _ = win.show();
            let _ = win.set_focus();
            println!("[Panel] Shown");
        }
        return;
    }
    match build_panel(app) {
        Ok(win) => {
            let _ = win.show();
            let _ = win.set_focus();
            println!("[Panel] Created & Shown");
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
            "允许 Galaxy 使用摄像头与麦克风？\n\n\
             授权后，Galaxy 能「看到/听到」你的桌面环境，由本地多模态模型(Gemma4 / MiniCPM-o)\
             原生理解，提供更自然的助理体验。采集仅在本机处理；可随时在设置中关闭。",
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

#[tauri::command]
async fn get_config(state: State<'_, AppState>) -> Result<Value, String> {
    let base = state.gateway_base.clone();
    match state.http.get(format!("{base}/api/config")).send().await {
        Ok(resp) if resp.status().is_success() => match resp.json::<Value>().await {
            Ok(v) => {
                *state.config_cache.lock().unwrap() = v.clone();
                Ok(v)
            }
            Err(_) => Ok(state.config_cache.lock().unwrap().clone()),
        },
        _ => Ok(state.config_cache.lock().unwrap().clone()),
    }
}

#[tauri::command]
async fn set_config(app: AppHandle, state: State<'_, AppState>, config: Value) -> Result<Value, String> {
    let base = state.gateway_base.clone();
    match state
        .http
        .post(format!("{base}/api/config"))
        .json(&config)
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
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            get_backend_url,
            get_window_size,
            set_ignore_mouse,
            get_perception_config,
            send_desktop_perception,
            get_config,
            set_config,
            save_config
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

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Galaxy overlay (Tauri)");
}
