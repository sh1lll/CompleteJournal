// Keeps the capture page available offline (only active on secure origins,
// e.g. localhost or a private HTTPS network). Notes themselves are queued in
// IndexedDB by the page, so they survive with or without this worker.
const CACHE = 'cj-capture-v1';
const SHELL = ['/capture', '/manifest.webmanifest', '/icon.svg'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))));
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || !SHELL.includes(url.pathname)) return;
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r;
  }).catch(() => caches.match(e.request)));
});
