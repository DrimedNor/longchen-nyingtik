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
import struct
import sys
import time
import zlib
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


# ---------------------------------------------------------------- 目录名去序号 / 音频文件夹路径
def clean_dir_name(name):
    """去掉目录名前方自带的层级序号（如 "1. "、"1.1 "、"4."）。"""
    return re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', name)


def audio_folder_rel(fname):
    """返回 mp3 相对「音频资源」目录的完整文件夹路径（如 "2. 上师法音/2.1 仪轨与经文"）。
    用于音频资源页按文件夹层级分组、以及折叠导航中按文件夹归属音频。"""
    path = LOCAL_AUDIO.get(fname)
    if not path:
        return ""
    rel = os.path.relpath(os.path.dirname(path), CONTENT_DIR)
    parts = [x for x in rel.split(os.sep) if x and x != "."]
    if parts and parts[0] == "音频资源":
        parts = parts[1:]
    return "/".join(parts)


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
                # 显示音频「名字」（去扩展名、去 TTS 音色尾缀如 _云扬），再附播放按钮
                base = fname[:-4] if fname.lower().endswith(".mp3") else fname
                aname = re.sub(r"_云扬$", "", base)
                return ('<span class="audio-name">%s</span>'
                        '<button class="play-btn" data-audio="%s">▶ 播放</button>'
                        % (html_mod.escape(aname, quote=True),
                           html_mod.escape(fname, quote=True)))
            return ('<a class="audio-jump" href="%s" target="_blank" rel="noopener">'
                    '🎧 收听音频（跳转昌列寺）</a>' % CHANGLESI_ALBUM)
        # 内部链接 -> data-page 锚点
        slug = target.strip()
        return ('<a class="wikilink" data-page="%s">%s</a>'
                % (html_mod.escape(slug, quote=True), html_mod.escape(label)))
    # Obsidian 嵌入图片 ![[image.png|width]] —— 构建时复制到 dist/assets/，此处生成 <img>
    def _embed(m):
        target = m.group(1)
        parts = target.split("|")
        fname = parts[0].strip()
        width = parts[1].strip() if len(parts) > 1 else ""
        # 在 content/ 下查找图片文件
        img_src = None
        for _dp, _dn, _fn in os.walk(CONTENT_DIR):
            if fname in _fn:
                rel = os.path.relpath(os.path.join(_dp, fname), CONTENT_DIR).replace("\\", "/")
                img_src = "assets/" + rel
                break
        if img_src:
            w = ' width="%s"' % html_mod.escape(width, quote=True) if width else ""
            return '<img src="%s"%s alt="%s" loading="lazy">' % (
                html_mod.escape(img_src, quote=True), w, html_mod.escape(fname))
        return ""  # 图片不存在则隐藏
    text = re.sub(r"!\[\[([^\]]+)\]\]", _embed, text)
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
            items = []
            for x in list_buf:
                # 支持列表项内的标题（如 "- ### 《书名》"）：遇到标题先关闭当前列表，渲染标题后再继续
                m_head = re.match(r"^(#{1,6})\s+(.*)$", x)
                if m_head:
                    if items:
                        out.append("<ul>" + "".join("<li>%s</li>" % inline(i) for i in items) + "</ul>")
                        items = []
                    lvl = len(m_head.group(1))
                    out.append("<h%d>%s</h%d>" % (lvl, inline(m_head.group(2)), lvl))
                else:
                    items.append(x)
            if items:
                out.append("<ul>" + "".join("<li>%s</li>" % inline(i) for i in items) + "</ul>")
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
    # 排除规则：隐藏目录（.开头）和「不推送」目录（用户不想公开的音频/资料，仅本地保留）
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".") and "不推送" not in d]
        for f in files:
            if f.lower().endswith((".mp3", ".m4a", ".wav")):
                LOCAL_AUDIO[f] = os.path.join(dirpath, f)
    # 第二遍：解析 md
    pages = []
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".") and "不推送" not in d]
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            if f == "本次更新内容.md":
                # 首页「本次更新内容」区块的源文件：仅作内容展示，不进入导航/目录树/普通页面
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, CONTENT_DIR).replace("\\", "/")
            txt = open(full, encoding="utf-8").read()
            meta, body = parse_frontmatter(txt)
            fallback = re.sub(r"🔊\s*", "", f[:-3]).strip()
            title = meta.get("title") or fallback or rel
            title = title.strip('"').strip()
            # Obsidian 文件名尾缀 "X/x" 仅标识未配置录音语音文件，发布页不显示该标记
            # （slug 保留原文件名以维持站内 wikilink 一致，仅剥离展示用标题）
            title = re.sub(r"[Xx]$", "", title).strip()
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
    # 规则：未经用户确认，不得自动给文章添加任何角标/提示文字（含"音频制作中"等）。
    # 如需添加此类提示，必须先与用户确认文案后再手动添加。
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
<!-- 禁止国内搜索引擎收录（百度/搜狗/360/字节），允许国外搜索引擎（Google/Bing/DuckDuckGo）-->
<meta name="baiduspider" content="noindex, nofollow, noarchive">
<meta name="sogou" content="noindex, nofollow, noarchive">
<meta name="360spider" content="noindex, nofollow, noarchive">
<meta name="bytespider" content="noindex, nofollow, noarchive">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='20' fill='%238a1f1c'/%3E%3Ctext x='50' y='68' font-size='52' font-family='serif' font-weight='bold' text-anchor='middle' fill='%23d9b86a'%3E%E9%BE%99%3C/text%3E%3C/svg%3E">
<title>@@SITE_TITLE@@</title>
<style>
:root{
  /* —— 背景：奶白 / 宣纸（白色=慈悲） —— */
  --bg:#f6f1e6;            /* 页面主背景，温润宣纸色 */
  --bg-2:#efe7d6;          /* 区块/段落交替底色 */
  --surface:#fffdf8;       /* 卡片/面板表面（近白暖色，慈悲之白） */
  --surface-soft:#f0e8d6;  /* 引用块/代码/标签/选中态的浅暖底 */
  --surface-hover:#ebe1cb; /* 悬停态浅暖底 */
  /* —— 文字层级（暖深棕，保证可读性） —— */
  --ink:#3b2a22;           /* 主文字 / 标题：沉静深棕 */
  --ink-soft:#6a4f43;      /* 次级文字：正文辅助、导航项 */
  --ink-faint:#9b8475;     /* 三级文字：提示、面包屑、元信息 */
  /* —— 线条 —— */
  --line:#e2d6bf;          /* 普通分割线 / 边框 */
  --line-strong:#cbb893;   /* 强调分割线（金褐） */
  /* —— 主色：深红（护法·庄严·能量） —— */
  --accent:#8a1f1c;        /* 主色：链接 / 按钮 / 关键强调 */
  --accent-soft:#b0473f;   /* 浅红：悬停 / 次级强调 */
  --accent-deep:#6e1614;   /* 深红：按下 / 当前激活态 */
  /* —— 辅助色：金黄（尊贵·庄严） —— */
  --gold:#b8893b;          /* 描边 / 修饰线 / 标题强调 */
  --gold-soft:#d9b86a;     /* 浅金：悬停 / 高光 */
  --gold-deep:#8a6320;     /* 深金：文字型强调 */
  /* —— 强调色：绿松石（清净） —— */
  --turq:#2f9b8f;          /* 进度条填充 / 播放中指示 */
  --turq-soft:#5bb8ad;     /* 浅松石：悬停 */
  /* —— 靛蓝（沉静·护法） —— */
  --indigo:#2f3a5c;        /* 链接 / 次级强调 */
  --indigo-soft:#4a577e;   /* 浅靛蓝：悬停 */
  --fs:1rem;
}
/* 暗色模式：深棕底 + 藏红/金黄调整亮度，保证可读性 */
[data-theme="dark"]{
  --bg:#1a1410;
  --bg-2:#221a14;
  --surface:#2a2018;
  --surface-soft:#332820;
  --surface-hover:#3d3028;
  --ink:#e8dcc8;
  --ink-soft:#b8a890;
  --ink-faint:#8a7a68;
  --line:#3d3028;
  --line-strong:#5a4a38;
  --accent:#c44a42;
  --accent-soft:#d46a60;
  --accent-deep:#a03028;
  --gold:#d9a84a;
  --gold-soft:#e8c068;
  --gold-deep:#b88830;
  --turq:#4ab8a8;
  --turq-soft:#6ad0c0;
  --indigo:#6a7ab0;
  --indigo-soft:#8a9ad0;
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
  padding:.7rem 1.2rem; background:rgba(246,241,230,.92); backdrop-filter:blur(10px);
  border-bottom:2px solid var(--gold);
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
/* 暗色模式切换按钮 */
.theme-toggle{width:2rem; height:2rem; font-size:1rem; border:1px solid var(--line);
  background:var(--surface); color:var(--ink-soft); border-radius:999px; cursor:pointer; margin-left:.3rem; line-height:1}
.theme-toggle:hover{background:var(--surface-hover); color:var(--ink)}

/* 布局 */
.layout{display:flex; min-height:calc(100vh - 53px)}
.sidebar{
  width:300px; flex:0 0 300px; border-right:1px solid var(--line); padding:1.6rem 1.1rem;
  overflow-y:auto; position:sticky; top:53px; height:calc(100vh - 53px); background:var(--bg);
}
.sidebar .search{width:100%; padding:.6rem .8rem; border:1px solid var(--line);
  border-radius:8px; font-size:1.05rem; background:#fff; color:var(--ink); margin-bottom:1.2rem;
  outline:none}
.sidebar .search:focus{border-color:var(--accent-soft)}
.nav a{display:block; padding:.4rem .6rem; border-radius:6px; color:var(--ink-soft);
  font-size:1.05rem; cursor:pointer}
.nav a:hover{background:var(--surface-hover); color:var(--ink)}
/* 选中态：深红底 + 白字（反色高亮）。加 [data-depth] 提升特异性，压过 .dir-name[data-depth] 的层级配色，
   确保鼠标移开后白字仍稳定显示，不回落到层级深红字（否则红底深红字几乎不可读）。 */
.nav a.active,
.nav a.active[data-depth]{background:var(--accent); color:#fff; text-decoration:none;
  box-shadow:inset 3px 0 0 var(--gold)}
.nav a.active:hover,
.nav a.active[data-depth]:hover{background:var(--accent); color:#fff; text-decoration:none;
  box-shadow:inset 3px 0 0 var(--gold)}
.nav .dir-name.active,
.nav .dir-name.active[data-depth]{background:var(--accent); color:#fff; text-decoration:none;
  box-shadow:inset 3px 0 0 var(--gold)}
.nav .dir-name.active:hover,
.nav .dir-name.active[data-depth]:hover{background:var(--accent); color:#fff; text-decoration:none;
  box-shadow:inset 3px 0 0 var(--gold)}
.nav .group-label{font-size:1rem; color:var(--ink-faint); letter-spacing:.1em;
  padding:.9rem .6rem .3rem; font-weight:600}
/* 目录项：仅显示目录（不显示文章列表）；按层级区分字号/字重/颜色/缩进 */
.nav .dir-name{display:flex; align-items:baseline; gap:.55rem; cursor:pointer;
  border-radius:6px; line-height:1.45; transition:background .15s}
.nav .dir-name .dir-num{font-variant-numeric:tabular-nums; font-weight:700; color:inherit; flex:0 0 auto}
.nav .dir-name .dir-label{flex:1; min-width:0; word-break:break-word}
/* 层级配色：字体越大（层级越高）颜色越深 —— 一级最深深红 → 二级深红 → 三级金黄 → 四级浅褐 */
.nav .dir-name[data-depth="0"]{font-size:1.7rem; font-weight:700; color:#6e1614;
  padding:.55rem .5rem .3rem; letter-spacing:.02em}
.nav .dir-name[data-depth="1"]{font-size:1.3rem; font-weight:600; color:#8a1f1c;
  padding:.5rem .5rem .25rem 1.2rem}
.nav .dir-name[data-depth="2"]{font-size:1.08rem; font-weight:500; color:#b8893b;
  padding:.4rem .5rem .2rem 2.3rem}
.nav .dir-name[data-depth="3"]{font-size:1rem; font-weight:500; color:#9b8475;
  padding:.35rem .5rem .2rem 3.4rem}
.nav .dir-name:hover{background:var(--surface-hover)}
/* 手风琴折叠导航：一级标题常驻，子层级默认收起，点头部展开/收起（可多开互不干扰） */
.nav .nav-sec{margin:0}
.nav .nav-sec-head{display:flex; align-items:baseline; gap:.4rem; cursor:pointer;
  border-radius:6px; line-height:1.45; transition:background .15s}
.nav .nav-sec-head .nav-chev{flex:0 0 auto; font-size:.72em; color:var(--gold-deep);
  width:1em; text-align:center; transition:transform .18s}
.nav .nav-sec-head .nav-chev-none{visibility:hidden}
.nav .nav-sec.open > .nav-sec-head .nav-chev{transform:rotate(90deg)}
.nav .nav-sec-head .dir-label{flex:1; min-width:0; word-break:break-word}
/* 层级配色与旧目录一致：一级最深深红 → 二级深红 → 三级金黄 → 四级浅褐 */
.nav .nav-sec[data-depth="0"] > .nav-sec-head{font-size:1.7rem; font-weight:700; color:#6e1614;
  padding:.55rem .5rem .3rem; letter-spacing:.02em}
.nav .nav-sec[data-depth="1"] > .nav-sec-head{font-size:1.3rem; font-weight:600; color:#8a1f1c;
  padding:.5rem .5rem .25rem 1.2rem}
.nav .nav-sec[data-depth="2"] > .nav-sec-head{font-size:1.08rem; font-weight:500; color:#b8893b;
  padding:.4rem .5rem .2rem 2.3rem}
.nav .nav-sec[data-depth="3"] > .nav-sec-head{font-size:1rem; font-weight:500; color:#9b8475;
  padding:.35rem .5rem .2rem 3.4rem}
.nav .nav-sec-head:hover{background:var(--surface-hover)}
.nav .nav-sec-head.active,
.nav .nav-sec-head.active[data-depth]{background:var(--accent)!important; color:#fff!important;
  box-shadow:inset 3px 0 0 var(--gold)}
.nav .nav-sec-head.active .nav-chev,
.nav .nav-sec-head.active .dir-label{color:inherit!important}
.nav .nav-sec-children{margin-top:.1rem}
.nav .nav-sec-body{display:none}
.nav .nav-sec.open > .nav-sec-body{display:block; padding-bottom:.1rem}
/* 折叠导航内的直属音频条目：左侧金色细线指示归属层级 */
.nav .nav-audio-list{margin:.3rem 0 .45rem 2.2rem; border-left:2px solid var(--gold-soft);
  padding:.15rem 0 .15rem .5rem}
.nav .nav-audio-list .hn-audio{display:block; font-size:.95rem; padding:.32rem .5rem;
  border-radius:6px; color:var(--ink-soft)}
.nav .nav-audio-list .hn-audio:hover{background:var(--surface-hover); color:var(--ink)}
.nav .nav-audio-list .hn-audio.playing{color:var(--accent); font-weight:600; background:var(--surface-soft)}
/* 搜索结果 */
.nav .search-result{display:block; padding:.5rem .6rem; border-radius:6px; color:var(--ink); text-decoration:none}
.nav .search-result:hover{background:var(--surface-hover)}
.nav .sr-title{display:block; font-size:1.02rem; font-weight:600; color:var(--ink)}
.nav .sr-snip{display:block; font-size:.85rem; color:var(--ink-faint); margin-top:.2rem; line-height:1.5}
.search-hl{background:var(--gold-soft); color:var(--accent-deep); font-weight:600; padding:0 .15em; border-radius:2px}
/* 移动端抽屉式侧栏的关闭按钮（仅移动端显示）与遮罩 */
.sidebar-close{display:none; position:absolute; top:.5rem; right:.6rem; z-index:2;
  border:none; background:none; color:var(--ink-soft); font-size:1.5rem; line-height:1; cursor:pointer}
.sidebar-overlay{position:fixed; inset:0; background:rgba(59,42,34,.3); z-index:14; display:none}
.sidebar-overlay.show{display:block}

/* 内容区 */
.content{flex:1; padding:2.6rem clamp(1.4rem, 6vw, 4.5rem) 9rem; max-width:820px; margin:0 auto}
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
  font-size:.95em; cursor:pointer; margin:.15rem 0 .25rem; transition:all .15s; font-family:inherit}
.article .play-btn:hover{background:var(--accent); color:#fff}
.article .play-btn.playing{background:var(--accent); color:#fff}
.article .audio-name{display:block; font-weight:600; color:var(--ink);
  margin:.1rem 0 .45rem; font-size:1.02em; line-height:1.4}
/* 音频条目：让 <li> 成浅卡条，淡化 disc 项符；用 :has() 精准只命中含播放按钮的列表 */
.article li:has(.play-btn){list-style:none; margin-left:-1.1em;
  padding:.55em .85em; border:1px solid var(--line); border-left:3px solid var(--accent-soft);
  border-radius:8px; background:var(--surface-soft)}
/* 文字页「音频制作中」角标（柔和金色边卡片，零维护：配上 [[xxx.mp3]] 即消失） */
.article .audio-pending{margin:.2rem 0 1.2rem; padding:.7rem 1rem;
  border:1px dashed var(--gold); border-left:3px solid var(--gold);
  background:rgba(212,175,55,.06); color:var(--gold-deep);
  border-radius:6px; font-size:.95em; line-height:1.5}
.article .audio-pending b{color:var(--gold-deep); font-weight:600}
.article .audio-jump{display:inline-block; border:1px solid var(--accent); color:var(--accent);
  padding:.3rem 1.1rem; border-radius:999px; font-size:.92em; margin:.4rem 0}
.article .audio-jump:hover{background:var(--accent); color:#fff}
.album-card{border:1px solid var(--gold-soft); border-radius:10px; padding:1.1rem 1.3rem;
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

/* 全局播放器（默认占据下三分之一屏） */
.player{position:fixed; left:0; right:0; bottom:0; z-index:40; background:var(--surface);
  border-top:3px solid var(--gold); box-shadow:0 -6px 24px rgba(59,42,34,.18);
  transform:translateY(100%); transition:transform .28s ease, max-height .28s ease;
  display:flex; flex-direction:column; height:auto; min-height:33vh; max-height:33vh;
  padding-bottom:env(safe-area-inset-bottom,0)}
.player.show{transform:translateY(0)}
.player.pl-open{max-height:72vh}   /* 展开播放列表时自动增高，默认仅占据下 1/3 屏 */
/* 第1行：状态栏（左：当前音频名 / 右：关闭叉号） */
.player .p-status{display:flex; align-items:center; gap:.6rem; padding:.85rem 1.3rem;
  font-size:1rem; color:var(--ink-soft); border-bottom:1px solid var(--line); flex:0 0 auto}
.player .p-status-text{flex:1; min-width:0; text-align:left; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; font-weight:500}
.player .p-status b{color:var(--accent); font-weight:600}
/* 第2行：控制按钮（上一首 ⏮ / 后退15秒 -15 / 播放 ▶ / 下一首 ⏭ / 前进15秒 +15） */
.player .p-controls{display:flex; align-items:center; justify-content:center; gap:1rem;
  padding:.9rem; flex:0 0 auto}
.player .p-btn{border:none; background:none; cursor:pointer; color:var(--ink);
  font-size:1.5rem; width:3.4rem; height:3.4rem; border-radius:50%; line-height:1;
  display:flex; align-items:center; justify-content:center; transition:background .15s; font-weight:600}
.player .p-btn:hover{background:var(--surface-hover)}
.player .p-btn.p-play{width:4.4rem; height:4.4rem; background:var(--accent); color:#fff; font-size:1.6rem}
.player .p-btn.p-play:hover{background:var(--accent-soft)}
.player .p-btn.p-skip{font-size:1.05rem; color:var(--accent); border:1px solid var(--line); width:3.8rem; height:3.8rem}
.player .p-btn.p-skip:hover{background:var(--surface-soft); border-color:var(--gold)}
/* 第3行：进度条 + 两端分秒数字 */
.player .p-time-row{display:flex; align-items:center; gap:.8rem; padding:0 1.3rem; flex:0 0 auto}
.player .p-time{font-variant-numeric:tabular-nums; font-size:.85rem; color:var(--ink-faint);
  flex:0 0 auto; min-width:3.2em; text-align:center}
.player .p-progress{flex:1; height:8px; background:var(--line); border-radius:4px;
  cursor:pointer; position:relative; touch-action:none}
.player .p-progress .p-fill{position:absolute; left:0; top:0; bottom:0; background:var(--turq);
  border-radius:4px; width:0%}
.player .p-progress .p-thumb{position:absolute; top:50%; width:16px; height:16px; border-radius:50%;
  background:#fff; border:2px solid var(--gold); transform:translate(-50%,-50%); left:0%}
/* 第4行：播放模式 + 播放列表 同一行（两端对齐，空隙均衡；播放列表按钮不再居中） */
.player .p-footer{display:flex; align-items:center; justify-content:space-between; gap:.6rem;
  padding:.6rem 1.3rem; flex:0 0 auto; border-top:1px solid var(--line)}
.player .p-footer .p-mode{margin:0; flex:0 0 auto}
.player .p-footer .p-pl-toggle{margin:0; flex:0 0 auto}
.player .p-pl-toggle{border:1px solid var(--gold); background:var(--surface); color:var(--gold-deep);
  cursor:pointer; font-size:.92rem; padding:.35rem .9rem; border-radius:999px;
  display:inline-flex; align-items:center; gap:.35rem; font-family:inherit; transition:background .15s;
  white-space:nowrap}
.player .p-pl-toggle:hover{background:var(--surface-soft)}
.player .p-pl-hint{font-size:.8rem; color:var(--ink-faint)}
.player .p-close{border:none; background:none; cursor:pointer; color:var(--ink-soft);
  font-size:1.3rem; width:2.3rem; height:2.3rem; border-radius:8px; line-height:1}
.player .p-close:hover{background:var(--surface-hover)}
/* 播放模式切换按钮（状态栏左侧胶囊）：点击在 顺序/逆序/随机/单曲循环 间循环，并显示当前模式 */
.player .p-mode{border:1px solid var(--gold); background:var(--surface); color:var(--gold-deep);
  cursor:pointer; font-size:.85rem; padding:.2rem .7rem; border-radius:999px;
  display:inline-flex; align-items:center; gap:.3rem; font-family:inherit; white-space:nowrap; transition:background .15s}
.player .p-mode:hover{background:var(--surface-soft)}
/* 倍速按钮（位于播放器底部最右侧，与播放模式同款胶囊样式） */
.player .p-speed-wrap{position:relative; display:inline-flex}
.player .p-speed{border:1px solid var(--gold); background:var(--surface); color:var(--gold-deep);
  cursor:pointer; font-size:.85rem; padding:.2rem .7rem; border-radius:999px;
  display:inline-flex; align-items:center; gap:.3rem; font-family:inherit; white-space:nowrap; transition:background .15s}
.player .p-speed:hover{background:var(--surface-soft)}
.player .p-speed-menu{position:absolute; bottom:calc(100% + 8px); right:0; z-index:50;
  background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:.3rem;
  box-shadow:0 -6px 20px rgba(59,42,34,.18); min-width:7.5rem}
.player .p-speed-menu .sp-item{padding:.45rem .7rem; border-radius:8px; font-size:.9rem; color:var(--ink-soft);
  cursor:pointer; white-space:nowrap; transition:background .15s}
.player .p-speed-menu .sp-item:hover{background:var(--surface-soft)}
.player .p-speed-menu .sp-item.active{color:var(--accent); font-weight:600; background:var(--surface-soft)}
/* 播放列表（默认收起，点击展开） */
.player .p-playlist{flex:1 1 auto; overflow-y:auto; -webkit-overflow-scrolling:touch;
  padding:.3rem 0; display:none}
.player .p-playlist.open{display:block}
.player .pl-item{display:flex; align-items:center; gap:.8rem; padding:.85rem 1.4rem;
  cursor:pointer; border-bottom:1px solid var(--line); color:var(--ink-soft); font-size:1.1em}
.player .pl-item:hover{background:var(--surface-soft)}
.player .pl-item.playing{color:var(--accent); font-weight:600; background:var(--surface-soft)}
.player .pl-item .pl-idx{font-variant-numeric:tabular-nums; color:var(--ink-faint); flex:0 0 1.8em; text-align:right}
.player .pl-item.playing .pl-idx{color:var(--accent)}
.player .pl-item .pl-dot{width:7px; height:7px; border-radius:50%; background:var(--turq-soft); flex:0 0 7px}
.player .pl-item.playing .pl-dot{background:var(--turq)}
/* 悬浮打开播放器按钮 */
.player-launch{position:fixed; right:1.1rem; bottom:1.1rem; z-index:41;
  background:var(--accent); color:#fff; border:none; cursor:pointer;
  padding:.7rem 1.1rem; border-radius:999px; font-size:1rem; font-weight:600;
  box-shadow:0 4px 14px rgba(59,42,34,.28); display:flex; align-items:center; gap:.4rem}
.player-launch:hover{background:var(--accent-soft)}
.player.show + .player-launch{display:none}

/* 底部迷你条：关闭整屏播放器但音频仍在播放时，常驻一行 */
.player-mini{position:fixed; left:0; right:0; bottom:0; z-index:39; display:none;
  align-items:center; gap:.7rem; padding:.5rem .9rem;
  background:var(--surface); border-top:1px solid var(--line);
  box-shadow:0 -2px 12px rgba(59,42,34,.10)}
.player-mini.show{display:flex}
.player-mini .pm-btn{border:none; background:none; cursor:pointer; color:var(--ink);
  font-size:1.1rem; width:2.4rem; height:2.4rem; border-radius:50%; flex:0 0 auto;
  display:flex; align-items:center; justify-content:center}
.player-mini .pm-btn:hover{background:var(--surface-hover)}
.player-mini .pm-name{font-size:.92rem; color:var(--ink); font-weight:600;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:0 1 auto; max-width:42%}
.player-mini .pm-progress{flex:1 1 auto; height:6px; background:var(--line);
  border-radius:3px; position:relative; cursor:pointer; overflow:hidden}
.player-mini .pm-fill{position:absolute; left:0; top:0; bottom:0;
  background:var(--turq); border-radius:3px; width:0}
.player-mini .pm-expand{flex:0 0 auto}
/* 迷你条倍速按钮（紧凑胶囊，位于展开按钮左侧） */
.player-mini .pm-speed-wrap{position:relative; display:inline-flex}
.player-mini .pm-speed{border:1px solid var(--gold); background:var(--surface); color:var(--gold-deep);
  cursor:pointer; font-size:.78rem; padding:.1rem .5rem; border-radius:999px; font-family:inherit;
  white-space:nowrap; line-height:1.6; flex:0 0 auto}
.player-mini .pm-speed:hover{background:var(--surface-soft)}
.player-mini .pm-speed-menu{position:absolute; bottom:calc(100% + 8px); right:0; z-index:50;
  background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:.3rem;
  box-shadow:0 -6px 20px rgba(59,42,34,.18); min-width:6.5rem}
.player-mini .pm-speed-menu .sp-item{padding:.4rem .6rem; border-radius:8px; font-size:.85rem; color:var(--ink-soft);
  cursor:pointer; white-space:nowrap; transition:background .15s}
.player-mini .pm-speed-menu .sp-item:hover{background:var(--surface-soft)}
.player-mini .pm-speed-menu .sp-item.active{color:var(--accent); font-weight:600; background:var(--surface-soft)}

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
.hn-dir{font-size:.82em; color:#9b8475; font-weight:700; letter-spacing:.05em;
  margin:.9rem 0 .35rem}
.hn-dir[data-depth="0"]{margin-top:.5rem; font-size:1.05em; color:#6e1614}
.hn-dir[data-depth="1"]{margin-top:.7rem; font-size:.98em; color:#8a1f1c; font-weight:600}
.hn-dir[data-depth="2"]{margin-top:.55rem; font-size:.9em; color:#b8893b; font-weight:500}
.hn-link{display:flex; align-items:center; gap:.4rem; padding:.42rem .7rem;
  border-radius:8px; color:var(--ink-soft); font-size:.95em; cursor:pointer;
  border:1px solid transparent; transition:all .15s}
.hn-link:hover{background:var(--surface-hover); color:var(--ink); border-color:var(--line)}
.hn-link::before{content:""; width:5px; height:5px; border-radius:50%;
  background:var(--accent-soft); flex:0 0 5px; opacity:.6}
.hn-link:hover::before{background:var(--accent); opacity:1}
.hn-audio{cursor:pointer}
.hn-link.hn-audio{font-size:1.2em; padding:.85rem 1rem}
.hn-audio.playing{color:var(--accent); font-weight:600; background:var(--surface-soft); border-color:var(--accent-soft)}
.hn-audio.playing::before{background:var(--accent); opacity:1}
.audio-list{margin-top:.5rem}
.audio-list-title{font-size:.95em; color:var(--ink-faint); margin:1.2rem 0 .5rem; font-weight:600}
.audio-group-title{font-size:.82em; color:var(--gold-deep); font-weight:700; letter-spacing:.04em; margin:1rem 0 .35rem; padding-left:.2rem; border-left:3px solid var(--gold); padding-left:.5rem}
.audio-note{color:var(--ink-soft); font-size:.95em; margin:.6rem 0 1rem; line-height:1.7}
.hn-tips{margin:.4rem 0 1rem; padding-left:1.2rem; list-style:disc}
.hn-tips li{color:var(--ink-soft); font-size:.9em; line-height:1.7; margin:.3rem 0}
/* 首页「本次更新内容」区块：与代码/导航结构清晰区分的独立内容展示区 */
.home-update{border:1px solid var(--gold-soft); border-left:4px solid var(--accent);
  border-radius:12px; padding:1.1rem 1.4rem; margin:1.6rem 0; background:var(--surface-soft)}
.home-update .hn-sec-title{margin-top:0}
.home-update h3{font-size:1.05em; color:var(--gold-deep); margin:1.2em 0 .4em; font-weight:600}
.home-update ul{margin:.4em 0 .8em 1.4em; padding:0}
.home-update li{margin:.35em 0}
.home-update .play-btn{margin:.2rem 0 .2rem 0}
.dir-children{margin-top:.6rem}
.dir-children .hn-link{font-size:1.02em}

/* 移动端 */
@media(max-width:760px){
  .menu-btn{display:inline-block}
  .sidebar{position:fixed; left:0; top:53px; bottom:0; transform:translateX(-100%);
    transition:transform .2s; z-index:15; width:260px; background:var(--bg)}
  .sidebar.open{transform:translateX(0)}
  .sidebar-close{display:block}
  .content{padding:1.6rem 1.1rem 9rem}
  .welcome .big{font-size:1.7em}
  .player{height:auto; min-height:34vh; max-height:34vh}
  .player.pl-open{max-height:80vh}
  .player .p-controls{gap:.7rem; padding:.85rem}
  .player .p-btn{width:3.2rem; height:3.2rem; font-size:1.35rem}
  .player .p-btn.p-play{width:3.9rem; height:3.9rem; font-size:1.45rem}
  .player .p-btn.p-skip{width:3.5rem; height:3.5rem; font-size:1.05rem}
  .player-launch{font-size:.9rem; padding:.6rem .9rem}
  /* 移动端：避免右上角字号按钮挤压网站名 —— 隐藏「字号」字样、压缩药丸、品牌名省略号 */
  .topbar{gap:.4rem; padding:.6rem .9rem}
  .brand{flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.92rem}
  .fs-cap{display:none}
  .fs-pill{padding:.05rem .15rem; gap:0}
  .fs-pill button{width:1.7rem; height:1.7rem; font-size:.9rem}
  .player .p-footer{gap:.4rem; padding:.55rem .9rem}
  .player .p-pl-toggle{font-size:.82rem; padding:.3rem .7rem}
  .player .p-pl-hint{font-size:.74rem}
}
/* 页脚 */
.site-footer{border-top:1px solid var(--line); background:var(--surface-soft); padding:1.2rem 1rem; margin-top:2rem}
.footer-inner{max-width:820px; margin:0 auto; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem; font-size:.85rem; color:var(--ink-faint)}
.footer-copy{color:var(--ink-soft)}
.footer-build{color:var(--ink-faint)}
/* 回到顶部按钮 */
.back-top{position:fixed; right:1.2rem; bottom:5.5rem; width:2.6rem; height:2.6rem; border-radius:50%;
  background:var(--accent); color:#fff; border:none; font-size:1.2rem; cursor:pointer; opacity:0;
  transition:opacity .3s; box-shadow:0 2px 8px rgba(0,0,0,.2); z-index:20}
.back-top:hover{background:var(--accent-deep)}
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
  <button id="themeToggle" class="theme-toggle" title="切换暗色/浅色模式">🌙</button>
  <span id="hitStat" style="display:none; font-size:.82rem; color:var(--ink-faint); white-space:nowrap; margin-left:.4rem"></span>
</div>

<div class="layout">
  <aside class="sidebar" id="sidebar">
    <button class="sidebar-close" id="sidebarClose" title="关闭菜单">✕</button>
    <input class="search" id="search" type="text" placeholder="搜索…">
    <nav class="nav" id="nav"></nav>
  </aside>
  <main class="content" id="content"></main>
</div>

<!-- 移动端：点击菜单外空白区域关闭侧栏 -->
<div class="sidebar-overlay" id="sidebarOverlay"></div>

<!-- 全局播放器（默认占据下三分之一屏） -->
<div class="player" id="player">
  <!-- 第1行：状态栏（左：当前音频名 / 右：关闭叉号） -->
  <div class="p-status" id="pStatus">
    <span class="p-status-text" id="pStatusText">暂未播放</span>
    <button class="p-close" id="pClose" title="关闭播放器">✕</button>
  </div>
  <!-- 第2行：控制按钮（上一首 / 后退15秒 / 播放 / 下一首 / 前进15秒） -->
  <div class="p-controls">
    <button class="p-btn" id="pPrev" title="上一首">⏮</button>
    <button class="p-btn p-skip" id="pBack" title="后退 15 秒">-15</button>
    <button class="p-btn p-play" id="pPlay" title="播放 / 暂停">▶</button>
    <button class="p-btn p-skip" id="pFwd" title="前进 15 秒">+15</button>
    <button class="p-btn" id="pNext" title="下一首">⏭</button>
  </div>
  <!-- 第3行：进度条 + 两端分秒数字 -->
  <div class="p-time-row">
    <span class="p-time" id="pTimeCur">0:00</span>
    <div class="p-progress" id="pProgress"><div class="p-fill" id="pFill"></div><div class="p-thumb" id="pThumb"></div></div>
    <span class="p-time" id="pTimeDur">0:00</span>
  </div>
  <!-- 第4行：播放列表(最左) + 播放模式/调整顺序(中) + 倍速(最右) -->
  <div class="p-footer">
    <button class="p-pl-toggle" id="pPlToggle">📋 播放列表 <span class="p-pl-hint" id="pPlHint">点击展开播放列表</span></button>
    <button class="p-mode" id="pMode" title="播放模式：顺序 / 逆序 / 随机 / 单曲循环（点击切换）">🔁 顺序</button>
    <span class="p-speed-wrap">
      <button class="p-speed" id="pSpeed" title="播放速度（点击选择倍速）">倍速 1x</button>
      <div class="p-speed-menu" id="pSpeedMenu" style="display:none">
        <div class="sp-item" data-rate="0.5">0.5x</div>
        <div class="sp-item" data-rate="0.75">0.75x</div>
        <div class="sp-item" data-rate="1">1x（默认）</div>
        <div class="sp-item" data-rate="1.25">1.25x</div>
        <div class="sp-item" data-rate="1.5">1.5x</div>
        <div class="sp-item" data-rate="2">2x</div>
      </div>
    </span>
  </div>
  <!-- 完整播放列表（点击开关展开） -->
  <div class="p-playlist" id="pPlaylist"></div>
</div>
<button class="player-launch" id="playerLaunch">🎧 播放器</button>

<!-- 底部迷你条：关闭播放器但仍在播放时，常驻显示当前音频名 + 进度 -->
<div class="player-mini" id="playerMini">
  <button class="pm-btn" id="pmPlay" title="播放 / 暂停">⏸</button>
  <span class="pm-name" id="pmName">暂未播放</span>
  <div class="pm-progress" id="pmProgress"><div class="pm-fill" id="pmFill"></div></div>
  <span class="pm-speed-wrap">
    <button class="pm-speed" id="pmSpeed" title="播放速度（点击选择倍速）">1x</button>
    <div class="pm-speed-menu" id="pmSpeedMenu" style="display:none">
      <div class="sp-item" data-rate="0.5">0.5x</div>
      <div class="sp-item" data-rate="0.75">0.75x</div>
      <div class="sp-item" data-rate="1">1x（默认）</div>
      <div class="sp-item" data-rate="1.25">1.25x</div>
      <div class="sp-item" data-rate="1.5">1.5x</div>
      <div class="sp-item" data-rate="2">2x</div>
    </div>
  </span>
  <button class="pm-btn" id="pmExpand" title="展开播放器">↗</button>
</div>

<script>
// ---- Service Worker 注册：音频离线缓存 + 页面更新策略（sw.js 由构建时复制到 dist 根） ----
if ('serviceWorker' in navigator){
  window.addEventListener('load', function(){
    navigator.serviceWorker.register('sw.js').catch(function(e){ console.warn('SW 注册失败:', e); });
  });
}
var SITE_TITLE = @@SITE_TITLE_JSON@@;
var PAGES = @@PAGES_JSON@@;
var TREE = @@TREE_JSON@@;
var AUDIO_ALBUM = @@AUDIO_ALBUM_JSON@@;
var AUDIO_TRACKS = @@AUDIO_TRACKS_JSON@@;
var HOME_UPDATE_HTML = @@HOME_UPDATE_JSON@@;   // 首页「本次更新内容」区块（纯用户资料，不含技术调整）
var HOME_UPDATE_DATE = "@@HOME_UPDATE_DATE@@"; // 首页公告区标题用的更新日期（取自内容文件 frontmatter date 字段）

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

// ---- 暗色模式切换（localStorage 记忆 + prefers-color-scheme 自动适配）----
var THEME_KEY = 'longchen-theme';
var savedTheme = localStorage.getItem(THEME_KEY);
if (!savedTheme){
  savedTheme = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
}
function applyTheme(theme){
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('themeToggle').textContent = theme === 'dark' ? '☀️' : '🌙';
  localStorage.setItem(THEME_KEY, theme);
}
applyTheme(savedTheme);
document.getElementById('themeToggle').onclick = function(){
  var cur = document.documentElement.getAttribute('data-theme');
  applyTheme(cur === 'dark' ? 'light' : 'dark');
};

// ---- 渲染目录树（仅显示目录，不显示文章列表）----
// 目录优先跳转到自身的 index 页；若无 index，则跳到该目录下第一篇开示；
// 完全无内容的目录则不显示，避免出现无法点击的死项。
function firstPageUnder(pathPrefix){
  var list = PAGES.filter(function(p){
    return p.slug.indexOf(pathPrefix + '/') === 0 && p.slug !== pathPrefix + '/index';
  });
  list.sort(function(a, b){ return a.slug < b.slug ? -1 : 1; });
  return list.length ? list[0].slug : null;
}
// 去掉目录名前方自带的层级序号（如 "1. "、"1.1 "、"4."），改用统一计算序号避免重复
function cleanDirName(name){
  return name.replace(/^\d+(?:\.\d+)*\.?\s*/, '');
}
// 导航悬停底色：自适应每项文字颜色，保证文字与底色对比清晰、不融合
function navTextRGB(el){
  var c = getComputedStyle(el).color, m = c.match(/\d+/g);
  return [+m[0], +m[1], +m[2]];
}
// 依据背景亮度返回对比足够的文字色（浅底→深棕，深底→白）
function contrastInk(r, g, b){
  var f = function(c){ c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  var L = 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  return L > 0.45 ? '#3b2a22' : '#ffffff';
}
// 比空闲底色更深的同色调色块（文字色混入 24% 到暖白底），既「更深」又自适应文字色
function navHoverBg(el){
  var rgb = navTextRGB(el);
  var mix = function(x){ return Math.round(x * 0.24 + 245 * 0.76); };
  return 'rgb(' + mix(rgb[0]) + ',' + mix(rgb[1]) + ',' + mix(rgb[2]) + ')';
}
function renderNav(){
  var nav = document.getElementById('nav');
  // 一级目录固定顺序（与首页导览一致）；其余新增目录按名称追加在末尾
  var TOP_ORDER = ['上师开示', '龙钦宁提传承', '音频资源', '书籍', '更新日志'];
  function topKey(name){ var i = TOP_ORDER.indexOf(name); return i < 0 ? 1000 : i; }
  // 某文件夹（完整路径，如 "音频资源/2. 上师法音"）直属的音频条目；只匹配直接归属，不含子文件夹
  function navAudioList(full){
    if (!full || full.indexOf('音频资源/') !== 0) return '';
    var key = full.slice('音频资源/'.length);
    var items = [];
    AUDIO_TRACKS.forEach(function(t, i){
      if ((t.folder || '') === key){
        items.push('<a class="hn-link hn-audio" data-idx="' + i + '">🔊 ' + esc(t.title) + '</a>');
      }
    });
    return items.join('');
  }
  // 递归渲染手风琴：每个有内容的目录 = 一个可折叠小节；正文 = 子目录小节 + 直属音频
  // 默认只展示一级标题（一级始终可见），子层级收起，点击一级展开
  function walk(node, prefix, depth){
    if (depth > 2) return '';   // 控制在 3 个层级（depth 0 / 1 / 2）
    var names = (node.dirs ? Object.keys(node.dirs) : []).slice();
    if (depth === 0) names.sort(function(a, b){ return topKey(a) - topKey(b); });
    else names.sort();
    var out = '';
    names.forEach(function(name){
      var sub = node.dirs[name];
      var full = (prefix ? prefix + '/' : '') + name;
      var target = full + '/index';
      if (!bySlug[target]) target = firstPageUnder(full);
      if (!target) return;
      var children = walk(sub, full, depth + 1);
      var audio = navAudioList(full);
      var body = (children ? '<div class="nav-sec-children">' + children + '</div>' : '')
               + (audio ? '<div class="nav-audio-list">' + audio + '</div>' : '');
      var hasBody = body !== '';
      out += '<div class="nav-sec" data-depth="' + depth + '" data-slug="' + esc(target) + '">'
        + '<div class="nav-sec-head' + (hasBody ? ' has-body' : '') + '" data-slug="' + esc(target) + '">'
        + '<span class="nav-chev' + (hasBody ? '' : ' nav-chev-none') + '">▸</span>'
        + '<span class="dir-label">' + esc(name) + '</span></div>'
        + (hasBody ? '<div class="nav-sec-body">' + body + '</div>' : '')
        + '</div>';
    });
    return out;
  }
  var html = walk(TREE, '', 0);
  // 顶层独立页面（如「更新日志」）：作为一级可点击项排在末尾
  (TREE.children || []).forEach(function(c){
    if (c.type === 'page' && !c.is_index){
      html += '<div class="nav-sec" data-depth="0" data-slug="' + esc(c.slug) + '">'
        + '<div class="nav-sec-head" data-slug="' + esc(c.slug) + '">'
        + '<span class="nav-chev nav-chev-none">▸</span>'
        + '<span class="dir-label">' + esc(c.title) + '</span></div></div>';
    }
  });
  nav.innerHTML = html;
  // 折叠交互：点头部切换展开/收起（多个一级可同时展开，互不干扰）；叶子目录点击直达
  nav.querySelectorAll('.nav-sec-head').forEach(function(h){
    h.onclick = function(){
      var sec = h.closest('.nav-sec');
      var body = h.nextElementSibling;
      var hasBody = body && body.classList.contains('nav-sec-body');
      var isMobile = window.innerWidth <= 760;
      if (hasBody){
        sec.classList.toggle('open');
        // 手机端：有子内容时点击只展开/收起下级，不跳转页面；桌面端保持原行为（既展开又跳转）
        if (isMobile) return;
      }
      show(h.dataset.slug);
      if (isMobile) closeSidebar();
    };
    // 悬停：按该项文字色生成更深色块并选配对比文字，松开即恢复
    h.addEventListener('mouseenter', function(){
      if (h.classList.contains('active')) return;
      var m = navHoverBg(h).match(/\d+/g);
      h.style.background = 'rgb(' + m[0] + ',' + m[1] + ',' + m[2] + ')';
      h.style.color = contrastInk(+m[0], +m[1], +m[2]);
    });
    h.addEventListener('mouseleave', function(){
      h.style.background = '';
      h.style.color = '';
    });
  });
  // 导航内音频项 → 直接播放
  nav.querySelectorAll('.nav-audio-list .hn-audio').forEach(function(a){
    a.onclick = function(ev){
      ev.preventDefault();
      playTrack(parseInt(a.dataset.idx, 10));
    };
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
          + '<section class="hn-sec home-update"><h2 class="hn-sec-title">最近更新 · ' + HOME_UPDATE_DATE + '</h2>'
          + HOME_UPDATE_HTML + '</section>'
          + p.html + renderHomeNav();
  }
  // 目录 landing 页（非首页 index）：自动聚合展示其下文章列表
  if (p.is_index && p.slug !== 'index'){
    inner += renderDirChildren(p.slug);
  }
  // 音频资源页 → 按文件夹层级自动生成索引列表（嵌套子文件夹取完整路径；手工编排列表优先不重复附加）
  if (p.is_index && p.slug.indexOf('音频资源') === 0){
    var grp = null;
    if (p.slug !== '音频资源/index'){
      grp = p.slug.slice('音频资源/'.length).replace(/\/index$/, '');
    }
    var _curated = grp && p.html.indexOf('class="play-btn"') !== -1;
    if (!_curated) inner += renderAudioListByFolder(grp);
  }
  var crumb = renderBreadcrumb(p);
  document.getElementById('content').innerHTML = '<div class="article">' + crumb + inner + '</div>';
  document.getElementById('pageCrumbs').textContent = p.is_index ? '' : (' / ' + p.title);
  // 目录选中态：仅高亮「层级最深」的匹配项。
  // 当父目录（大标题，如「1 为何修行」）与子目录（如「1.1 诸行无常」）解析到同一页面
  // （data-slug 相同，父目录无自身内容、只含该子目录时会发生）时，只点亮子文件夹，
  // 避免点击子文件夹时连带上方大标题一并反色高亮。
  var _navHeads = document.querySelectorAll('.nav .nav-sec-head, .nav a');
  var _best = null, _bestDepth = -1;
  _navHeads.forEach(function(a){
    a.classList.remove('active');
    if (a.dataset.slug === slug){
      var sec = a.closest('.nav-sec');
      var d = sec ? parseInt(sec.dataset.depth || '0', 10) : 0;
      if (d > _bestDepth){ _bestDepth = d; _best = a; }
    }
  });
  if (_best){
    _best.classList.add('active');
    // 展开该选中项的祖先小节（自身不强制展开，允许用户收起），保证当前所在层级一目了然
    var el = _best.parentElement;
    if (el) el = el.parentElement;
    while (el && el.classList && !el.classList.contains('nav')){
      if (el.classList.contains('nav-sec')){
        var bd = el.querySelector('.nav-sec-body');
        if (bd && !el.classList.contains('open')) el.classList.add('open');
      }
      el = el.parentElement;
    }
  }
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
  } else if (p.slug !== 'index' && parts.length === 1){
    // 顶层独立页面（如「更新日志」）：无父级 index，直接显示当前页标题
    crumbs.push('<span class="sep">›</span><span class="cur">' + esc(p.title) + '</span>');
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

// ---- 首页导览：递归渲染目录树为可点击板块（同样统一层级序号）----
function walkBlock(node, prefix, depth, parentNum){
  var arr = [];
  var names = (node.dirs ? Object.keys(node.dirs) : []).slice().sort();
  names.forEach(function(name, idx){
    var sub = node.dirs[name];
    var num = parentNum ? (parentNum + '.' + (idx + 1)) : String(idx + 1);
    var full = (prefix ? prefix + '/' : '') + name;
    var target = full + '/index';
    if (!bySlug[target]) target = firstPageUnder(full);
    var hasSub = sub.dirs && Object.keys(sub.dirs).length;
    if (!target && !hasSub) return;   // 空目录（无 index / 无首篇 / 无子目录）→ 跳过
    arr.push('<div class="hn-dir" data-depth="' + depth + '">' + esc(num) + '. ' + esc(cleanDirName(name)) + '</div>');
    walkBlock(sub, full, depth + 1, num).forEach(function(x){ arr.push(x); });
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
  // 每个顶层目录板块的定制元信息（未配置的目录使用默认图标/说明）
  var META = {
    '上师开示': {icon:'📖', title:'上师开示', desc:'按主题整理的上师开示，点击标题直接阅读。', tips:true},
    '龙钦宁提传承': {icon:'🐉', title:'龙钦宁提传承', desc:'龙钦宁提传承相关资料与祖师传记，点击进入查看。'},
    '音频资源': {icon:'🎧', title:'音频资料', desc:'文字转语音版开示，点击标题即可在当前页面直接收听，也可用底部播放器连播。', audio:true, note:true},
    '书籍': {icon:'📚', title:'书籍', desc:'精选读物与参考资料，点击进入查看。'}
  };
  // 固定首页板块顺序：一级目录按指定顺序，其余新增目录排在末尾
  var ORDER = ['上师开示', '龙钦宁提传承', '音频资源', '书籍'];
  var dirNames = Object.keys(TREE.dirs).sort(function(a, b){
    var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
    if (ia < 0) ia = 99; if (ib < 0) ib = 99;
    return ia - ib;
  });
  dirNames.forEach(function(dirName){
    var node = TREE.dirs[dirName];
    var hasSub = node.dirs && Object.keys(node.dirs).length;
    var hasPages = node.children && node.children.length;
    if (!hasSub && !hasPages) return;   // 完全无内容的顶层目录不显示在首页
    var meta = META[dirName] || {icon:'📜', title:cleanDirName(dirName), desc:'点击进入查看相关内容。'};
    html.push('<section class="hn-sec">');
    html.push('<h2 class="hn-sec-title">' + meta.icon + ' ' + esc(meta.title) + '</h2>');
    if (meta.desc) html.push('<p class="hn-desc">' + meta.desc + '</p>');
    if (meta.tips){
      html.push('<ul class="hn-tips"><li>🔊 带有小喇叭标志的文章表示有配套音频，可直接点击收听；</li>'
        + '<li>未带小喇叭标志的文章暂无音频，正在陆续添加中，敬请期待。</li></ul>');
    }
    if (meta.audio){
      if (meta.note) html.push('<p class="audio-note">因为服务器在国外，缓冲需要时间，请耐心等一会儿。</p>');
      // 按一级文件夹分组展示全部音频（与折叠导航的层级一致，避免平铺 70+ 条）
      var _agroups = {};
      AUDIO_TRACKS.forEach(function(t, i){
        var g = cleanDirName((t.folder || '其他音频').split('/')[0]);
        (_agroups[g] = _agroups[g] || []).push({t: t, i: i});
      });
      Object.keys(_agroups).sort().forEach(function(g){
        html.push('<div class="audio-group-title">' + esc(g) + '</div>');
        _agroups[g].forEach(function(o){
          html.push('<a class="hn-link hn-audio" data-idx="' + o.i + '">🔊 ' + esc(o.t.title) + '</a>');
        });
      });
      html.push('<div class="album-card"><div class="t">《大圆满前行》有声书（226 集）</div>'
        + '<div class="d">嘎玛仁波切译 · 昌列寺收录。因音频体积较大，点击前往昌列寺官网在线收听。</div>'
        + '<a href="' + AUDIO_ALBUM + '" target="_blank" rel="noopener">前往昌列寺收听 ↗</a></div>');
    } else {
      walkBlock(node, dirName, 0, '').forEach(function(x){ html.push(x); });
    }
    html.push('</section>');
  });
  // 顶层独立页面（如「更新日志」）作为末位板块，与目录板块保持一致的视觉层级
  (TREE.children || []).forEach(function(c){
    if (c.type === 'page' && !c.is_index){
      html.push('<section class="hn-sec">');
      html.push('<h2 class="hn-sec-title">📝 ' + esc(c.title) + '</h2>');
      html.push('<p class="hn-desc">记录网站历次版本更新的关键内容，点击查看发版历史。</p>');
      html.push('<a class="hn-link" data-page="' + esc(c.slug) + '">' + esc(c.title) + '</a>');
      html.push('</section>');
    }
  });
  return '<div class="home-nav">' + html.join('') + '</div>';
}

// ---- 目录 landing 页：先展示直接子栏目卡片，再展示直属文章 ----
function renderDirChildren(dirSlug){
  var dirPath = dirSlug.replace(/\/index$/, '');
  var prefix = dirPath + '/';
  // 直接子目录：收集所有 slug 以 prefix 开头、且下一段目录名不同的页面，去重得到子目录名
  var subDirMap = {};
  PAGES.forEach(function(p){
    if (p.slug.indexOf(prefix) !== 0) return;
    var rest = p.slug.slice(prefix.length);
    var slashIdx = rest.indexOf('/');
    var dirName = slashIdx >= 0 ? rest.substring(0, slashIdx) : null;
    if (dirName) subDirMap[dirName] = true;
  });
  var subDirs = Object.keys(subDirMap).sort();
  // 直属文章：slug = dirSlug/文章名（文章名不含 /）
  var items = [];
  PAGES.forEach(function(p){
    if (p.is_index) return;
    if (p.slug.indexOf(prefix) !== 0) return;
    var rest = p.slug.slice(prefix.length);
    if (rest.indexOf('/') === -1){
      var hasAudio = p.html.indexOf('play-btn') >= 0;
      items.push('<a class="hn-link" data-page="' + esc(p.slug) + '">'
        + esc(p.title) + (hasAudio ? ' 🔊' : '') + '</a>');
    }
  });
  var html = '';
  if (subDirs.length){
    html += '<div class="dir-children"><div class="audio-list-title">子栏目（' + subDirs.length + ' 个）</div>';
    subDirs.forEach(function(d){
      var target = firstPageUnder(dirPath + '/' + d);
      if (target){
        html += '<a class="hn-link" data-page="' + esc(target) + '">📁 ' + esc(d) + '</a>';
      }
    });
    html += '</div>';
  }
  if (items.length){
    html += '<div class="dir-children"><div class="audio-list-title">本目录文章（' + items.length + ' 篇）</div>'
      + items.join('') + '</div>';
  }
  return html;
}

// ---- 音频资源页：按文件夹层级自动生成索引列表（folderKey=null 显示全部；否则显示该文件夹及其子文件夹音频）----
function renderAudioListByFolder(folderKey){
  if (!AUDIO_TRACKS.length) return '';
  var matched = [];
  AUDIO_TRACKS.forEach(function(t, i){
    var f = t.folder || '';
    if (!folderKey) matched.push({t: t, i: i, f: f});
    else if (f === folderKey || f.indexOf(folderKey + '/') === 0) matched.push({t: t, i: i, f: f});
  });
  if (!matched.length) return '';
  // 按 folderKey 下的直接子文件夹分组（同文件夹内的归为一组，保证层级清晰）
  var groups = {};
  matched.forEach(function(o){
    var rel = o.f;
    var sub = (folderKey && rel.indexOf(folderKey + '/') === 0) ? rel.slice(folderKey.length + 1) : rel;
    var g = (sub.indexOf('/') >= 0) ? sub.slice(0, sub.indexOf('/')) : '';
    (groups[g] = groups[g] || []).push(o);
  });
  var total = matched.length;
  var title = folderKey
    ? ('「' + cleanDirName(folderKey.split('/').pop()) + '」音频（' + total + ' 篇）')
    : ('全部音频（' + total + ' 篇）');
  var html = '<div class="audio-list"><div class="audio-list-title">' + title + '</div>'
    + '<p class="audio-note">因为服务器在国外，缓冲需要时间，请耐心等一会儿。</p>';
  var keys = Object.keys(groups);
  keys.sort(function(a, b){ if (a === '') return -1; if (b === '') return 1; return a < b ? -1 : 1; });
  keys.forEach(function(g){
    if (g) html += '<div class="audio-group-title">' + esc(cleanDirName(g)) + '</div>';
    groups[g].forEach(function(o){
      html += '<a class="hn-link hn-audio" data-idx="' + o.i + '">🔊 ' + esc(o.t.title) + '</a>';
    });
  });
  html += '</div>';
  return html;
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
// iOS 锁屏控制要求 <audio> 元素在 DOM 中，故用 createElement + appendChild，而非 new Audio()
var playerAudio = document.createElement('audio');
playerAudio.preload = 'metadata';   // iOS 需预加载元数据才能在锁屏显示标题/时长
// iOS：允许内联播放，后台/锁屏时保持播放并启用 Media Session 锁屏控制
try{ playerAudio.playsInline = true; playerAudio.setAttribute('playsinline', ''); }catch(e){}
playerAudio.style.display = 'none';
document.body.appendChild(playerAudio);
var curIdx = -1;
var SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];   // 倍速预设档位
var speedIdx = 2;                              // 默认 1x

// ---- 播放模式：顺序 / 逆序 / 随机 / 单曲循环 ----
var PLAY_MODES = ['顺序', '逆序', '随机', '单曲'];
var PLAY_ICONS = { '顺序':'🔁', '逆序':'🔄', '随机':'🔀', '单曲':'🔂' };
var playMode = 0;
function curMode(){ return PLAY_MODES[playMode]; }
// 自动连播时计算的下一首（wrap=false：到边界即停止；单曲循环返回当前以重播）
function autoNext(cur){
  var n = AUDIO_TRACKS.length; if (n === 0) return -1;
  if (curMode() === '单曲') return cur;
  if (curMode() === '随机'){ var r = cur; while (n > 1 && r === cur) r = Math.floor(Math.random() * n); return r; }
  if (curMode() === '逆序'){ var p = cur - 1; return p >= 0 ? p : -1; }
  var q = cur + 1; return q < n ? q : -1;            // 顺序
}
// 手动上一首 / 下一首（始终在列表内循环，便于连续切歌；逆序模式方向相反）
function manualNext(cur){
  var n = AUDIO_TRACKS.length; if (n === 0) return -1;
  if (curMode() === '逆序'){ var p = cur - 1; return p >= 0 ? p : n - 1; }
  if (curMode() === '随机'){ var r = cur; while (n > 1 && r === cur) r = Math.floor(Math.random() * n); return r; }
  var q = cur + 1; return q < n ? q : 0;            // 顺序 / 单曲 均向前
}
function manualPrev(cur){
  var n = AUDIO_TRACKS.length; if (n === 0) return -1;
  if (curMode() === '逆序'){ var q = cur + 1; return q < n ? q : 0; }
  if (curMode() === '随机'){ var r = cur; while (n > 1 && r === cur) r = Math.floor(Math.random() * n); return r; }
  var p = cur - 1; return p >= 0 ? p : n - 1;       // 顺序 / 单曲 均向后
}
function updateModeBtn(){
  var b = document.getElementById('pMode');
  if (b) b.textContent = PLAY_ICONS[curMode()] + ' ' + curMode();
}

function fmtTime(s){
  if (!isFinite(s) || s < 0) s = 0;
  var m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m + ':' + (sec < 10 ? '0' : '') + sec;
}

function showPlayer(){
  document.getElementById('player').classList.add('show');
  document.getElementById('playerMini').classList.remove('show');
  refreshLaunch();
}
function hidePlayer(){
  document.getElementById('player').classList.remove('show');
  document.getElementById('playerMini').classList.remove('show');
  refreshLaunch();
}
// 折叠为底部迷你条：整屏播放器收起，音频继续后台播放
function minimizePlayer(){
  document.getElementById('player').classList.remove('show');
  document.getElementById('playerMini').classList.add('show');
  updateMini();
  refreshLaunch();
}
// 悬浮「🎧 播放器」按钮：播放器或迷你条显示时隐藏，否则显示
function refreshLaunch(){
  var pShown = document.getElementById('player').classList.contains('show');
  var mShown = document.getElementById('playerMini').classList.contains('show');
  document.getElementById('playerLaunch').style.display = (pShown || mShown) ? 'none' : '';
}
// 同步迷你条上的音频名与播放/暂停图标
function updateMini(){
  var name = (curIdx >= 0 && AUDIO_TRACKS[curIdx]) ? AUDIO_TRACKS[curIdx].title : '暂未播放';
  document.getElementById('pmName').textContent = name;
  document.getElementById('pmPlay').textContent = playerAudio.paused ? '▶' : '⏸';
}

// ---- 设置 Media Session 元信息（iOS 锁屏显示标题/封面/控制）----
// 需在 playTrack 和 play 事件中都调用：iOS 有时要在音频真正开始播放后才能识别
function setMediaMeta(t){
  if (!('mediaSession' in navigator) || !t) return;
  try{
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title,
      artist: '龙的传人｜Longchen Nyingtik',
      album: (t.folder || '音频资源').replace(/^\d+\.\s*/, ''),
      artwork: [{ src: new URL('assets/cover.png', location.href).href, sizes: '512x512', type: 'image/png' }]
    });
    navigator.mediaSession.playbackState = 'playing';
  }catch(e){}
}

function playTrack(idx){
  if (idx < 0 || idx >= AUDIO_TRACKS.length) return;
  curIdx = idx;
  var t = AUDIO_TRACKS[idx];
  playerAudio.src = t.src;
  playerAudio.playbackRate = SPEEDS[speedIdx];
  playerAudio.play();
  document.getElementById('pStatusText').innerHTML = '正在播放：<b>' + esc(t.title) + '</b>';
  document.getElementById('pPlay').textContent = '⏸';
  showPlayer();
  renderPlist();
  updatePlayBtns();
  updateMini();
  setMediaMeta(t);
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
    b.textContent = active ? '⏸ 播放中' : '▶ 播放';
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
  if (curIdx < 0){ if (AUDIO_TRACKS.length) playTrack(0); return; }
  var n = manualNext(curIdx); if (n >= 0) playTrack(n);
};
document.getElementById('pPrev').onclick = function(){
  if (curIdx < 0){ if (AUDIO_TRACKS.length) playTrack(0); return; }
  var n = manualPrev(curIdx); if (n >= 0) playTrack(n);
};
// 快退 15 秒
document.getElementById('pBack').onclick = function(){
  if (curIdx < 0) return;
  playerAudio.currentTime = Math.max(0, playerAudio.currentTime - 15);
};
// 快进 15 秒
document.getElementById('pFwd').onclick = function(){
  if (curIdx < 0 || !playerAudio.duration) return;
  playerAudio.currentTime = Math.min(playerAudio.duration, playerAudio.currentTime + 15);
};

playerAudio.addEventListener('timeupdate', function(){
  var dur = playerAudio.duration || 0;
  var pct = dur ? (playerAudio.currentTime / dur * 100) : 0;
  document.getElementById('pFill').style.width = pct + '%';
  document.getElementById('pThumb').style.left = pct + '%';
  document.getElementById('pTimeCur').textContent = fmtTime(playerAudio.currentTime);
  document.getElementById('pTimeDur').textContent = fmtTime(dur);
  document.getElementById('pmFill').style.width = pct + '%';
});
playerAudio.addEventListener('ended', function(){
  // 依据当前播放模式自动连播：单曲循环重播本曲；顺序到末曲停止；逆序到首曲停止；随机取下一首
  if (curMode() === '单曲'){ playerAudio.currentTime = 0; playerAudio.play(); return; }
  var n = autoNext(curIdx);
  if (n >= 0) playTrack(n);
  else { document.getElementById('pPlay').textContent = '▶'; updateMini(); }
});
playerAudio.addEventListener('play', function(){
  document.getElementById('pPlay').textContent = '⏸'; updateMini();
  // iOS：音频真正开始播放时重新设置 Media Session 元信息，确保锁屏显示
  if (curIdx >= 0 && AUDIO_TRACKS[curIdx]) setMediaMeta(AUDIO_TRACKS[curIdx]);
  if ('mediaSession' in navigator){ try{ navigator.mediaSession.playbackState = 'playing'; }catch(e){} }
});
playerAudio.addEventListener('pause', function(){
  document.getElementById('pPlay').textContent = '▶'; updateMini();
  if ('mediaSession' in navigator){ try{ navigator.mediaSession.playbackState = 'paused'; }catch(e){} }
});

// ---- 锁屏播放控制（Media Session API）：手机锁屏/通知栏显示播放/暂停/上一首/下一首/快进快退按钮 ----
if ('mediaSession' in navigator){
  try{
    navigator.mediaSession.setActionHandler('play', function(){ if (curIdx < 0 && AUDIO_TRACKS.length) playTrack(0); else playerAudio.play(); });
    navigator.mediaSession.setActionHandler('pause', function(){ playerAudio.pause(); });
    navigator.mediaSession.setActionHandler('previoustrack', function(){ if (curIdx >= 0) playTrack(manualPrev(curIdx)); });
    navigator.mediaSession.setActionHandler('nexttrack', function(){ if (curIdx >= 0) playTrack(manualNext(curIdx)); });
    navigator.mediaSession.setActionHandler('seekbackward', function(){ if (curIdx >= 0) playerAudio.currentTime = Math.max(0, playerAudio.currentTime - 15); });
    navigator.mediaSession.setActionHandler('seekforward', function(){ if (curIdx >= 0 && playerAudio.duration) playerAudio.currentTime = Math.min(playerAudio.duration, playerAudio.currentTime + 15); });
  }catch(e){}
}
// 锁屏进度条：timeupdate 时同步 position state，部分浏览器锁屏显示进度
playerAudio.addEventListener('loadedmetadata', function(){
  if ('mediaSession' in navigator && playerAudio.duration){
    try{ navigator.mediaSession.setPositionState({ duration: playerAudio.duration, playbackRate: playerAudio.playbackRate, position: playerAudio.currentTime }); }catch(e){}
  }
});
playerAudio.addEventListener('timeupdate', function(){
  if ('mediaSession' in navigator && playerAudio.duration && !playerAudio.paused){
    try{ navigator.mediaSession.setPositionState({ duration: playerAudio.duration, playbackRate: playerAudio.playbackRate, position: playerAudio.currentTime }); }catch(e){}
  }
});

// 进度条：支持点击与拖动跳转（progEl 缺省为整屏播放器进度条）
var pProg = document.getElementById('pProgress');
var pDragging = false;
var pDragEl = null;
function seekFromEvent(ev, progEl){
  var el = progEl || pDragEl || pProg;
  if (curIdx < 0 || !playerAudio.duration) return;
  var rect = el.getBoundingClientRect();
  var x = (ev.touches && ev.touches.length) ? ev.touches[0].clientX : ev.clientX;
  var ratio = Math.min(1, Math.max(0, (x - rect.left) / rect.width));
  playerAudio.currentTime = ratio * playerAudio.duration;
  // 立即同步两端时间数字（拖动时反馈更顺滑）
  document.getElementById('pTimeCur').textContent = fmtTime(playerAudio.currentTime);
  document.getElementById('pTimeDur').textContent = fmtTime(playerAudio.duration);
}
pProg.addEventListener('mousedown', function(ev){ pDragging = true; pDragEl = pProg; seekFromEvent(ev); });
pProg.addEventListener('touchstart', function(ev){ pDragging = true; pDragEl = pProg; seekFromEvent(ev); }, {passive:true});
window.addEventListener('mousemove', function(ev){ if (pDragging) seekFromEvent(ev); });
window.addEventListener('touchmove', function(ev){ if (pDragging) seekFromEvent(ev); }, {passive:true});
window.addEventListener('mouseup', function(){ pDragging = false; pDragEl = null; });
window.addEventListener('touchend', function(){ pDragging = false; pDragEl = null; });

// 播放列表（内嵌于半屏播放器顶部）
function renderPlist(){
  var box = document.getElementById('pPlaylist');
  var arr = AUDIO_TRACKS.map(function(t, i){
    var playing = (i === curIdx);
    return '<div class="pl-item' + (playing ? ' playing' : '') + '" data-idx="' + i + '">'
      + '<span class="pl-idx">' + (i + 1) + '</span>'
      + '<span class="pl-dot"></span>'
      + '<span class="pl-title">' + esc(t.title) + '</span></div>';
  });
  box.innerHTML = arr.join('');
  box.querySelectorAll('.pl-item').forEach(function(it){
    it.onclick = function(ev){
      playTrack(parseInt(it.dataset.idx, 10));
    };
  });
}
// 播放列表：点击展开 / 收起（默认收起）
document.getElementById('pPlToggle').onclick = function(){
  var p = document.getElementById('player');
  var open = p.classList.toggle('pl-open');
  document.getElementById('pPlaylist').classList.toggle('open', open);
  document.getElementById('pPlHint').textContent = open ? '点击收起播放列表' : '点击展开播放列表';
};
// 关闭叉号：若正在播放（已选曲目）则折叠为底部迷你条，音频继续后台播放；否则完全关闭
document.getElementById('pClose').onclick = function(){
  if (curIdx >= 0) minimizePlayer();
  else hidePlayer();
};
// 播放模式切换：点击在 顺序 / 逆序 / 随机 / 单曲循环 间循环，并刷新按钮文案
document.getElementById('pMode').onclick = function(){
  playMode = (playMode + 1) % PLAY_MODES.length;
  updateModeBtn();
};
// ---- 播放速度（倍速）：点击按钮弹出菜单，选中档位实时生效 ----
function applySpeed(){
  var r = SPEEDS[speedIdx];
  playerAudio.playbackRate = r;                 // 实时改变音频播放速率
  var pb = document.getElementById('pSpeed');
  if (pb) pb.textContent = '倍速 ' + r + 'x';    // 按钮显示当前倍速值
  var mb = document.getElementById('pmSpeed');
  if (mb) mb.textContent = r + 'x';
  document.querySelectorAll('.sp-item').forEach(function(el){
    el.classList.toggle('active', parseFloat(el.getAttribute('data-rate')) === r);
  });
}
function closeAllSpeedMenus(){
  document.querySelectorAll('.p-speed-menu, .pm-speed-menu').forEach(function(m){ m.style.display = 'none'; });
}
document.getElementById('pSpeed').onclick = function(e){
  e.stopPropagation();
  var menu = document.getElementById('pSpeedMenu');
  var open = menu.style.display === 'block';
  closeAllSpeedMenus();
  if (!open) menu.style.display = 'block';
};
document.getElementById('pmSpeed').onclick = function(e){
  e.stopPropagation();
  var menu = document.getElementById('pmSpeedMenu');
  var open = menu.style.display === 'block';
  closeAllSpeedMenus();
  if (!open) menu.style.display = 'block';
};
document.querySelectorAll('.p-speed-menu .sp-item, .pm-speed-menu .sp-item').forEach(function(el){
  el.addEventListener('click', function(e){
    e.stopPropagation();
    var i = SPEEDS.indexOf(parseFloat(el.getAttribute('data-rate')));
    if (i >= 0) speedIdx = i;
    applySpeed();
    closeAllSpeedMenus();
  });
});
document.addEventListener('click', closeAllSpeedMenus);
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeAllSpeedMenus(); });
applySpeed();   // 初始化按钮文案与默认高亮
// 悬浮按钮：打开播放器
document.getElementById('playerLaunch').onclick = function(){
  document.getElementById('player').classList.add('show');
  document.getElementById('playerMini').classList.remove('show');
  refreshLaunch();
};
// 迷你条：播放/暂停
document.getElementById('pmPlay').onclick = function(){
  if (curIdx < 0 && AUDIO_TRACKS.length) playTrack(0);
  else if (playerAudio.paused) playerAudio.play();
  else playerAudio.pause();
};
// 迷你条：展开回整屏播放器
document.getElementById('pmExpand').onclick = showPlayer;
// 迷你条进度条：点击跳转
var pmProg = document.getElementById('pmProgress');
pmProg.addEventListener('mousedown', function(ev){ seekFromEvent(ev, pmProg); });
pmProg.addEventListener('touchstart', function(ev){ seekFromEvent(ev, pmProg); }, {passive:true});

// 顶栏品牌点击返回主页
document.getElementById('brandHome').onclick = function(){ show('index'); };

function esc(s){ var d=document.createElement('div'); d.textContent = s==null?'':String(s); return d.innerHTML; }

// ---- 搜索：中文二元分词 + 相关性排序 + 匹配摘要 + 关键词高亮 ----
function tokenize(q){
  var tokens = [];
  var parts = q.toLowerCase().split(/[^a-z0-9\u4e00-\u9fa5]+/).filter(Boolean);
  parts.forEach(function(p){
    if (/^[a-z0-9]+$/.test(p)){ tokens.push(p); }
    else {
      for (var i = 0; i < p.length - 1; i++) tokens.push(p.substring(i, i+2));
      if (p.length === 1) tokens.push(p);
    }
  });
  return tokens;
}
function scorePage(p, tokens, q){
  var title = p.title.toLowerCase();
  var html = p.html.toLowerCase();
  var score = 0;
  if (title.indexOf(q) >= 0) score += 10;
  if (html.indexOf(q) >= 0) score += 5;
  tokens.forEach(function(t){
    if (title.indexOf(t) >= 0) score += 3;
    if (html.indexOf(t) >= 0) score += 1;
  });
  return score;
}
function searchSnippet(p, q){
  var text = p.html.replace(/<[^>]+>/g, '');
  var idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return '';
  var start = Math.max(0, idx - 25);
  var end = Math.min(text.length, idx + q.length + 45);
  return (start > 0 ? '…' : '') + text.substring(start, end) + (end < text.length ? '…' : '');
}
function highlight(text, q){
  if (!q) return text;
  var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
  return text.replace(re, '<mark class="search-hl">$1</mark>');
}
document.getElementById('search').addEventListener('input', function(){
  var q = this.value.trim().toLowerCase();
  if (!q){ renderNav(); return; }
  var nav = document.getElementById('nav');
  var tokens = tokenize(q);
  var results = [];
  PAGES.forEach(function(p){
    if (p.slug === 'index' || p.slug === '更新日志') return; // 排除首页和更新日志
    var s = scorePage(p, tokens, q);
    if (s > 0) results.push({p: p, score: s});
  });
  results.sort(function(a, b){ return b.score - a.score; });
  if (!results.length){
    nav.innerHTML = '<div class="group-label">无匹配结果</div>';
    return;
  }
  var arr = ['<div class="group-label">找到 ' + results.length + ' 条结果</div>'];
  results.forEach(function(r){
    var snip = searchSnippet(r.p, q);
    arr.push('<a class="nav-link search-result" data-slug="' + esc(r.p.slug) + '">'
      + '<span class="sr-title">' + highlight(esc(r.p.title), q) + '</span>'
      + (snip ? '<span class="sr-snip">' + highlight(esc(snip), q) + '</span>' : '')
      + '</a>');
  });
  nav.innerHTML = arr.join('');
  nav.querySelectorAll('.search-result').forEach(function(a){
    a.onclick = function(){ show(a.dataset.slug); closeSidebar(); };
  });
});

// ---- 侧栏开合 ----
function closeSidebar(){
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('show');
}
document.getElementById('menuBtn').onclick = function(){
  var s = document.getElementById('sidebar'), o = document.getElementById('sidebarOverlay');
  var open = s.classList.toggle('open');
  o.classList.toggle('show', open);
};
// 关闭按钮 & 点击菜单外空白区域均可关闭抽屉
document.getElementById('sidebarClose').onclick = function(){ closeSidebar(); };
document.getElementById('sidebarOverlay').onclick = function(){ closeSidebar(); };

// ---- 初始化 ----
renderNav();
updateModeBtn();
var home = TREE.children && TREE.children.find(function(c){ return c.is_index; });
show(home ? home.slug : PAGES[0].slug);

// ---- 网页打开次数统计（仅作者/管理员可见）----
// 说明：纯静态站无法做登录鉴权。此处用免注册的公开计数 API 累加打开次数，
// 但仅在 URL 带管理员密钥（如 ?admin=longchen-admin）时才显示数字；
// 首次用密钥访问后会记住（localStorage），之后直接可见。密钥请自行修改。
var ADMIN_SECRET = 'longchen-admin';
var HIT_NS = 'longchen-nyingtik', HIT_KEY = 'page-views';
function isAdmin(){
  try {
    if (new URLSearchParams(location.search).get('admin') === ADMIN_SECRET){
      localStorage.setItem('longchen-admin', '1');
      return true;
    }
    return localStorage.getItem('longchen-admin') === '1';
  } catch(e){ return false; }
}
function trackVisit(){
  // 每次打开页面异步 +1（不阻塞页面；统计服务不可达时静默失败）
  try {
    fetch('https://api.countapi.xyz/hit/' + HIT_NS + '/' + HIT_KEY, {cache:'no-store'}).catch(function(){});
  } catch(e){}
}
function showHitStat(){
  var box = document.getElementById('hitStat');
  if (!box) return;
  box.style.display = 'inline-block';
  box.textContent = '网页打开次数：加载中…';
  fetch('https://api.countapi.xyz/get/' + HIT_NS + '/' + HIT_KEY, {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(d){ box.textContent = '网页打开次数：' + (d.value != null ? d.value : 0); })
    .catch(function(){ box.textContent = '网页打开次数：—（统计服务暂不可达）'; });
}
if (isAdmin()) showHitStat();
trackVisit();
</script>
<footer class="site-footer">
  <div class="footer-inner">
    <span class="footer-copy">© 2026 龙的传人｜Longchen Nyingtik · 个人学习整理，非商业用途</span>
    <span class="footer-build">构建于 @@BUILD_TIME@@</span>
  </div>
</footer>
<button class="back-top" id="backTop" title="回到顶部">↑</button>
<script>
document.getElementById('backTop').onclick = function(){ window.scrollTo({top:0, behavior:'smooth'}); };
window.addEventListener('scroll', function(){
  document.getElementById('backTop').style.opacity = window.scrollY > 300 ? '1' : '0';
});
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

    # 为每个含 mp3 但缺少 index 的音频文件夹，自动生成索引页（构建期合成，不写回 content/，零维护）
    # 这样「2. 上师法音 / 2.1 仪轨与经文 / 2.2 圣号与明咒」等只有音频没有 md 的文件夹
    # 也能进入导航树并拥有可浏览的对应索引页，保证所有文件夹内容都能通过折叠导航访问。
    _audio_folders = set()
    for _f in LOCAL_AUDIO:
        _fol = audio_folder_rel(_f)
        if not _fol:
            continue
        _segs = _fol.split("/")
        for _d in range(1, len(_segs) + 1):
            _audio_folders.add("/".join(_segs[:_d]))
    _existing_audio_index = set(p["slug"] for p in pages
                                if p["is_index"] and p["slug"].startswith("音频资源/"))
    for _key in sorted(_audio_folders):
        _slug = "音频资源/" + _key + "/index"
        if _slug in _existing_audio_index:
            continue
        pages.append({
            "slug": _slug,
            "title": clean_dir_name(_key.split("/")[-1]),
            "rel": _slug + ".md",
            "dir": "音频资源/" + _key,
            "is_index": True,
            "meta": {},
            "html": "",
        })

    tree = build_tree(pages)

    # 首页「本次更新内容」区块：读取独立内容源文件并渲染（仅用户资料，不含技术调整）
    home_update_html = ""
    home_update_date = ""
    upd_path = os.path.join(CONTENT_DIR, "本次更新内容.md")
    if os.path.exists(upd_path):
        upd_txt = open(upd_path, encoding="utf-8").read()
        upd_meta, upd_body = parse_frontmatter(upd_txt)
        home_update_html = md_to_html(upd_body)
        # 公告区标题日期：优先取 frontmatter 的 date 字段（如 2026-08-18），无则回退空串
        home_update_date = (upd_meta.get("date") or "").strip()

    site_title = "龙的传人｜Longchen Nyingtik"
    for p in pages:
        if p["slug"] == "index" and p["meta"].get("title"):
            site_title = p["meta"]["title"]

    # 生成音频轨道列表：以本地 mp3 为唯一来源，每条 mp3 仅收录一次（避免聚合页/文章页重复引用产生重复轨道）
    # title = mp3 文件名（去 .mp3，即音频真实名称，不再误用包含引用的页面标题）；slug = 引用它的文章页（优先非聚合页）
    ref_map = {}  # fname -> [(slug, page_title), ...]
    for p in pages:
        for m in re.finditer(r'data-audio="([^"]+)"', p["html"]):
            fname = m.group(1)
            ref_map.setdefault(fname, []).append((p["slug"], p["title"]))

    # 计算某音频所属分组（其父文件夹名），用于音频资源页分组展示
    def audio_group(fname):
        path = LOCAL_AUDIO.get(fname)
        if not path:
            return ""
        rel = os.path.relpath(os.path.dirname(path), CONTENT_DIR)
        parts = [x for x in rel.split(os.sep) if x and x != "."]
        return parts[-1] if parts else ""

    AGG_PREFIXES = ("音频资源",)
    AGG_SLUGS = ("本次更新内容",)
    audio_tracks = []
    for fname in sorted(LOCAL_AUDIO.keys()):
        title = fname[:-4] if fname.lower().endswith(".mp3") else fname
        refs = ref_map.get(fname, [])
        slug = ""
        for s, _pt in refs:
            if s and s not in AGG_SLUGS and not s.startswith(AGG_PREFIXES):
                slug = s
                break
        if not slug and refs:
            slug = refs[0][0]
        t = {
            "title": title,
            "slug": slug,
            "src": "audio/" + quote(fname),
            "file": fname,
        }
        t["group"] = audio_group(fname)
        t["folder"] = audio_folder_rel(fname)
        audio_tracks.append(t)


    html_out = PAGE_TEMPLATE
    html_out = html_out.replace("@@SITE_TITLE_JSON@@", json.dumps(site_title, ensure_ascii=False))
    html_out = html_out.replace("@@AUDIO_ALBUM_JSON@@", json.dumps(CHANGLESI_ALBUM, ensure_ascii=False))
    html_out = html_out.replace("@@AUDIO_TRACKS_JSON@@", json.dumps(audio_tracks, ensure_ascii=False))
    html_out = html_out.replace("@@PAGES_JSON@@", json.dumps(pages, ensure_ascii=False))
    html_out = html_out.replace("@@TREE_JSON@@", json.dumps(tree, ensure_ascii=False))
    html_out = html_out.replace("@@HOME_UPDATE_JSON@@", json.dumps(home_update_html, ensure_ascii=False))
    html_out = html_out.replace("@@HOME_UPDATE_DATE@@", home_update_date)
    html_out = html_out.replace("@@SITE_TITLE@@", site_title)
    html_out = html_out.replace("@@BUILD_TIME@@", time.strftime("%Y-%m-%d %H:%M"))

    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    # 生成 robots.txt：禁止国内搜索引擎收录（降低合规风险），允许国外搜索引擎收录（利益有缘人）
    robots_path = os.path.join(DIST_DIR, "robots.txt")
    with open(robots_path, "w", encoding="utf-8") as f:
        f.write(
            "# 禁止国内搜索引擎\n"
            "User-agent: Baiduspider\n"
            "Disallow: /\n\n"
            "User-agent: Baiduspider-news\n"
            "Disallow: /\n\n"
            "User-agent: Baiduspider-favo\n"
            "Disallow: /\n\n"
            "User-agent: Sogou spider\n"
            "Disallow: /\n\n"
            "User-agent: Sogou web spider\n"
            "Disallow: /\n\n"
            "User-agent: 360Spider\n"
            "Disallow: /\n\n"
            "User-agent: 360spider\n"
            "Disallow: /\n\n"
            "User-agent: Yisouspider\n"
            "Disallow: /\n\n"
            "User-agent: Bytespider\n"
            "Disallow: /\n\n"
            "User-agent: Bytespider-image\n"
            "Disallow: /\n\n"
            "# 允许国外搜索引擎（Google/Bing/DuckDuckGo/Yandex 等）\n"
            "User-agent: *\n"
            "Allow: /\n"
        )

    # 复制本地音频到 dist/audio/（覆盖式复制；旧残留由构建前 shell rm 清理）
    audio_dir = os.path.join(DIST_DIR, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    copied = 0
    for fname, src in LOCAL_AUDIO.items():
        shutil.copy2(src, os.path.join(audio_dir, fname))
        copied += 1

    # 复制 content/ 下的图片到 dist/assets/（保持相对目录结构，支持 Obsidian ![[image.png]] 嵌入）
    IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")
    assets_dir = os.path.join(DIST_DIR, "assets")
    img_copied = 0
    for _dp, _dn, _fn in os.walk(CONTENT_DIR):
        for f in _fn:
            if f.lower().endswith(IMG_EXT):
                src = os.path.join(_dp, f)
                rel = os.path.relpath(src, CONTENT_DIR)
                dst = os.path.join(assets_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                img_copied += 1

    # 生成锁屏封面图 assets/cover.png（Media Session artwork 用）
    cover_path = os.path.join(assets_dir, "cover.png")
    gen_cover_png(cover_path)
    print("封面图生成: %s" % cover_path)

    # 复制 content/sw.js 到 dist/ 根（Service Worker：音频离线缓存 + 页面更新策略）
    sw_src = os.path.join(CONTENT_DIR, "sw.js")
    if os.path.exists(sw_src):
        shutil.copy2(sw_src, os.path.join(DIST_DIR, "sw.js"))

    # 复制 Cloudflare Pages 的 _headers（缓存/安全策略）到 dist/ 根；仓库无此文件时跳过
    _headers_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflare", "_headers")
    if os.path.exists(_headers_src):
        shutil.copy2(_headers_src, os.path.join(DIST_DIR, "_headers"))

    print("已生成: %s" % out_path)
    print("文章数: %d" % len(pages))
    print("本地音频复制: %d 个" % copied)
    print("图片复制: %d 个" % img_copied)
    print("HTML 大小: %.1f KB" % (os.path.getsize(out_path) / 1024.0))


# ---- 生成锁屏封面图（纯标准库手写 PNG）：深红底 + 金色同心圆（坛城意象）----
# 用途：Media Session artwork，iOS/Android 锁屏界面显示播放控制时需要 PNG/JPG 封面
def gen_cover_png(path, size=512):
    W = H = size
    cx = cy = W / 2.0
    bg = (138, 31, 28)      # 深红 #8a1f1c
    gold = (217, 184, 106)  # 金 #d9b86a
    gold2 = (245, 222, 160) # 淡金
    rings = [(28, gold2, 7), (58, gold, 6), (95, gold2, 5), (132, gold, 6), (172, gold2, 4), (208, gold, 5), (244, gold2, 3)]
    rows = []
    for y in range(H):
        row = bytearray([0])  # PNG 每行首字节为 filter type（0 = None）
        for x in range(W):
            dx = x - cx
            dy = y - cy
            r = (dx * dx + dy * dy) ** 0.5
            color = bg
            for rr, c, w in rings:
                if abs(r - rr) < w:
                    color = c
                    break
            row += bytes(color) + b'\xff'
        rows.append(bytes(row))
    raw = b''.join(rows)

    def chunk(typ, data):
        c = struct.pack('>I', len(data)) + typ + data
        c += struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff)
        return c

    ihdr = struct.pack('>IIBBBBB', W, H, 8, 6, 0, 0, 0)  # 8bit RGBA
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', ihdr)
           + chunk(b'IDAT', zlib.compress(raw, 9))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


if __name__ == "__main__":
    main()
