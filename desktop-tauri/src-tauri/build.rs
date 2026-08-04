//! 构建脚本：把运行期需要的前端资产暂存到 `../frontend/`，再交给 tauri_build。
//!
//! 为什么需要这一步
//! ----------------
//! `tauri.conf.json` 的 `frontendDist` 原本直接指向 `../../electron/renderer`，
//! 好处是"不复制前端、单一真相来源"。代价是 **tauri 会把那个目录整个嵌进二进制**，
//! 而那里面有 68 MB 的 `electron/renderer/panel/node_modules` —— 运行期一个字节
//! 都用不到（Electron 与 Tauri 都只加载 `panel/dist/`）。
//!
//! 这直接抵消掉迁移 Tauri 的主要收益：换壳就是为了从"每个应用背一份 Chromium"
//! 变成"用系统 WebView"，结果二进制里塞了 68 MB 的构建期依赖。
//!
//! 为什么不用配置项解决
//! --------------------
//! 查过 `tauri-codegen-2.6.3/src/embedded_assets.rs`：资产收集是
//!
//! ```ignore
//! WalkDir::new(&path).follow_links(true).contents_first(true)
//! ```
//!
//! **没有任何过滤/忽略机制** —— 没有 `.taurignore`，没有 exclude 配置项，
//! `frontendDist` 底下有什么就嵌什么。所以只能从目录内容下手。
//!
//! 为什么不改目录结构
//! ------------------
//! 把面板源码移出 `electron/renderer/` 也能解决，但仓库里有 34 个文件、82 处
//! 引用 `renderer/panel` 这条路径（CI、启动器、测试、生成脚本、Electron 主进程）。
//! 为省 68 MB 动 82 处引用，风险与收益不成比例。
//!
//! 关于"不复制前端"那条原则
//! ------------------------
//! README 里那句话防的是**源码漂移**：两份都能编辑的前端，早晚各自演化。
//! 这里生成的 `frontend/` 是**构建产物**（已 gitignore，每次构建重建），
//! 跟 `panel/dist/` 是同一性质，不构成第二份可编辑的源。
//!
//! 排除用【黑名单】而不是白名单
//! ----------------------------
//! 这是刻意的：新加一个前端文件时，白名单会**默认漏掉**它，而漏掉的后果是
//! "覆盖层只在 Tauri release 构建里坏掉"—— CI 不构建 Tauri，没人会发现。
//! 黑名单则是新文件默认带上，只有已知的构建期垃圾被挡在外面。失败方向要选
//! 可恢复的那个。

use std::fs;
use std::path::{Path, PathBuf};

/// 相对 `electron/renderer/` 的排除项。命中即整棵子树跳过。
///
/// 只列**构建期产物与源码**：运行期加载的是 `panel/dist/`，面板源码、依赖、
/// 各类配置文件都进不了 WebView。
const EXCLUDE: &[&str] = &[
    "panel/node_modules",     // 68 MB，本脚本存在的全部理由
    "panel/src",              // TS 源码，运行期加载的是 dist/
    "panel/package.json",     //
    "panel/package-lock.json", //
    "panel/tsconfig.json",    //
    "panel/tsconfig.node.json",
    "panel/vite.config.ts",
    "panel/DESIGN.md",
    "types",                  // lumiv.d.ts —— 只给编辑器用
    "presence_motion.test.js", // node:test 用例，浏览器里跑不着
];

fn main() {
    let src = PathBuf::from("../../electron/renderer");
    let dst = PathBuf::from("../frontend");

    if !src.is_dir() {
        panic!(
            "找不到前端源目录 {} —— frontendDist 的暂存无法进行。\
             请在仓库根目录下构建（desktop-tauri/src-tauri）。",
            src.display()
        );
    }

    // 整个重建而不是增量同步：源里删掉的文件必须跟着消失，否则二进制里会留下
    // 幽灵资产。8 MB 量级，全量复制的开销可以忽略。
    if dst.exists() {
        fs::remove_dir_all(&dst).unwrap_or_else(|e| panic!("清理 {} 失败: {e}", dst.display()));
    }

    let copied = mirror(&src, &dst, &src);
    println!("cargo:warning=frontendDist 暂存完成：{copied} 个文件 → {}", dst.display());

    // 源码变了要重新暂存。cargo 会递归看这个目录里的 mtime。
    println!("cargo:rerun-if-changed=../../electron/renderer");

    tauri_build::build()
}

/// 递归镜像 `dir` 到 `dst`，跳过 EXCLUDE 命中的路径。返回复制的文件数。
fn mirror(dir: &Path, dst_root: &Path, src_root: &Path) -> usize {
    let mut n = 0;
    let entries = fs::read_dir(dir).unwrap_or_else(|e| panic!("读取 {} 失败: {e}", dir.display()));

    for entry in entries {
        let entry = entry.expect("目录项读取失败");
        let path = entry.path();

        let rel = path
            .strip_prefix(src_root)
            .expect("路径不在源根之下")
            .to_string_lossy()
            .replace('\\', "/"); // Windows 上统一成 / 再比对

        if EXCLUDE.iter().any(|ex| rel == *ex || rel.starts_with(&format!("{ex}/"))) {
            continue;
        }

        let target = dst_root.join(path.strip_prefix(src_root).expect("路径不在源根之下"));
        if path.is_dir() {
            fs::create_dir_all(&target).unwrap_or_else(|e| panic!("创建 {} 失败: {e}", target.display()));
            n += mirror(&path, dst_root, src_root);
        } else {
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent).unwrap_or_else(|e| panic!("创建 {} 失败: {e}", parent.display()));
            }
            fs::copy(&path, &target)
                .unwrap_or_else(|e| panic!("复制 {} → {} 失败: {e}", path.display(), target.display()));
            n += 1;
        }
    }
    n
}
