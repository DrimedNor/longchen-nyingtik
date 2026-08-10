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
    st.textContent = ".audio-player{margin:1rem 0;}.audio-player audio{width:100%;}";
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
  function setupPlaylist(root) {
    var section = root.querySelector("[data-audio-playlist]");
    if (!section || section.dataset.playlistBound) return;
    section.dataset.playlistBound = "true";
    var tracks = Array.prototype.slice.call(section.querySelectorAll(".audio-track"));
    if (tracks.length === 0) return;
    var player = document.createElement("audio");
    player.preload = "none";
    document.body.appendChild(player);
    var current = -1;
    function clearPlaying() {
      tracks.forEach(function (t) { t.classList.remove("playing"); });
    }
    function playIndex(i) {
      if (i < 0 || i >= tracks.length) return;
      current = i;
      clearPlaying();
      tracks[i].classList.add("playing");
      player.src = tracks[i].getAttribute("data-audio-src");
      var p = player.play();
      if (p && p.catch) p.catch(function () {});
    }
    player.addEventListener("ended", function () {
      if (current + 1 < tracks.length) {
        playIndex(current + 1);
      } else {
        clearPlaying();
        current = -1;
      }
    });
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
  if (document.getElementById("fontsize-style")) return;
  var st = document.createElement("style");
  st.id = "fontsize-style";
  st.textContent = "#font-size-bar{position:fixed;right:1rem;bottom:1rem;z-index:9999;display:flex;gap:.3rem;background:var(--light);border:1px solid var(--lightgray);border-radius:999px;padding:.3rem .5rem;box-shadow:0 2px 10px rgba(0,0,0,.12);}#font-size-bar button{width:2.2rem;height:2.2rem;border:none;border-radius:50%;background:var(--tertiary);color:var(--light);font-size:1rem;cursor:pointer;line-height:1;}#font-size-bar button:hover{opacity:.9;}#font-size-bar .fs-label{min-width:3.2rem;display:flex;align-items:center;justify-content:center;font-size:.8rem;color:var(--darkgray);}";
  document.head.appendChild(st);

  var SCALES = [0.9, 1, 1.1, 1.25, 1.4];
  var KEY = "lct-fontscale";
  function apply(i) {
    var v = SCALES[i];
    document.documentElement.style.fontSize = (16 * v) + "px";
    var label = document.getElementById("fs-label");
    if (label) label.textContent = Math.round(v * 100) + "%";
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
  label.id = "fs-label";
  label.className = "fs-label";
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
