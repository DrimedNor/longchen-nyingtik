// ResourceIndex — 通用资源索引组件
// 为配置的「资源型栏目」（文件夹）在其页面列出该目录下的文件（电子书/文档等），
// 生成可点击打开/下载的清单。文件列表在构建时实时扫描，因此每次发布自动更新。
import { jsx, jsxs } from "preact/jsx-runtime"
import { readdirSync, existsSync, statSync } from "node:fs"
import { join } from "node:path"
import { pathToRoot } from "@quartz-community/utils/path"

// 默认只覆盖「书籍」栏目；如需为更多栏目建索引，在 quartz.config.yaml 的
// @quartz-community/resource-index.options.sections 中加一行配置即可（无需改代码）。
const DEFAULT_SECTIONS = [
  { slug: "书籍", label: "电子书", exts: [".pdf", ".epub", ".mobi", ".azw3"], target: "_blank" },
]

// 字节数 -> 易读字符串
function fmtSize(bytes) {
  if (bytes == null || isNaN(bytes)) return ""
  if (bytes < 1024) return bytes + " B"
  const kb = bytes / 1024
  if (kb < 1024) return kb.toFixed(1) + " KB"
  const mb = kb / 1024
  if (mb < 1024) return mb.toFixed(1) + " MB"
  return (mb / 1024).toFixed(2) + " GB"
}

function scanFiles(contentRoot, slug, exts) {
  const dir = join(contentRoot, slug)
  if (!existsSync(dir)) return []
  let entries = []
  try {
    entries = readdirSync(dir)
  } catch {
    return []
  }
  return entries
    .filter((f) => {
      const ext = f.slice(f.lastIndexOf(".")).toLowerCase()
      return exts.includes(ext)
    })
    .map((f) => {
      let size = 0
      try {
        size = statSync(join(dir, f)).size
      } catch {}
      const title = f.replace(/\.[^.]+$/, "")
      return { file: f, title, size }
    })
    .sort((a, b) => a.title.localeCompare(b.title, "zh"))
}

var ResourceIndex = (userOpts) => {
  const sections = (userOpts && userOpts.sections) || DEFAULT_SECTIONS
  return (props) => {
    const { fileData, ctx } = props
    const slug = String(fileData.slug ?? "")
    // 当前页属于哪个资源栏目（精确匹配或子路径）
    const section = sections.find((s) => slug === s.slug || slug.startsWith(s.slug + "/"))
    if (!section) return null

    const contentRoot = ctx?.argv?.directory ?? join(process.cwd(), "content")
    const files = scanFiles(contentRoot, section.slug, section.exts)
    if (files.length === 0) return null

    // pathToRoot 可能返回 ".." 之类不带尾斜杠的值，拼接时须补上，
    // 否则会生成 "..书籍/..." 这种错误路径段（浏览器当成字面文件名 -> 404）。
    const rootRaw = pathToRoot(fileData.slug ?? section.slug)
    const root = rootRaw.endsWith("/") ? rootRaw : rootRaw + "/"
    const target = section.target || "_blank"

    return jsxs("section", {
      class: "resource-index",
      "data-resource-index": section.slug,
      children: [
        jsx("h2", { children: section.label + "（共 " + files.length + " 本）" }),
        jsx("p", {
          class: "resource-index-hint",
          children: "点击书名即可在线阅读或下载，列表随文件自动更新。",
        }),
        jsx(
          "ul",
          {
            class: "resource-list",
            children: files.map((f, i) => {
              const encodedSrc =
                root + encodeURIComponent(section.slug) + "/" + encodeURIComponent(f.file)
              return jsx(
                "li",
                {
                  class: "resource-item",
                  children: jsxs("a", {
                    class: "resource-link",
                    href: encodedSrc,
                    target: target,
                    rel: "noopener",
                    children: [
                      jsx("span", { class: "resource-title", children: f.title }),
                      f.size ? jsx("span", { class: "resource-size", children: fmtSize(f.size) }) : null,
                    ],
                  }),
                },
                f.file,
              )
            }),
          },
        ),
      ],
    })
  }
}

ResourceIndex.css = `
.resource-index {
  margin-top: 1.5rem;
  border-top: 1px solid var(--lightgray);
  padding-top: 1rem;
}
.resource-index h2 {
  font-size: 1.3rem;
  margin: 0 0 0.4rem;
}
.resource-index-hint {
  color: var(--gray);
  font-size: 0.9rem;
  margin: 0 0 1rem;
}
.resource-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.resource-item {
  margin: 0.5rem 0;
}
.resource-link {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  text-decoration: none;
  color: var(--darkgray);
  border: 1px solid var(--lightgray);
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
}
.resource-link:hover {
  background: var(--lightgray);
  border-color: var(--tertiary);
}
.resource-title {
  flex: 1;
  font-size: 1rem;
}
.resource-size {
  color: var(--gray);
  font-size: 0.8rem;
  white-space: nowrap;
}
`

export { ResourceIndex }
