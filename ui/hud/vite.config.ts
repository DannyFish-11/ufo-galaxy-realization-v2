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
      '@contract': fileURLToPath(
        new URL(
          '../../electron/renderer/panel/src/types/phase_contract.gen.ts',
          import.meta.url,
        ),
      ),
    },
  },
  server: {
    fs: { allow: ['..', '../..'] },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
  },
});
