import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(() => {
  const backendHost = process.env.BACKEND_HOST || '127.0.0.1'
  const backendPort = process.env.BACKEND_PORT || '8001'
  const backendTarget = `http://${backendHost}:${backendPort}`

  // All API route prefixes used by the frontend
  const proxyRoutes = [
    '/upload', '/chat', '/files', '/health',
    '/ollama', '/provider', '/export', '/session', '/sessions',
    '/auth', '/guest',
    '/user', '/billing',
    '/analyses', '/templates', '/reports',
    '/history', '/datasets',
  ]

  const proxy = {}
  for (const route of proxyRoutes) {
    proxy[route] = {
      target: backendTarget,
      changeOrigin: true,
    }
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy,
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
