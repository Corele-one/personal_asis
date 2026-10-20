// Retire the old search PWA cache. No personal API responses are cached offline.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const name of await caches.keys())await caches.delete(name);await self.clients.claim();})()));
