/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
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
    // Split the 1.1MB bundle into smaller chunks for faster initial load.
    // Vendor libs are separated so they can be cached independently of
    // application code. Radix UI alone is ~300KB and rarely changes.
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'radix-vendor': [
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-popover',
            '@radix-ui/react-select',
            '@radix-ui/react-tabs',
            '@radix-ui/react-tooltip',
            '@radix-ui/react-scroll-area',
            '@radix-ui/react-accordion',
            '@radix-ui/react-checkbox',
            '@radix-ui/react-switch',
            '@radix-ui/react-slider',
            '@radix-ui/react-progress',
          ],
          'markdown-vendor': ['react-markdown', 'remark-gfm', 'react-syntax-highlighter'],
          'chart-vendor': ['recharts'],
          'motion-vendor': ['framer-motion'],
          'dnd-vendor': ['@dnd-kit/core', '@dnd-kit/sortable', '@dnd-kit/utilities'],
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
})
