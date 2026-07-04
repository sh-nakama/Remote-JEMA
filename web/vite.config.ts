import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// JEMA web frontend — faithful port of the Claude Design hi-fi exports.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true, strictPort: false },
})
