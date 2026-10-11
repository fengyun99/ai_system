import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9310',
        changeOrigin: true,
        // SSE 透传：禁缓冲
        configure(proxy: any) {
          proxy.on('proxyRes', (proxyRes: any) => {
            if (String(proxyRes.headers['content-type'] || '').includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
      '/mcp': { target: 'http://127.0.0.1:9310', changeOrigin: true },
    },
  },
})
