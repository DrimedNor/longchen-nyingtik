// Service Worker — 龙的传人
// 字体缩放与导航增强之外的性能层：
//  - 音频文件：cache-first（下载一次，之后秒开、可离线重听）
//  - 其他同源资源/页面：stale-while-revalidate（先看缓存，后台更新）
const CACHE = "lct-cache-v1"
const AUDIO_EXT = [".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"]

self.addEventListener("install", function () {
  self.skipWaiting()
})

self.addEventListener("activate", function (event) {
  event.waitUntil(
    (async function () {
      const keys = await caches.keys()
      await Promise.all(
        keys
          .filter(function (k) { return k !== CACHE })
          .map(function (k) { return caches.delete(k) }),
      )
      await self.clients.claim()
    })(),
  )
})

self.addEventListener("fetch", function (event) {
  const req = event.request
  if (req.method !== "GET") return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return // 仅同源

  const isAudio = AUDIO_EXT.some(function (ext) {
    return url.pathname.toLowerCase().endsWith(ext)
  })

  if (isAudio) {
    // 音频：缓存优先，首次下载后永久缓存，适合手机反复收听
    event.respondWith(
      (async function () {
        const cache = await caches.open(CACHE)
        const cached = await cache.match(req)
        if (cached) return cached
        try {
          const res = await fetch(req)
          if (res && res.ok) cache.put(req, res.clone())
          return res
        } catch (err) {
          return cached || Response.error()
        }
      })(),
    )
    return
  }

  // 页面/样式/脚本：stale-while-revalidate
  event.respondWith(
    (async function () {
      const cache = await caches.open(CACHE)
      const cached = await cache.match(req)
      const network = fetch(req)
        .then(function (res) {
          if (res && res.ok && (res.type === "basic" || res.type === "default")) {
            cache.put(req, res.clone())
          }
          return res
        })
        .catch(function () {
          return cached
        })
      return cached || network
    })(),
  )
})
