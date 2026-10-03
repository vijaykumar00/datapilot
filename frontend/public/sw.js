/*
 * Retirement service worker.
 *
 * Earlier builds shipped a service worker with a hard-coded loopback API
 * fallback.  The app no longer registers a service worker, but browsers that
 * installed the old one keep checking this URL for updates.  This version
 * replaces it, deletes its caches, unregisters itself and reloads open tabs so
 * they talk to the real API again.  Served with Cache-Control: no-cache (nginx).
 */
self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try {
      const keys = await caches.keys()
      await Promise.all(keys.map((key) => caches.delete(key)))
    } catch (_) { /* ignore */ }
    await self.registration.unregister()
    const clients = await self.clients.matchAll({ type: 'window' })
    for (const client of clients) {
      try { client.navigate(client.url) } catch (_) { /* ignore */ }
    }
  })())
})
