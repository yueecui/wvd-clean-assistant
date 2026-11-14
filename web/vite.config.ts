import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// Dev: `pnpm dev` 起 Vite(5173)，/api 转发到 python 后端(23456)
// Prod: `pnpm build` 产出 web/dist，由 app/main.py 直接 serve（同源）
const BACKEND = process.env.WVD_BACKEND || 'http://127.0.0.1:23456'

export default defineConfig({
  base: './',
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: BACKEND, changeOrigin: true } },
  },
  build: { outDir: 'dist', emptyOutDir: true, target: 'chrome110' },
})
