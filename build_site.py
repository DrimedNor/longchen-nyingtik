# -*- coding: utf-8 -*-
"""
build_site.py — 把 content/ 下的 Obsidian 库生成静态站 (dist/)
零第三方依赖，仅 Python 标准库。

用法:
  python build_site.py
生成:
  dist/index.html         单文件站点（内联 CSS/JS）
  dist/audio/*.mp3        本地音频（正文 [[xxx.mp3]] 引用的上师开示文字转语音音频）

音频策略(2026-08-13 定):
  1. 正文 [[xxx.mp3]] 引用且本地 content 下存在同名文件 → 内嵌 <audio> 本地播放；
  2. 本地不存在的（如《大圆满前行》226集，已迁走）→ 音频资源页放常乐寺详情页跳转链接。
"""
import os
import re
import json
import html as html_mod
import shutil
import sys
from urllib.parse import quote

CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content")
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")

# 常乐寺《大圆满前行》有声书专辑详情页（稳定地址，用于跳转）
CHANGLESI_ALBUM = "http://www.changleisi.com/index/Audio/details/id/71"

# 收集本地存在的音频文件名（含 .mp3 后缀），供 inline 判断
LOCAL_AUDIO = {}


# ---------------------------------------------------------------- frontmatter
def parse_frontmatter(text):
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            block = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                m = re.match(r"^([\w-]+):\s*(.*)$", line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    if key == "tags":
                        val = [t.strip() for t in re.sub(r"[\[\]]", "", val).split(",") if t.strip()]
                    meta[key] = val
    return meta, body


# ---------------------------------------------------------------- inline markdown
def inline(text):
    # 加粗
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # 行内代码
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # wikilink: [[target]] 或 [[target|alias]] 或 [[xxx.mp3]]
    def _wl(m):
        inner = m.group(1)
        if "|" in inner:
            target, alias = inner.split("|", 1)
        else:
            target, alias = inner, None
        label = alias if alias else target
        if target.lower().endswith((".mp3", ".m4a", ".wav")):
            # 本地存在 → 内嵌播放器；否则跳转常乐寺
            fname = target.split("/")[-1].strip()
            if fname in LOCAL_AUDIO:
                src = "audio/" + quote(fname)
                return ('<audio class="inline-audio" controls preload="none" src="%s">'
                        '您的浏览器不支持音频播放</audio>' % src)
            return ('<a class="audio-jump" href="%s" target="_blank" rel="noopener">'
                    '🎧 收听音频（跳转常乐寺）</a>' % CHANGLESI_ALBUM)
        # 内部链接 -> data-page 锚点
        slug = target.strip()
        return ('<a class="wikilink" data-page="%s">%s</a>'
                % (html_mod.escape(slug, quote=True), html_mod.escape(label)))
    text = re.sub(r"\[\[([^\]]+)\]\]", _wl, text)
    # 普通 markdown 链接
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


# ---------------------------------------------------------------- block markdown
def md_to_html(body):
    lines = body.split("\n")
    out = []
    i = 0
    n = len(lines)
    list_buf = []          # 累积列表项
    quote_buf = []         # 累积引用行
    in_callout = None

    def flush_list():
        nonlocal list_buf
        if list_buf:
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in list_buf) + "</ul>")
            list_buf = []

    def flush_quote():
        nonlocal quote_buf, in_callout
        if quote_buf:
            txt = "<br>".join(inline(x) for x in quote_buf)
            if in_callout:
                out.append('<div class="callout">%s</div>' % txt)
            else:
                out.append("<blockquote>%s</blockquote>" % txt)
            quote_buf = []
            in_callout = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # callout 起始: > [!...] 或 > [!...] 后续正文
        if stripped.startswith("> [!"):
            flush_list(); flush_quote()
            in_callout = "callout"
            m_inner = re.match(r"^>\s*\[!(.*?)\]\s*(.*)$", stripped)
            if m_inner:
                label = m_inner.group(1).strip()
                rest = m_inner.group(2).strip()
                quote_buf.append('<span class="callout-title">%s</span>' % inline(label))
                if rest:
                    quote_buf.append(rest)
            else:
                quote_buf.append(stripped)
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            flush_list()
            quote_buf.append(stripped[1:].strip())
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}$", stripped):
            flush_list(); flush_quote()
            out.append("<hr>")
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_list(); flush_quote()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            i += 1
            continue

        # 列表
        if re.match(r"^[-*]\s+", stripped):
            flush_quote()
            list_buf.append(stripped[2:])
            i += 1
            continue

        # 空行
        if not stripped:
            flush_list(); flush_quote()
            i += 1
            continue

        # 普通段落
        flush_list(); flush_quote()
        out.append("<p>%s</p>" % inline(stripped))
        i += 1

    flush_list(); flush_quote()
    return "\n".join(out)


# ---------------------------------------------------------------- 文件发现
def discover_pages():
    global LOCAL_AUDIO
    LOCAL_AUDIO = {}
    # 第一遍：先扫描收集所有本地音频（必须在解析 md 之前完成）
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.lower().endswith((".mp3", ".m4a", ".wav")):
                LOCAL_AUDIO[f] = os.path.join(dirpath, f)
    # 第二遍：解析 md
    pages = []
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, CONTENT_DIR).replace("\\", "/")
            txt = open(full, encoding="utf-8").read()
            meta, body = parse_frontmatter(txt)
            fallback = re.sub(r"🔊\s*", "", f[:-3]).strip()
            title = meta.get("title") or fallback or rel
            title = title.strip('"').strip()
            slug = rel[:-3]
            slug = re.sub(r"🔊\s*", "", slug)
            slug = "/".join(seg.strip() for seg in slug.split("/"))
            is_index = f == "index.md"
            pages.append({
                "slug": slug,
                "title": title,
                "rel": rel,
                "dir": os.path.dirname(rel).replace("\\", "/"),
                "is_index": is_index,
                "meta": meta,
                "html": md_to_html(body),
            })
    return pages


# ---------------------------------------------------------------- 目录树
def build_tree(pages):
    nodes = {"children": [], "dirs": {}}

    def ensure_dir(path_parts, nodes_ref):
        cur = nodes_ref
        for p in path_parts:
            if p not in cur["dirs"]:
                cur["dirs"][p] = {"name": p, "children": [], "dirs": {}}
            cur = cur["dirs"][p]
        return cur

    for pg in pages:
        if pg["dir"] == "." or pg["dir"] == "":
            if pg["is_index"]:
                nodes["children"].append({"type": "page", "slug": pg["slug"], "title": pg["title"], "is_index": True})
            else:
                nodes["children"].append({"type": "page", "slug": pg["slug"], "title": pg["title"]})
            continue
        parts = [p for p in pg["dir"].split("/") if p]
        d = ensure_dir(parts, nodes)
        if pg["is_index"]:
            d["children"].insert(0, {"type": "page", "slug": pg["slug"], "title": pg["title"], "is_index": True})
        else:
            d["children"].append({"type": "page", "slug": pg["slug"], "title": pg["title"]})

    def sort_children(nd):
        pages_in = [c for c in nd["children"] if c["type"] == "page"]
        pages_in.sort(key=lambda c: (0 if c.get("is_index") else 1, c["title"]))
        nd["children"] = pages_in
        for name, sub in nd["dirs"].items():
            sort_children(sub)

    sort_children(nodes)
    return nodes


# ---------------------------------------------------------------- HTML 模板（简约风）
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>@@SITE_TITLE@@</title>
<style>
:root{
  --bg:#fcfbf9; --ink:#2b2722; --ink-soft:#8b857b; --ink-faint:#b5afa4;
  --line:#ece8e0; --accent:#a07a3c; --accent-soft:#c2a467; --fs:1rem;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"PingFang SC","Microsoft YaHei",-apple-system,"Segoe UI",sans-serif;
  background:var(--bg); color:var(--ink); font-size:var(--fs); line-height:1.9;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
a{color:var(--accent); text-decoration:none}
a:hover{color:var(--accent-soft)}

/* 顶栏 */
.topbar{
  position:sticky; top:0; z-index:20; display:flex; align-items:center; gap:.8rem;
  padding:.7rem 1.2rem; background:rgba(252,251,249,.9); backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);
}
.brand{font-size:1rem; font-weight:600; color:var(--ink); letter-spacing:.06em}
.brand small{color:var(--ink-faint); font-weight:400; margin-left:.5em; letter-spacing:0}
.topbar .spacer{flex:1}
.menu-btn{display:none; border:none; background:none; color:var(--ink);
  font-size:1.2rem; cursor:pointer; padding:.2rem .4rem}

/* 字号调节 */
.fs-pill{display:flex; align-items:center; gap:.1rem; border:1px solid var(--line);
  border-radius:999px; padding:.1rem .2rem; background:#fff}
.fs-pill button{border:none; background:none; cursor:pointer; color:var(--ink-soft);
  font-size:.95rem; width:1.9rem; height:1.9rem; border-radius:999px; line-height:1}
.fs-pill button:hover{background:var(--bg); color:var(--ink)}
.fs-pill .fs-cap{font-size:.7rem; color:var(--ink-faint); padding:0 .15rem}

/* 布局 */
.layout{display:flex; min-height:calc(100vh - 53px)}
.sidebar{
  width:264px; flex:0 0 264px; border-right:1px solid var(--line); padding:1.3rem .9rem;
  overflow-y:auto; position:sticky; top:53px; height:calc(100vh - 53px); background:var(--bg);
}
.sidebar .search{width:100%; padding:.5rem .7rem; border:1px solid var(--line);
  border-radius:8px; font-size:.9rem; background:#fff; color:var(--ink); margin-bottom:1rem;
  outline:none}
.sidebar .search:focus{border-color:var(--accent-soft)}
.nav a{display:block; padding:.32rem .55rem; border-radius:6px; color:var(--ink-soft);
  font-size:.9rem; cursor:pointer}
.nav a:hover{background:#f3f0ea; color:var(--ink)}
.nav a.active{background:var(--ink); color:#fff; text-decoration:none}
.nav .group-label{font-size:.75rem; color:var(--ink-faint); letter-spacing:.1em;
  padding:.7rem .55rem .2rem; font-weight:600}
.nav .dir-name{font-size:.78rem; color:var(--accent); padding:.55rem .55rem .1rem; font-weight:600}

/* 内容区 */
.content{flex:1; padding:2.6rem clamp(1.4rem, 6vw, 4.5rem) 5rem; max-width:820px; margin:0 auto}
.article h1{font-size:1.85em; margin:.1rem 0 .7rem; line-height:1.35; font-weight:700}
.article h2{font-size:1.3em; margin:1.7em 0 .6em; padding-bottom:.35em; border-bottom:1px solid var(--line); font-weight:600}
.article h3{font-size:1.1em; margin:1.5em 0 .4em; font-weight:600}
.article h4,h5,h6{font-size:1em; margin:1.2em 0 .3em; font-weight:600}
.article p{margin:.85em 0}
.article blockquote{border-left:2px solid var(--accent-soft); margin:1.1em 0; padding:.1em 0 .1em 1.1em;
  color:var(--ink-soft); font-size:.96em}
.article .callout{border:1px solid var(--line); background:#f7f4ee;
  border-radius:8px; padding:1em 1.2em; margin:1.1em 0}
.article .callout-title{display:block; font-weight:600; color:var(--accent);
  margin-bottom:.35em; font-size:.95em}
.article ul{margin:.6em 0 .6em 1.5em; padding:0}
.article li{margin:.35em 0}
.article hr{border:none; border-top:1px solid var(--line); margin:2.4em auto; width:50%}
.article code{background:#f3f0ea; padding:.1em .4em; border-radius:4px; font-size:.88em; font-family:ui-monospace,Consolas,monospace}
.article strong{color:var(--ink); font-weight:600}

/* 音频 */
.article .inline-audio{display:block; width:100%; max-width:520px; margin:1rem 0}
.article .audio-jump{display:inline-block; border:1px solid var(--accent); color:var(--accent);
  padding:.3rem 1.1rem; border-radius:999px; font-size:.92em; margin:.4rem 0}
.article .audio-jump:hover{background:var(--accent); color:#fff}
.album-card{border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.3rem;
  margin:1.2rem 0; background:#f7f4ee}
.album-card .t{font-weight:600; margin-bottom:.3rem}
.album-card .d{color:var(--ink-soft); font-size:.92em}
.album-card a{display:inline-block; margin-top:.6rem; border:1px solid var(--accent);
  color:var(--accent); padding:.3rem 1.1rem; border-radius:999px; font-size:.92em}
.album-card a:hover{background:var(--accent); color:#fff}

/* 元信息 */
.meta{font-size:.85em; color:var(--ink-faint); margin:1.2rem 0 1.6rem; display:flex; flex-wrap:wrap; gap:.3rem .9rem}
.meta .tag{background:#f3f0ea; padding:.05em .7em; border-radius:999px; font-size:.88em; color:var(--ink-soft)}
.meta .src a{color:var(--accent-soft)}

/* 欢迎页 */
.welcome{text-align:left; padding:.5rem 0 1rem}
.welcome .big{font-size:2.2em; color:var(--ink); font-weight:700; margin-bottom:.5rem; letter-spacing:.02em}

/* 移动端 */
@media(max-width:760px){
  .menu-btn{display:inline-block}
  .sidebar{position:fixed; left:0; top:53px; bottom:0; transform:translateX(-100%);
    transition:transform .2s; z-index:15; width:260px; background:var(--bg)}
  .sidebar.open{transform:translateX(0)}
  .content{padding:1.6rem 1.1rem 3.5rem}
}
</style>
</head>
<body>
<div class="topbar">
  <button class="menu-btn" id="menuBtn">☰</button>
  <span class="brand">@@SITE_TITLE@@<small id="pageCrumbs"></small></span>
  <span class="spacer"></span>
  <div class="fs-pill">
    <button id="fsDec" title="缩小字号">A−</button>
    <span class="fs-cap">字号</span>
    <button id="fsInc" title="放大字号">A+</button>
  </div>
</div>

<div class="layout">
  <aside class="sidebar" id="sidebar">
    <input class="search" id="search" type="text" placeholder="搜索…">
    <nav class="nav" id="nav"></nav>
  </aside>
  <main class="content" id="content"></main>
</div>

<script>
var SITE_TITLE = @@SITE_TITLE_JSON@@;
var PAGES = @@PAGES_JSON@@;
var TREE = @@TREE_JSON@@;

var bySlug = {};
PAGES.forEach(function(p){ bySlug[p.slug] = p; });

// ---- 字号调节（localStorage 记忆）----
var FS_KEY = 'longchen-fontscale';
var FS_MIN = 90, FS_MAX = 150, FS_STEP = 10;
var fsVal = parseInt(localStorage.getItem(FS_KEY) || '100', 10);
function applyFs(){
  document.documentElement.style.setProperty('--fs', fsVal + '%');
  localStorage.setItem(FS_KEY, String(fsVal));
}
applyFs();
document.getElementById('fsInc').onclick = function(){ fsVal = Math.min(FS_MAX, fsVal + FS_STEP); applyFs(); };
document.getElementById('fsDec').onclick = function(){ fsVal = Math.max(FS_MIN, fsVal - FS_STEP); applyFs(); };

// ---- 渲染目录树 ----
function renderNav(){
  var nav = document.getElementById('nav');
  function walk(node, htmlArr){
    (node.dirs ? Object.keys(node.dirs) : []).forEach(function(name){
      var sub = node.dirs[name];
      htmlArr.push('<div class="dir-name">' + esc(name) + '</div>');
      walk(sub, htmlArr);
    });
    (node.children || []).forEach(function(c){
      if (c.type === 'page'){
        htmlArr.push('<a class="nav-link" data-slug="' + esc(c.slug) + '">' + esc(c.title) + '</a>');
      }
    });
    return htmlArr;
  }
  var arr = walk(TREE, []);
  nav.innerHTML = arr.join('');
  nav.querySelectorAll('.nav-link').forEach(function(a){
    a.onclick = function(){ show(a.dataset.slug); closeSidebar(); };
  });
}

// ---- 显示页面 ----
function show(slug){
  var p = bySlug[slug];
  if (!p) return;
  var meta = '';
  if (p.meta.author) meta += '<span>作者：' + esc(p.meta.author) + '</span>';
  if (p.meta.source_url) meta += '<span class="src"><a href="' + esc(p.meta.source_url) + '" target="_blank" rel="noopener">查看原文 ↗</a></span>';
  if (p.meta.tags && p.meta.tags.length) meta += p.meta.tags.map(function(t){return '<span class="tag">' + esc(t) + '</span>';}).join('');
  var titleHtml = p.is_index ? '' : '<h1>' + esc(p.title) + '</h1>';
  var metaHtml = meta ? '<div class="meta">' + meta + '</div>' : '';
  var inner = titleHtml + metaHtml + p.html;
  if (p.is_index){
    inner = '<div class="welcome"><div class="big">' + esc(SITE_TITLE) + '</div></div>' + p.html;
  }
  document.getElementById('content').innerHTML = '<div class="article">' + inner + '</div>';
  document.getElementById('pageCrumbs').textContent = p.is_index ? '' : (' / ' + p.title);
  document.querySelectorAll('.nav-link').forEach(function(a){
    a.classList.toggle('active', a.dataset.slug === slug);
  });
  document.querySelectorAll('.wikilink').forEach(function(a){
    a.onclick = function(ev){
      ev.preventDefault();
      var target = a.dataset.page;
      var hit = bySlug[target] || matchByTitle(target);
      if (hit) show(hit.slug); else alert('未找到页面：' + target);
    };
  });
  window.scrollTo({top:0, behavior:'smooth'});
}

function matchByTitle(t){
  t = t.replace(/🔊\s*/g, '').trim();
  for (var k in bySlug){
    if (k.replace(/🔊\s*/g,'').trim() === t) return bySlug[k];
    if (bySlug[k].title.replace(/🔊\s*/g,'').trim() === t) return bySlug[k];
  }
  return null;
}

function esc(s){ var d=document.createElement('div'); d.textContent = s==null?'':String(s); return d.innerHTML; }

// ---- 搜索 ----
document.getElementById('search').addEventListener('input', function(){
  var q = this.value.trim().toLowerCase();
  if (!q){ renderNav(); return; }
  var nav = document.getElementById('nav');
  var arr = [];
  PAGES.forEach(function(p){
    if (p.title.toLowerCase().indexOf(q) >= 0 || p.html.toLowerCase().indexOf(q) >= 0){
      arr.push('<a class="nav-link" data-slug="' + esc(p.slug) + '">' + esc(p.title) + '</a>');
    }
  });
  if (!arr.length) arr.push('<div class="group-label">无匹配结果</div>');
  nav.innerHTML = arr.join('');
  nav.querySelectorAll('.nav-link').forEach(function(a){
    a.onclick = function(){ show(a.dataset.slug); closeSidebar(); };
  });
});

// ---- 侧栏开合 ----
function closeSidebar(){ document.getElementById('sidebar').classList.remove('open'); }
document.getElementById('menuBtn').onclick = function(){
  document.getElementById('sidebar').classList.toggle('open');
};

// ---- 初始化 ----
renderNav();
var home = TREE.children && TREE.children.find(function(c){ return c.is_index; });
show(home ? home.slug : PAGES[0].slug);
</script>
</body>
</html>
"""


def main():
    pages = discover_pages()
    if not pages:
        print("content 目录下没有找到 md 文件"); sys.exit(1)

    # 在「音频资源」index 页追加常乐寺跳转卡片
    for p in pages:
        if p["is_index"] and p["slug"].startswith("音频资源"):
            card = ('<div class="album-card">'
                    '<div class="t">《大圆满前行》有声书（226 集）</div>'
                    '<div class="d">嘎玛仁波切译 · 常乐寺收录。因音频体积较大，点击下方按钮前往常乐寺官网在线收听。</div>'
                    '<a href="%s" target="_blank" rel="noopener">前往常乐寺收听 ↗</a>'
                    '</div>' % CHANGLESI_ALBUM)
            p["html"] += card
            break

    tree = build_tree(pages)
    site_title = "龙的传人"
    for p in pages:
        if p["slug"] == "index" and p["meta"].get("title"):
            site_title = p["meta"]["title"]

    html_out = PAGE_TEMPLATE
    html_out = html_out.replace("@@SITE_TITLE_JSON@@", json.dumps(site_title, ensure_ascii=False))
    html_out = html_out.replace("@@PAGES_JSON@@", json.dumps(pages, ensure_ascii=False))
    html_out = html_out.replace("@@TREE_JSON@@", json.dumps(tree, ensure_ascii=False))
    html_out = html_out.replace("@@SITE_TITLE@@", site_title)

    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    # 复制本地音频到 dist/audio/（覆盖式复制；旧残留由构建前 shell rm 清理）
    audio_dir = os.path.join(DIST_DIR, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    copied = 0
    for fname, src in LOCAL_AUDIO.items():
        shutil.copy2(src, os.path.join(audio_dir, fname))
        copied += 1

    print("已生成: %s" % out_path)
    print("文章数: %d" % len(pages))
    print("本地音频复制: %d 个" % copied)
    print("HTML 大小: %.1f KB" % (os.path.getsize(out_path) / 1024.0))


if __name__ == "__main__":
    main()
