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
  2. 本地不存在的（如《大圆满前行》226集，已迁走）→ 音频资源页放昌列寺详情页跳转链接。
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

# 昌列寺《大圆满前行》有声书专辑详情页（稳定地址，用于跳转）
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
            # 本地存在 → 播放按钮（触发全局播放器）；否则跳转昌列寺
            fname = target.split("/")[-1].strip()
            if fname in LOCAL_AUDIO:
                return ('<button class="play-btn" data-audio="%s">▶ 播放本篇开示</button>'
                        % html_mod.escape(fname, quote=True))
            return ('<a class="audio-jump" href="%s" target="_blank" rel="noopener">'
                    '🎧 收听音频（跳转昌列寺）</a>' % CHANGLESI_ALBUM)
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
  /* —— 背景：浅红系 —— */
  --bg:#fbf1ef;            /* 页面主背景，极浅暖红 */
  --bg-2:#fcedea;          /* 区块/段落交替底色 */
  --surface:#fff8f6;       /* 卡片/播放条/弹层表面（近白暖红） */
  --surface-soft:#fae9e6;  /* 引用块/代码/标签/选中态的浅红底 */
  --surface-hover:#f6e0dc; /* 悬停态浅红底 */
  /* —— 文字层级 —— */
  --ink:#722f37;           /* 主文字 / 标题：酱红 maroon（深红） */
  --ink-soft:#8c4a52;      /* 次级文字：正文辅助、导航项（红褐） */
  --ink-faint:#b0817d;     /* 三级文字：提示、面包屑、元信息（浅酱红） */
  /* —— 线条 —— */
  --line:#f0d7d2;          /* 普通分割线 / 边框 */
  --line-strong:#e6c2bc;   /* 强调分割线 */
  /* —— 藏红主色系 —— */
  --accent:#a3332e;        /* 藏红主色：链接 / 按钮 / 关键强调 */
  --accent-soft:#c2554e;   /* 藏红浅色：悬停 / 次级强调（如目录名、进度） */
  --accent-deep:#7e221e;   /* 藏红深色：按下 / 当前激活态 */
  --fs:1rem;
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
  padding:.7rem 1.2rem; background:rgba(251,241,239,.9); backdrop-filter:blur(10px);
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
.nav a:hover{background:var(--surface-hover); color:var(--ink)}
.nav a.active{background:var(--accent); color:#fff; text-decoration:none}
.nav .group-label{font-size:.75rem; color:var(--ink-faint); letter-spacing:.1em;
  padding:.7rem .55rem .2rem; font-weight:600}
.nav .dir-name{font-size:.78rem; color:var(--accent); padding:.55rem .55rem .1rem; font-weight:600}

/* 内容区 */
.content{flex:1; padding:2.6rem clamp(1.4rem, 6vw, 4.5rem) 6.5rem; max-width:820px; margin:0 auto}
.article h1{font-size:1.85em; margin:.1rem 0 .7rem; line-height:1.35; font-weight:700}
.article h2{font-size:1.3em; margin:1.7em 0 .6em; padding-bottom:.35em; border-bottom:1px solid var(--line); font-weight:600}
.article h3{font-size:1.1em; margin:1.5em 0 .4em; font-weight:600}
.article h4,h5,h6{font-size:1em; margin:1.2em 0 .3em; font-weight:600}
.article p{margin:.85em 0}
.article blockquote{border-left:2px solid var(--accent-soft); margin:1.1em 0; padding:.1em 0 .1em 1.1em;
  color:var(--ink-soft); font-size:.96em}
.article .callout{border:1px solid var(--line); background:var(--surface-soft);
  border-radius:8px; padding:1em 1.2em; margin:1.1em 0}
.article .callout-title{display:block; font-weight:600; color:var(--accent);
  margin-bottom:.35em; font-size:.95em}
.article ul{margin:.6em 0 .6em 1.5em; padding:0}
.article li{margin:.35em 0}
.article hr{border:none; border-top:1px solid var(--line); margin:2.4em auto; width:50%}
.article code{background:var(--surface-soft); padding:.1em .4em; border-radius:4px; font-size:.88em; font-family:ui-monospace,Consolas,monospace}
.article strong{color:var(--ink); font-weight:600}

/* 音频 */
.article .play-btn{display:inline-flex; align-items:center; gap:.4rem; border:1px solid var(--accent);
  color:var(--accent); background:#fff; padding:.42rem 1.2rem; border-radius:999px;
  font-size:.95em; cursor:pointer; margin:.5rem 0; transition:all .15s; font-family:inherit}
.article .play-btn:hover{background:var(--accent); color:#fff}
.article .play-btn.playing{background:var(--accent); color:#fff}
.article .audio-jump{display:inline-block; border:1px solid var(--accent); color:var(--accent);
  padding:.3rem 1.1rem; border-radius:999px; font-size:.92em; margin:.4rem 0}
.article .audio-jump:hover{background:var(--accent); color:#fff}
.album-card{border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.3rem;
  margin:1.2rem 0; background:var(--surface-soft)}
.album-card .t{font-weight:600; margin-bottom:.3rem}
.album-card .d{color:var(--ink-soft); font-size:.92em}
.album-card a{display:inline-block; margin-top:.6rem; border:1px solid var(--accent);
  color:var(--accent); padding:.3rem 1.1rem; border-radius:999px; font-size:.92em}
.album-card a:hover{background:var(--accent); color:#fff}

/* 面包屑导航 */
.breadcrumb{display:flex; flex-wrap:wrap; align-items:center; gap:.3rem;
  font-size:.85em; color:var(--ink-faint); margin:0 0 1.2rem; padding-bottom:.9rem;
  border-bottom:1px solid var(--line)}
.breadcrumb a{color:var(--ink-soft); cursor:pointer}
.breadcrumb a:hover{color:var(--accent)}
.breadcrumb .sep{color:var(--ink-faint); opacity:.5; padding:0 .1rem}
.breadcrumb .cur{color:var(--ink); font-weight:600}

/* 全局播放条 */
.player{position:fixed; left:0; right:0; bottom:0; z-index:40; background:var(--surface);
  border-top:1px solid var(--line); box-shadow:0 -2px 12px rgba(0,0,0,.05);
  transform:translateY(100%); transition:transform .25s}
.player.show{transform:translateY(0)}
.player .p-bar{display:flex; align-items:center; gap:.7rem; padding:.55rem 1.2rem;
  max-width:960px; margin:0 auto}
.player .p-info{flex:1; min-width:0}
.player .p-title{font-size:.92em; color:var(--ink); font-weight:600; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis}
.player .p-sub{font-size:.78em; color:var(--ink-faint)}
.player .p-progress{height:3px; background:var(--line); border-radius:2px; margin-top:.4rem; cursor:pointer; position:relative}
.player .p-progress .p-fill{position:absolute; left:0; top:0; bottom:0; background:var(--accent);
  border-radius:2px; width:0%}
.player .p-btn{border:none; background:none; cursor:pointer; color:var(--ink);
  font-size:1.15rem; width:2.4rem; height:2.4rem; border-radius:50%; line-height:1;
  display:flex; align-items:center; justify-content:center; transition:background .15s}
.player .p-btn:hover{background:var(--surface-hover)}
.player .p-btn.p-play{width:2.9rem; height:2.9rem; background:var(--accent); color:#fff; font-size:1.1rem}
.player .p-btn.p-play:hover{background:var(--accent-soft)}
.player .p-time{font-size:.78em; color:var(--ink-faint); white-space:nowrap}
.player .p-listbtn{font-size:1rem}

/* 播放列表弹层 */
.plist{position:fixed; left:0; right:0; bottom:0; z-index:39; background:var(--surface);
  border-top:1px solid var(--line); box-shadow:0 -4px 16px rgba(0,0,0,.08);
  transform:translateY(100%); transition:transform .25s; max-height:60vh; overflow-y:auto}
.plist.show{transform:translateY(0)}
.plist .pl-head{display:flex; align-items:center; justify-content:space-between;
  padding:.8rem 1.2rem; border-bottom:1px solid var(--line); font-weight:600}
.plist .pl-close{border:none; background:none; cursor:pointer; color:var(--ink-soft); font-size:1.2rem}
.plist .pl-item{display:flex; align-items:center; gap:.6rem; padding:.65rem 1.2rem;
  cursor:pointer; border-bottom:1px solid var(--line); color:var(--ink-soft); font-size:.94em}
.plist .pl-item:hover{background:var(--surface-soft)}
.plist .pl-item.playing{color:var(--accent); font-weight:600; background:var(--surface-soft)}
.plist .pl-item .pl-dot{width:6px; height:6px; border-radius:50%; background:var(--accent-soft); flex:0 0 6px}
.plist .pl-item.playing .pl-dot{background:var(--accent)}

/* 元信息 */
.meta{font-size:.85em; color:var(--ink-faint); margin:1.2rem 0 1.6rem; display:flex; flex-wrap:wrap; gap:.3rem .9rem}
.meta .tag{background:var(--surface-soft); padding:.05em .7em; border-radius:999px; font-size:.88em; color:var(--ink-soft)}
.meta .src a{color:var(--accent-soft)}

/* 欢迎页 */
.welcome{text-align:left; padding:.5rem 0 1rem}
.welcome .big{font-size:2.2em; color:var(--ink); font-weight:700; margin-bottom:.5rem; letter-spacing:.02em}
.welcome .welcome-sub{color:var(--ink-faint); font-size:.95em}

/* 首页导览 */
.home-nav{margin-top:2.2rem; border-top:1px solid var(--line); padding-top:1.8rem}
.hn-sec{margin-bottom:2.2rem}
.hn-sec-title{font-size:1.15em; font-weight:700; color:var(--ink); margin:0 0 .3rem;
  display:flex; align-items:center; gap:.5rem; letter-spacing:.02em}
.hn-desc{color:var(--ink-faint); font-size:.88em; margin:0 0 .8rem}
.hn-dir{font-size:.82em; color:var(--accent); font-weight:600; letter-spacing:.05em;
  margin:.85rem 0 .35rem}
.hn-dir[data-depth="0"]{margin-top:.4rem; font-size:.88em}
.hn-dir[data-depth="1"]{margin-top:.7rem}
.hn-dir[data-depth="2"]{margin-top:.55rem; color:var(--ink-soft); font-weight:500}
.hn-link{display:flex; align-items:center; gap:.4rem; padding:.42rem .7rem;
  border-radius:8px; color:var(--ink-soft); font-size:.95em; cursor:pointer;
  border:1px solid transparent; transition:all .15s}
.hn-link:hover{background:var(--surface-hover); color:var(--ink); border-color:var(--line)}
.hn-link::before{content:""; width:5px; height:5px; border-radius:50%;
  background:var(--accent-soft); flex:0 0 5px; opacity:.6}
.hn-link:hover::before{background:var(--accent); opacity:1}
.hn-audio{cursor:pointer}
.hn-audio.playing{color:var(--accent); font-weight:600; background:var(--surface-soft); border-color:var(--accent-soft)}
.hn-audio.playing::before{background:var(--accent); opacity:1}
.audio-list{margin-top:.5rem}
.audio-list-title{font-size:.88em; color:var(--ink-faint); margin:1.2rem 0 .5rem; font-weight:600}

/* 移动端 */
@media(max-width:760px){
  .menu-btn{display:inline-block}
  .sidebar{position:fixed; left:0; top:53px; bottom:0; transform:translateX(-100%);
    transition:transform .2s; z-index:15; width:260px; background:var(--bg)}
  .sidebar.open{transform:translateX(0)}
  .content{padding:1.6rem 1.1rem 6rem}
  .welcome .big{font-size:1.7em}
  .player .p-bar{padding:.5rem .7rem; gap:.45rem}
  .player .p-time{display:none}
  .player .p-sub{display:none}
}
</style>
</head>
<body>
<div class="topbar">
  <button class="menu-btn" id="menuBtn">☰</button>
  <span class="brand" id="brandHome" style="cursor:pointer">@@SITE_TITLE@@<small id="pageCrumbs"></small></span>
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

<!-- 全局播放条 -->
<div class="player" id="player">
  <div class="p-bar">
    <button class="p-btn" id="pListBtn" title="播放列表">☰</button>
    <button class="p-btn" id="pPrev" title="上一首">⏮</button>
    <button class="p-btn p-play" id="pPlay" title="播放/暂停">▶</button>
    <button class="p-btn" id="pNext" title="下一首">⏭</button>
    <div class="p-info">
      <div class="p-title" id="pTitle">未播放</div>
      <div class="p-sub" id="pSub"></div>
      <div class="p-progress" id="pProgress"><div class="p-fill" id="pFill"></div></div>
    </div>
    <span class="p-time" id="pTime">0:00 / 0:00</span>
  </div>
</div>

<!-- 播放列表弹层 -->
<div class="plist" id="plist">
  <div class="pl-head"><span>🎧 开示音频列表</span><button class="pl-close" id="plClose">✕</button></div>
  <div id="plItems"></div>
</div>

<script>
var SITE_TITLE = @@SITE_TITLE_JSON@@;
var PAGES = @@PAGES_JSON@@;
var TREE = @@TREE_JSON@@;
var AUDIO_ALBUM = @@AUDIO_ALBUM_JSON@@;
var AUDIO_TRACKS = @@AUDIO_TRACKS_JSON@@;

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
  var isHome = (p.slug === 'index');
  var titleHtml = p.is_index ? '' : '<h1>' + esc(p.title) + '</h1>';
  var metaHtml = meta ? '<div class="meta">' + meta + '</div>' : '';
  var inner = titleHtml + metaHtml + p.html;
  if (isHome){
    inner = '<div class="welcome"><div class="big">' + esc(SITE_TITLE) + '</div>'
          + '<div class="welcome-sub">龙钦宁提资料库 · 学习整理与分享</div></div>'
          + p.html + renderHomeNav();
  }
  // 音频资源页 → 附加独立音频列表
  if (p.is_index && p.slug.indexOf('音频资源') === 0){
    inner += renderAudioList();
  }
  var crumb = renderBreadcrumb(p);
  document.getElementById('content').innerHTML = '<div class="article">' + crumb + inner + '</div>';
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
  // 首页导览卡片点击跳转
  document.querySelectorAll('.hn-link').forEach(function(a){
    a.onclick = function(ev){
      ev.preventDefault();
      var target = a.dataset.page;
      var hit = bySlug[target] || matchByTitle(target);
      if (hit) show(hit.slug); else alert('未找到页面：' + target);
    };
  });
  // 首页导览音频项 → 直接播放
  document.querySelectorAll('.hn-audio').forEach(function(a){
    a.onclick = function(ev){
      ev.preventDefault();
      playTrack(parseInt(a.dataset.idx, 10));
    };
  });
  // 面包屑链接
  document.querySelectorAll('.breadcrumb a').forEach(function(a){
    a.onclick = function(ev){
      ev.preventDefault();
      var target = a.dataset.page;
      var hit = bySlug[target] || matchByTitle(target);
      if (hit) show(hit.slug); else alert('未找到页面：' + target);
    };
  });
  // 播放按钮 → 触发全局播放器
  document.querySelectorAll('.play-btn').forEach(function(b){
    b.onclick = function(){
      playByAudio(b.dataset.audio);
    };
  });
  updatePlayBtns();
  window.scrollTo({top:0, behavior:'smooth'});
}

// ---- 面包屑导航 ----
function renderBreadcrumb(p){
  var parts = p.slug.split('/').filter(function(x){ return x && x !== 'index'; });
  var crumbs = ['<a class="crumb" data-page="index">主页</a>'];
  var sectionSlug = parts[0] ? parts[0] + '/index' : null;
  if (sectionSlug && bySlug[sectionSlug] && parts.length > 1){
    crumbs.push('<span class="sep">›</span><a class="crumb" data-page="' + esc(sectionSlug) + '">' + esc(parts[0]) + '</a>');
  } else if (sectionSlug && bySlug[sectionSlug] && parts.length === 1 && p.slug !== 'index'){
    crumbs.push('<span class="sep">›</span><span class="cur">' + esc(parts[0]) + '</span>');
  }
  // 中间目录层级（不可点击，仅展示）
  for (var i = 1; i < parts.length - 1; i++){
    crumbs.push('<span class="sep">›</span><span>' + esc(parts[i]) + '</span>');
  }
  // 当前页标题（文章页）
  if (parts.length > 1){
    crumbs.push('<span class="sep">›</span><span class="cur">' + esc(p.title) + '</span>');
  }
  return '<div class="breadcrumb">' + crumbs.join('') + '</div>';
}

// ---- 首页导览：递归渲染目录树为可点击板块 ----
function walkBlock(node, depth){
  var arr = [];
  var childDirs = node.dirs ? Object.keys(node.dirs) : [];
  childDirs.forEach(function(name){
    var sub = node.dirs[name];
    arr.push('<div class="hn-dir" data-depth="' + depth + '">' + esc(name) + '</div>');
    walkBlock(sub, depth + 1).forEach(function(x){ arr.push(x); });
  });
  (node.children || []).forEach(function(c){
    if (c.type === 'page' && !c.is_index){
      var p = bySlug[c.slug];
      var hasAudio = p && p.html.indexOf('play-btn') >= 0;
      arr.push('<a class="hn-link" data-page="' + esc(c.slug) + '">'
        + esc(c.title) + (hasAudio ? ' 🔊' : '') + '</a>');
    }
  });
  return arr;
}

function renderHomeNav(){
  var html = [];
  // 板块一：上师开示
  if (TREE.dirs['上师开示']){
    html.push('<section class="hn-sec">');
    html.push('<h2 class="hn-sec-title">📖 上师开示</h2>');
    html.push('<p class="hn-desc">按主题整理的上师开示，点击标题直接阅读。</p>');
    walkBlock(TREE.dirs['上师开示'], 0).forEach(function(x){ html.push(x); });
    html.push('</section>');
  }
  // 板块二：音频资料（独立音频列表，点击直接播放）
  html.push('<section class="hn-sec">');
  html.push('<h2 class="hn-sec-title">🎧 音频资料</h2>');
  html.push('<p class="hn-desc">文字转语音版开示，点击标题即可在当前页面直接收听，也可用底部播放器连播。</p>');
  AUDIO_TRACKS.forEach(function(t, i){
    html.push('<a class="hn-link hn-audio" data-idx="' + i + '">🔊 ' + esc(t.title) + '</a>');
  });
  html.push('<div class="album-card"><div class="t">《大圆满前行》有声书（226 集）</div>'
    + '<div class="d">嘎玛仁波切译 · 昌列寺收录。因音频体积较大，点击前往昌列寺官网在线收听。</div>'
    + '<a href="' + AUDIO_ALBUM + '" target="_blank" rel="noopener">前往昌列寺收听 ↗</a></div>');
  html.push('</section>');
  // 板块三：书籍
  if (TREE.dirs['书籍']){
    html.push('<section class="hn-sec">');
    html.push('<h2 class="hn-sec-title">📚 书籍</h2>');
    walkBlock(TREE.dirs['书籍'], 0).forEach(function(x){ html.push(x); });
    html.push('</section>');
  }
  return '<div class="home-nav">' + html.join('') + '</div>';
}

// ---- 音频资源页：独立音频列表 ----
function renderAudioList(){
  if (!AUDIO_TRACKS.length) return '';
  var items = AUDIO_TRACKS.map(function(t, i){
    return '<a class="hn-link hn-audio" data-idx="' + i + '">🔊 ' + esc(t.title) + '</a>';
  }).join('');
  return '<div class="audio-list"><div class="audio-list-title">全部开示音频（' + AUDIO_TRACKS.length + ' 篇）</div>' + items + '</div>';
}

function matchByTitle(t){
  t = t.replace(/🔊\s*/g, '').trim();
  for (var k in bySlug){
    if (k.replace(/🔊\s*/g,'').trim() === t) return bySlug[k];
    if (bySlug[k].title.replace(/🔊\s*/g,'').trim() === t) return bySlug[k];
  }
  return null;
}

// ---- 全局音频播放器 ----
var playerAudio = new Audio();
playerAudio.preload = 'none';
var curIdx = -1;

function fmtTime(s){
  if (!isFinite(s) || s < 0) s = 0;
  var m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m + ':' + (sec < 10 ? '0' : '') + sec;
}

function showPlayer(){
  document.getElementById('player').classList.add('show');
  document.getElementById('plist').classList.remove('show');
}

function playTrack(idx){
  if (idx < 0 || idx >= AUDIO_TRACKS.length) return;
  curIdx = idx;
  var t = AUDIO_TRACKS[idx];
  playerAudio.src = t.src;
  playerAudio.play();
  document.getElementById('pTitle').textContent = t.title;
  document.getElementById('pSub').textContent = '第 ' + (idx + 1) + ' / ' + AUDIO_TRACKS.length + ' 篇';
  document.getElementById('pPlay').textContent = '⏸';
  showPlayer();
  renderPlist();
  updatePlayBtns();
}

function playByAudio(fname){
  for (var i = 0; i < AUDIO_TRACKS.length; i++){
    if (AUDIO_TRACKS[i].src.indexOf(encodeURIComponent(fname)) >= 0 || AUDIO_TRACKS[i].src.indexOf(fname) >= 0){
      playTrack(i); return;
    }
  }
  // 兜底：按文件名匹配
  for (var j = 0; j < AUDIO_TRACKS.length; j++){
    var srcName = decodeURIComponent(AUDIO_TRACKS[j].src.split('/').pop());
    if (srcName === fname){ playTrack(j); return; }
  }
}

function updatePlayBtns(){
  // 文章内播放按钮
  document.querySelectorAll('.play-btn').forEach(function(b){
    var active = false;
    if (curIdx >= 0){
      var srcName = decodeURIComponent(AUDIO_TRACKS[curIdx].src.split('/').pop());
      active = (srcName === b.dataset.audio);
    }
    b.classList.toggle('playing', active);
    b.textContent = active ? '⏸ 正在播放' : '▶ 播放本篇开示';
  });
  // 首页/音频资源页的音频列表项
  document.querySelectorAll('.hn-audio').forEach(function(a){
    a.classList.toggle('playing', parseInt(a.dataset.idx, 10) === curIdx);
  });
  // 播放列表弹层项
  document.querySelectorAll('.pl-item').forEach(function(it){
    it.classList.toggle('playing', parseInt(it.dataset.idx, 10) === curIdx);
  });
}

document.getElementById('pPlay').onclick = function(){
  if (curIdx < 0 && AUDIO_TRACKS.length) playTrack(0);
  else if (playerAudio.paused){ playerAudio.play(); this.textContent = '⏸'; }
  else { playerAudio.pause(); this.textContent = '▶'; }
};
document.getElementById('pNext').onclick = function(){
  if (curIdx < 0) playTrack(0);
  else playTrack((curIdx + 1) % AUDIO_TRACKS.length);
};
document.getElementById('pPrev').onclick = function(){
  if (curIdx < 0) playTrack(0);
  else playTrack((curIdx - 1 + AUDIO_TRACKS.length) % AUDIO_TRACKS.length);
};

playerAudio.addEventListener('timeupdate', function(){
  var pct = playerAudio.duration ? (playerAudio.currentTime / playerAudio.duration * 100) : 0;
  document.getElementById('pFill').style.width = pct + '%';
  document.getElementById('pTime').textContent = fmtTime(playerAudio.currentTime) + ' / ' + fmtTime(playerAudio.duration);
});
playerAudio.addEventListener('ended', function(){
  // 自动连播下一首
  if (curIdx >= 0 && curIdx < AUDIO_TRACKS.length - 1) playTrack(curIdx + 1);
  else { document.getElementById('pPlay').textContent = '▶'; }
});
playerAudio.addEventListener('play', function(){ document.getElementById('pPlay').textContent = '⏸'; });
playerAudio.addEventListener('pause', function(){ document.getElementById('pPlay').textContent = '▶'; });

// 进度条点击跳转
document.getElementById('pProgress').onclick = function(ev){
  if (curIdx < 0 || !playerAudio.duration) return;
  var rect = this.getBoundingClientRect();
  var ratio = (ev.clientX - rect.left) / rect.width;
  playerAudio.currentTime = ratio * playerAudio.duration;
};

// 播放列表弹层
function renderPlist(){
  var box = document.getElementById('plItems');
  var arr = AUDIO_TRACKS.map(function(t, i){
    return '<div class="pl-item' + (i === curIdx ? ' playing' : '') + '" data-idx="' + i + '">'
      + '<span class="pl-dot"></span><span>' + esc(t.title) + '</span></div>';
  });
  box.innerHTML = arr.join('');
  box.querySelectorAll('.pl-item').forEach(function(it){
    it.onclick = function(){ playTrack(parseInt(it.dataset.idx, 10)); };
  });
}
document.getElementById('pListBtn').onclick = function(){
  var pl = document.getElementById('plist');
  pl.classList.toggle('show');
  if (pl.classList.contains('show')) renderPlist();
};
document.getElementById('plClose').onclick = function(){
  document.getElementById('plist').classList.remove('show');
};

// 顶栏品牌点击返回主页
document.getElementById('brandHome').onclick = function(){ show('index'); };

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

    # 在「音频资源」index 页追加昌列寺跳转卡片
    for p in pages:
        if p["is_index"] and p["slug"].startswith("音频资源"):
            card = ('<div class="album-card">'
                    '<div class="t">《大圆满前行》有声书（226 集）</div>'
                    '<div class="d">嘎玛仁波切译 · 昌列寺收录。因音频体积较大，点击下方按钮前往昌列寺官网在线收听。</div>'
                    '<a href="%s" target="_blank" rel="noopener">前往昌列寺收听 ↗</a>'
                    '</div>' % CHANGLESI_ALBUM)
            p["html"] += card
            break

    tree = build_tree(pages)
    site_title = "龙的传人"
    for p in pages:
        if p["slug"] == "index" and p["meta"].get("title"):
            site_title = p["meta"]["title"]

    # 生成音频轨道列表：每篇带本地音频的文章，对应一个 track（标题=文章标题，src=audio/文件名）
    audio_tracks = []
    for p in pages:
        for m in re.finditer(r'data-audio="([^"]+)"', p["html"]):
            fname = m.group(1)
            title = fname[:-4] if fname.lower().endswith(".mp3") else fname
            audio_tracks.append({
                "title": p["title"] or title,
                "slug": p["slug"],
                "src": "audio/" + quote(fname),
                "file": fname,
            })

    html_out = PAGE_TEMPLATE
    html_out = html_out.replace("@@SITE_TITLE_JSON@@", json.dumps(site_title, ensure_ascii=False))
    html_out = html_out.replace("@@AUDIO_ALBUM_JSON@@", json.dumps(CHANGLESI_ALBUM, ensure_ascii=False))
    html_out = html_out.replace("@@AUDIO_TRACKS_JSON@@", json.dumps(audio_tracks, ensure_ascii=False))
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
