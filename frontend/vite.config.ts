/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Ports are env-configured — scripts/dev-full.js resolves free ports BEFORE the
// dev server starts and passes them down, so the proxy target can never drift
// from the backend that actually bound. strictPort keeps that contract honest:
// if the agreed port is taken, fail loudly instead of silently serving 3001
// while Electron loads 3000.
const frontendPort = Number(process.env.LOCALMIND_FRONTEND_PORT) || 3000
const backendHost = process.env.LOCALMIND_HOST || '127.0.0.1'
const backendPort = Number(process.env.LOCALMIND_PORT) || 8000

export default defineConfig({
  // Relative asset URLs: the packaged Electron app loads dist/index.html from disk (file://),
  // where an absolute "/assets/..." points at the filesystem root, finds nothing, and leaves the
  // window blank forever. "./" works from a file, a web server and the dev server alike.
  base: './',
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
    port: frontendPort,
    strictPort: true,
    // Bind IPv4 explicitly — the dev tooling (wait-frontend, Electron, the
    // orchestrator's probes) all target 127.0.0.1, and an IPv6-only localhost
    // bind is exactly the drift class this port contract exists to prevent.
    host: backendHost === '0.0.0.0' ? 'localhost' : backendHost,
    proxy: {
      '/api': {
        target: `http://${backendHost}:${backendPort}`,
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
