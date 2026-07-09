import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (err, req, res) => {
            // Backend not ready yet — return a clean 503 so the
            // UI health-check loop can retry gracefully instead of
            // crashing on a JSON parse error from an empty 502 body.
            // Cast to NodeJS.ErrnoException to access the .code property
            // (a Node.js extension not present on the base Error type).
            const errnoErr = err as NodeJS.ErrnoException
            if (errnoErr.code === 'ECONNREFUSED') {
              if (!res.headersSent) {
                res.writeHead(503, { 'Content-Type': 'application/json' })
                res.end(JSON.stringify({ status: 'unavailable', error: 'backend_starting' }))
              }
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
