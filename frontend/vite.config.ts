/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icono.svg'],
      manifest: {
        name: 'ACMA — Gestión de mantenimiento',
        short_name: 'ACMA',
        description: 'Plataforma de gestión de mantenimiento para empresas y prestadores de servicio',
        lang: 'es-MX',
        theme_color: '#1C3D8F',
        background_color: '#F5F7FB',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icono-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icono-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icono-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        importScripts: ['sw-push.js'],
        // Precache del shell y de los módulos de campo; la API va NetworkFirst con respaldo a caché solo en lecturas (P05).
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//],
        runtimeCaching: [
          {
            urlPattern: ({ url, request }) => url.pathname.startsWith('/api/') && request.method === 'GET' && !url.pathname.endsWith('/stream'),
            handler: 'NetworkFirst',
            options: { cacheName: 'acma-api', networkTimeoutSeconds: 8, expiration: { maxEntries: 500, maxAgeSeconds: 7 * 24 * 3600 }, cacheableResponse: { statuses: [200] } },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true, changeOrigin: false }, // P05: WebSocket del chat
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    testTimeout: 20000, // pruebas de interacción en jsdom con IndexedDB simulada
    include: ['tests/**/*.test.{ts,tsx}'],
  },
})
