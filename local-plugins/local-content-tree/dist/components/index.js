// ContentTree v4 — nested nav per Obsidian folder structure
// theme -> sub-folder (as sub-theme) -> article link; audio dir lists audio files directly.
import { jsx, jsxs, Fragment } from "preact/jsx-runtime"
import { resolveRelative } from "@quartz-community/utils/path"
import { readdirSync, existsSync } from "node:fs"
import { join } from "node:path"

const AUDIO_DIR = "音频资源"
const AUDIO_EXTS = [".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"]

function titleOf(file, lastSeg) {
  return file?.frontmatter?.title ?? lastSeg
}

function buildNode() {
  return { subs: new Map(), articles: [] }
}

// Insert an article into the tree. The LAST path segment is the article file
// itself -> it becomes an article entry of its parent node, NOT a sub-folder.
function insert(node, segs, slug, title) {
  if (segs.length <= 1) {
    // article sits directly under this node
    node.articles.push({ slug, title })
    return
  }
  const seg = segs[0]
  if (!node.subs.has(seg)) node.subs.set(seg, buildNode())
  insert(node.subs.get(seg), segs.slice(1), slug, title)
}

function buildTree(allFiles) {
  const root = buildNode()
  for (const file of allFiles) {
    const slug = file?.slug
    if (!slug) continue
    const s = String(slug)
    if (s.startsWith("tags/")) continue
    if (s === "index" || s === "" || s === "404") continue
    if (s.startsWith("404/")) continue
    if (s.startsWith(AUDIO_DIR + "/")) continue // audio handled separately
    const segs = s.split("/")
    if (segs[segs.length - 1] === "index") continue
    const lastSeg = decodeURIComponent(segs[segs.length - 1])
    const title = titleOf(file, lastSeg)
    const decoded = segs.map((seg) => decodeURIComponent(seg))
    insert(root, decoded, s, title)
  }
  return root
}

// Scan audio files at build time so the nav can list them like articles.
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
      return { title: name, file: f }
    })
    .sort((a, b) => a.title.localeCompare(b.title, "zh"))
}

function renderArticles(articles, fromSlug) {
  return jsx("ul", {
    class: "tree-ul",
    children: articles.map((a) =>
      jsx("li", {
        class: "tree-li",
        children: jsx("a", {
          href: resolveRelative(fromSlug, a.slug),
          class: "internal internal-link tree-link",
          children: a.title,
        }),
      }),
    ),
  })
}

// Audio entries: link to the audio index page with a #hash of the track name,
// so the playlist script on that page can auto-play the chosen track.
function renderAudioEntries(entries, fromSlug) {
  const audioIndexSlug = AUDIO_DIR + "/index"
  const baseHref = resolveRelative(fromSlug, audioIndexSlug)
  return jsx("ul", {
    class: "tree-ul tree-audio-ul",
    children: entries.map((a) =>
      jsx("li", {
        class: "tree-li tree-audio-li",
        children: jsx("a", {
          href: baseHref + "#" + encodeURIComponent(a.title),
          class: "internal internal-link tree-link tree-audio-link",
          children: a.title,
        }),
      }),
    ),
  })
}

// Render a node: direct articles first, then sub-folders as nested sub-themes.
function renderNode(node, fromSlug, depth) {
  const children = []
  if (node.articles.length > 0) {
    children.push(renderArticles(node.articles, fromSlug))
  }
  const subKeys = [...node.subs.keys()].sort((a, b) => a.localeCompare(b, "zh"))
  for (const key of subKeys) {
    const child = node.subs.get(key)
    const block = jsxs(
      "div",
      {
        class: "tree-sub",
        children: [
          jsx("h4", { class: "tree-subtheme", children: key }),
          renderNode(child, fromSlug, depth + 1),
        ],
      },
      key,
    )
    children.push(block)
  }
  return jsxs("div", { class: "tree-nested", children }, "n" + depth)
}

var Component = (props) => {
  const { fileData, allFiles, ctx } = props
  const fm = fileData.frontmatter
  if (!fm || !fm.homepage) return null
  const fromSlug = fileData.slug ?? ""
  const tree = buildTree(allFiles)
  const navRoot = tree

  // Audio: list audio files directly under the 音频资源 group (clickable -> autoplay)
  const contentRoot = ctx?.argv?.directory ?? join(process.cwd(), "content")
  const audioEntries = scanAudioFiles(contentRoot)
  if (audioEntries.length > 0) {
    navRoot.subs.set(AUDIO_DIR, { subs: new Map(), articles: [], audioEntries })
  }

  const themeOrder = [...navRoot.subs.keys()].sort((a, b) => a.localeCompare(b, "zh"))

  return jsxs("nav", {
    class: "content-tree",
    children: [
      jsx("h2", { children: "内容导航" }),
      jsx("p", {
        class: "content-tree-hint",
        children: "按主题与文件夹归类，全部文章与音频一键展开，随笔记更新自动同步。",
      }),
      themeOrder.map((theme) =>
        jsxs(
          "section",
          {
            class: "tree-group",
            children: [
              jsx("h3", { class: "tree-theme", children: theme }),
              theme === AUDIO_DIR && audioEntries.length > 0
                ? renderAudioEntries(audioEntries, fromSlug)
                : renderNode(navRoot.subs.get(theme), fromSlug, 0),
            ],
          },
          theme,
        ),
      ),
    ],
  })
}

Component.css = `
.content-tree {
  margin-top: 1.5rem;
  border-top: 1px solid var(--lightgray);
  padding-top: 1rem;
}
.content-tree h2 {
  font-size: 1.3rem;
  margin: 0 0 0.4rem;
}
.content-tree-hint {
  color: var(--gray);
  font-size: 0.9rem;
  margin: 0 0 1rem;
}
.content-tree .tree-group {
  margin: 1rem 0;
}
.content-tree .tree-theme {
  font-size: 1.1rem;
  margin: 0 0 0.5rem;
  color: var(--darkgray);
  border-left: 3px solid var(--tertiary);
  padding-left: 0.5rem;
}
.content-tree .tree-sub {
  margin: 0.5rem 0 0.5rem 0.4rem;
}
.content-tree .tree-subtheme {
  font-size: 0.98rem;
  margin: 0.4rem 0 0.2rem;
  color: var(--secondary);
  font-weight: 600;
}
.content-tree .tree-ul {
  list-style: none;
  padding-left: 1rem;
  margin: 0;
}
.content-tree .tree-nested {
  margin-left: 0.3rem;
}
.content-tree .tree-nested .tree-subtheme {
  margin-left: 0.4rem;
}
.content-tree .tree-li {
  margin: 0.3rem 0;
}
.content-tree .tree-link {
  font-weight: 500;
}
.content-tree .tree-audio-link::before {
  content: "▶ ";
  color: var(--tertiary);
  font-size: 0.75rem;
}
`

var ContentTree = () => Component
export { ContentTree }
