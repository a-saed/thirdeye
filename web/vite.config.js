import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    fs: {
      // config/thresholds.json lives at the repo root and is imported by
      // src/lib/thresholds.ts. It is the same file the pipeline and the API
      // read — copying it into web/ would recreate the duplication this
      // import exists to remove.
      allow: ['..'],
    },
    // The Go API serves from RAM on :8080. Proxying keeps the frontend
    // same-origin, so there is no CORS config to get wrong and no API host
    // baked into the bundle.
    proxy: {
      // No rewrite: the API serves JSON under /api itself, because the bare
      // /report path is HTML now (server-rendered meta for share previews).
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    },
  },
})
