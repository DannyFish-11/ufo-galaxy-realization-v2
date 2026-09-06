import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';

/**
 * 面板的构建配置。
 *
 * 没有任何 UI 框架插件 —— 这是刻意的:卡片是一个自己回收 DOM 的池子,
 * 自己写 transform、自己控过渡时序。虚拟 DOM 的调和会跟这些打架
 * (组件一旦重挂载,正在跑的 CSS 过渡会被静默掐掉,画面不报错,只是变顿)。
 *
 * `@contract` 指向【既有的】生成文件,不复制一份:
 * 相位契约的唯一定义处是 core/phase_contract.py,由 scripts/gen_ts_types.py
 * 生成 TS。这里只是多一个消费方。
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // 契约的唯一定义处是 core/phase_contract.py,由 scripts/gen_ts_types.py
      // 生成到 src/types/。面板只是消费方,不复制一份。
      '@contract': fileURLToPath(
        new URL('./src/types/phase_contract.gen.ts', import.meta.url),
      ),
    },
  },
  // Electron 用 `loadFile()` 加载 dist/index.html —— **协议是 file://,不是 http://**。
  //
  // 默认的 base '/' 会生成 `/assets/index-xxx.js`,在 file:// 下解析到**文件系统
  // 根目录**,不是面板目录。相对路径才落在 dist/ 里。
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
    // **必须是 IIFE,不能是 ES module。**
    //
    // 实测:file:// 下 `<script type="module">` 会被 CORS 直接拦掉 ——
    //   Access to script at 'file:///…/index.js' from origin 'null' has been
    //   blocked by CORS policy: Cross origin requests are only supported for
    //   protocol schemes: chrome, chrome-extension, …, http, https
    // 跟 crossorigin 属性无关,module 这个类型本身就走 CORS。脚本不执行,而面板
    // 窗口是 transparent 的,于是表现为「面板打不开」且**没有任何报错**。
    //
    // 这个仓库为同一件事栽过一次(见 electron/main.js createPanelWindow 里那段
    // 说明)。经典脚本没有这条限制,所以打成 IIFE 单块。
    rollupOptions: {
      output: {
        format: 'iife' as const,
        inlineDynamicImports: true,
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  plugins: [
    {
      // Vite 按 build.target 决定 HTML 里那个标签,**不看 output.format** ——
      // 就算打成了 IIFE,它照样写 `type="module" crossorigin`,于是 file:// 下
      // 仍然被 CORS 拦掉。这里把那两个属性去掉,让它成为一个普通脚本。
      //
      // 判据在 tests/test_panel_loads_under_file_protocol.py:那条会真的用
      // file:// 打开构建产物,查面板有没有挂上。改坏了当场就红。
      name: 'galaxy-classic-script',
      enforce: 'post' as const,
      transformIndexHtml(html: string) {
        return html
          .replace(/<script\s+type="module"\s+/g, '<script defer ')
          .replace(/\s+crossorigin(?=[\s>=])/g, '');
      },
    },
  ],
});
