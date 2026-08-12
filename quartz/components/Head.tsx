import { i18n } from "../i18n"
import { FullSlug, getFileExtension, joinSegments, pathToRoot } from "../util/path"
import { CSSResourceToStyleElement, JSResourceToScriptElement } from "../util/resources"
import { googleFontHref, googleFontSubsetHref } from "../util/theme"
import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
import { unescapeHTML } from "../util/escape"

export default (() => {
  const Head: QuartzComponent = ({
    cfg,
    fileData,
    externalResources,
    ctx,
  }: QuartzComponentProps) => {
    const titleSuffix = cfg.pageTitleSuffix ?? ""
    const title =
      (fileData.frontmatter?.title ?? i18n(cfg.locale).propertyDefaults.title) + titleSuffix
    const description =
      fileData.frontmatter?.socialDescription ??
      fileData.frontmatter?.description ??
      unescapeHTML(fileData.description?.trim() ?? i18n(cfg.locale).propertyDefaults.description)

    const { css, js, additionalHead } = externalResources

    // 音频播放器增强：把文章里指向 .mp3/.wav/.ogg 等音频文件的链接
    // 自动替换为 <audio controls> 播放器（对原始笔记零侵入，纯前端处理）。
    const audioPlayerScript = `
(function () {
  var exts = [".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"];
  function enhanceAudio() {
    var links = document.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      var href = a.getAttribute("href") || "";
      var lower = href.toLowerCase();
      var isAudio = exts.some(function (e) { return lower.endsWith(e); });
      if (!isAudio) continue;
      if (a.dataset.audioEnhanced) continue;
      a.dataset.audioEnhanced = "true";
      var audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = href;
      var wrapper = document.createElement("div");
      wrapper.className = "audio-player";
      wrapper.appendChild(audio);
      if (a.parentNode) {
        a.parentNode.insertBefore(wrapper, a);
        a.remove();
      }
    }
  }
  function init() {
    enhanceAudio();
    if (window.MutationObserver) {
      try {
        var target = document.body || document.documentElement;
        var obs = new MutationObserver(function () { enhanceAudio(); });
        obs.observe(target, { childList: true, subtree: true });
      } catch (e) {}
    }
    document.addEventListener("nav", function () { enhanceAudio(); });
  }
  if (!document.getElementById("audio-player-style")) {
    var st = document.createElement("style");
    st.id = "audio-player-style";
    st.textContent = ".audio-player{margin:1rem 0;}.audio-player audio{width:100%;}.article-title{background:transparent!important;}" +
      ".audio-player-bar{position:sticky;top:0;z-index:60;display:flex;flex-direction:column;gap:.8rem;background:var(--light);border:2px solid var(--lightgray);border-radius:14px;padding:1rem 1.1rem;margin:.4rem 0 1rem;box-shadow:0 2px 14px rgba(0,0,0,.12);}" +
      ".audio-player-bar .ap-row{display:flex;align-items:center;justify-content:center;gap:.8rem;}" +
      ".audio-player-bar .ap-btn{height:5rem;border:none;background:var(--tertiary);color:var(--light);font-size:1.6rem;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center;flex:0 0 auto;}" +
      ".audio-player-bar .ap-btn:hover{opacity:.92;}" +
      ".audio-player-bar .ap-toggle{width:6rem;height:6rem;font-size:2.6rem;border-radius:50%;}" +
      ".audio-player-bar .ap-prev,.audio-player-bar .ap-next{width:5rem;height:5rem;border-radius:50%;}" +
      ".audio-player-bar .ap-back15,.audio-player-bar .ap-fwd15,.audio-player-bar .ap-speed{width:auto;min-width:5rem;border-radius:999px;padding:0 .9rem;font-size:1.15rem;font-weight:700;}" +
      ".audio-player-bar .ap-meta{flex:1;min-width:0;}" +
      ".audio-player-bar .ap-title{font-size:1.15rem;font-weight:700;color:var(--darkgray);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}" +
      ".audio-player-bar .ap-time{font-size:.95rem;color:var(--gray);margin-top:.15rem;}" +
      ".audio-player-bar .ap-status{font-size:.95rem;color:var(--tertiary);margin-top:.1rem;font-weight:700;}" +
      ".audio-player-bar .ap-progress{width:100%;height:1.4rem;accent-color:var(--tertiary);cursor:pointer;}";
    document.head.appendChild(st);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
`;

// 音频总览连播：扫描页面上的播放列表，点击单曲或「全部连播」顺序播放。
var audioPlaylistScript = `
(function () {
  function fmtTime(s) {
    if (!isFinite(s) || s < 0) s = 0;
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return (m < 10 ? "0" + m : m) + ":" + (sec < 10 ? "0" + sec : sec);
  }
  function setupPlaylist(root) {
    var section = root.querySelector("[data-audio-playlist]");
    if (!section || section.dataset.playlistBound) return;
    section.dataset.playlistBound = "true";
    var tracks = Array.prototype.slice.call(section.querySelectorAll(".audio-track"));
    if (tracks.length === 0) return;

    // 隐藏的播放引擎：仅承载媒体控制，界面由下方自建卡片呈现。
    // 原先这里没有 controls，移动端就只剩声音、没有任何界面。
    var player = document.createElement("audio");
    player.preload = "none";
    player.style.display = "none";
    document.body.appendChild(player);

    // 自建可见播放卡片：进度条 + 播放/暂停 + 曲目名 + 上一首/下一首。
    var bar = document.createElement("div");
    bar.className = "audio-player-bar";
    bar.innerHTML =
      '<div class="ap-row ap-row-main">' +
        '<button class="ap-btn ap-back15" aria-label="后退15秒">\\u221215\\u79d2</button>' +
        '<button class="ap-btn ap-toggle" aria-label="播放或暂停">\\u25B6</button>' +
        '<button class="ap-btn ap-fwd15" aria-label="前进15秒">+15\\u79d2</button>' +
      '</div>' +
      '<div class="ap-row ap-row-sub">' +
        '<button class="ap-btn ap-prev" aria-label="上一首">\\u23EE</button>' +
        '<button class="ap-btn ap-speed" aria-label="切换播放速度">1.0\\u00d7</button>' +
        '<button class="ap-btn ap-next" aria-label="下一首">\\u23ED</button>' +
      '</div>' +
      '<div class="ap-meta">' +
        '<div class="ap-title">未选择音频</div>' +
        '<div class="ap-time">00:00 / 00:00</div>' +
        '<div class="ap-status">就绪</div>' +
      '</div>' +
      '<input class="ap-progress" type="range" min="0" max="1000" value="0" step="1" aria-label="播放进度">';
    section.insertBefore(bar, section.firstChild);

    var btnPrev = bar.querySelector(".ap-prev");
    var btnToggle = bar.querySelector(".ap-toggle");
    var btnNext = bar.querySelector(".ap-next");
    var btnBack15 = bar.querySelector(".ap-back15");
    var btnFwd15 = bar.querySelector(".ap-fwd15");
    var btnSpeed = bar.querySelector(".ap-speed");
    var elTitle = bar.querySelector(".ap-title");
    var elTime = bar.querySelector(".ap-time");
    var elStatus = bar.querySelector(".ap-status");
    var elProg = bar.querySelector(".ap-progress");

    var current = -1;

    // 倍速：循环切换 0.75x ~ 2.0x（适老化——老人可放慢听清，或加速听完长开示）
    var SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0];
    var speedIdx = 1;
    function applySpeed() {
      player.playbackRate = SPEEDS[speedIdx];
      btnSpeed.textContent = SPEEDS[speedIdx].toFixed(1) + "\\u00d7";
    }
    // 进度条下方显示明确文字状态（不只靠颜色，照顾视力下降的老人）
    function setStatus(text) {
      if (elStatus) elStatus.textContent = text;
    }
    function seekBy(d) {
      if (!player.duration) return;
      var t = player.currentTime + d;
      if (t < 0) t = 0;
      if (t > player.duration) t = player.duration;
      player.currentTime = t;
    }

    function clearPlaying() {
      tracks.forEach(function (t) { t.classList.remove("playing"); });
    }
    function setToggleIcon() {
      btnToggle.textContent = player.paused ? "\\u25B6" : "\\u23F8";
      setStatus(player.paused ? "已暂停" : "正在播放");
    }
    function playIndex(i) {
      if (i < 0 || i >= tracks.length) return;
      current = i;
      clearPlaying();
      tracks[i].classList.add("playing");
      var titleEl = tracks[i].querySelector(".audio-title");
      elTitle.textContent = titleEl ? titleEl.textContent : ("第 " + (i + 1) + " 首");
      elProg.value = 0;
      elTime.textContent = "00:00 / 00:00";
      player.src = tracks[i].getAttribute("data-audio-src");
      // 关键：换源后必须 load()，否则部分浏览器（尤其移动端）在 ended 后
      // 直接 play() 会因媒体未就绪而静默失败，导致连播播完第一首就停住。
      try { player.load(); } catch (e) {}
      var p = player.play();
      if (p && p.catch) p.catch(function () {});
    }
    function togglePlay() {
      if (current === -1) { playIndex(0); return; }
      if (player.paused) {
        var p = player.play();
        if (p && p.catch) p.catch(function () {});
      } else {
        player.pause();
      }
    }
    function seek() {
      if (!player.duration) return;
      player.currentTime = (parseFloat(elProg.value) / 1000) * player.duration;
    }

    player.addEventListener("play", setToggleIcon);
    player.addEventListener("pause", setToggleIcon);
    player.addEventListener("ended", function () {
      if (current + 1 < tracks.length) {
        playIndex(current + 1);
      } else {
        clearPlaying();
        current = -1;
        btnToggle.textContent = "\\u25B6";
        setStatus("播放完毕");
        elTitle.textContent = "播放完毕";
        elProg.value = 0;
      }
    });
    player.addEventListener("timeupdate", function () {
      if (player.duration) {
        elProg.value = Math.round((player.currentTime / player.duration) * 1000);
        elTime.textContent = fmtTime(player.currentTime) + " / " + fmtTime(player.duration);
      }
    });
    player.addEventListener("loadedmetadata", function () {
      elTime.textContent = fmtTime(player.currentTime) + " / " + fmtTime(player.duration);
    });

    btnToggle.addEventListener("click", togglePlay);
    btnPrev.addEventListener("click", function () { if (current > 0) playIndex(current - 1); });
    btnNext.addEventListener("click", function () { if (current < tracks.length - 1) playIndex(current + 1); });
    btnBack15.addEventListener("click", function () { seekBy(-15); });
    btnFwd15.addEventListener("click", function () { seekBy(15); });
    btnSpeed.addEventListener("click", function () { speedIdx = (speedIdx + 1) % SPEEDS.length; applySpeed(); });
    // 初始化倍速标签（默认 1.0x）；换曲后 player.playbackRate 在同一元素上保持，无需重置
    applySpeed();
    elProg.addEventListener("input", seek);

    tracks.forEach(function (t, i) {
      t.addEventListener("click", function () { playIndex(i); });
    });
    var playAll = section.querySelector("[data-play-all]");
    if (playAll) {
      playAll.addEventListener("click", function () { playIndex(0); });
    }
    // Auto-play a track named by the URL hash (e.g. #计划赶不上无常),
    // so links from the content nav can deep-link straight into playback.
    function tryPlayHash() {
      var raw = window.location.hash || "";
      if (!raw) return;
      var name = decodeURIComponent(raw.slice(1));
      var idx = tracks.findIndex(function (t) {
        var btn = t.querySelector(".audio-title");
        return btn && btn.textContent === name;
      });
      if (idx >= 0) {
        playIndex(idx);
        // scroll the chosen track into view
        try { tracks[idx].scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {}
      }
    }
    tryPlayHash();
    window.addEventListener("hashchange", tryPlayHash);
  }
  function initPlaylist() {
    setupPlaylist(document);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPlaylist);
  } else {
    initPlaylist();
  }
  document.addEventListener("nav", function () { initPlaylist(); });
})();
`;

// 注册 Service Worker（缓存层）：自动适配 GitHub Pages 子路径与自定义域名。
var swRegisterScript = `
(function () {
  if (!("serviceWorker" in navigator)) return;
  if (window.location.protocol !== "https:" && window.location.hostname !== "localhost") return;
  function getScope() {
    var path = window.location.pathname;
    // GitHub Pages 项目站点：域名后第一段即仓库名，需作为 scope
    if (/github\\.io$/.test(window.location.hostname)) {
      var seg = path.split("/").filter(Boolean);
      if (seg.length > 0) return "/" + seg[0] + "/";
    }
    var base = document.querySelector("base");
    if (base && base.getAttribute("href")) return base.getAttribute("href");
    return "./";
  }
  var scope = getScope();
  window.addEventListener("load", function () {
    navigator.serviceWorker.register(scope + "sw.js", { scope: scope }).catch(function () {});
  });
})();
`;

// 字号调节：悬浮按钮 A- / A+，5 档循环，写入 localStorage，作用于全站根字号。
var fontSizeScript = `
(function () {
  function initFs() {
    if (document.getElementById("fontsize-style")) return;
    var st = document.createElement("style");
  st.id = "fontsize-style";
  st.textContent = "#font-size-bar{position:fixed;top:4.2rem;right:1rem;z-index:9999;display:flex;align-items:center;gap:.5rem;background:var(--light,#fff);border:2px solid var(--lightgray,#ccc);border-radius:999px;padding:.5rem .8rem;box-shadow:0 2px 14px rgba(0,0,0,.18);}#font-size-bar button{width:3.4rem;height:3.4rem;border:none;border-radius:999px;background:var(--tertiary,#3b6ea5);color:var(--light,#fff);font-size:1.5rem;font-weight:700;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center;flex:0 0 auto;}#font-size-bar button:hover{opacity:.9;}#font-size-bar .fs-label{display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--darkgray,#333);line-height:1.15;}#font-size-bar .fs-label .fs-cap{font-size:.8rem;font-weight:700;}#font-size-bar .fs-label .fs-val{font-size:1.05rem;font-weight:700;color:var(--tertiary,#3b6ea5);}";
  document.head.appendChild(st);

  var SCALES = [0.9, 1, 1.1, 1.25, 1.4];
  var KEY = "lct-fontscale";
  function apply(i) {
    var v = SCALES[i];
    document.documentElement.style.fontSize = (16 * v) + "px";
    var valEl = document.getElementById("fs-val");
    if (valEl) valEl.textContent = Math.round(v * 100) + "%";
    try { localStorage.setItem(KEY, String(i)); } catch (e) {}
  }
  function current() {
    try { var s = localStorage.getItem(KEY); if (s !== null) return parseInt(s, 10); } catch (e) {}
    return 1;
  }
  var bar = document.createElement("div");
  bar.id = "font-size-bar";
  bar.setAttribute("aria-label", "调节字号");
  var dec = document.createElement("button");
  dec.textContent = "A−";
  dec.title = "缩小字号";
  var label = document.createElement("span");
  label.className = "fs-label";
  var cap = document.createElement("span");
  cap.className = "fs-cap";
  cap.textContent = "字号";
  var val = document.createElement("span");
  val.id = "fs-val";
  val.className = "fs-val";
  label.appendChild(cap);
  label.appendChild(val);
  var inc = document.createElement("button");
  inc.textContent = "A+";
  inc.title = "放大字号";
  dec.addEventListener("click", function () {
    var i = current(); if (i > 0) apply(i - 1);
  });
  inc.addEventListener("click", function () {
    var i = current(); if (i < SCALES.length - 1) apply(i + 1);
  });
  bar.appendChild(dec); bar.appendChild(label); bar.appendChild(inc);
  document.body.appendChild(bar);
  apply(current());
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFs);
  } else {
    initFs();
  }
})();
`;

    const url = new URL(`https://${cfg.baseUrl ?? "example.com"}`)
    const path = url.pathname as FullSlug
    const baseDir = fileData.slug === "404" ? path : pathToRoot(fileData.slug!)
    const iconPath = joinSegments(baseDir, "static/icon.png")

    // Url of current page
    const socialUrl =
      fileData.slug === "404" ? url.toString() : joinSegments(url.toString(), fileData.slug!)

    const usesCustomOgImage = ctx.cfg.plugins.emitters.some((e) => e.name === "CustomOgImages")
    const ogImageDefaultPath = `https://${cfg.baseUrl}/static/og-image.png`

    const coreStylesheet = css[0]?.content
    const coreScript = js.find(
      (r) => r.loadTime === "beforeDOMReady" && r.contentType === "external",
    )

    return (
      <head>
        <title>{title}</title>
        <meta charSet="utf-8" />
        {coreStylesheet && <link rel="preload" href={coreStylesheet} as="style" />}
        {coreScript && coreScript.contentType === "external" && (
          <link rel="preload" href={coreScript.src} as="script" />
        )}
        {cfg.theme.cdnCaching && cfg.theme.fontOrigin === "googleFonts" && (
          <>
            <link rel="preconnect" href="https://fonts.googleapis.com" />
            <link rel="preconnect" href="https://fonts.gstatic.com" />
            <link rel="stylesheet" href={googleFontHref(cfg.theme)} />
            {cfg.theme.typography.title && (
              <link rel="stylesheet" href={googleFontSubsetHref(cfg.theme, cfg.pageTitle)} />
            )}
          </>
        )}
        <link rel="preconnect" href="https://cdnjs.cloudflare.com" crossOrigin="anonymous" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />

        <meta name="og:site_name" content={cfg.pageTitle}></meta>
        <meta property="og:title" content={title} />
        <meta property="og:type" content="website" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={title} />
        <meta name="twitter:description" content={description} />
        <meta property="og:description" content={description} />
        <meta property="og:image:alt" content={description} />

        {!usesCustomOgImage && (
          <>
            <meta property="og:image" content={ogImageDefaultPath} />
            <meta property="og:image:url" content={ogImageDefaultPath} />
            <meta name="twitter:image" content={ogImageDefaultPath} />
            <meta
              property="og:image:type"
              content={`image/${getFileExtension(ogImageDefaultPath) ?? "png"}`}
            />
          </>
        )}

        {cfg.baseUrl && (
          <>
            <meta property="twitter:domain" content={cfg.baseUrl}></meta>
            <meta property="og:url" content={socialUrl}></meta>
            <meta property="twitter:url" content={socialUrl}></meta>
          </>
        )}

        <link rel="icon" href={iconPath} />
        <meta name="description" content={description} />
        <meta name="generator" content="Quartz" />

        {css.map((resource) => CSSResourceToStyleElement(resource, true))}
        {js
          .filter((resource) => resource.loadTime === "beforeDOMReady")
          .map((res) => JSResourceToScriptElement(res, true))}
        {additionalHead.map((resource) => {
          if (typeof resource === "function") {
            return resource(fileData)
          } else {
            return resource
          }
        })}
        <script dangerouslySetInnerHTML={{ __html: audioPlayerScript }} />
        <script dangerouslySetInnerHTML={{ __html: audioPlaylistScript }} />
        <script dangerouslySetInnerHTML={{ __html: fontSizeScript }} />
        <script dangerouslySetInnerHTML={{ __html: swRegisterScript }} />
      </head>
    )
  }

  return Head
}) satisfies QuartzComponentConstructor
