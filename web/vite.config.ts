import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Config runs in Node; declare `process` locally so tsc doesn't need @types/node.
declare const process: { env: Record<string, string | undefined> }

// JEMA web frontend — faithful port of the Claude Design hi-fi exports.
//
// `base` is configurable via the VITE_BASE env var so the same build serves
// from a root domain (`/`, dev + custom domain / HF static Space) or from a
// GitHub Pages *project* site (`/<repo>/`). It flows into import.meta.env.BASE_URL,
// which `lib/data.ts` uses to resolve the /data/web/** snapshot URLs, so the
// data fetches stay correct under any base. Defaults to `/`.
// The dev server proxies `/api` to the local `repower web-api` (default :8787),
// which powers the app's interactive mode (Manage writes + Run catch-up). This
// proxy exists ONLY under `npm run dev`; a production `vite build` for GitHub
// Pages has no `/api`, so the deployed site stays read-only.
export default defineConfig({
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    strictPort: false,
    proxy: {
      '/api': {
        target: process.env.VITE_API || 'http://127.0.0.1:8787',
        changeOrigin: true,
      },
    },
  },
})
