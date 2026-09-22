/* Roof Tattoo admin PWA — API asla cache'lenmez; müşteri sitesine dokunulmaz. */
const CACHE_VERSION = 'roof-admin-20260922173000';
const ADMIN_SHELL = [
  '/sp-admin-x7k.html',
  '/admin.js?v=20260922173000',
  '/admin.css?v=20260922173000',
  '/mobile-safe.css?v=20260818131000',
  '/admin.webmanifest',
  '/img/logo.png',
  '/img/pwa/icon-192.png',
  '/img/pwa/icon-512.png',
  '/img/pwa/apple-touch-180.png',
  '/fonts/roboto-latin-400.woff2',
  '/fonts/roboto-latin-ext-400.woff2',
  '/vendor/flatpickr/flatpickr.min.css',
  '/vendor/flatpickr/flatpickr.min.js',
  '/vendor/flatpickr/tr.js',
];

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('push', (event) => {
  let payload = { title: 'Roof Tattoo Gallery', body: 'Yeni bildirim', url: '/sp-admin-x7k.html' };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch {
    /* JSON degilse varsayilan metin kullanilir */
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/img/pwa/icon-192.png',
      badge: '/img/pwa/icon-192.png',
      data: { url: payload.url || '/sp-admin-x7k.html' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/sp-admin-x7k.html';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes('sp-admin-x7k.html') && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(ADMIN_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  );
});

function isApi(url) {
  return url.pathname.startsWith('/api/');
}

function isAdminAsset(url) {
  if (url.origin !== self.location.origin) return false;
  const path = url.pathname;
  return (
    path === '/sp-admin-x7k.html' ||
    path === '/admin.webmanifest' ||
    path === '/admin-sw.js' ||
    path === '/admin.js' ||
    path === '/admin.css' ||
    path === '/mobile-safe.css' ||
    path.startsWith('/img/pwa/') ||
    path === '/img/logo.png' ||
    path.startsWith('/vendor/flatpickr/') ||
    path.startsWith('/fonts/roboto-')
  );
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }

  if (isApi(url)) {
    event.respondWith(fetch(req));
    return;
  }

  if (url.hostname === 'cdnjs.cloudflare.com') {
    event.respondWith(staleWhileRevalidate(req));
    return;
  }

  if (!isAdminAsset(url)) {
    return;
  }

  event.respondWith(networkFirstAdmin(req, url));
});

async function networkFirstAdmin(req, url) {
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(req, fresh.clone());
    }
    return fresh;
  } catch (err) {
    const cached = await caches.match(req) || await caches.match(url.pathname);
    if (cached) return cached;
    if (url.pathname === '/sp-admin-x7k.html' || req.mode === 'navigate') {
      const shell = await caches.match('/sp-admin-x7k.html');
      if (shell) return shell;
    }
    throw err;
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(req);
  const fetching = fetch(req)
    .then((res) => {
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    })
    .catch(() => cached);
  return cached || fetching;
}
