import fs from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// TLS, when scripts/dev.sh was started with WEB_HTTPS=1.
// This is not about eavesdropping on a dev server. navigator.geolocation is
// gated on a SECURE CONTEXT, which means https or localhost and nothing else:
// over http://<lan-ip> the browser refuses the call outright, so the locate
// button cannot be tested from a phone — the one device that actually has a
// GPS radio — without it. Unset means plain http, exactly as before.
const tlsKey = process.env.WEB_TLS_KEY
const tlsCert = process.env.WEB_TLS_CERT
const https = tlsKey && tlsCert
  ? { key: fs.readFileSync(tlsKey), cert: fs.readFileSync(tlsCert) }
  : undefined

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    https,
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
