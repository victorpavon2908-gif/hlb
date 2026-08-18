const CACHE='hbl-shell-v5';
const SHELL=['/offline/','/static/hbl/css/app.css','/static/hbl/js/app.js','/static/hbl/img/logo.svg'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)));self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',e=>{
  const req=e.request; const url=new URL(req.url);
  if(req.method!=='GET'||url.origin!==location.origin||url.pathname.startsWith('/api/')||url.pathname.startsWith('/billetera/')||url.pathname.startsWith('/retiros/')||url.pathname.startsWith('/pagos/')) return;
  if(req.mode==='navigate'){e.respondWith(fetch(req).catch(()=>caches.match('/offline/')));return;}
  if(url.pathname.startsWith('/static/hbl/')) e.respondWith(caches.match(req).then(r=>r||fetch(req).then(resp=>{const copy=resp.clone();caches.open(CACHE).then(c=>c.put(req,copy));return resp;})));
});
