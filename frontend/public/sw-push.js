// Manejador de push PWA (P05): lo importa el service worker generado por vite-plugin-pwa (importScripts).
self.addEventListener('push', (evento) => {
  let datos = { titulo: 'ACMA', cuerpo: '', datos: {} }
  try { datos = evento.data ? evento.data.json() : datos } catch { datos.cuerpo = evento.data ? evento.data.text() : '' }
  evento.waitUntil(self.registration.showNotification(datos.titulo || 'ACMA', { body: datos.cuerpo || '', icon: '/icono-192.png', badge: '/icono-192.png', data: datos.datos || {} }))
})
self.addEventListener('notificationclick', (evento) => {
  evento.notification.close()
  const url = (evento.notification.data && evento.notification.data.url) || '/'
  evento.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((lista) => {
    const abierta = lista.find((c) => 'focus' in c)
    if (abierta) { abierta.navigate(url); return abierta.focus() }
    return self.clients.openWindow(url)
  }))
})
