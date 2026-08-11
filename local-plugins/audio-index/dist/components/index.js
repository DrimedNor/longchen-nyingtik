// AudioIndex v2 — audio index + playlist
// Build-time scan of content/音樂资源/ for audio files; lists them with continuous play.
import { jsx, jsxs, Fragment } from "preact/jsx-runtime"
import { readdirSync, existsSync } from "node:fs"
import { join, dirname } from "node:path"
import { pathToRoot } from "@quartz-community/utils/path"

const AUDIO_EXTS = [".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"]
const AUDIO_DIR = "音频资源"

function scanAudioFiles(contentRoot) {
  const dir = join(contentRoot, AUDIO_DIR)
  if (!existsSync(dir)) return []
  let entries = []
  try {
    entries = readdirSync(dir)
  } catch {
    return []
  }
  return entries
    .filter((f) => AUDIO_EXTS.includes(f.slice(f.lastIndexOf(".")).toLowerCase()))
    .map((f) => {
      const name = f.replace(/\.[^.]+$/, "")
      const ext = f.slice(f.lastIndexOf(".")).toLowerCase()
      return { file: f, title: name, ext, slug: AUDIO_DIR + "/" + name }
    })
    .sort((a, b) => a.title.localeCompare(b.title, "zh"))
}

var Component = (props) => {
  const { fileData, ctx } = props
  const fm = fileData.frontmatter
  // Only render on the audio index page (slug starts with the audio dir)
  const slug = String(fileData.slug ?? "")
  if (!slug.startsWith(AUDIO_DIR + "/")) return null

  const contentRoot = ctx?.argv?.directory ?? join(process.cwd(), "content")
  const audios = scanAudioFiles(contentRoot)
  const rootRaw = pathToRoot(fileData.slug ?? AUDIO_DIR)
  // pathToRoot 可能返回 ".." 之类不带尾斜杠的值，
  // 直接拼接 AUDIO_DIR 会得到 "..音频资源/..." 这种错误路径段（浏览器当成字面文件名 -> 404）。
  // 这里统一补上尾斜杠，确保生成 "../音频资源/..." 这样的合法相对路径。
  const root = rootRaw.endsWith("/") ? rootRaw : rootRaw + "/"

  if (audios.length === 0) {
    return jsx("div", {
      class: "audio-index",
      children: jsx("p", { children: "暂未收录音频文件。" }),
    })
  }

  return jsxs("section", {
    class: "audio-index",
    "data-audio-playlist": "true",
    children: [
      jsx("h2", { children: "音频总览（连续播放）" }),
      jsx("p", {
        class: "audio-index-hint",
        children: "点击「全部联播」可顺序播放全部音频；点击单曲可单独播放。",
      }),
      jsx("div", {
        class: "audio-player-top",
        children: jsx("button", {
          class: "audio-play-all",
          "data-play-all": "true",
          children: "全部连播",
        }),
      }),
      jsx(
        "ul",
        {
          class: "audio-list",
          children: audios.map((a, i) => {
            const encodedSrc = root + AUDIO_DIR + "/" + encodeURIComponent(a.title) + a.ext
            return jsx(
              "li",
              {
                class: "audio-item",
                "data-index": String(i),
                children: jsxs("button", {
                  class: "audio-track",
                  "data-audio-src": encodedSrc,
                  children: [
                    jsx("span", { class: "audio-seq", children: (i + 1) + "." }),
                    jsx("span", { class: "audio-title", children: a.title }),
                    jsx("span", { class: "audio-status", children: "" }),
                  ],
                }),
              },
              a.slug,
            )
          }),
        },
      ),
    ],
  })
}

Component.css = `
.audio-index {
  margin-top: 1.5rem;
  border-top: 1px solid var(--lightgray);
  padding-top: 1rem;
}
.audio-index h2 {
  font-size: 1.3rem;
  margin: 0 0 0.4rem;
}
.audio-index-hint {
  color: var(--gray);
  font-size: 0.9rem;
  margin: 0 0 1rem;
}
.audio-player-top {
  margin-bottom: 1rem;
}
.audio-play-all {
  background: var(--tertiary);
  color: var(--light);
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.1rem;
  font-size: 1rem;
  cursor: pointer;
}
.audio-play-all:hover { opacity: 0.9; }
.audio-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.audio-item {
  margin: 0.4rem 0;
}
.audio-track {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid var(--lightgray);
  border-radius: 6px;
  padding: 0.5rem 0.8rem;
  cursor: pointer;
  color: var(--darkgray);
  font-size: 1rem;
}
.audio-track:hover { background: var(--lightgray); }
.audio-seq { color: var(--gray); min-width: 1.5rem; }
.audio-title { flex: 1; }
.audio-status { min-width: 4rem; text-align: right; color: var(--tertiary); font-size: 0.85rem; }
.audio-track.playing {
  border-color: var(--tertiary);
  background: var(--lightgray);
}
.audio-track.playing .audio-status::after { content: "播放中"; }
`

var AudioIndex = () => Component
export { AudioIndex }
