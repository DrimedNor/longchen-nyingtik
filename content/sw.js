// Service Worker — 龙的传人
// 缓存策略：
//  - 音频文件：cache-first + Range切片修复（下载一次，之后秒开、可离线重听）
//  - 图片文件：cache-first（海报/封面/图标不变动，永久缓存）
//  - 文章内容JSON：stale-while-revalidate（先缓存秒开，后台更新）
//  - HTML/JS/CSS：network-first（保证功能更新即时生效）
const CACHE = "lct-cache-v3"
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

// 从完整缓存响应中切出Range片段（Cache API不允许直接存206）
function sliceResponse(full, rangeHeader) {
  var m = /bytes=(\d+)-(\d*)/.exec(rangeHeader || "")
  if (!m) return full
  return full.arrayBuffer().then(function (buf) {
    var start = parseInt(m[1], 10)
    var end = m[2] ? parseInt(m[2], 10) : buf.byteLength - 1
    if (start >= buf.byteLength) return new Response(null, { status: 416 })
    end = Math.min(end, buf.byteLength - 1)
    return new Response(buf.slice(start, end + 1), {
      status: 206,
      statusText: "Partial Content",
      headers: {
        "Content-Type": full.headers.get("Content-Type") || "application/octet-stream",
        "Content-Range": "bytes " + start + "-" + end + "/" + buf.byteLength,
        "Content-Length": String(end - start + 1)
      }
    })
  })
}

self.addEventListener("fetch", function (event) {
  const req = event.request
  if (req.method !== "GET") return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return // 仅同源

  const isAudio = AUDIO_EXT.some(function (ext) {
    return url.pathname.toLowerCase().endsWith(ext)
  })
  const isImage = /\.(png|jpe?g|webp|gif|ico)$/i.test(url.pathname)
  const isPageJSON = url.pathname.indexOf("/pages/") === 0 && url.pathname.endsWith(".json")

  // ── 音频：cache-first + Range切片修复 ──
  if (isAudio) {
    event.respondWith((async function () {
      const cache = await caches.open(CACHE)
      const cachedFull = await cache.match(url.href)  // match忽略Range头，直接找全量
      if (cachedFull) {
        if (req.headers.has("range")) return sliceResponse(cachedFull, req.headers.get("range"))
        return cachedFull
      }
      try {
        if (req.headers.has("range")) {
          // 首次遇到Range且无缓存：拉全量入缓存，再切片返回
          const full = await fetch(new Request(url.href))
          if (full && full.status === 200) {
            cache.put(url.href, full.clone())
            return sliceResponse(full.clone(), req.headers.get("range"))
          }
          return full
        }
        const res = await fetch(req)
        if (res && res.status === 200) cache.put(req, res.clone())  // 只缓存200
        return res
      } catch (err) {
        const c = await cache.match(url.href)
        return c || Response.error()
      }
    })())
    return
  }

  // ── 图片：cache-first（海报/封面/图标内容不变动）──
  if (isImage) {
    event.respondWith((async function () {
      const cache = await caches.open(CACHE)
      const cached = await cache.match(req)
      if (cached) return cached
      try {
        const res = await fetch(req)
        if (res && res.status === 200) cache.put(req, res.clone())
        return res
      } catch (err) {
        return cached || Response.error()
      }
    })())
    return
  }

  // ── 文章内容JSON：stale-while-revalidate（秒开 + 后台更新）──
  if (isPageJSON) {
    event.respondWith((async function () {
      const cache = await caches.open(CACHE)
      const cached = await cache.match(req)
      const fetchAndUpdate = fetch(req).then(function (res) {
        if (res && res.status === 200) cache.put(req, res.clone())
        return res
      }).catch(function () { return cached })
      // 有缓存先秒开（同时后台更新），无缓存等网络
      return cached || fetchAndUpdate
    })())
    return
  }

  // ── 其他（HTML/JS/CSS）：network-first，失败回退缓存 ──
  event.respondWith((async function () {
    const cache = await caches.open(CACHE)
    try {
      const res = await fetch(req)
      if (res && res.status === 200 && (res.type === "basic" || res.type === "default")) {
        cache.put(req, res.clone())
      }
      return res
    } catch (err) {
      const cached = await cache.match(req)
      return cached || Response.error()
    }
  })())
})
