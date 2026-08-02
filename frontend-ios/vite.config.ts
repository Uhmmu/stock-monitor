import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: { alias: { '@shared': new URL('../packages/shared/src', import.meta.url).pathname } },
  server: { port: 5174, proxy: { '/api': 'http://localhost:8000' } },
  test: { include: ['src/**/*.test.ts'] },
})
