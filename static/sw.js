/* CRM Base Service Worker */
var CACHE = 'crm-v1';
var STATIC = [
  '/static/css/theme.css',
  '/static/css/sidebar.css',
  '/static/css/mobile.css',
  '/static/js/sidebar.js',
  '/static/img/my_logo.png',
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(STATIC); })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);
  // Cache-first for static assets
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(function (cached) {
        return cached || fetch(e.request).then(function (resp) {
          var clone = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, clone); });
          return resp;
        });
      })
    );
    return;
  }
  // Network-first for everything else
  e.respondWith(fetch(e.request).catch(function () { return caches.match(e.request); }));
});
