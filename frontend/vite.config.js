import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(() => {
  const backendHost = process.env.BACKEND_HOST || '127.0.0.1'
  const backendPort = process.env.BACKEND_PORT || '8001'
  const backendTarget = `http://${backendHost}:${backendPort}`

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/upload': backendTarget,
        '/chat': backendTarget,
        '/files': backendTarget,
        '/health': backendTarget,
        '/ollama': backendTarget,
        '/provider': backendTarget,
      }
    },
    optimizeDeps: {
      include: ['plotly.js-dist-min'],
    },
    build: {
      commonjsOptions: {
        include: [/plotly\.js/, /node_modules/],
      },
    },
  }
})
