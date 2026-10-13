const CACHE='asis-shell-v1';
const SHELL=['/','/app.js','/app.css','/icon.svg','/manifest.webmanifest'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(event.request.method==='GET'&&url.origin===self.location.origin&&SHELL.includes(url.pathname)&&!url.search){event.respondWith(fetch(event.request).catch(()=>caches.match(url.pathname)));}});
