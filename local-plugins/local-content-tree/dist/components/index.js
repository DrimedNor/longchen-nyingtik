// ContentTree v2 — 扁平全展开导航
// 按一级主题（路径首段）分组，直接列出全部文章（含子目录），全展开，自动随内容更新。
import { jsx, jsxs, Fragment } from "preact/jsx-runtime"
import { resolveRelative } from "@quartz-community/utils/path"

function buildGroups(allFiles) {
  const groups = new Map()
  for (const file of allFiles) {
    const slug = file?.slug
    if (!slug) continue
    const s = String(slug)
    if (s.startsWith("tags/")) continue
    if (s === "index" || s === "" || s === "404") continue
    if (s.startsWith("音频资源/")) continue // 音频集中在音频总览页，不混入文章导航
    const segs = s.split("/")
    const theme = decodeURIComponent(segs[0])
    if (theme === "404") continue
    // 跳过文件夹落地页（如 上师开示/index），主题标题已作为分组头展示
    if (segs[segs.length - 1] === "index") continue
    if (!groups.has(theme)) groups.set(theme, [])
    groups.get(theme).push({
      slug: s,
      title: file?.frontmatter?.title ?? segs[segs.length - 1],
    })
  }
  for (const list of groups.values()) {
    list.sort((a, b) => String(a.title).localeCompare(String(b.title), "zh"))
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0], "zh"))
}

var Component = (props) => {
  const { fileData, allFiles } = props
  const fm = fileData.frontmatter
  if (!fm || !fm.homepage) return null
  const groups = buildGroups(allFiles)
  return jsxs("nav", {
    class: "content-tree",
    children: [
      jsx("h2", { children: "📖 内容导航" }),
      jsx("p", {
        class: "content-tree-hint",
        children: "按主题归类，全部文章一键展开，随笔记更新自动同步。",
      }),
      groups.map(([theme, articles]) =>
        jsxs(
          "section",
          {
            class: "tree-group",
            children: [
              jsx("h3", { class: "tree-theme", children: theme }),
              jsx(
                "ul",
                {
                  class: "tree-ul",
                  children: articles.map((a) =>
                    jsx("li", {
                      class: "tree-li",
                      children: jsx("a", {
                        href: resolveRelative(fileData.slug ?? "", a.slug),
                        class: "internal internal-link tree-link",
                        children: a.title,
                      }),
                    }),
                  ),
                },
              ),
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
.content-tree .tree-ul {
  list-style: none;
  padding-left: 1rem;
  margin: 0;
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
