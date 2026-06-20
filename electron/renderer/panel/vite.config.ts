import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Electron 通过 file://(origin=null) 加载构建产物。Vite 默认给 module 脚本/样式注入
// `crossorigin` 属性，这会触发 CORS 检查 → file:// 无 CORS 响应头 → 资源被拦截，
// React 永不挂载 → 透明面板窗口一片空白（用户表现为「F12 面板打不开」）。
// 该插件在构建时移除 crossorigin，使产物可在 file:// 下正常加载。
function stripCrossorigin() {
  return {
    name: 'strip-crossorigin',
    enforce: 'post' as const,
    transformIndexHtml(html: string) {
      return html.replace(/\s+crossorigin(?=[\s/>])/g, '');
    },
  };
}

export default defineConfig({
  // Electron 通过 file:// 加载 index.html，必须用相对路径（./assets/...），
  // 否则 /assets/ 会被解析到文件系统根目录而加载失败。
  base: './',
  plugins: [react(), stripCrossorigin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
      },
    },
  },
});