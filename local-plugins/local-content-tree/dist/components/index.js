// ContentTree v3 — nested nav per Obsidian folder structure
// top theme -> sub-theme (folder) -> articles, fully expanded; audio dir as clickable group.
import { jsx, jsxs, Fragment } from "preact/jsx-runtime"
import { resolveRelative } from "@quartz-community/utils/path"

const AUDIO_DIR = "音频资源"

function titleOf(file, lastSeg) {
  return file?.frontmatter?.title ?? lastSeg
}

function buildNode() {
  return { subs: new Map(), articles: [] }
}

function insert(node, segs, slug, title) {
  if (segs.length === 0) {
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
    const segs = s.split("/")
    if (segs[segs.length - 1] === "index") continue
    const lastSeg = decodeURIComponent(segs[segs.length - 1])
    const title = titleOf(file, lastSeg)
    const decoded = segs.map((seg) => decodeURIComponent(seg))
    insert(root, decoded, s, title)
  }
  return root
}

// Convert a tree node into nested <div class="tree-sub">/ul for rendering.
function renderNode(node, fromSlug, depth) {
  const children = []
  // top-level articles of this node (direct files)
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

var Component = (props) => {
  const { fileData, allFiles } = props
  const fm = fileData.frontmatter
  if (!fm || !fm.homepage) return null
  const fromSlug = fileData.slug ?? ""
  const tree = buildTree(allFiles)
  const navRoot = tree

  // Audio dir: add its index landing page as a clickable group entry in the nav
  const audioIdx = allFiles.find((f) => String(f?.slug) === AUDIO_DIR + "/index")
  if (audioIdx && !navRoot.subs.has("音频资源")) {
    const an = buildNode()
    an.articles.push({ slug: AUDIO_DIR + "/index", title: audioIdx?.frontmatter?.title ?? "音频资源" })
    navRoot.subs.set("音频资源", an)
  }

  const themeOrder = [...navRoot.subs.keys()].sort((a, b) => a.localeCompare(b, "zh"))

  return jsxs("nav", {
    class: "content-tree",
    children: [
      jsx("h2", { children: "内容导航" }),
      jsx("p", {
        class: "content-tree-hint",
        children: "按主题与文件夹归类，全部文章一键展开，随笔记更新自动同步。",
      }),
      themeOrder.map((theme) =>
        jsxs(
          "section",
          {
            class: "tree-group",
            children: [
              jsx("h3", { class: "tree-theme", children: theme }),
              renderNode(navRoot.subs.get(theme), fromSlug, 0),
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
`

var ContentTree = () => Component
export { ContentTree }
