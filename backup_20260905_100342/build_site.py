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
import datetime

# 自然排序：按文件名开头的数字大小排序，解决"10."排在"2."前面的问题
def natural_sort_key(s):
    parts = re.split(r'(\d+)', s)
    return [int(p) if p.isdigit() else p.lower() for p in parts]
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
            _dn[:] = [d for d in _dn if not is_excluded_dir(d)]
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

        # 标题（为 h2/h3 添加 id，用于目录跳转）
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_list(); flush_quote()
            lvl = len(m.group(1))
            title_text = m.group(2)
            title_html = inline(title_text)
            if lvl in (2, 3):
                # 生成 id：去除标点、空格转连字符
                heading_id = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", title_text).strip("-")
                out.append('<h%d id="toc-%s">%s</h%d>' % (lvl, heading_id, title_html, lvl))
            else:
                out.append("<h%d>%s</h%d>" % (lvl, title_html, lvl))
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
def is_excluded_dir(d):
    """判断目录是否应该被排除（隐藏目录、不推送目录、备份目录）"""
    return d.startswith(".") or "不推送" in d or "_backup" in d or d.endswith("_backup")

def discover_pages():
    global LOCAL_AUDIO
    LOCAL_AUDIO = {}
    # 第一遍：先扫描收集所有本地音频（必须在解析 md 之前完成）
    # 排除规则：隐藏目录（.开头）、「不推送」目录、备份目录
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not is_excluded_dir(d)]
        for f in files:
            if f.lower().endswith((".mp3", ".m4a", ".wav")):
                LOCAL_AUDIO[f] = os.path.join(dirpath, f)
    # 第二遍：解析 md
    pages = []
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not is_excluded_dir(d)]
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
            # draft: true 的文章为草稿，不发布
            if str(meta.get("draft", "")).lower() in ("true", "yes", "1"):
                continue
            fallback = f[:-3].strip()
            title = meta.get("title") or fallback or rel
            title = title.strip()  # 规则：所有文章标题必须跟Obsidian文件名一模一样，不擅自改动（只去前后空格）
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
    # 排除标记为 hide_from_nav 的页面（如法音详情页）
    pages = [p for p in pages if not p.get("hide_from_nav")]

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

/* 访问密码保护遮罩层 */
.access-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:9999;display:flex;align-items:center;justify-content:center;padding:1rem}
.access-box{background:var(--surface);border-radius:16px;padding:2.5rem 2rem;max-width:420px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.3)}
.access-box .access-icon{font-size:3rem;margin-bottom:1rem}
.access-box h2{font-size:1.4rem;color:var(--ink);margin-bottom:.5rem;font-weight:700}
.access-box .access-desc{font-size:.9rem;color:var(--ink-soft);margin-bottom:1.5rem;line-height:1.6}
.access-box input[type="password"]{width:100%;padding:.8rem 1rem;border:2px solid var(--line);border-radius:10px;font-size:1rem;font-family:inherit;background:var(--surface-soft);color:var(--ink);box-sizing:border-box;margin-bottom:1rem;transition:border-color .2s}
.access-box input[type="password"]:focus{outline:none;border-color:var(--accent)}
.access-box .access-btn{width:100%;padding:.8rem;background:var(--accent);color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity .2s}
.access-box .access-btn:hover{opacity:.9}
.access-box .access-error{color:#c0392b;font-size:.85rem;margin-top:.8rem;min-height:1.2rem}
.access-box .access-footer{margin-top:1.2rem;font-size:.75rem;color:var(--ink-faint);line-height:1.5}

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

/* 访问密码保护遮罩层 */
.access-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:9999;display:flex;align-items:center;justify-content:center;padding:1rem}
.access-box{background:var(--surface);border-radius:16px;padding:2.5rem 2rem;max-width:420px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.3)}
.access-box .access-icon{font-size:3rem;margin-bottom:1rem}
.access-box h2{font-size:1.4rem;color:var(--ink);margin-bottom:.5rem;font-weight:700}
.access-box .access-desc{font-size:.9rem;color:var(--ink-soft);margin-bottom:1.5rem;line-height:1.6}
.access-box input[type="password"]{width:100%;padding:.8rem 1rem;border:2px solid var(--line);border-radius:10px;font-size:1rem;font-family:inherit;background:var(--surface-soft);color:var(--ink);box-sizing:border-box;margin-bottom:1rem;transition:border-color .2s}
.access-box input[type="password"]:focus{outline:none;border-color:var(--accent)}
.access-box .access-btn{width:100%;padding:.8rem;background:var(--accent);color:#fff;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity .2s}
.access-box .access-btn:hover{opacity:.9}
.access-box .access-error{color:#c0392b;font-size:.85rem;margin-top:.8rem;min-height:1.2rem}
.access-box .access-footer{margin-top:1.2rem;font-size:.75rem;color:var(--ink-faint);line-height:1.5}

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
.breadcrumb a.dir-crumb{cursor:pointer}
.breadcrumb a.dir-crumb:active{color:var(--accent)}

/* 目录弹层：手机端点面包屑目录层级时弹出该目录下的文章列表 */
.dir-pop{position:fixed; inset:0; z-index:60; display:none}
.dir-pop.show{display:block}
.dir-pop-mask{position:absolute; inset:0; background:rgba(59,42,34,.35)}
.dir-pop-panel{position:absolute; left:0; right:0; bottom:0; background:var(--surface);
  border-radius:16px 16px 0 0; max-height:72vh; display:flex; flex-direction:column;
  padding-bottom:env(safe-area-inset-bottom,0); box-shadow:0 -8px 30px rgba(59,42,34,.25)}
.dir-pop-head{display:flex; align-items:center; justify-content:space-between; padding:1rem 1.2rem;
  font-weight:600; color:var(--ink); border-bottom:1px solid var(--line); flex:0 0 auto}
.dir-pop-x{border:none; background:none; color:var(--ink-soft); font-size:1.1rem; cursor:pointer; padding:.2rem .4rem}
.dir-pop-body{overflow-y:auto; flex:1}
.dir-pop-item{padding:.95rem 1.2rem; cursor:pointer; color:var(--ink);
  border-bottom:1px solid var(--line); font-size:1rem; line-height:1.4}
.dir-pop-item:active{background:var(--surface-soft)}
.dir-pop-dir{color:var(--accent); font-weight:500; display:flex; justify-content:space-between; align-items:center}
.dir-pop-arrow{color:var(--ink-faint)}
.dir-pop-empty{padding:1.5rem 1.2rem; color:var(--ink-faint); text-align:center}
@media (min-width:761px){
  .dir-pop-panel{left:50%; right:auto; width:420px; transform:translateX(-50%);
    border-radius:16px; bottom:50%; margin-bottom:-40vh}
}

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
.player .p-minimize{border:none; background:none; cursor:pointer; color:var(--ink-soft);
  font-size:1.5rem; width:2.3rem; height:2.3rem; border-radius:8px; line-height:1; margin-left:auto}
.player .p-minimize:hover{background:var(--surface-hover)}
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
.player-launch{position:fixed !important; right:1.1rem; bottom:1.1rem; z-index:41;
  background:var(--accent); color:#fff; border:none; cursor:grab;
  padding:.7rem 1.1rem; border-radius:999px; font-size:.9rem; font-weight:600;
  box-shadow:0 4px 14px rgba(59,42,34,.28); display:flex; align-items:center; gap:.4rem;
  user-select:none;-webkit-user-select:none;touch-action:none; opacity:.75; transition:opacity .2s}
.player-launch:hover{background:var(--accent-soft); opacity:1}
.player-launch:active{cursor:grabbing}
.player-launch.dragging{opacity:.85;box-shadow:0 6px 20px rgba(0,0,0,.4)}
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
.hn-sec-title{font-size:1.25em; font-weight:700; color:var(--ink); margin:0 0 .3rem;
  display:flex; align-items:center; gap:.5rem; letter-spacing:.02em}
.hn-desc{color:var(--ink-faint); font-size:.98em; margin:0 0 .8rem}
.hn-dir{font-size:.82em; color:#9b8475; font-weight:700; letter-spacing:.05em;
  margin:.9rem 0 .35rem}
.hn-dir[data-depth="0"]{margin-top:.5rem; font-size:1.1em; color:#6e1614; font-weight:700}
.hn-dir[data-depth="1"]{margin-top:.6rem; font-size:1.05em; color:#8a1f1c; font-weight:600}
.hn-dir[data-depth="2"]{margin-top:.55rem; font-size:1.0em; color:#b8893b; font-weight:500}
.hn-link{display:flex; align-items:center; gap:.4rem; padding:.42rem .7rem;
  border-radius:8px; color:var(--ink-soft); font-size:1.05em; cursor:pointer;
  border:1px solid transparent; transition:all .15s}
.hn-link:hover{background:var(--surface-hover); color:var(--ink); border-color:var(--line)}
.hn-link::before{content:""; width:5px; height:5px; border-radius:50%;
  background:var(--accent-soft); flex:0 0 5px; opacity:.6}
.hn-link:hover::before{background:var(--accent); opacity:1}
.hn-audio{cursor:pointer}
.hn-link.hn-audio{font-size:1.05em; padding:.6rem .9rem}
.hn-audio.playing{color:var(--accent); font-weight:600; background:var(--surface-soft); border-color:var(--accent-soft)}
.hn-audio.playing::before{background:var(--accent); opacity:1}
.audio-list{margin-top:.5rem}
.audio-list-title{font-size:.95em; color:var(--ink-faint); margin:1.2rem 0 .5rem; font-weight:600}
.audio-group{margin:.8rem 0; border:1px solid var(--line); border-radius:10px; overflow:hidden; background:var(--surface)}
.audio-group-header{display:flex; align-items:center; gap:.5rem; padding:.7rem 1rem; cursor:pointer; user-select:none; background:var(--surface-soft); transition:background .15s}
.audio-group-header:hover{background:var(--surface-hover)}
.audio-group-chev{font-size:.7em; color:var(--gold-deep); transition:transform .2s; flex:0 0 auto}
.audio-group-title{font-size:1.05em; color:var(--gold-deep); font-weight:700; letter-spacing:.04em; flex:1}
.audio-group-count{font-size:.82em; color:var(--ink-faint); flex:0 0 auto}
.audio-group-hint{font-size:.75em; color:var(--ink-faint); opacity:.6; flex:0 0 auto}
.audio-group-play-btn{flex:0 0 auto}
.audio-group-spacer{flex:1 !important}
/* 手机端：标题独占第一行，按钮和提示在第二行 */
@media (max-width: 768px){
  .audio-group-header{flex-wrap:wrap !important; align-items:center; padding:.6rem .8rem !important; gap:.3rem .5rem !important}
  .audio-group-chev{order:1 !important; flex:0 0 auto !important}
  .audio-group-title{order:2 !important; flex:0 1 auto !important; min-width:0 !important; font-size:1em !important; margin-right:0 !important}
  .audio-group-count{order:3 !important; flex:0 0 auto !important; margin-left:0 !important}
  .audio-group-spacer{order:4 !important; flex:0 0 100% !important; height:0 !important; padding:0 !important; margin:0 !important}
  .audio-group-play-btn{order:5 !important; flex:0 0 auto !important; margin-left:0 !important; margin-top:.4rem !important}
  .audio-group-hint{order:6 !important; flex:0 0 auto !important; margin-left:auto !important; margin-top:.4rem !important}
}
.audio-group-body{padding:.3rem .5rem .6rem}
.audio-group-body .hn-link{margin:.15rem 0}
.audio-note{color:var(--ink-soft); font-size:.95em; margin:.6rem 0 1rem; line-height:1.7}
.hn-tips{margin:.4rem 0 1rem; padding-left:1.2rem; list-style:disc}
.hn-tips li{color:var(--ink-soft); font-size:.9em; line-height:1.7; margin:.3rem 0}
/* 首页「本次更新内容」区块：与代码/导航结构清晰区分的独立内容展示区 */
.home-update{border:1px solid var(--gold-soft); border-left:4px solid var(--accent);
  border-radius:12px; padding:1.1rem 1.4rem; margin:1.6rem 0; background:var(--surface-soft)}
.home-update .hn-sec-title{margin-top:0}
.home-update h3{font-size:1.1em; color:var(--gold-deep); margin:1.2em 0 .4em; font-weight:600}
.home-update ul{margin:.4em 0 .8em 1.4em; padding:0}
.home-update li{margin:.35em 0}
.home-update .play-btn{margin:.2rem 0 .2rem 0}
.dir-children{margin-top:.6rem}
.dir-children .hn-link{font-size:.95em}
/* 目录 Index 完整目录树容器 */
.dir-full-tree{margin-top:1.4rem; padding-top:.6rem}

/* ===== AI 问答入口 ===== */
/* 首页 AI 问答卡片 */
.ai-ask-card{display:flex; flex-direction:column; gap:.8rem; padding:1.1rem 1.3rem; border:1px solid var(--line); border-radius:12px; background:var(--surface-soft); text-decoration:none; color:var(--ink); transition:all .2s; margin-top:.5rem}
.ai-ask-card:hover{border-color:var(--accent); background:var(--surface-hover); transform:translateY(-2px); box-shadow:0 4px 16px rgba(0,0,0,.08)}
.ai-ask-top-row{display:flex; align-items:center; justify-content:flex-end; width:100%}
.ai-ask-bottom-row{display:flex; align-items:center; gap:1rem; width:100%}
.ai-ask-icon{font-size:2em; flex:0 0 auto}
.ai-ask-text{flex:1; min-width:0}
.ai-ask-title{font-weight:700; font-size:1.05em; color:var(--ink); margin-bottom:.2rem}
.ai-ask-desc{font-size:.88em; color:var(--ink-faint)}
.ai-ask-arrow{flex:0 0 auto; color:var(--accent); font-size:.9em; font-weight:600; white-space:nowrap}
/* 导航栏外部链接项 */
.nav-ai-ask{margin-top:.6rem; border-top:1px solid var(--line); padding-top:.6rem}
.nav-external{text-decoration:none; display:flex; align-items:center; gap:.5rem; padding:.55rem .7rem; border-radius:8px; color:var(--ink-soft); cursor:pointer; transition:all .15s}
.nav-external:hover{background:var(--surface-hover); color:var(--accent)}
.nav-external .dir-label{flex:1}
/* 文章页 AI 问答浮动按钮 */
.ai-ask-fab{position:fixed; right:1.2rem; bottom:5.5rem; z-index:50; width:48px; height:48px; border-radius:50%; background:var(--accent); color:#fff; align-items:center; justify-content:center; font-size:1.3em; text-decoration:none; box-shadow:0 4px 16px rgba(110,22,20,.35); transition:all .2s; display:none}
.ai-ask-fab:hover{transform:scale(1.1); box-shadow:0 6px 20px rgba(110,22,20,.5)}
.back-to-top{position:fixed; right:1.2rem; bottom:9rem; width:44px; height:44px; border-radius:50%; background:var(--surface); color:var(--ink-soft); border:1px solid var(--line); font-size:1.1rem; cursor:pointer; display:none; align-items:center; justify-content:center; box-shadow:0 4px 12px rgba(0,0,0,.1); z-index:90; transition:all .2s}
.back-to-top:hover{background:var(--accent); color:#fff; border-color:var(--accent); transform:translateY(-2px)}
.back-to-top.visible{display:flex}
.page-404{text-align:center; padding:4rem 1rem}
.page-404-code{font-size:5em; font-weight:700; color:var(--accent); line-height:1; margin-bottom:1rem}
.page-404-text{font-size:1.5em; color:var(--ink); margin-bottom:.8rem}
.page-404 p{color:var(--ink-faint); margin-bottom:1.5rem}
.page-404-home{display:inline-block; padding:.6rem 1.5rem; background:var(--accent); color:#fff; border-radius:8px; text-decoration:none; transition:background .15s}
.page-404-home:hover{background:var(--accent-deep)}
/* 文章目录 */
.article-toc{border:1px solid var(--line); border-radius:10px; margin:1rem 0 1.5rem; background:var(--surface-soft); overflow:hidden}
.article-toc-head{display:flex; align-items:center; gap:.5rem; padding:.7rem 1rem; cursor:pointer; user-select:none; font-weight:600; color:var(--ink); font-size:.95em}
.article-toc-chev{margin-left:auto; font-size:.7em; color:var(--ink-faint); transition:transform .2s}
.article-toc:not(.open) .article-toc-body{display:none}
.article-toc:not(.open) .article-toc-chev{transform:rotate(-90deg)}
.article-toc-body{padding:.5rem 1rem .8rem; border-top:1px solid var(--line)}
.article-toc-item{display:block; padding:.3rem 0; color:var(--ink-soft); text-decoration:none; font-size:.9em; line-height:1.5; transition:color .15s}
.article-toc-item:hover{color:var(--accent)}
.article-toc-l3{padding-left:1.2rem; font-size:.85em; color:var(--ink-faint)}
@media(max-width:760px){
  .ai-ask-fab{right:1rem; bottom:5rem; width:44px; height:44px; font-size:1.15em}
}

/* ===== 法音卡片式布局 ===== */
.audio-card{display:flex; gap:1rem; padding:1rem; margin-bottom:1rem; border:1px solid var(--line); border-radius:12px; background:var(--surface-soft); transition:all .2s}
.audio-card:hover{border-color:var(--accent); box-shadow:0 4px 12px rgba(0,0,0,.08)}
.audio-card-poster{width:100px; height:140px; object-fit:cover; border-radius:8px; cursor:pointer; flex:0 0 auto; transition:transform .2s}
.audio-card-poster:hover{transform:scale(1.05)}
.audio-card-info{flex:1; min-width:0; display:flex; flex-direction:column; justify-content:center}
.audio-card-title{font-size:1.15em; font-weight:700; color:var(--ink); margin-bottom:.3rem}
.audio-card-author{font-size:.85em; color:var(--ink-faint); margin-bottom:.8rem}
.audio-card-actions{display:flex; gap:.6rem}
.audio-card-btn{display:inline-flex; align-items:center; gap:.3rem; padding:.45rem .9rem; border-radius:8px; font-size:.9em; text-decoration:none; cursor:pointer; border:none; transition:all .15s}
.audio-card-play{background:var(--accent); color:#fff}
.audio-card-play:hover{background:var(--accent-deep)}
.audio-card-download{background:var(--surface-hover); color:var(--ink-soft); border:1px solid var(--line)}
.audio-card-download:hover{border-color:var(--accent); color:var(--accent)}
/* 海报大图查看 */
.poster-overlay{position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,.85); z-index:1000; display:flex; align-items:center; justify-content:center; cursor:zoom-out}
.poster-overlay img{max-height:90vh; max-width:90vw; border-radius:8px; box-shadow:0 8px 32px rgba(0,0,0,.5)}

/* ===== 法音详情页 ===== */
.audio-detail{max-width:520px; margin:0 auto; padding:1rem 0 2rem; text-align:center}
.audio-detail-poster{width:100%; max-width:400px; border-radius:12px; box-shadow:0 8px 32px rgba(0,0,0,.15); margin-bottom:1.5rem; cursor:zoom-in; transition:transform .2s}
.audio-detail-poster:hover{transform:scale(1.02)}
.audio-detail-title{font-size:1.6em; font-weight:700; color:var(--ink); margin-bottom:.5rem}
.audio-detail-author{font-size:.95em; color:var(--ink-faint); margin-bottom:1.5rem}
.audio-detail-actions{display:flex; gap:1rem; justify-content:center; margin-bottom:1rem}
.audio-detail-btn{display:inline-flex; align-items:center; gap:.4rem; padding:.7rem 1.5rem; border-radius:10px; font-size:1em; font-weight:600; text-decoration:none; cursor:pointer; border:none; transition:all .15s}
.audio-detail-play{background:var(--accent); color:#fff}
.audio-detail-play:hover{background:var(--accent-deep); transform:translateY(-1px)}
.audio-detail-download{background:var(--surface-hover); color:var(--ink-soft); border:1px solid var(--line)}
.audio-detail-download:hover{border-color:var(--accent); color:var(--accent)}
.audio-detail-tip{font-size:.8em; color:var(--ink-faint); margin-top:.5rem}
@media(max-width:760px){
  .audio-detail-poster{max-width:300px}
  .audio-detail-title{font-size:1.3em}
  .audio-detail-actions{flex-direction:column; align-items:center}
  .audio-detail-btn{width:80%; justify-content:center}
}

/* ===== Index 页音频缩略图列表 ===== */
.hn-audio-with-poster{display:flex !important; align-items:center; gap:.8rem; padding:.6rem .8rem !important; border-radius:10px}
.hn-audio-with-poster:hover{background:var(--surface-hover)}
.audio-list-thumb{width:42px; height:56px; border-radius:6px; background-size:contain; background-position:center; background-repeat:no-repeat; flex:0 0 auto; box-shadow:0 2px 8px rgba(0,0,0,.1)}
.audio-list-title{flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.audio-list-arrow{color:var(--ink-faint); font-size:1.2em; flex:0 0 auto}

/* ===== 法音详情页 ===== */
.mantra-detail{max-width:600px; margin:0 auto; text-align:center; padding:1rem 0 2rem}
.mantra-detail-title{font-size:1.7em; font-weight:400; color:var(--ink); margin-bottom:1.2rem; letter-spacing:.05em}
.mantra-detail-player{display:flex; align-items:center; gap:.8rem; justify-content:center; margin-bottom:1.2rem}
.mantra-detail-player audio{flex:1; max-width:480px; height:44px; border-radius:24px; box-shadow:0 4px 16px rgba(0,0,0,.12)}
.mantra-detail-download{display:inline-flex; align-items:center; justify-content:center; width:44px; height:44px; border-radius:50%; background:var(--surface-hover); color:var(--ink-soft); border:1px solid var(--line); text-decoration:none; font-size:1.1em; flex-shrink:0; transition:all .15s}
.mantra-detail-download:hover{border-color:var(--accent); color:var(--accent); transform:translateY(-1px)}
.mantra-detail-author{font-size:.95em; color:var(--ink-faint); margin-bottom:1.5rem; letter-spacing:.08em}
.mantra-detail-poster{margin-bottom:1rem}
.mantra-detail-poster img{max-width:100%; height:auto; border-radius:4px; box-shadow:0 8px 32px rgba(0,0,0,.15); cursor:zoom-in; display:block; margin:0 auto}
.mantra-detail-tip{font-size:.85em; color:var(--ink-faint); opacity:.7}

/* Index 页：有海报的经咒条目（带缩略图） */
.hn-audio-with-poster{display:flex; align-items:center; gap:.8rem; padding:.6rem .8rem}
.audio-list-thumb{width:40px; height:56px; object-fit:cover; border-radius:4px; flex:0 0 auto}
.audio-list-title{flex:1; text-align:left}
.audio-list-arrow{color:var(--ink-faint); font-size:1.2em; flex:0 0 auto}
@media(max-width:760px){
  .audio-card{flex-direction:column; align-items:center; text-align:center}
  .audio-card-poster{width:140px; height:196px}
  .audio-card-actions{justify-content:center}
}

/* ===== 划线与分享 ===== */
/* 划线高亮：金色底纹（类似微信读书划线） */
.hl{background:linear-gradient(transparent 55%, rgba(184,137,59,.38) 55%); cursor:pointer; border-radius:2px; padding:0 1px; transition:background .2s}
.hl:hover{background:linear-gradient(transparent 50%, rgba(184,137,59,.6) 50%)}
/* 选中浮动工具栏 */
.sel-toolbar{position:fixed; z-index:9999; background:#2a1f1a; color:#f5efe8; border-radius:10px; padding:5px; display:flex; gap:2px; box-shadow:0 6px 24px rgba(0,0,0,.35); font-size:14px}
.sel-toolbar button{background:transparent; border:none; color:#f5efe8; padding:7px 14px; border-radius:7px; cursor:pointer; font-size:13px; white-space:nowrap; transition:background .15s}
.sel-toolbar button:hover{background:rgba(255,255,255,.14)}
.sel-toolbar .st-sep{width:1px; background:rgba(255,255,255,.15); margin:5px 0}
@media(max-width:760px){
  .sel-toolbar{padding:6px; border-radius:12px}
  .sel-toolbar button{padding:10px 18px; font-size:15px}
}
/* 文章操作栏（分享按钮） */
.article-actions{margin:.3rem 0 1rem; display:flex; gap:.6rem; align-items:center}
.share-btn{background:var(--surface-soft); border:1px solid var(--line); color:var(--ink-soft); padding:.32rem .95rem; border-radius:20px; font-size:.84em; cursor:pointer; transition:all .15s}
.share-btn:hover{border-color:var(--accent); color:var(--accent); background:var(--surface-hover)}
/* 分享面板（底部弹层） */
.share-mask{position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:9998; display:none}
.share-mask.show{display:block}
.share-panel{position:fixed; left:0; right:0; bottom:0; background:var(--surface); border-radius:18px 18px 0 0; padding:1.3rem 1.4rem 1.8rem; z-index:9999; transform:translateY(100%); transition:transform .28s ease; max-height:82vh; overflow-y:auto}
.share-panel.show{transform:translateY(0)}
.share-panel h3{margin:0 0 .9rem; font-size:1.08em; color:var(--ink)}
.share-panel .sp-row{display:flex; gap:.7rem; margin:.7rem 0; flex-wrap:wrap}
.share-panel .sp-btn{flex:1; min-width:110px; padding:.75rem .5rem; border:1px solid var(--line); border-radius:10px; background:var(--surface-soft); cursor:pointer; text-align:center; font-size:.88em; color:var(--ink-soft); transition:all .15s}
.share-panel .sp-btn:hover{border-color:var(--accent); color:var(--accent)}
.share-panel .sp-link{width:100%; box-sizing:border-box; padding:.5rem .7rem; border:1px solid var(--line); border-radius:8px; font-size:.78em; background:var(--surface-soft); color:var(--ink-faint); word-break:break-all; margin-top:.5rem}
.share-card-preview{text-align:center; margin:.9rem 0}
.share-card-preview canvas{max-width:100%; border-radius:14px; box-shadow:0 6px 24px rgba(0,0,0,.18)}

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

/* 悬浮搜索/AI问答按钮（可拖动） */
.fab-search{position:fixed !important;top:70px;right:12px;z-index:100;padding:.7rem 1.1rem;border-radius:999px;
  background:var(--accent);color:#fff;border:none;cursor:grab;font-size:.9rem;font-weight:600;
  box-shadow:0 4px 14px rgba(59,42,34,.28);display:flex;align-items:center;gap:.4rem;
  transition:box-shadow .2s,opacity .2s;user-select:none;-webkit-user-select:none;touch-action:none;opacity:.75}
.fab-search:hover{background:var(--accent-soft);opacity:1}
.fab-search:active{cursor:grabbing}
.fab-search.dragging{opacity:.85;box-shadow:0 6px 20px rgba(0,0,0,.4)}
.fab-search .fab-icon{font-size:1.1em}

/* 悬浮搜索面板 */
.search-panel{position:fixed;top:0;left:0;right:0;bottom:0;z-index:200;display:none;
  background:rgba(0,0,0,.5);backdrop-filter:blur(4px)}
.search-panel.open{display:block}
.search-panel-box{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
  width:90%;max-width:560px;background:var(--surface);border-radius:16px;
  box-shadow:0 10px 40px rgba(0,0,0,.3);overflow:hidden;max-height:80vh;display:flex;flex-direction:column}
.search-panel-header{display:flex;align-items:center;padding:1rem 1.2rem;border-bottom:1px solid var(--line)}
.search-panel-tabs{display:flex;gap:.5rem}
.search-panel-title{font-weight:600;font-size:1.05em;color:var(--ink)}
.search-panel-tab{padding:.4rem 1rem;border-radius:20px;cursor:pointer;font-size:.95em;
  background:var(--surface-soft);color:var(--ink-soft);border:none;transition:all .2s}
.search-panel-tab.active{background:var(--accent);color:#fff}
.search-panel-close{margin-left:auto;background:none;border:none;font-size:1.3em;cursor:pointer;
  color:var(--ink-faint);padding:.2rem .5rem;border-radius:6px}
.search-panel-close:hover{color:var(--ink);background:var(--surface-soft)}
.search-panel-body{padding:1rem 1.2rem;overflow-y:auto;flex:1}
.search-panel-input{width:100%;padding:.7rem 1rem;border:1px solid var(--line);border-radius:10px;
  font-size:1em;background:var(--surface-soft);color:var(--ink);box-sizing:border-box}
.search-panel-input:focus{outline:none;border-color:var(--accent)}
.search-panel-results{margin-top:1rem}
/* AI搜索最小化浮窗：手机端竖屏样式 */
@media (max-width: 768px){
  .search-mini-float{
    width:140px !important;
    max-height:220px !important;
    top:60px !important;
    left:8px !important;
    border-radius:12px !important;
  }
  .search-mini-float > div:first-child{
    padding:.4rem .5rem !important;
    font-size:.75em !important;
  }
  .search-mini-float #searchPanelMinimizedContent{
    max-height:170px !important;
    font-size:.7em !important;
    line-height:1.6 !important;
    padding:.4rem .5rem !important;
  }
}
.search-result-item{padding:.6rem .8rem;border-radius:8px;cursor:pointer;margin-bottom:.3rem;
  color:var(--ink-soft);font-size:.95em;line-height:1.5}
.search-result-item:hover{background:var(--surface-soft);color:var(--accent)}
.search-result-item .sr-title{font-weight:600;color:var(--ink)}
.search-result-item .sr-path{font-size:.85em;color:var(--ink-faint);margin-top:.2rem}
.ai-ask-messages{margin-top:1rem;max-height:400px;overflow-y:auto}
.ai-msg{margin:.5rem 0;padding:.6rem .9rem;border-radius:12px;max-width:90%;line-height:1.6;font-size:.95em}
.ai-msg.user{background:var(--accent);color:#fff;margin-left:auto;border-radius:12px 12px 2px 12px}
.ai-msg.bot{background:var(--surface-soft);color:var(--ink);border-radius:12px 12px 12px 2px;white-space:pre-wrap}
.ai-msg.thinking{color:var(--ink-faint);font-style:italic}
.ai-ask-input-row{display:flex;gap:.5rem;margin-top:1rem}
.ai-ask-input-row input{flex:1;padding:.6rem .8rem;border:1px solid var(--line);border-radius:8px;
  font-size:.95em;background:var(--surface-soft);color:var(--ink)}
.ai-ask-input-row button{padding:.6rem 1.2rem;background:var(--accent);color:#fff;border:none;
  border-radius:8px;cursor:pointer;font-size:.95em}

/* ===== 全局响应式：防止页面超宽 ===== */
html,body{overflow-x:hidden;width:100%;margin:0;padding:0}
*{max-width:100%;box-sizing:border-box}
table{display:block;overflow-x:auto;white-space:nowrap}
pre{white-space:pre-wrap;word-wrap:break-word;overflow-x:auto}
img{height:auto;max-width:100%}

/* ===== 悬浮按钮靠边贴紧样式 ===== */
.fab-search.edge-left{right:auto !important;left:0 !important;border-radius:0 999px 999px 0;padding:.7rem .8rem .7rem .5rem}
.fab-search.edge-left .fab-icon{font-size:1.2em}
.fab-search.edge-left span:not(.fab-icon){display:none}
.fab-search.edge-right{left:auto !important;right:0 !important;border-radius:999px 0 0 999px;padding:.7rem .5rem .7rem .8rem}
.fab-search.edge-right .fab-icon{font-size:1.2em}
.fab-search.edge-right span:not(.fab-icon){display:none}

/* 播放器按钮靠边隐藏样式 */
.player-launch.edge-left{right:auto !important;left:0 !important;border-radius:0 999px 999px 0;padding:.7rem .8rem .7rem .5rem;font-size:0;}
.player-launch.edge-left::before{content:"🎧";font-size:1.1rem;}
.player-launch.edge-right{left:auto !important;right:0 !important;border-radius:999px 0 0 999px;padding:.7rem .5rem .7rem .8rem;font-size:0;}
.player-launch.edge-right::before{content:"🎧";font-size:1.1rem;}

/* ===== 文章底部导航样式 ===== */
.article-bottom-nav{margin-top:2.5rem;padding-top:1.5rem;border-top:1px solid var(--line)}
.bottom-nav-link{display:block;padding:.6rem .8rem;border-radius:8px;margin-bottom:.4rem;text-decoration:none;transition:background .15s}
.bottom-nav-link:hover{background:var(--surface-soft)}
.bottom-nav-link.disabled{opacity:.4;pointer-events:none}
.bottom-nav-label{display:block;font-size:.8em;color:var(--ink-faint);margin-bottom:.2rem}
.bottom-nav-title{display:block;font-size:1em;color:var(--ink);font-weight:500}
.bottom-nav-prev{border-left:3px solid var(--accent-soft)}
.bottom-nav-next{border-right:3px solid var(--accent-soft);text-align:right}
.bottom-nav-buttons{display:flex;gap:.8rem;margin-top:1rem;flex-wrap:wrap}
.bottom-nav-btn{flex:1;min-width:120px;text-align:center;padding:.6rem 1rem;border-radius:8px;
  background:var(--surface-soft);color:var(--ink-soft);text-decoration:none;font-size:.9em;
  border:1px solid var(--line);transition:all .15s}
.bottom-nav-btn:hover{background:var(--accent-soft);color:var(--accent-deep);border-color:var(--accent)}

/* ===== 手机端响应式（768px以下） ===== */
@media (max-width:768px){
  body{font-size:18px}
  .layout{padding:0 16px}
  .article{padding:1rem 0}
  .article p,.article li{text-align:justify;text-justify:inter-ideograph}
  .article h1{font-size:1.5em !important}
  .hn-sec-title{font-size:1.2em}
  .fab-search{font-size:.9em;padding:.6rem .9rem}
  .bottom-nav-btn{font-size:.85em;padding:.5rem .8rem}
  .bottom-nav-label{font-size:.75em}
  .bottom-nav-title{font-size:.95em}
}
</style>
<script data-goatcounter="https://drimed.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
</head>
<body>

<!-- 访问密码保护遮罩层（默认隐藏） -->
<div class="access-overlay" id="accessOverlay" style="display:none">
  <div class="access-box">
    <div class="access-icon">🔒</div>
    <h2>访问验证</h2>
    <p class="access-desc">本站为个人学习使用，非公开用途。<br>访问请输入密码：</p>
    <input type="password" id="accessPasswordInput" placeholder="请输入访问密码" />
    <button class="access-btn" id="accessSubmitBtn">进入网站</button>
    <div class="access-error" id="accessError"></div>
  </div>
</div>
<!-- 注册申请遮罩层（默认隐藏，设备数达到 100 后显示） -->
<div class="register-overlay access-overlay" id="registerOverlay" style="display:none">
  <div class="access-box">
    <div class="access-icon">📝</div>
    <h2>注册申请</h2>
    <p class="access-desc">本站仅为个人学习使用，需注册审核后访问。<br>请填写以下信息，管理员审核通过后即可访问。</p>
    <input type="text" id="regNickname" placeholder="您的昵称（必填）" style="margin-bottom:.8rem" />
    <textarea id="regReason" placeholder="申请理由（必填，如：学佛同修、朋友推荐等）" style="width:100%;padding:.8rem 1rem;border:2px solid var(--line);border-radius:10px;font-size:.9rem;font-family:inherit;background:var(--surface-soft);color:var(--ink);box-sizing:border-box;margin-bottom:.8rem;min-height:80px;resize:vertical"></textarea>
    <input type="text" id="regContact" placeholder="联系方式（选填，方便管理员联系）" style="margin-bottom:1rem" />
    <button class="access-btn" id="regSubmitBtn">提交申请</button>
    <div class="access-error" id="regError"></div>
  </div>
</div>


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
</div>

<!-- AI搜索悬浮按钮（移到topbar外面，避免backdrop-filter导致fixed定位失效） -->
<button class="fab-search" id="fabSearch" title="点击搜索 / AI 问答，可拖动位置">
  <span class="fab-icon">🔍</span><span>AI 搜索</span>
</button>

<div class="layout">
  <aside class="sidebar" id="sidebar">
    <button class="sidebar-close" id="sidebarClose" title="关闭菜单">✕</button>
    <nav class="nav" id="nav"></nav>
  </aside>
  <main class="content" id="content"></main>
</div>

<!-- 移动端：点击菜单外空白区域关闭侧栏 -->
<div class="sidebar-overlay" id="sidebarOverlay"></div>

<!-- 悬浮搜索/AI问答面板 -->
<div class="search-panel" id="searchPanel">
  <div class="search-panel-box">
    <div class="search-panel-header">
      <div class="search-panel-title">🔍 AI 搜索</div>
      <button class="search-panel-minimize" onclick="minimizeSearchPanel()" style="margin-left:auto;background:none;border:none;font-size:1.1em;cursor:pointer;color:var(--ink-faint);padding:.2rem .5rem;border-radius:4px;" title="最小化">—</button>
      <button class="search-panel-close" onclick="closeSearchPanel()">✕</button>
    </div>
    <div class="search-panel-body">
      <input class="search-panel-input" id="searchPanelInput" type="text" placeholder="输入关键词或问题，如：什么是菩提心？" onkeydown="if(event.key==='Enter')doPanelSearch()">
      <div class="ai-ask-messages" id="aiAskMessages"></div>
      <div class="search-panel-results" id="searchPanelResults"></div>
      <p style="font-size:.85em;color:var(--ink-faint);margin-top:.5rem;opacity:.7;line-height:1.6;">回答首先基于本站所收集的龙钦宁提相关材料；<br>如果本站没有相关内容，会基于网络搜索内容回答，仅供参考。</p>
    </div>
  </div>
</div>

<!-- AI搜索面板最小化缩略浮窗（默认隐藏） -->
<div id="searchPanelMinimized" class="search-mini-float" style="display:none;position:fixed;top:70px;left:12px;z-index:199;width:220px;max-height:160px;background:var(--bg);border:1px solid var(--line);border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.15);cursor:pointer;overflow:hidden;" onclick="restoreSearchPanel()">
  <div style="background:var(--accent);color:#fff;padding:.35rem .6rem;font-size:.8em;font-weight:500;display:flex;align-items:center;gap:.3rem;">
    <span>🔍</span>
    <span>点击返回问答</span>
  </div>
  <div id="searchPanelMinimizedContent" style="padding:.5rem .6rem;font-size:.75em;color:var(--ink-soft);line-height:1.5;max-height:110px;overflow:hidden;opacity:.85;">
    AI 问答已最小化，点击返回查看完整回答
  </div>
</div>

<!-- 全局播放器（默认占据下三分之一屏） -->
<div class="player" id="player">
  <!-- 第1行：状态栏（左：当前音频名 / 右：关闭叉号） -->
  <div class="p-status" id="pStatus">
    <span class="p-status-text" id="pStatusText">暂未播放</span>
    <button class="p-minimize" id="pMinimize" title="最小化到迷你条">—</button>
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
@@QRCODE_LIB@@
// ---- Service Worker 注册：音频离线缓存 + 页面更新策略（sw.js 由构建时复制到 dist 根） ----
if ('serviceWorker' in navigator){
  window.addEventListener('load', function(){
    navigator.serviceWorker.register('sw.js').catch(function(e){ console.warn('SW 注册失败:', e); });
  });
}




// ---- 访问统计与密码保护 ----
var STATS_API = "https://longchen-stats-auth.drimednor.workers.dev";
var ACCESS_KEY = "longchen-access-granted";
var DEVICE_KEY = "longchen-device-id";
var REG_KEY = "longchen-reg-id";

// 生成或获取设备 ID
function getDeviceId() {
  var deviceId = localStorage.getItem(DEVICE_KEY);
  if (!deviceId) {
    deviceId = 'dev_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem(DEVICE_KEY, deviceId);
  }
  return deviceId;
}

// 带设备 ID 的 fetch
function fetchWithDevice(url, options) {
  options = options || {};
  options.headers = options.headers || {};
  options.headers['X-Device-ID'] = getDeviceId();
  return fetch(url, options);
}

// 检查是否需要密码或注册
async function checkAccess() {
  // 无论是否已验证，都先调用 /api/track 记录设备访问
  if (STATS_API) {
    try {
      await fetchWithDevice(STATS_API + "/api/track");
    } catch (e) {
      console.warn("设备统计上报失败:", e);
    }
  }
  
  // 检查临时访问链接
  var urlParams = new URLSearchParams(window.location.search);
  var tempToken = urlParams.get('temp');
  if (tempToken && STATS_API) {
    try {
      var tempResp = await fetch(STATS_API + "/api/verify-temp", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: tempToken })
      });
      var tempData = await tempResp.json();
      if (tempData.success) {
        // 临时链接验证通过，设置访问权限
        localStorage.setItem(ACCESS_KEY, "true");
        // 从URL中移除temp参数，避免刷新时重复验证
        var newUrl = window.location.pathname + window.location.hash;
        window.history.replaceState({}, document.title, newUrl);
        return true;
      }
    } catch (e) {
      console.warn("临时链接验证失败:", e);
    }
  }
  
  // 已验证过，直接通过
  if (localStorage.getItem(ACCESS_KEY) === "true") {
    return true;
  }
  
  // 已注册并审核通过，直接通过
  var regId = localStorage.getItem(REG_KEY);
  if (regId) {
    try {
      var resp = await fetchWithDevice(STATS_API + "/api/login", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regId: regId })
      });
      var data = await resp.json();
      if (data.success) {
        return true;
      }
    } catch (e) {
      console.warn("登录验证失败:", e);
    }
  }
  
  if (!STATS_API) return true;
  
  try {
    var response = await fetchWithDevice(STATS_API + "/api/track");
    var data = await response.json();
    
    // 不需要密码和注册，直接通过
    if (!data.needPassword && !data.needRegister) {
      return true;
    }
    
    // 需要注册审核
    if (data.needRegister) {
      showRegisterOverlay();
      return false;
    }
    
    // 需要密码
    if (data.needPassword) {
      showAccessOverlay();
      return false;
    }
    
    return true;
  } catch (e) {
    console.warn("统计 API 调用失败，默认放行:", e);
    return true;
  }
}

// 显示密码输入界面
function showAccessOverlay() {
  var overlay = document.getElementById('accessOverlay');
  if (overlay) {
    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    setTimeout(function(){
      var input = document.getElementById('accessPasswordInput');
      if (input) input.focus();
    }, 100);
  }
}

// 显示注册界面
function showRegisterOverlay() {
  var overlay = document.getElementById('registerOverlay');
  if (overlay) {
    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }
}

// 隐藏所有遮罩
function hideOverlays() {
  var overlays = document.querySelectorAll('.access-overlay, .register-overlay');
  overlays.forEach(function(o) { o.style.display = 'none'; });
  document.body.style.overflow = '';
}

// 验证密码
async function verifyAccessPassword() {
  var input = document.getElementById('accessPasswordInput');
  var errorDiv = document.getElementById('accessError');
  var password = input ? input.value : '';
  
  if (!password) {
    if (errorDiv) errorDiv.textContent = '请输入访问密码';
    return;
  }
  
  try {
    var response = await fetchWithDevice(STATS_API + "/api/verify-password", {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password })
    });
    var data = await response.json();
    
    if (data.success) {
      localStorage.setItem(ACCESS_KEY, "true");
      hideOverlays();
    } else {
      if (errorDiv) errorDiv.textContent = data.message || '密码错误，请重试';
      if (input) input.value = '';
    }
  } catch (e) {
    console.warn("密码验证失败:", e);
    if (errorDiv) errorDiv.textContent = '网络错误，请稍后重试';
  }
}

// 提交注册申请
async function submitRegistration() {
  var nickname = document.getElementById('regNickname').value;
  var reason = document.getElementById('regReason').value;
  var contact = document.getElementById('regContact').value;
  var errorDiv = document.getElementById('regError');
  
  if (!nickname || !reason) {
    if (errorDiv) errorDiv.textContent = '请填写昵称和申请理由';
    return;
  }
  
  try {
    var response = await fetchWithDevice(STATS_API + "/api/register", {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nickname: nickname, reason: reason, contact: contact })
    });
    var data = await response.json();
    
    if (data.success) {
      localStorage.setItem(REG_KEY, data.regId);
      if (errorDiv) {
        errorDiv.style.color = '#27ae60';
        errorDiv.textContent = '注册申请已提交，请等待管理员审核。审核通过后刷新页面即可访问。';
      }
    } else {
      if (errorDiv) errorDiv.textContent = data.message || '提交失败，请重试';
    }
  } catch (e) {
    console.warn("注册失败:", e);
    if (errorDiv) errorDiv.textContent = '网络错误，请稍后重试';
  }
}

// 初始化访问控制
function initAccessControl() {
  // 密码提交按钮
  var submitBtn = document.getElementById('accessSubmitBtn');
  if (submitBtn) submitBtn.onclick = verifyAccessPassword;
  
  // 密码回车提交
  var input = document.getElementById('accessPasswordInput');
  if (input) {
    input.addEventListener('keydown', function(e){
      if (e.key === 'Enter') verifyAccessPassword();
    });
  }
  
  // 注册提交按钮
  var regBtn = document.getElementById('regSubmitBtn');
  if (regBtn) regBtn.onclick = submitRegistration;
  
  // 检查访问权限
  checkAccess();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAccessControl);
} else {
  initAccessControl();
}

// ========== 设备信息收集与上报 ==========
var DEVICE_INFO_ENDPOINT = 'https://stats.longchen-nyingtik.wiki/api/stats/device-info';

function collectDeviceInfo() {
  var ua = navigator.userAgent;
  var info = {};
  
  // 设备类型
  if (/Mobile|Android|iP(hone|od)|IEMobile|BlackBerry|Kindle|Silk-Accelerated|(hpw|web)OS|Opera M(obi|ini)/.test(ua)) {
    info.deviceType = '手机';
  } else if (/iPad|Tablet|PlayBook|Silk/.test(ua)) {
    info.deviceType = '平板';
  } else {
    info.deviceType = 'PC';
  }
  
  // 操作系统
  if (/Windows NT 10/.test(ua)) info.os = 'Windows 10/11';
  else if (/Windows NT 6.3/.test(ua)) info.os = 'Windows 8.1';
  else if (/Windows NT 6.2/.test(ua)) info.os = 'Windows 8';
  else if (/Windows NT 6.1/.test(ua)) info.os = 'Windows 7';
  else if (/Mac OS X/.test(ua)) info.os = 'macOS';
  else if (/Android/.test(ua)) info.os = 'Android';
  else if (/iPhone|iPad|iPod/.test(ua)) info.os = 'iOS';
  else if (/Linux/.test(ua)) info.os = 'Linux';
  else info.os = '未知';
  
  // 浏览器
  if (/MicroMessenger/.test(ua)) {
    info.browser = '微信内置浏览器';
    info.isWechat = true;
  } else if (/Edg/.test(ua)) info.browser = 'Edge';
  else if (/Chrome/.test(ua)) info.browser = 'Chrome';
  else if (/Safari/.test(ua)) info.browser = 'Safari';
  else if (/Firefox/.test(ua)) info.browser = 'Firefox';
  else if (/Opera/.test(ua)) info.browser = 'Opera';
  else info.browser = '未知';
  
  // 屏幕分辨率
  info.screenWidth = screen.width;
  info.screenHeight = screen.height;
  
  // 语言
  info.language = navigator.language || '';
  
  // 是否支持触摸
  info.isTouch = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;
  
  return info;
}

// 上报设备信息
function reportDeviceInfo() {
  var deviceId = localStorage.getItem('device_id') || '';
  if (!deviceId) return;
  var info = collectDeviceInfo();
  info.deviceId = deviceId;
  try {
    fetch(DEVICE_INFO_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(info)
    }).catch(function(){});
  } catch(e) {}
}

// 页面加载后上报设备信息
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', reportDeviceInfo);
} else {
  reportDeviceInfo();
}

// 设备识别：检测URL参数 identify=phone 或 identify=pc
function doDeviceIdentify() {
  try {
    var urlParams = new URLSearchParams(window.location.search);
    var identify = urlParams.get('identify');
    if (identify === 'phone' || identify === 'pc') {
      var deviceId = getDeviceId();
      if (deviceId) {
        fetch('https://stats.longchen-nyingtik.wiki/api/stats/identify-device', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ deviceId: deviceId, identify: identify })
        }).then(function(resp){
          return resp.json();
        }).then(function(data){
          if (data.success) {
            // 识别成功后，从URL中移除参数
            var newUrl = window.location.pathname + window.location.hash;
            window.history.replaceState({}, document.title, newUrl);
            // 显示提示
            var tip = document.createElement('div');
            tip.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#4CAF50;color:#fff;padding:10px 20px;border-radius:5px;z-index:9999;font-size:14px;';
            tip.textContent = '设备识别成功：' + (identify === 'phone' ? '手机' : '电脑');
            document.body.appendChild(tip);
            setTimeout(function(){ tip.remove(); }, 3000);
          }
        }).catch(function(e){
          console.error('设备识别失败:', e);
        });
      }
    }
  } catch(e) {
    console.error('设备识别异常:', e);
  }
}

// 页面加载后延迟执行设备识别
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function(){ setTimeout(doDeviceIdentify, 500); });
} else {
  setTimeout(doDeviceIdentify, 500);
}

// ========== 全局点击追踪统计 ==========
var clickBuffer = [];
var clickFlushTimer = null;
var CLICK_STATS_ENDPOINT = 'https://stats.longchen-nyingtik.wiki/api/stats/click';

function getClickTargetInfo(el) {
  // 向上查找可点击的元素
  var target = el;
  for (var i = 0; i < 5; i++) {
    if (!target || target === document.body) break;
    if (target.tagName === 'A' || target.tagName === 'BUTTON' || 
        target.onclick || (target.getAttribute && target.getAttribute('onclick')) ||
        target.classList && (target.classList.contains('search-result-item') || 
                              target.classList.contains('audio-item') ||
                              target.classList.contains('dir-item') ||
                              target.classList.contains('toc-item'))) {
      break;
    }
    target = target.parentElement;
  }
  if (!target || target === document.body) return null;
  
  var type = 'other';
  var targetName = '';
  
  // 判断点击类型
  var text = (target.textContent || target.innerText || '').trim().substring(0, 50);
  var href = target.getAttribute ? target.getAttribute('href') : '';
  var onclick = target.getAttribute ? target.getAttribute('onclick') : '';
  
  if (target.tagName === 'A' && href && href.indexOf('#/') === 0) {
    type = 'article_link';
    targetName = text || href;
  } else if (onclick && onclick.indexOf('show(') >= 0) {
    type = 'article_link';
    targetName = text || '文章';
  } else if (onclick && onclick.indexOf('toggleDir') >= 0) {
    type = 'dir_toggle';
    targetName = text || '目录展开/折叠';
  } else if (onclick && onclick.indexOf('playAudio') >= 0 || target.classList.contains('audio-item')) {
    type = 'audio_play';
    targetName = text || '音频播放';
  } else if (onclick && onclick.indexOf('openSearchPanel') >= 0 || onclick.indexOf('doPanelSearch') >= 0) {
    type = 'ai_search';
    targetName = text || 'AI搜索';
  } else if (onclick && onclick.indexOf('sendAiAsk') >= 0) {
    type = 'ai_ask';
    targetName = text || 'AI问答';
  } else if (target.tagName === 'BUTTON') {
    type = 'button';
    targetName = text || target.id || '按钮';
  } else if (target.classList.contains('search-result-item')) {
    type = 'search_result';
    targetName = text || '搜索结果';
  } else if (target.classList.contains('toc-item')) {
    type = 'toc_nav';
    targetName = text || '目录导航';
  }
  
  return { type: type, target: targetName };
}

function flushClickBuffer() {
  if (clickBuffer.length === 0) return;
  var buffer = clickBuffer.splice(0, clickBuffer.length);
  var deviceId = localStorage.getItem('device_id') || '';
  try {
    fetch(CLICK_STATS_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clicks: buffer, deviceId: deviceId })
    }).catch(function(){});
  } catch(e) {}
}

document.addEventListener('click', function(e) {
  var info = getClickTargetInfo(e.target);
  if (!info) return;
  
  var currentPage = location.hash.replace('#/', '') || 'index';
  clickBuffer.push({
    type: info.type,
    target: info.target,
    page: currentPage,
    timestamp: Date.now()
  });
  
  // 积累10次或5秒后上报
  if (clickBuffer.length >= 10) {
    flushClickBuffer();
  } else if (!clickFlushTimer) {
    clickFlushTimer = setTimeout(function() {
      clickFlushTimer = null;
      flushClickBuffer();
    }, 5000);
  }
}, true);

// 页面关闭前尝试上报
window.addEventListener('beforeunload', flushClickBuffer);

// ========== 使用时长追踪统计 ==========
var DURATION_STATS_ENDPOINT = 'https://stats.longchen-nyingtik.wiki/api/stats/duration';
var pageEnterTime = Date.now();
var currentTrackPage = location.hash.replace('#/', '') || 'index';
var durationFlushTimer = null;

function reportDuration() {
  var now = Date.now();
  var duration = Math.floor((now - pageEnterTime) / 1000);
  if (duration < 5) return; // 少于5秒不上报
  var deviceId = localStorage.getItem('device_id') || '';
  try {
    fetch(DURATION_STATS_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deviceId: deviceId, duration: duration, page: currentTrackPage })
    }).catch(function(){});
  } catch(e) {}
  pageEnterTime = now;
}

// 每隔30秒上报一次累计时长
durationFlushTimer = setInterval(reportDuration, 30000);

// 监听页面切换（hash变化）
window.addEventListener('hashchange', function() {
  // 上报上一个页面的停留时长
  var now = Date.now();
  var duration = Math.floor((now - pageEnterTime) / 1000);
  if (duration >= 5) {
    var deviceId = localStorage.getItem('device_id') || '';
    try {
      fetch(DURATION_STATS_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deviceId: deviceId, duration: duration, page: currentTrackPage })
      }).catch(function(){});
    } catch(e) {}
  }
  // 重置计时
  pageEnterTime = Date.now();
  currentTrackPage = location.hash.replace('#/', '') || 'index';
});

// 页面关闭前上报最后一次时长
window.addEventListener('beforeunload', function() {
  var now = Date.now();
  var duration = Math.floor((now - pageEnterTime) / 1000);
  if (duration >= 5) {
    var deviceId = localStorage.getItem('device_id') || '';
    try {
      navigator.sendBeacon(DURATION_STATS_ENDPOINT, JSON.stringify({
        deviceId: deviceId,
        duration: duration,
        page: currentTrackPage
      }));
    } catch(e) {}
  }
});



var SITE_TITLE = @@SITE_TITLE_JSON@@;
var PAGES = @@PAGES_JSON@@;
var TREE = @@TREE_JSON@@;
var AUDIO_ALBUM = @@AUDIO_ALBUM_JSON@@;
var AUDIO_TRACKS = @@AUDIO_TRACKS_JSON@@;
var HOME_UPDATE_HTML = @@HOME_UPDATE_JSON@@;   // 首页「本次更新内容」区块（纯用户资料，不含技术调整）
var HOME_UPDATE_DATE = "@@HOME_UPDATE_DATE@@"; // 首页公告区标题用的更新日期（取自内容文件 frontmatter date 字段）
var KNOWLEDGE_BASE = @@KNOWLEDGE_BASE_JSON@@;  // AI问答知识库索引（构建时生成，标题+正文摘要）

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
  var cleaned = name.replace(/^\d+(?:\.\d+)*\.?\s*/, '');
  // 特殊名称映射
  var nameMap = {
    '上师法音': '上师法音・经咒念诵'
  };
  if (nameMap[cleaned]) return nameMap[cleaned];
  return cleaned;
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
  // 简化导航：只显示一级菜单，点击直接进入该目录的 Index 页面（Index 内展示完整目录）
  var TOP_ORDER = ['上师开示', '龙钦宁提传承', '音频资源', '书籍', '关于本站'];
  function topKey(name){ var i = TOP_ORDER.indexOf(name); return i < 0 ? 1000 : i; }
  var html = '';
  // AI 搜索入口（放在最上面，用分隔线隔开）
  html += '<div class="nav-sec nav-ai-ask" data-depth="0">'
    + '<div class="nav-sec-head" onclick="openSearchPanel()">'
    + '<span class="nav-chev nav-chev-none">🔍</span>'
    + '<span class="dir-label">AI 搜索</span></div></div>';
  html += '<hr style="border:none;border-top:1px solid var(--line);margin:.5rem 0;">';
  Object.keys(TREE.dirs).sort(function(a, b){ return topKey(a) - topKey(b); }).forEach(function(name){
    var target = name + '/index';
    if (!bySlug[target]) target = firstPageUnder(name);
    if (!target) return;   // 空目录（无 index / 无首篇 / 无子目录）→ 跳过
    html += '<div class="nav-sec" data-depth="0" data-slug="' + esc(target) + '">'
      + '<div class="nav-sec-head" data-slug="' + esc(target) + '">'
      + '<span class="nav-chev nav-chev-none">▸</span>'
      + '<span class="dir-label">' + esc(cleanDirName(name)) + '</span></div></div>';
  });
  nav.innerHTML = html;
  // 一级菜单点击：直接进入该目录 Index 页面
  nav.querySelectorAll('.nav-sec-head').forEach(function(h){
    if (h.classList.contains('nav-external')) return;   // 外部链接项不绑定点击，让 <a> 默认跳转
    h.onclick = function(){
      show(h.dataset.slug);
      if (window.innerWidth <= 760) closeSidebar();
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
}





// ---- 目录弹层：手机端点面包屑目录层级时，弹出该目录下的子目录+文章列表 ----
function treeNode(path){
  var node = TREE;
  (String(path).split('/') || []).forEach(function(seg){
    if (node && node.dirs) node = node.dirs[seg];
  });
  return node;
}
// 某目录下直接文章（不含子目录 index，不含更深层级）
function dirDirectPages(path){
  var pre = path + '/';
  return PAGES.filter(function(p){
    if (p.slug.indexOf(pre) !== 0) return false;
    if (p.slug === path + '/index') return false;
    var rest = p.slug.slice(pre.length);
    return rest.indexOf('/') === -1;
  }).sort(function(a, b){ return a.slug < b.slug ? -1 : 1; });
}
function openDirList(path){
  var node = treeNode(path);
  var html = '';
  // 子目录（可继续展开下一级）
  var dirNames = node && node.dirs ? Object.keys(node.dirs).slice().sort(naturalCompare) : [];
  dirNames.forEach(function(name){
    var subFull = path + '/' + name;
    var subTarget = subFull + '/index';
    if (!bySlug[subTarget]) subTarget = firstPageUnder(subFull);
    html += '<div class="dir-pop-item dir-pop-dir" data-dir="' + esc(subFull) + '" data-jump="' + esc(subTarget || '') + '">📁 ' + esc(cleanDirName(name)) + '<span class="dir-pop-arrow">›</span></div>';
  });
  // 直接文章（点击直接打开）
  var pages = dirDirectPages(path);
  pages.forEach(function(p){
    html += '<div class="dir-pop-item dir-pop-page" data-jump="' + esc(p.slug) + '">' + esc(p.title) + '</div>';
  });
  if (!html) html = '<div class="dir-pop-empty">（暂无内容）</div>';
  var label = cleanDirName(String(path).split('/').pop() || path);
  document.getElementById('dirPopTitle').textContent = label;
  document.getElementById('dirPopBody').innerHTML = html;
  document.getElementById('dirPop').classList.add('show');
  // 子目录 → 继续展开；文章 → 跳转
  document.querySelectorAll('#dirPop .dir-pop-dir').forEach(function(el){
    el.onclick = function(){ openDirList(el.dataset.dir); };
  });
  document.querySelectorAll('#dirPop .dir-pop-page').forEach(function(el){
    el.onclick = function(){
      closeDirPop();
      var slug = el.dataset.jump;
      if (bySlug[slug]) show(slug);
    };
  });
}




function closeDirPop(){
  document.getElementById('dirPop').classList.remove('show');
}

// ---- 内容统计（页面浏览 + 音频播放）----
var STATS_API = 'https://stats.longchen-nyingtik.wiki';
var pageViewSlug = null;
var pageViewStartTime = 0;
var audioPlayName = null;
var audioPlayStartTime = 0;

function reportPageView(slug, duration) {
  if (!slug || duration < 60) return;  // 时长小于1分钟忽略
  try {
    fetch(STATS_API + '/api/stats/page-view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Device-ID': getDeviceId() },
      body: JSON.stringify({ slug: slug, duration: Math.round(duration) })
    }).catch(function(){});
  } catch(e){}
}

function reportAudioPlay(name, duration) {
  if (!name || duration < 60) return;  // 时长小于1分钟忽略
  try {
    fetch(STATS_API + '/api/stats/audio-play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, duration: Math.round(duration) })
    }).catch(function(){});
  } catch(e){}
}

// 页面卸载时上报最后一次统计
window.addEventListener('beforeunload', function() {
  var now = Date.now() / 1000;
  if (pageViewSlug && pageViewStartTime) {
    reportPageView(pageViewSlug, now - pageViewStartTime);
  }
  if (audioPlayName && audioPlayStartTime && !playerAudio.paused) {
    reportAudioPlay(audioPlayName, now - audioPlayStartTime);
  }
});

// ---- 显示页面 ----
var currentSlug = null;
function show(slug){
  // 页面浏览统计：计算上一个页面的阅读时长并上报
  var now = Date.now() / 1000;
  if (pageViewSlug && pageViewStartTime && pageViewSlug !== 'index' && !pageViewSlug.endsWith('/index')) {
    reportPageView(pageViewSlug, now - pageViewStartTime);
  }
  pageViewSlug = slug;
  pageViewStartTime = now;
  var p = bySlug[slug];
  if (!p){
    // 404 页面
    currentSlug = slug;
    document.getElementById('pageCrumbs').textContent = ' / 页面未找到';
    document.getElementById('content').innerHTML = '<div class="article"><div class="page-404"><div class="page-404-code">404</div><div class="page-404-text">页面未找到</div><p>您访问的页面不存在或已被移动。</p><a class="page-404-home" href="#/index">返回首页</a></div></div>';
    document.title = SITE_TITLE + ' · 页面未找到';
    window.scrollTo({top:0, behavior:'smooth'});
    return;
  }
  if (currentSlug === slug) return;
  currentSlug = slug;
  // Hash 路由：更新 URL 使文章可被链接分享（replaceState 不触发 hashchange，避免循环）
  var targetHash = '#/' + slug.split('/').map(encodeURIComponent).join('/');
  if (location.hash !== targetHash) history.replaceState(null, '', targetHash);
  var meta = '';
  if (p.meta.author) meta += '<span>作者：' + esc(p.meta.author) + '</span>';
  if (p.meta.source_url) meta += '<span class="src"><a href="' + esc(p.meta.source_url) + '" target="_blank" rel="noopener">查看原文 ↗</a></span>';
  if (p.meta.tags && p.meta.tags.length) meta += p.meta.tags.map(function(t){return '<span class="tag">' + esc(t) + '</span>';}).join('');
  var isHome = (p.slug === 'index');
  var titleHtml = p.is_index ? '' : '<h1>' + esc(p.title) + '</h1>';
  var metaHtml = meta ? '<div class="meta">' + meta + '</div>' : '';
  // 文章目录（TOC）：仅非目录页且有 h2/h3 标题时显示
  var tocHtml = '';
  if (!p.is_index && p.html){
    var headings = [];
    var tmp = document.createElement('div');
    tmp.innerHTML = p.html;
    tmp.querySelectorAll('h2[id^=toc-], h3[id^=toc-]').forEach(function(h){
      headings.push({level: parseInt(h.tagName[1], 10), id: h.id, text: h.textContent});
    });
    if (headings.length > 1){
      tocHtml = '<div class="article-toc"><div class="article-toc-head" onclick="this.parentElement.classList.toggle(\'open\')">📑 文章目录 <span class="article-toc-chev">▼</span></div><div class="article-toc-body">';
      headings.forEach(function(h){
        tocHtml += '<a class="article-toc-item article-toc-l' + h.level + '" href="#' + h.id + '" onclick="event.preventDefault(); document.getElementById(\'' + h.id + '\').scrollIntoView({behavior:\'smooth\'});">' + esc(h.text) + '</a>';
      });
      tocHtml += '</div></div>';
    }
  }
  // 文章页（非目录 index）不加分享按钮
  var inner = titleHtml + metaHtml + tocHtml + p.html;
  if (isHome){
    inner = '<div class="welcome"><div class="big">' + esc(SITE_TITLE) + '</div>'
          + '<div class="welcome-sub">龙钦宁提资料库</div></div>'
          + '<section class="hn-sec home-update"><h2 class="hn-sec-title">最近更新 · ' + HOME_UPDATE_DATE + '</h2>'
          + HOME_UPDATE_HTML + '</section>'
          + p.html + renderHomeNav();
  }
  // 目录 landing 页（非首页 index）：自动聚合展示其下文章列表
  if (p.is_index && p.slug !== 'index'){
    // 音频资源目录特殊渲染（按文件夹层级列出音频）
    if (p.slug.indexOf('音频资源') === 0){
      var grp = null;
      if (p.slug !== '音频资源/index'){
        grp = p.slug.slice('音频资源/'.length).replace(/\/index$/, '');
      }
      var _curated = grp && p.html && p.html.indexOf('class="play-btn"') !== -1;
      if (!_curated){
        // 直接调用renderAudioListByFolder，该函数内部已包含工具栏和《大圆满前行》卡片
        inner += renderAudioListByFolder(grp);
      }
    } else {
      // 其他目录：展示完整目录树（所有层级子目录+文章，无需逐级点开）
      inner += renderFullDirTree(p.slug);
    }
  }
  var crumb = renderBreadcrumb(p);
  // 文章底部导航：上一篇/下一篇、回到首页/回到分类（仅非目录页）
  if (!p.is_index && !isHome) {
    var navHtml = '<div class="article-bottom-nav">';
    var slugParts = p.slug.split('/');
    var rootCat = slugParts[0];
    var rootCatSlug = rootCat + '/index';
    // 拉通当前一级目录下的所有文章
    var allRootArticles = PAGES.filter(function(page){
      return !page.is_index && page.slug.startsWith(rootCat + '/');
    }).sort(function(a, b){ return a.slug < b.slug ? -1 : 1; });
    var curIdx = allRootArticles.findIndex(function(page){ return page.slug === p.slug; });
    var prevArticle = curIdx > 0 ? allRootArticles[curIdx - 1] : null;
    var nextArticle = curIdx >= 0 && curIdx < allRootArticles.length - 1 ? allRootArticles[curIdx + 1] : null;
    // 上一篇
    if (prevArticle) {
      navHtml += '<a class="bottom-nav-link bottom-nav-prev" href="#/' + prevArticle.slug.split('/').map(encodeURIComponent).join('/') + '">';
      navHtml += '<span class="bottom-nav-label">← 上一篇</span>';
      navHtml += '<span class="bottom-nav-title">' + esc(prevArticle.title) + '</span>';
      navHtml += '</a>';
    } else {
      navHtml += '<div class="bottom-nav-link bottom-nav-prev disabled"><span class="bottom-nav-label">← 上一篇</span><span class="bottom-nav-title">已经是第一篇</span></div>';
    }
    // 下一篇
    if (nextArticle) {
      navHtml += '<a class="bottom-nav-link bottom-nav-next" href="#/' + nextArticle.slug.split('/').map(encodeURIComponent).join('/') + '">';
      navHtml += '<span class="bottom-nav-label">下一篇 →</span>';
      navHtml += '<span class="bottom-nav-title">' + esc(nextArticle.title) + '</span>';
      navHtml += '</a>';
    } else {
      navHtml += '<div class="bottom-nav-link bottom-nav-next disabled"><span class="bottom-nav-label">下一篇 →</span><span class="bottom-nav-title">已经是最后一篇</span></div>';
    }
    // 回到首页和分类首页按钮
    navHtml += '<div class="bottom-nav-buttons">';
    navHtml += '<a class="bottom-nav-btn" href="#/index">🏠 回到首页</a>';
    navHtml += '<a class="bottom-nav-btn" href="#/' + rootCatSlug.split('/').map(encodeURIComponent).join('/') + '">📁 回到分类</a>';
    navHtml += '</div>';
    navHtml += '</div>';
    inner += navHtml;
  }
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
  // 精确匹配未命中时：按一级菜单前缀匹配（如文章「上师开示/...」高亮一级「上师开示」）
  if (!_best){
    _navHeads.forEach(function(a){
      var s = a.dataset.slug;
      if (s && _best) return;
      if (s && s.indexOf('/index') > 0 && slug !== s && slug.indexOf(s.replace(/\/index$/, '')) === 0){
        _best = a; _bestDepth = 0;
      }
    });
  }
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
  // 首页导览音频项 → 直接播放（有详情页链接的除外，让其正常跳转）
  document.querySelectorAll('.hn-audio').forEach(function(a){
    a.onclick = function(ev){
      if (a.getAttribute('href') && a.getAttribute('href').indexOf('#/') === 0) return;  // 有详情页链接，正常跳转
      ev.preventDefault();
      playTrack(parseInt(a.dataset.idx, 10));
    };
  });
  // 面包屑链接：手机端点目录层级弹出该目录文章列表；主页/桌面端正常跳转
  document.querySelectorAll('.breadcrumb a').forEach(function(a){
    a.onclick = function(ev){
      ev.preventDefault();
      var isMobile = window.innerWidth <= 760;
      if (a.dataset.dir && isMobile){ openDirList(a.dataset.dir); return; }
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
  // 文章分享按钮
  var sab = document.getElementById('shareArticleBtn');
  if (sab) sab.onclick = function(){ shareArticle(); };
  // 恢复本页划线
  if (!p.is_index) restoreHighlights(slug);
  updatePlayBtns();
  // AI 问答浮动按钮：仅非首页显示
  var _fab = document.getElementById('aiAskFab');
  if (_fab) _fab.style.display = (p.is_index || slug === 'index') ? 'none' : 'flex';
  // 恢复阅读进度（非首页且有保存位置时）
  var savedScroll = 0;
  if (!p.is_index && slug !== 'index'){
    savedScroll = parseInt(localStorage.getItem(SCROLL_KEY + slug) || '0', 10);
  }
  if (savedScroll > 60){
    setTimeout(function(){ window.scrollTo(0, savedScroll); }, 80);
  } else {
    window.scrollTo({top:0, behavior:'smooth'});
  }
  // 页面访问统计（本地记录，不显示；GoatCounter 后台统计真实访问量）
  if (typeof trackPageView === 'function') trackPageView();
  // GoatCounter SPA 页面切换统计
  if (window.goatcounter && window.goatcounter.count){
    try { window.goatcounter.count({path: location.pathname + location.hash}); } catch(e){}
  }
}

// ==================== 划线与分享系统 ====================
var HL_KEY_PREFIX = 'longchen-hl-';
var selToolbar = null;

// ---- 选中浮动工具栏 ----
function initSelToolbar(){
  if (selToolbar) return;
  selToolbar = document.createElement('div');
  selToolbar.className = 'sel-toolbar';
  selToolbar.style.display = 'none';
  selToolbar.innerHTML = '<button data-act="highlight">划线</button>'
    + '<div class="st-sep"></div>'
    + '<button data-act="copy">复制</button>'
    + '<div class="st-sep"></div>'
    + '<button data-act="share">分享</button>';
  document.body.appendChild(selToolbar);
  selToolbar.addEventListener('mousedown', function(e){ e.preventDefault(); });
  selToolbar.querySelectorAll('button').forEach(function(b){
    b.onclick = function(){
      var act = b.dataset.act;
      var text = getSelText();
      if (!text){ hideSelToolbar(); return; }
      if (act === 'highlight') doHighlight(text);
      else if (act === 'copy'){ copyText(text); toast('已复制'); }
      else if (act === 'share') shareHighlight(text);
      hideSelToolbar();
    };
  });
}




function getSelText(){
  var sel = window.getSelection();
  return sel ? sel.toString().trim() : '';
}
function showSelToolbar(){
  initSelToolbar();
  var sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  var range = sel.getRangeAt(0);
  var rect = range.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  selToolbar.style.display = 'flex';
  var tbW = selToolbar.offsetWidth;
  var left = rect.left + rect.width / 2 - tbW / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tbW - 8));
  var isMobile = window.innerWidth <= 760;
  var top;
  if (isMobile){
    // 手机端：显示在选区下方，避免与系统编辑菜单（通常在上方）重叠
    top = rect.bottom + 8;
    if (top + selToolbar.offsetHeight > window.innerHeight - 8) top = rect.top - selToolbar.offsetHeight - 8;
  } else {
    top = rect.top - selToolbar.offsetHeight - 8;
    if (top < 8) top = rect.bottom + 8;
  }
  selToolbar.style.left = left + 'px';
  selToolbar.style.top = top + 'px';
}
function hideSelToolbar(){ if (selToolbar) selToolbar.style.display = 'none'; }

// ---- 划线操作 ----
function doHighlight(text){
  var sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  var range = sel.getRangeAt(0);
  var mark = document.createElement('mark');
  mark.className = 'hl';
  try {
    range.surroundContents(mark);
  } catch(e){
    // 跨节点时用 extractContents 方案
    try {
      var frag = range.extractContents();
      mark.appendChild(frag);
      range.insertNode(mark);
    } catch(e2){ return; }
  }
  saveHighlight(currentSlug, text);
  sel.removeAllRanges();
}
function saveHighlight(slug, text){
  var key = HL_KEY_PREFIX + slug;
  var list = [];
  try { list = JSON.parse(localStorage.getItem(key) || '[]'); } catch(e){}
  if (list.indexOf(text) === -1) list.push(text);
  localStorage.setItem(key, JSON.stringify(list));
}
function getHighlights(slug){
  try { return JSON.parse(localStorage.getItem(HL_KEY_PREFIX + slug) || '[]'); } catch(e){ return []; }
}
function removeHighlight(slug, text){
  var key = HL_KEY_PREFIX + slug;
  var list = getHighlights(slug);
  var idx = list.indexOf(text);
  if (idx > -1) list.splice(idx, 1);
  localStorage.setItem(key, JSON.stringify(list));
}
function restoreHighlights(slug){
  var list = getHighlights(slug);
  if (!list.length) return;
  var article = document.querySelector('.article');
  if (!article) return;
  list.forEach(function(text){ highlightTextInElement(article, text); });
}
function highlightTextInElement(root, text){
  if (!text) return;
  var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  var node;
  while (node = walker.nextNode()){
    var idx = node.nodeValue.indexOf(text);
    if (idx > -1){
      var range = document.createRange();
      range.setStart(node, idx);
      range.setEnd(node, idx + text.length);
      try {
        var mark = document.createElement('mark');
        mark.className = 'hl';
        range.surroundContents(mark);
      } catch(e){}
      return;
    }
  }
}

// ---- 复制与提示 ----
function copyText(text){
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).catch(function(){ fallbackCopy(text); });
  } else fallbackCopy(text);
}
function fallbackCopy(text){
  var ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); } catch(e){}
  document.body.removeChild(ta);
}
function toast(msg){
  var t = document.createElement('div');
  t.style.cssText = 'position:fixed;top:24px;left:50%;transform:translateX(-50%);background:rgba(42,31,26,.92);color:#f5efe8;padding:.55rem 1.2rem;border-radius:20px;font-size:.88em;z-index:10000;pointer-events:none;transition:opacity .3s';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function(){ t.style.opacity = '0'; }, 1400);
  setTimeout(function(){ t.remove(); }, 1800);
}

// ---- 分享面板 ----
var shareMask = null, sharePanel = null;
function openSharePanel(opts){
  if (!shareMask){
    shareMask = document.createElement('div');
    shareMask.className = 'share-mask';
    sharePanel = document.createElement('div');
    sharePanel.className = 'share-panel';
    document.body.appendChild(shareMask);
    document.body.appendChild(sharePanel);
    shareMask.onclick = closeSharePanel;
  }
  var hasCard = !!opts.highlight;
  sharePanel.innerHTML = '<h3>' + (hasCard ? '分享划线' : '分享本文') + '</h3>'
    + (hasCard ? '<div class="share-card-preview"><canvas id="shareCard" width="750" height="1000"></canvas></div>' : '')
    + '<div class="sp-row">'
    + '<button class="sp-btn" data-act="copy-link">复制链接</button>'
    + '<button class="sp-btn" data-act="copy-text">复制文字</button>'
    + (hasCard ? '<button class="sp-btn" data-act="save-card">保存卡片图片</button>' : '')
    + '</div>'
    + '<div class="sp-link">' + esc(opts.url) + '</div>';
  shareMask.classList.add('show');
  sharePanel.classList.add('show');
  if (hasCard) drawShareCard(opts.title, opts.highlight, opts.url);
  sharePanel.querySelectorAll('.sp-btn').forEach(function(b){
    b.onclick = function(){
      var act = b.dataset.act;
      if (act === 'copy-link'){ copyText(opts.url); toast('链接已复制'); }
      else if (act === 'copy-text'){ copyText(opts.text); toast('文字已复制'); }
      else if (act === 'save-card'){ saveShareCard(); toast('图片已保存'); }
      closeSharePanel();
    };
  });
}




function closeSharePanel(){
  if (shareMask) shareMask.classList.remove('show');
  if (sharePanel) sharePanel.classList.remove('show');
}
function shareArticle(){
  var p = bySlug[currentSlug];
  if (!p) return;
  var url = location.origin + location.pathname + '#/' + currentSlug.split('/').map(encodeURIComponent).join('/');
  openSharePanel({ title: p.title, url: url, text: p.title + '\n' + url });
}
function shareHighlight(text){
  var p = bySlug[currentSlug];
  var title = p ? p.title : '';
  var url = location.origin + location.pathname + '#/' + currentSlug.split('/').map(encodeURIComponent).join('/');
  openSharePanel({
    title: title, url: url,
    text: '「' + text + '」\n—— ' + title + '\n' + url,
    highlight: text
  });
}





// ---- Canvas 分享卡片 ----
function drawQRCode(ctx, text, x, y, size){
  try {
    if (typeof qrcode !== 'function') return;
    var qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    var count = qr.getModuleCount();
    var cell = size / count;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(x - 5, y - 5, size + 10, size + 10);
    ctx.fillStyle = '#2a1f1a';
    for (var r = 0; r < count; r++){
      for (var c = 0; c < count; c++){
        if (qr.isDark(r, c)) ctx.fillRect(x + c * cell, y + r * cell, Math.ceil(cell), Math.ceil(cell));
      }
    }
  } catch(e){}
}
function drawShareCard(title, text, url){
  var canvas = document.getElementById('shareCard');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var W = 750, H = 1000;
  // 背景
  ctx.fillStyle = '#f5efe8';
  ctx.fillRect(0, 0, W, H);
  // 顶部装饰条
  ctx.fillStyle = '#6e1614';
  ctx.fillRect(0, 0, W, 8);
  // 标题
  ctx.fillStyle = '#6e1614';
  ctx.font = 'bold 34px "Noto Serif SC","Songti SC","SimSun",serif';
  ctx.textAlign = 'center';
  ctx.fillText(title || '', W / 2, 130);
  // 分隔线
  ctx.strokeStyle = '#b8893b';
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(W / 2 - 60, 165); ctx.lineTo(W / 2 + 60, 165); ctx.stroke();
  // 划线内容（自动换行）
  ctx.fillStyle = '#2a1f1a';
  ctx.font = '28px "Noto Serif SC","Songti SC","SimSun",serif';
  ctx.textAlign = 'left';
  var maxW = W - 120;
  var chars = text.split('');
  var lines = [], line = '';
  for (var i = 0; i < chars.length; i++){
    var test = line + chars[i];
    if (ctx.measureText(test).width > maxW && line){
      lines.push(line); line = chars[i];
    } else line = test;
  }
  if (line) lines.push(line);
  var lineH = 48;
  var startY = 240;
  lines.slice(0, 12).forEach(function(l, i){
    var tw = ctx.measureText(l).width;
    ctx.fillStyle = 'rgba(184,137,59,.28)';
    ctx.fillRect(60, startY + i * lineH - 32, tw, 40);
    ctx.fillStyle = '#2a1f1a';
    ctx.fillText(l, 60, startY + i * lineH);
  });
  // 底部区域：左侧来源+提示，右侧二维码
  ctx.fillStyle = '#9b8475';
  ctx.font = '20px "Noto Serif SC",sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('龙的传人 · Longchen Nyingtik', 60, H - 100);
  ctx.fillStyle = '#b8893b';
  ctx.font = '18px "Noto Serif SC",sans-serif';
  ctx.fillText('长按识别二维码 · 查看原文', 60, H - 65);
  // 二维码
  if (url) drawQRCode(ctx, url, W - 155, H - 145, 105);
}
function saveShareCard(){
  var canvas = document.getElementById('shareCard');
  if (!canvas) return;
  var link = document.createElement('a');
  link.download = '分享卡片.png';
  link.href = canvas.toDataURL('image/png');
  link.click();
}

// ---- 面包屑导航 ----
// 目录层级（非最后一级）均渲染为可点击 crumb：手机端点击弹出该目录下的子目录+文章列表，
// 桌面端点击跳转到该目录（data-page 优先 index，弹层函数另有兜底）。
function renderBreadcrumb(p){
  var parts = p.slug.split('/').filter(function(x){ return x && x !== 'index'; });
  var crumbs = ['<a class="crumb" data-page="index">主页</a>'];
  var acc = '';
  for (var i = 0; i < parts.length; i++){
    acc = acc ? acc + '/' + parts[i] : parts[i];
    crumbs.push('<span class="sep">›</span>');
    if (i < parts.length - 1){
      crumbs.push('<a class="crumb dir-crumb" data-page="' + esc(acc + '/index') + '" data-dir="' + esc(acc) + '">' + esc(parts[i]) + '</a>');
    } else {
      crumbs.push('<span class="cur">' + esc(parts[i]) + '</span>');
    }
  }
  return '<div class="breadcrumb">' + crumbs.join('') + '</div>';
}

// 自然排序：按文件名开头的数字大小排序
function naturalCompare(a, b) {
  var aParts = a.split(/(\d+)/);
  var bParts = b.split(/(\d+)/);
  for (var i = 0; i < Math.min(aParts.length, bParts.length); i++) {
    var aPart = aParts[i];
    var bPart = bParts[i];
    if (aPart !== bPart) {
      var aNum = parseInt(aPart, 10);
      var bNum = parseInt(bPart, 10);
      if (!isNaN(aNum) && !isNaN(bNum)) {
        return aNum - bNum;
      }
      return aPart < bPart ? -1 : 1;
    }
  }
  return aParts.length - bParts.length;
}

// 递归统计目录下所有非index文章数量
function countArticles(node){
  var count = 0;
  if (node.children){
    node.children.forEach(function(c){
      if (c.type === 'page' && !c.is_index) count++;
    });
  }
  if (node.dirs){
    Object.keys(node.dirs).forEach(function(name){
      count += countArticles(node.dirs[name]);
    });
  }
  return count;
}

// ---- 首页导览：递归渲染目录树为可点击板块（同样统一层级序号）----
function walkBlock(node, prefix, depth, parentNum, defaultCollapsed, introMap){
  var arr = [];
  // 最多展示三个层级（depth 0, 1, 2）
  if (depth > 2) return arr;
  var names = (node.dirs ? Object.keys(node.dirs) : []).slice().sort(naturalCompare);
  names.forEach(function(name, idx){
    var sub = node.dirs[name];
    var num = parentNum ? (parentNum + '.' + (idx + 1)) : String(idx + 1);
    var full = (prefix ? prefix + '/' : '') + name;
    var target = full + '/index';
    if (!bySlug[target]) target = firstPageUnder(full);
    var hasSub = sub.dirs && Object.keys(sub.dirs).length;
    var hasPages = sub.children && sub.children.length;
    if (!target && !hasSub && !hasPages) return;   // 空目录 → 跳过
    var subHasPages = sub.children && sub.children.filter(function(c){ return c.type === 'page' && !c.is_index; }).length > 4;
    var subHasSubDirs = sub.dirs && Object.keys(sub.dirs).length > 0;
    // 统计该目录下所有文章数量（用于一级目录显示）
    var totalArticleCount = countArticles(sub);
    // defaultCollapsed为true时，一级目录默认关闭；否则一级目录默认展开
    var isDefaultOpen = defaultCollapsed ? false : ((depth === 0) || (subHasSubDirs && !subHasPages));
    var groupId = 'dir-' + depth + '-' + full.replace(/[^a-z0-9]/gi, '');
    arr.push('<div class="dir-group" data-depth="' + depth + '" id="' + groupId + '">');
    arr.push('<div class="dir-group-header" onclick="toggleDirGroup(this)" style="cursor:pointer;user-select:none;display:flex;align-items:center;gap:.4rem;">'
      + '<span class="dir-group-chev" style="font-size:.7em;color:var(--gold-deep);transition:transform .2s;flex:0 0 auto;">' + (isDefaultOpen ? '▼' : '▶') + '</span>'
      + '<span class="hn-dir" data-depth="' + depth + '" style="margin:0;flex:0 0 auto;">' + esc(num) + '. ' + esc(cleanDirName(name)) + '</span>'
      + (depth === 0 && defaultCollapsed && totalArticleCount > 0 ? '<span class="dir-article-count" style="font-size:.75em;color:var(--ink-faint);flex:0 0 auto;margin-left:-.2rem;">(' + totalArticleCount + '篇)</span>' : '')
      + '<span class="audio-group-spacer"></span>'
      + '</div>');
    // 一级目录引导语（仅在defaultCollapsed模式下显示）
    if (depth === 0 && defaultCollapsed && introMap && introMap[cleanDirName(name)]){
      arr.push('<div class="dir-intro" style="padding-left:1.6rem;padding-bottom:.3rem;font-size:.85em;color:var(--ink-soft);font-style:italic;">' + esc(introMap[cleanDirName(name)]) + '</div>');
    }
    arr.push('<div class="dir-group-body" style="' + (isDefaultOpen ? '' : 'display:none;') + 'padding-left:1rem;">');
    walkBlock(sub, full, depth + 1, num, defaultCollapsed, introMap).forEach(function(x){ arr.push(x); });
    arr.push('</div></div>');
  });
  // 目录下文章超过4篇时，只显示前4篇，其余通过标题左侧的▶展开
  var hasSubDirs = node.dirs && Object.keys(node.dirs).length > 0;
  var pageCount = 0;
  var totalPages = (node.children || []).filter(function(c){ return c.type === 'page' && !c.is_index; }).length;
  var shouldCollapse = totalPages > 2;  // 文章超过2篇时折叠（不管有没有子目录）
  var MAX_VISIBLE = 2;  // 没有子目录只有文章时最多展示2篇
  (node.children || []).forEach(function(c){
    if (c.type === 'page' && !c.is_index){
      pageCount++;
      var isHidden = shouldCollapse && pageCount > MAX_VISIBLE;
      var p = bySlug[c.slug];
      var hasAudio = p && p.html && p.html.indexOf('play-btn') >= 0;
      arr.push('<a class="hn-link hn-hidden-page" data-page="' + esc(c.slug) + '" style="margin-left:1rem;' + (isHidden ? 'display:none;' : '') + '">'
        + esc(c.title) + '</a>');
    }
  });
  return arr;
}

// 展开更多文章
function showMorePages(btn){
  btn.style.display = 'none';
  var next = btn.nextElementSibling;
  while(next){
    if(next.classList && next.classList.contains('hn-hidden-page')){
      next.style.display = '';
    }
    next = next.nextElementSibling;
  }
}

// 目录分组折叠/展开（同时展开/折叠隐藏的文章）
function toggleDirGroup(header){
  // 保存当前滚动位置，防止页面跳动
  var scrollPos = window.scrollY || window.pageYOffset;
  var group = header.parentElement;
  var body = group.querySelector('.dir-group-body');
  var chev = header.querySelector('.dir-group-chev');
  if (body.style.display === 'none'){
    body.style.display = '';
    chev.textContent = '▼';
    // 展开时显示所有隐藏的文章
    var hiddenPages = body.querySelectorAll('.hn-hidden-page');
    hiddenPages.forEach(function(el){ el.style.display = ''; });
  } else {
    body.style.display = 'none';
    chev.textContent = '▶';
    // 折叠时重新隐藏超过2篇的文章
    var hiddenPages = body.querySelectorAll('.hn-hidden-page');
    var visibleCount = 0;
    hiddenPages.forEach(function(el){
      visibleCount++;
      if (visibleCount > 2){
        el.style.display = 'none';
      } else {
        el.style.display = '';
      }
    });
  }
  // 恢复滚动位置，防止页面跳动
  window.scrollTo(0, scrollPos);
}

// 展开/折叠所有目录组
function toggleAllDirGroups(btn){
  // 保存当前滚动位置，防止页面跳动
  var scrollPos = window.scrollY || window.pageYOffset;
  var isOpen = btn.textContent.indexOf('折叠') >= 0;
  // 展开/折叠所有层级的目录组，而不仅仅是一级
  var dirGroups = document.querySelectorAll('.dir-group');
  dirGroups.forEach(function(group){
    var header = group.querySelector('.dir-group-header');
    var body = group.querySelector('.dir-group-body');
    if (!body) return;
    var chev = header ? header.querySelector('.dir-group-chev') : null;
    if (isOpen){
      // 折叠
      body.style.display = 'none';
      if (chev) chev.textContent = '▶';
    } else {
      // 展开
      body.style.display = '';
      if (chev) chev.textContent = '▼';
      // 展开时显示所有隐藏的文章
      var hiddenPages = body.querySelectorAll('.hn-hidden-page');
      hiddenPages.forEach(function(el){ el.style.display = ''; });
    }
  });
  btn.textContent = isOpen ? '展开全部目录' : '折叠全部目录';
  // 恢复滚动位置，防止页面跳动
  window.scrollTo(0, scrollPos);
}

function renderHomeNav(){
  var html = [];
  // 每个顶层目录板块的定制元信息（未配置的目录使用默认图标/说明）
  var META = {
    '上师开示': {icon:'📖', title:'上师开示', desc:'', tips:true},
    '龙钦宁提传承': {icon:'🐉', title:'龙钦宁提传承', desc:'龙钦宁提传承相关资料与祖师传记，点击进入查看。'},
    '音频资源': {icon:'🎧', title:'音频资料', desc:'', audio:true, note:true},
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
    var dirIndexSlug = dirName + '/index';
    html.push('<h2 class="hn-sec-title" style="cursor:pointer;" onclick="show(\'' + esc(dirIndexSlug) + '\')" title="点击进入' + esc(meta.title) + '目录">' + meta.icon + ' ' + esc(meta.title) + ' <span style="font-size:.7em;color:var(--ink-faint);font-weight:normal;">›</span></h2>');
    if (meta.desc) html.push('<p class="hn-desc">' + meta.desc + '</p>');
    if (meta.tips){
      html.push('<ul class="hn-tips">'
        + '<li>点击标题栏左侧的 ▶，可展开或折叠子目录；</li>'
        + '<li>带有小喇叭 🔊 标志的文章表示有配套音频，可直接点击收听；</li>'
        + '<li>未带小喇叭标志的文章暂无音频，正在陆续添加中，敬请期待。</li>'
        + '</ul>');
      // 工具栏：展开/折叠全部 + AI搜索
      html.push('<div class="dir-toolbar" style="display:flex;gap:.5rem;margin:.5rem 0 1rem;flex-wrap:wrap;">'
        + '<button class="dir-toggle-all-btn" onclick="toggleAllDirGroups(this)" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--gold-deep);background:transparent;color:var(--gold-deep);border-radius:4px;cursor:pointer;">展开全部目录</button>'
        + '<button class="dir-ai-search-btn" onclick="openSearchPanel()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">🔍 AI 搜索</button>'
        + '</div>');
    }
    if (meta.audio){
      if (meta.note) html.push('<p class="audio-note">文件较大，缓冲需要时间，请耐心等待</p>');
      // 工具栏：展开/折叠全部 + 播放全部 + AI搜索
      html.push('<div class="dir-toolbar" style="display:flex;gap:.5rem;margin:.5rem 0 1rem;flex-wrap:wrap;">'
        + '<button class="dir-toggle-all-btn" onclick="toggleAllAudioGroups(this)" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--gold-deep);background:transparent;color:var(--gold-deep);border-radius:4px;cursor:pointer;">展开全部</button>'
        + '<button class="dir-play-all-btn" onclick="playAllAudio()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">▶ 播放全部</button>'
        + '<button class="dir-ai-search-btn" onclick="openSearchPanel()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">🔍 AI 搜索</button>'
        + '</div>');
      // 按文件夹分组展示全部音频（简洁一级目录列表，与参考样式一致）
      var _agroups = {};
      AUDIO_TRACKS.forEach(function(t, i){
        var folderParts = (t.folder || '其他音频').split('/');
        var g;
        if (folderParts[0] && folderParts[0].indexOf('上师法音') >= 0 && folderParts.length > 1) {
          // 上师法音：使用二级文件夹名称
          g = cleanDirName(folderParts[1]);
        } else {
          // 其他：使用一级文件夹名称
          g = cleanDirName(folderParts[0]);
        }
        (_agroups[g] = _agroups[g] || []).push({t: t, i: i});
      });
      
      // 按照指定顺序排序：上师开示（AI朗读）→ 上师赞歌 → 仪轨与经文 → 圣号与明咒
      var sortOrder = ['上师开示（AI朗读）', '上师赞歌', '仪轨与经文（上师亲诵）', '圣号与明咒（上师亲诵）'];
      var _akeys = Object.keys(_agroups).sort(function(a, b){
        var idxA = sortOrder.indexOf(a);
        var idxB = sortOrder.indexOf(b);
        if (idxA >= 0 && idxB >= 0) return idxA - idxB;
        if (idxA >= 0) return -1;
        if (idxB >= 0) return 1;
        return a < b ? -1 : 1;
      });
      
      _akeys.forEach(function(g, gi){
        var groupId = 'hag-' + gi + '-' + g.replace(/[^a-z0-9]/gi, '');
        html.push('<div class="audio-group" data-group="' + groupId + '" style="margin:.5rem 0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface-soft);">'
          + '<div class="audio-group-header" onclick="toggleAudioGroup(this)" style="display:flex;align-items:center;gap:.5rem;padding:.7rem 1rem;cursor:pointer;">'
          + '<span class="audio-group-chev" style="font-size:.8em;color:var(--gold-deep);">▶</span>'
          + '<span class="audio-group-title" style="font-size:1.05em;color:var(--gold-deep);font-weight:700;flex:0 0 auto;">' + esc(g) + '</span>'
          + '<span class="audio-group-count" style="font-size:.85em;color:var(--ink-faint);flex:0 0 auto;margin-left:-.2rem;">(' + _agroups[g].length + ')</span>'
          + '<span class="audio-group-spacer"></span>'
          + '<button class="audio-group-play-btn" onclick="event.stopPropagation(); playAllAudio(\'' + esc(g).replace(/'/g, "\\'") + '\')" style="padding:.3rem .7rem;font-size:.8em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">▶ 播放专辑</button>'
          + '<span class="audio-group-hint" style="font-size:.75em;color:var(--ink-faint);opacity:.6;">点击展开</span>'
          + '</div>'
          + '<div class="audio-group-body" style="display:none;padding:.5rem 1rem 1rem;">');
        
        _agroups[g].forEach(function(o){
          // 所有音频统一显示为纯文本链接，不显示缩略图
          html.push('<a class="hn-link hn-audio" data-idx="' + o.i + '" style="display:block;padding:.3rem 0;">' + esc(o.t.title) + '</a>');
        });
        html.push('</div></div>');
      });
      html.push('<div class="album-card"><div class="t">《大圆满前行》有声书（226 集）</div>'
        + '<div class="d">嘎玛仁波切译 · 昌列寺收录。因音频体积较大，可点击前往昌列寺官网在线收听。</div>'
        + '<a href="' + AUDIO_ALBUM + '" target="_blank" rel="noopener">前往昌列寺收听 ↗</a></div>');
    } else if (meta.tips){
      // 上师开示：一级目录默认折叠，显示引导语和文章数量
      var TEACHING_INTROS = {
        '信心之源': '伟大的传承、伟大的教法',
        '为什么要修行': '弄明白为什么出发，才不会走偏',
        '寻找上师': '修行路上最重要的选择',
        '如何依止上师': '找到了之后，怎样跟对人、走对路',
        '踏上实修之路': '从闻思到实修，一步步走起来',
        '做一个靠谱的修行人': '修行不是空谈，是做人做事',
        '积累福报与资粮': '修行路上的粮草和盘缠',
        '在生活中修行': '生活处处是修行',
        '跨越修行的障碍': '正是修行时...',
        '上师书信与节日开示': '上师的叮咛嘱咐...'
      };
      walkBlock(node, dirName, 0, '', true, TEACHING_INTROS).forEach(function(x){ html.push(x); });
    } else {
      // 其他目录（书籍、龙钦宁提传承等）：一级目录默认折叠，显示引导语
      var OTHER_INTROS = {
        '书籍': {
          '上师开示集': '上师开示合集',
          '上师推荐书目': '上师推荐的修行读物',
          '传承相关书籍': '龙钦宁提传承相关的经典著作'
        },
        '龙钦宁提传承': {
          '上师介绍': '上师的生平与事迹',
          '传承祖师': '历代传承祖师的传记'
        }
      };
      var introMap = OTHER_INTROS[dirName] || null;
      var useCollapsed = !!introMap;
      if (useCollapsed){
        // 添加工具栏
        html.push('<div class="dir-toolbar" style="display:flex;gap:.5rem;margin:.5rem 0 1rem;flex-wrap:wrap;">'
          + '<button class="dir-toggle-all-btn" onclick="toggleAllDirGroups(this)" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--gold-deep);background:transparent;color:var(--gold-deep);border-radius:4px;cursor:pointer;">展开全部目录</button>'
          + '<button class="dir-ai-search-btn" onclick="openSearchPanel()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">🔍 AI 搜索</button>'
          + '</div>');
      }
      walkBlock(node, dirName, 0, '', useCollapsed, introMap).forEach(function(x){ html.push(x); });
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
  // AI 问答入口（点击打开悬浮面板）
  html.push('<section class="hn-sec ai-ask-sec">');
  html.push('<h2 class="hn-sec-title">🤖 AI 问答</h2>');
  html.push('<p class="hn-desc">基于本站所收集整理的龙钦宁提相关资料，有问题随时向 AI 提问。回答仅供参考。</p>');
  html.push('<div class="ai-ask-card" onclick="openSearchPanel()" style="cursor:pointer;">');
  html.push('<div class="ai-ask-top-row"><div class="ai-ask-arrow">点击开始提问 →</div></div>');
  html.push('<div class="ai-ask-bottom-row"><div class="ai-ask-icon">💬</div>');
  html.push('<div class="ai-ask-text"><div class="ai-ask-title">龙的传人 · AI 问答</div><div class="ai-ask-desc">点击打开问答面板，AI 基于上师开示等资料为你解答</div></div></div>');
  html.push('</div>');
  html.push('</section>');
  return '<div class="home-nav">' + html.join('') + '</div>';
}

// ---- 目录 Index 完整目录树：展示该目录下所有层级的子目录+文章（类似首页导览，无需逐级点开）----
function renderFullDirTree(dirSlug){
  var dirPath = dirSlug.replace(/\/index$/, '');
  var node = TREE;
  var segs = dirPath.split('/');
  for (var i = 0; i < segs.length; i++){
    if (node && node.dirs) node = node.dirs[segs[i]];
    else return '';
  }
  if (!node) return '';
  // 各一级目录的引导语配置
  var DIR_INTROS = {
    '上师开示': {
      '信心之源': '伟大的传承、伟大的教法',
      '为什么要修行': '弄明白为什么出发，才不会走偏',
      '寻找上师': '修行路上最重要的选择',
      '如何依止上师': '找到了之后，怎样跟对人、走对路',
      '踏上实修之路': '从闻思到实修，一步步走起来',
      '做一个靠谱的修行人': '修行不是空谈，是做人做事',
      '积累福报与资粮': '修行路上的粮草和盘缠',
      '在生活中修行': '生活处处是修行',
      '跨越修行的障碍': '正是修行时...',
      '上师书信与节日开示': '上师的叮咛嘱咐...'
    },
    '音频资源': {
      '上师开示（AI朗读）': '文字转语音版开示，可直接收听',
      '上师法音': '上师亲诵的经咒与仪轨，可在线播放',
      '上师赞歌': '上师相关的赞颂歌曲'
    },
    '书籍': {
      '上师开示集': '上师开示合集',
      '上师推荐书目': '上师推荐的修行读物',
      '传承相关书籍': '龙钦宁提传承相关的经典著作'
    },
    '龙钦宁提传承': {
      '上师介绍': '上师的生平与事迹',
      '传承祖师': '历代传承祖师的传记'
    }
  };
  var topDir = segs[0];
  var introMap = DIR_INTROS[topDir] || null;
  var useCollapsed = !!introMap;  // 有引导语配置的目录使用默认折叠
  var arr = walkBlock(node, dirPath, 0, '', useCollapsed, introMap);
  if (!arr.length) return '';
  var html = '';
  // 有引导语配置的目录添加工具栏
  if (useCollapsed){
    html += '<div class="dir-toolbar" style="display:flex;gap:.5rem;margin:.5rem 0 1rem;flex-wrap:wrap;">'
      + '<button class="dir-toggle-all-btn" onclick="toggleAllDirGroups(this)" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--gold-deep);background:transparent;color:var(--gold-deep);border-radius:4px;cursor:pointer;">展开全部目录</button>'
      + '<button class="dir-ai-search-btn" onclick="openSearchPanel()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">🔍 AI 搜索</button>'
      + '</div>';
  }
  html += '<div class="dir-full-tree">' + arr.join('') + '</div>';
  return html;
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
  var subDirs = Object.keys(subDirMap).sort(naturalCompare);
  // 直属文章：slug = dirSlug/文章名（文章名不含 /）
  var items = [];
  PAGES.forEach(function(p){
    if (p.is_index) return;
    if (p.slug.indexOf(prefix) !== 0) return;
    var rest = p.slug.slice(prefix.length);
    if (rest.indexOf('/') === -1){
      var hasAudio = p && p.html && p.html.indexOf('play-btn') >= 0;
      items.push('<a class="hn-link" data-page="' + esc(p.slug) + '">'
        + esc(p.title) + '</a>');
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
  
  // 按文件夹分组（上师法音按照二级文件夹分组，其他按照一级文件夹分组）
  var groups = {};
  matched.forEach(function(o){
    var folderParts = o.f.split('/');
    var g;
    if (folderParts[0] && folderParts[0].indexOf('上师法音') >= 0 && folderParts.length > 1) {
      // 上师法音：使用二级文件夹名称
      g = cleanDirName(folderParts[1]);
    } else {
      // 其他：使用一级文件夹名称
      g = cleanDirName(folderParts[0]);
    }
    (groups[g] = groups[g] || []).push(o);
  });
  
  var total = matched.length;
  var title = folderKey
    ? ('「' + cleanDirName(folderKey.split('/').pop()) + '」音频（' + total + ' 篇）')
    : ('全部音频（' + total + ' 篇）');
  
  var html = '<div class="audio-list">';
  
  // 工具栏：展开全部 + 播放全部 + AI搜索
  html += '<div class="dir-toolbar" style="display:flex;gap:.5rem;margin:.5rem 0 1rem;flex-wrap:wrap;">'
    + '<button class="dir-toggle-all-btn" onclick="toggleAllAudioGroups(this)" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--gold-deep);background:transparent;color:var(--gold-deep);border-radius:4px;cursor:pointer;">展开全部</button>'
    + '<button class="dir-play-all-btn" onclick="playAllAudio()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">▶ 播放全部</button>'
    + '<button class="dir-ai-search-btn" onclick="openSearchPanel()" style="padding:.35rem .8rem;font-size:.85em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">🔍 AI 搜索</button>'
    + '</div>';
  
  // 按照指定顺序排序：上师开示（AI朗读）→ 上师赞歌 → 仪轨与经文 → 圣号与明咒
  var sortOrder = ['上师开示（AI朗读）', '上师赞歌', '仪轨与经文（上师亲诵）', '圣号与明咒（上师亲诵）'];
  var keys = Object.keys(groups).sort(function(a, b){
    var idxA = sortOrder.indexOf(a);
    var idxB = sortOrder.indexOf(b);
    if (idxA >= 0 && idxB >= 0) return idxA - idxB;
    if (idxA >= 0) return -1;
    if (idxB >= 0) return 1;
    return a < b ? -1 : 1;
  });
  
  keys.forEach(function(g, gi){
    var groupId = 'ag-' + gi + '-' + g.replace(/[^a-z0-9]/gi, '');
    html += '<div class="audio-group" data-group="' + groupId + '" style="margin:.5rem 0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface-soft);">'
      + '<div class="audio-group-header" onclick="toggleAudioGroup(this)" style="display:flex;align-items:center;gap:.5rem;padding:.7rem 1rem;cursor:pointer;">'
      + '<span class="audio-group-chev" style="font-size:.8em;color:var(--gold-deep);">▶</span>'
      + '<span class="audio-group-title" style="font-size:1.05em;color:var(--gold-deep);font-weight:700;flex:0 0 auto;">' + esc(g) + '</span>'
      + '<span class="audio-group-count" style="font-size:.85em;color:var(--ink-faint);flex:0 0 auto;margin-left:-.2rem;">(' + groups[g].length + ')</span>'
      + '<span class="audio-group-spacer"></span>'
      + '<button class="audio-group-play-btn" onclick="event.stopPropagation(); playAllAudio(\'' + esc(g).replace(/'/g, "\\'") + '\')" style="padding:.3rem .7rem;font-size:.8em;border:1px solid var(--accent);background:transparent;color:var(--accent);border-radius:4px;cursor:pointer;">▶ 播放专辑</button>'
      + '<span class="audio-group-hint" style="font-size:.75em;color:var(--ink-faint);opacity:.6;">点击展开</span>'
      + '</div>'
      + '<div class="audio-group-body" style="display:none;padding:.5rem 1rem 1rem;">';
    
    groups[g].forEach(function(o){
      // 所有音频统一显示为纯文本链接，不显示缩略图
      html += '<a class="hn-link hn-audio" data-idx="' + o.i + '" style="display:block;padding:.3rem 0;">' + esc(o.t.title) + '</a>';
    });
    html += '</div></div>';
  });
  
  // 《大圆满前行》有声书卡片
  html += '<div class="album-card" style="margin-top:1rem;padding:1rem;border:1px solid var(--gold-soft);border-radius:8px;background:var(--surface-soft);">'
    + '<div class="t" style="font-size:1.05em;font-weight:700;color:var(--ink);margin-bottom:.5rem;">《大圆满前行》有声书（226 集）</div>'
    + '<div class="d" style="font-size:.9em;color:var(--ink-soft);margin-bottom:.8rem;line-height:1.6;">嘎玛仁波切译 · 昌列寺收录。因音频体积较大，可点击前往昌列寺官网在线收听。</div>'
    + '<a href="' + AUDIO_ALBUM + '" target="_blank" rel="noopener" style="display:inline-block;padding:.4rem 1rem;border:1px solid var(--accent);color:var(--accent);border-radius:4px;text-decoration:none;font-size:.9em;">前往昌列寺收听 ↗</a>'
    + '</div>';
  
  html += '</div>';
  return html;
}

// 音频分组折叠/展开
function toggleAudioGroup(header){
  // 保存当前滚动位置，防止页面跳动
  var scrollPos = window.scrollY || window.pageYOffset;
  var body = header.nextElementSibling;
  var chev = header.querySelector('.audio-group-chev');
  var hint = header.querySelector('.audio-group-hint');
  if (body.style.display === 'none'){
    body.style.display = '';
    chev.textContent = '▼';
    hint.textContent = '点击收起';
  } else {
    body.style.display = 'none';
    chev.textContent = '▶';
    hint.textContent = '点击展开';
  }
  // 恢复滚动位置，防止页面跳动
  window.scrollTo(0, scrollPos);
}
// 三级目录展开/折叠
function toggleAudioSubGroup(header){
  // 保存当前滚动位置，防止页面跳动
  var scrollPos = window.scrollY || window.pageYOffset;
  var body = header.nextElementSibling;
  var chev = header.querySelector('.audio-subgroup-chev');
  if (body.style.display === 'none'){
    body.style.display = '';
    chev.textContent = '▼';
  } else {
    body.style.display = 'none';
    chev.textContent = '▶';
  }
  // 恢复滚动位置，防止页面跳动
  window.scrollTo(0, scrollPos);
}
// 展开/折叠所有音频分组
function toggleAllAudioGroups(btn){
  // 保存当前滚动位置，防止页面跳动
  var scrollPos = window.scrollY || window.pageYOffset;
  var isOpen = btn.textContent.indexOf('折叠') >= 0;
  var groups = document.querySelectorAll('.audio-group');
  groups.forEach(function(group){
    var header = group.querySelector('.audio-group-header');
    var body = group.querySelector('.audio-group-body');
    var chev = header.querySelector('.audio-group-chev');
    var hint = header.querySelector('.audio-group-hint');
    if (isOpen){
      body.style.display = 'none';
      chev.textContent = '▶';
      hint.textContent = '点击展开';
    } else {
      body.style.display = '';
      chev.textContent = '▼';
      hint.textContent = '点击收起';
    }
  });
  btn.textContent = isOpen ? '展开全部' : '折叠全部';
  // 恢复滚动位置，防止页面跳动
  window.scrollTo(0, scrollPos);
}
// 播放全部音频（从第一个开始，按顺序连播）
// 如果传入 albumName，则只播放该专辑的音频
var ORIGINAL_AUDIO_TRACKS = null;  // 保存原始播放列表
var CURRENT_ALBUM = null;  // 当前播放的专辑名称

function playAllAudio(albumName){
  if (!AUDIO_TRACKS.length) return;
  // 确保连播模式开启
  if (typeof autoNext !== 'undefined') autoNext = true;
  
  // 保存原始播放列表（只保存一次）
  if (!ORIGINAL_AUDIO_TRACKS) {
    ORIGINAL_AUDIO_TRACKS = AUDIO_TRACKS.slice();
  }
  
  if (albumName) {
    // 停止当前播放
    var player = document.getElementById('audioPlayer');
    if (player) {
      player.pause();
      player.currentTime = 0;
    }
    
    // 从原始列表中过滤指定专辑
    // 专辑名称直接匹配文件夹路径中的任意部分
    var albumTracks = ORIGINAL_AUDIO_TRACKS.filter(function(t){ 
      return t.folder && t.folder.indexOf(albumName) >= 0;
    });
    if (albumTracks.length > 0) {
      AUDIO_TRACKS = albumTracks;
      CURRENT_ALBUM = albumName;
      playTrack(0);
      return;
    }
  } else {
    // 播放全部：恢复原始列表
    if (ORIGINAL_AUDIO_TRACKS) {
      AUDIO_TRACKS = ORIGINAL_AUDIO_TRACKS.slice();
    }
    CURRENT_ALBUM = null;
  }
  playTrack(0);
}
// 海报大图查看
function showPosterBig(src, alt){
  var overlay = document.createElement('div');
  overlay.className = 'poster-overlay';
  overlay.onclick = function(){ document.body.removeChild(overlay); };
  var img = document.createElement('img');
  img.src = src;
  img.alt = alt || '';
  overlay.appendChild(img);
  document.body.appendChild(overlay);
}

// ===== 悬浮搜索/AI问答面板 =====
function openSearchPanel(){
  var panel = document.getElementById('searchPanel');
  panel.classList.add('open');
  // 聚焦到输入框
  setTimeout(function(){
    document.getElementById('searchPanelInput').focus();
  }, 100);
}

function closeSearchPanel(){
  document.getElementById('searchPanel').classList.remove('open');
  document.getElementById('searchPanelMinimized').style.display = 'none';
}

// 最小化搜索面板（显示缩略浮窗）
function minimizeSearchPanel(){
  document.getElementById('searchPanel').classList.remove('open');
  var minimized = document.getElementById('searchPanelMinimized');
  minimized.style.display = 'block';
  // 提取最新的AI回答内容摘要显示在缩略窗中
  try {
    var messages = document.getElementById('aiAskMessages');
    if (messages) {
      var answers = messages.querySelectorAll('span[style*="surface-soft"]');
      if (answers.length > 0) {
        var lastAnswer = answers[answers.length - 1];
        var text = lastAnswer.textContent || lastAnswer.innerText || '';
        // 去掉引用标记，只取前100字
        text = text.replace(/\[\d+\]/g, '').replace(/\s+/g, ' ').trim();
        if (text.length > 100) text = text.substring(0, 100) + '...';
        if (text) {
          document.getElementById('searchPanelMinimizedContent').textContent = text;
        }
      }
    }
  } catch(e) {}
}

// 恢复搜索面板
function restoreSearchPanel(){
  document.getElementById('searchPanelMinimized').style.display = 'none';
  document.getElementById('searchPanel').classList.add('open');
}

function switchSearchTab(tab){
  var tabs = document.querySelectorAll('.search-panel-tab');
  tabs.forEach(function(t){
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  document.getElementById('searchTabContent').style.display = tab === 'search' ? 'block' : 'none';
  document.getElementById('aiTabContent').style.display = tab === 'ai' ? 'block' : 'none';
}

// 面板搜索 + AI 问答（自动触发）
function doPanelSearch(){
  var q = document.getElementById('searchPanelInput').value.trim();
  var results = document.getElementById('searchPanelResults');
  var messages = document.getElementById('aiAskMessages');
  if (!q){
    results.innerHTML = '<p style="color:var(--ink-faint);font-size:.9em;text-align:center;padding:1rem;">输入关键词或问题开始搜索</p>';
    messages.innerHTML = '';
    return;
  }
  // 1. 本地关键词搜索（增强模糊匹配）
  var ql = q.toLowerCase();
  var matched = [];
  // 先尝试直接子串匹配
  PAGES.forEach(function(p){
    if (p.is_index || p.is_audio_detail || p.hide_from_nav) return;
    var title = (p.title || '').toLowerCase();
    var slug = (p.slug || '').toLowerCase();
    var text = (p.html || '').replace(/<[^>]+>/g, '').toLowerCase();
    if (title.indexOf(ql) >= 0 || slug.indexOf(ql) >= 0 || text.indexOf(ql) >= 0){
      matched.push(p);
    }
  });
  // 如果直接匹配没有结果，尝试模糊匹配（提取关键词）
  if (matched.length === 0){
    var fuzzyKeywords = [];
    var parts = q.split(/[\s，。？！、；：""''（）【】]+/).filter(function(k){ return k.length >= 1; });
    parts.forEach(function(p){
      if (p.length >= 2) fuzzyKeywords.push(p);
      if (p.length >= 3) {
        for (var len = 2; len <= Math.min(3, p.length); len++) {
          for (var i = 0; i <= p.length - len; i++) {
            fuzzyKeywords.push(p.substring(i, i + len));
          }
        }
      }
    });
    fuzzyKeywords = fuzzyKeywords.filter(function(v, i, a){ return a.indexOf(v) === i; });
    PAGES.forEach(function(p){
      if (p.is_index || p.is_audio_detail || p.hide_from_nav) return;
      var title = (p.title || '').toLowerCase();
      var text = (p.html || '').replace(/<[^>]+>/g, '').toLowerCase();
      var score = 0;
      fuzzyKeywords.forEach(function(kw){
        if (kw.length < 2) return;
        if (title.indexOf(kw) >= 0) score += 3;
        if (text.indexOf(kw) >= 0) score += 1;
      });
      if (score >= 2) matched.push(p);
    });
  }
  if (matched.length === 0){
    results.innerHTML = '<p style="color:var(--ink-faint);font-size:.9em;text-align:center;padding:1rem;">未找到相关文章</p>';
  } else {
    results.innerHTML = '<div style="font-weight:600;margin-bottom:.5rem;color:var(--ink-soft);">📚 相关文章（' + matched.length + '）</div>' +
      matched.slice(0, 10).map(function(p){
        var path = p.slug.replace(/\//g, ' / ');
        return '<div class="search-result-item" onclick="minimizeSearchPanel();show(\'' + p.slug.replace(/'/g, "\\'") + '\')">'
          + '<div class="sr-title">' + esc(p.title) + '</div>'
          + '<div class="sr-path">' + esc(path) + '</div></div>';
      }).join('');
  }
  // 2. AI 问答（自动触发）
  sendAiAsk(q);
}

// ===== AI 问答功能 =====
var AI_API_ENDPOINT = 'https://steep-rain-0d77longchen-ai-ask.drimednor.workers.dev';  // Cloudflare Workers 代理地址（配置后启用）
var AI_API_KEY = '';        // API Key（通过代理传递，不在前端暴露）

// 展开/收起问答框
function toggleAiAsk(){
  // 兼容旧调用：打开悬浮面板
  openSearchPanel();
}

// 本地知识库搜索：关键词匹配，返回最相关的前3篇文章
function searchKnowledge(question){
  // 同义词/近义词词典（用于模糊匹配）
  var synonyms = {
    "上师": ["上师", "善知识", "师父", "师尊", "喇嘛", "仁波切"],
    "依止": ["依止", "依止上师", "跟随", "亲近", "依教奉行"],
    "修行": ["修行", "修持", "实修", "修炼", "用功", "办道"],
    "信心": ["信心", "信念", "相信", "信赖", "不退转"],
    "无常": ["无常", "诸行无常", "死亡", "生死", "短暂"],
    "菩提心": ["菩提心", "发心", "利他", "慈悲", "菩萨心"],
    "空性": ["空性", "缘起", "性空", "般若", "智慧"],
    "戒律": ["戒律", "持戒", "戒", "规矩", "规范"],
    "福报": ["福报", "资粮", "功德", "善根", "福德"],
    "回向": ["回向", "功德回向", "回向功德"],
    "皈依": ["皈依", "皈依三宝", "皈依佛门"],
    "发愿": ["发愿", "愿", "誓愿", "愿力"],
    "打坐": ["打坐", "静坐", "禅修", "冥想", "坐禅"],
    "念诵": ["念诵", "念经", "持咒", "念咒", "诵读"],
    "烦恼": ["烦恼", "妄念", "杂念", "情绪", "痛苦"],
    "心": ["心", "心念", "内心", "心灵", "心性"],
    "生活": ["生活", "日常", "平时", "工作", "家庭"],
    "婚姻": ["婚姻", "爱情", "感情", "家庭", "伴侣"],
    "死亡": ["死亡", "死", "无常", "生死", "中阴"],
    "疾病": ["疾病", "病", "病痛", "身体", "健康"],
    "传承": ["传承", "法脉", "法系", "源流"],
    "龙钦": ["龙钦", "龙钦宁提", "宁提", "大圆满"],
    "多智钦": ["多智钦", "多智钦寺", "龙洋", "仁波切"],
  };
  
  // 提取关键词（更细粒度）
  var keywords = [];
  // 先按标点分割
  var parts = question.split(/[\s，。？！、；：""''（）【】]+/).filter(function(k){ return k.length >= 1; });
  parts.forEach(function(p){
    if (p.length >= 2) keywords.push(p);
    // 对长词再进行2-4字的子串提取
    if (p.length >= 4) {
      for (var len = 2; len <= Math.min(4, p.length); len++) {
        for (var i = 0; i <= p.length - len; i++) {
          keywords.push(p.substring(i, i + len));
        }
      }
    }
  });
  // 去重
  keywords = keywords.filter(function(v, i, a){ return a.indexOf(v) === i; });
  
  // 扩展同义词
  var expandedKeywords = [];
  keywords.forEach(function(kw){
    expandedKeywords.push(kw);
    for (var key in synonyms) {
      if (kw.indexOf(key) >= 0 || key.indexOf(kw) >= 0) {
        synonyms[key].forEach(function(syn){
          if (expandedKeywords.indexOf(syn) < 0) {
            expandedKeywords.push(syn);
          }
        });
      }
    }
  });
  
  var results = [];
  KNOWLEDGE_BASE.forEach(function(item){
    var score = 0;
    var title = item.title || '';
    var content = item.content || '';
    var tags = item.tags || [];
    
    expandedKeywords.forEach(function(kw){
      if (kw.length < 2) return;
      // 标题匹配权重高
      if (title.indexOf(kw) >= 0) score += 5;
      // 内容匹配
      if (content.indexOf(kw) >= 0) score += 1;
      // tags匹配
      if (tags && tags.length > 0) {
        tags.forEach(function(tag){
          if (tag.indexOf(kw) >= 0 || kw.indexOf(tag) >= 0) score += 3;
        });
      }
    });
    
    // 模糊匹配：计算问题与标题的字符重叠度
    var overlap = 0;
    for (var i = 0; i < question.length; i++) {
      if (title.indexOf(question[i]) >= 0) overlap++;
    }
    if (overlap >= Math.min(3, question.length * 0.5)) {
      score += overlap * 0.5;
    }
    
    if (score > 0) results.push({item: item, score: score});
  });
  
  results.sort(function(a, b){ return b.score - a.score; });
  
  // 过滤规则1：永远不要引用更新日志
  results = results.filter(function(r){
    return r.item.slug.indexOf('更新日志') < 0 && r.item.slug.indexOf('changelog') < 0;
  });
  
  // 过滤规则2：如果上师开示目录下有匹配的文章，则不显示书籍中的三部开示集
  var hasTeachingsMatch = results.some(function(r){
    return r.item.slug.indexOf('上师开示/') === 0;
  });
  if (hasTeachingsMatch){
    var excludedBooks = ['做一个真正的修行人', '师尊龙洋仁波切开示集', '自在人生之路'];
    results = results.filter(function(r){
      if (r.item.slug.indexOf('书籍/') !== 0) return true;
      for (var i = 0; i < excludedBooks.length; i++) {
        if (r.item.title.indexOf(excludedBooks[i]) >= 0) return false;
      }
      return true;
    });
  }
  
  // 返回得分最高的5篇
  return results.slice(0, 5).map(function(r){ return r.item; });
}

// 发送问题（接受可选 question 参数）
function sendAiAsk(question){
  if (!question){
    question = document.getElementById('searchPanelInput').value.trim();
  }
  if (!question) return;
  var messages = document.getElementById('aiAskMessages');

  // 显示用户问题
  messages.innerHTML = '<div style="text-align:right;margin:.5rem 0;"><span style="display:inline-block;background:var(--accent);color:#fff;padding:.5rem .8rem;border-radius:12px 12px 2px 12px;max-width:80%;">' + esc(question) + '</span></div>';

  // 搜索相关内容
  var related = searchKnowledge(question);
  var hasContext = related.length > 0;

  // 显示"正在思考"
  var thinkingId = 'ai-thinking-' + Date.now();
  var thinkingText = hasContext ? '正在基于本站内容思考...' : '正在基于通用知识思考...';
  messages.innerHTML += '<div id="' + thinkingId + '" style="text-align:left;margin:.5rem 0;color:var(--ink-faint);">' + thinkingText + '</div>';
  messages.scrollTop = messages.scrollHeight;

  // 如果未配置 API，显示本地搜索结果（降级模式）
  if (!AI_API_ENDPOINT){
    if (hasContext){
      var answer = '根据本站相关文章：\n\n';
      related.forEach(function(item, idx){
        answer += (idx+1) + '. 《' + item.title + '》\n';
        answer += item.content.slice(0, 200) + '...\n';
        answer += '[查看全文](#' + item.slug + ')\n\n';
      });
      answer += '（AI 代理未配置，当前显示相关文章摘要。配置 API 后可获得智能回答。）';
    } else {
      var answer = '本网站未收集到相关资料，以下内容由 AI 基于通用知识生成，可能与本网站观点不一致，请谨慎参考。\n\n（AI 代理未配置，无法生成智能回答。配置 API 后可获得基于通用知识的回答。）';
    }
    document.getElementById(thinkingId).remove();
    messages.innerHTML += '<div style="text-align:left;margin:.5rem 0;"><span style="display:inline-block;background:var(--surface-soft);color:var(--ink);padding:.7rem 1rem;border-radius:12px 12px 12px 2px;max-width:90%;white-space:pre-wrap;line-height:1.7;">' + esc(answer) + '</span></div>';
    messages.scrollTop = messages.scrollHeight;
    return;
  }

  // 调用 API（通过 Cloudflare Workers 代理）
  var context = hasContext ? related.map(function(item){
    return '《' + item.title + '》\n' + item.content;
  }).join('\n\n---\n\n') : '';

  fetch(AI_API_ENDPOINT, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      question: question,
      context: context,
      related: related.map(function(r){ return {title: r.title, slug: r.slug}; })
    })
  }).then(function(r){ return r.json(); })
  .then(function(data){
    document.getElementById(thinkingId).remove();
    var answer = data.answer || data.response || '抱歉，AI 暂时无法回答，请稍后再试。';
    var answerHtml = '<div style="text-align:left;margin:.5rem 0;"><span style="display:inline-block;background:var(--surface-soft);color:var(--ink);padding:.7rem 1rem;border-radius:12px 12px 12px 2px;max-width:90%;white-space:pre-wrap;line-height:1.7;">' + esc(answer) + '</span></div>';
    // 如果有参考资料，在回答末尾添加引用来源列表
    if (hasContext && related && related.length > 0){
      answerHtml += '<div style="text-align:left;margin:.3rem 0 .5rem 0;padding-left:.5rem;">'
        + '<div style="font-size:.8em;color:var(--ink-faint);margin-bottom:.3rem;">📚 引用来源（点击跳转）：</div>'
        + related.map(function(item, idx){
            var path = item.slug.replace(/\//g, ' / ');
            return '<div class="search-result-item" style="padding:.25rem .5rem;margin:.15rem 0;font-size:.85em;cursor:pointer;border-radius:4px;" onclick="minimizeSearchPanel();show(\'' + item.slug.replace(/'/g, "\\'") + '\')">'
              + '<div style="display:flex;align-items:baseline;gap:.3rem;">'
              + '<span style="color:var(--gold-deep);font-weight:600;flex:0 0 auto;">[' + (idx+1) + ']</span>'
              + '<span style="font-weight:500;">' + esc(item.title) + '</span>'
              + '</div>'
              + '<div style="font-size:.75em;color:var(--ink-faint);padding-left:1.2rem;margin-top:.1rem;">' + esc(path) + '</div>'
              + '</div>';
          }).join('')
        + '</div>';
    }
    messages.innerHTML += answerHtml;
    messages.scrollTop = messages.scrollHeight;
  }).catch(function(err){
    document.getElementById(thinkingId).remove();
    messages.innerHTML += '<div style="text-align:left;margin:.5rem 0;color:#c0392b;">调用失败：' + esc(err.message) + '</div>';
  });
}





// 根据经咒标题播放音频
function playMantra(title){
  for (var i = 0; i < AUDIO_TRACKS.length; i++){
    if (AUDIO_TRACKS[i].title === title){
      playTrack(i);
      return;
    }
  }
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
// 播放进度记忆：每5秒保存一次
playerAudio.addEventListener('timeupdate', function(){
  if (curIdx >= 0 && playerAudio.currentTime > 5) {
    try { localStorage.setItem('longchen-audio-pos-' + curIdx, String(playerAudio.currentTime)); } catch(e){}
  }
});
// 播放结束时清除进度记忆
playerAudio.addEventListener('ended', function(){
  if (curIdx >= 0) {
    try { localStorage.removeItem('longchen-audio-pos-' + curIdx); } catch(e){}
  }
});
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
  // 停止音频播放
  if (playerAudio) {
    playerAudio.pause();
    playerAudio.currentTime = 0;
  }
  // 恢复原始播放列表
  if (ORIGINAL_AUDIO_TRACKS) {
    AUDIO_TRACKS = ORIGINAL_AUDIO_TRACKS.slice();
    ORIGINAL_AUDIO_TRACKS = null;
    CURRENT_ALBUM = null;
  }
  curIdx = -1;
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
  // 音频播放统计：计算上一个音频的播放时长并上报
  var now = Date.now() / 1000;
  if (audioPlayName && audioPlayStartTime) {
    reportAudioPlay(audioPlayName, now - audioPlayStartTime);
  }
  curIdx = idx;
  var t = AUDIO_TRACKS[idx];
  audioPlayName = t.title;
  audioPlayStartTime = now;
  playerAudio.src = t.src;
  playerAudio.playbackRate = SPEEDS[speedIdx];
  // 恢复上次播放进度（如果有保存）
  var savedPos = 0;
  try { savedPos = parseFloat(localStorage.getItem('longchen-audio-pos-' + idx) || '0'); } catch(e){}
  if (savedPos > 0 && savedPos < (t.duration || 99999)) {
    playerAudio.currentTime = savedPos;
  }
  playerAudio.play();
  // 保存当前播放
  try { localStorage.setItem('longchen-audio-cur', String(idx)); } catch(e){}
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
  // 音频播放统计：播放时重置开始时间
  audioPlayStartTime = Date.now() / 1000;
});
playerAudio.addEventListener('pause', function(){
  document.getElementById('pPlay').textContent = '▶'; updateMini();
  if ('mediaSession' in navigator){ try{ navigator.mediaSession.playbackState = 'paused'; }catch(e){} }
  // 音频播放统计：暂停时上报播放时长
  var now = Date.now() / 1000;
  if (audioPlayName && audioPlayStartTime) {
    reportAudioPlay(audioPlayName, now - audioPlayStartTime);
    audioPlayStartTime = 0;
  }
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
// 关闭叉号：完全关闭播放器，显示"播放器"悬浮按钮
document.getElementById('pClose').onclick = function(){
  hidePlayer();
};
// 最小化按钮：折叠为底部迷你条，音频继续后台播放
document.getElementById('pMinimize').onclick = function(){
  minimizePlayer();
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
}



);
document.addEventListener('click', closeAllSpeedMenus);
document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeAllSpeedMenus(); });
applySpeed();   // 初始化按钮文案与默认高亮
// 悬浮按钮：打开播放器（点击事件已在拖动功能中处理）
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
// 搜索框已移除，改用悬浮搜索面板
// document.getElementById('search').addEventListener('input', function(){ ... });

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

// ---- 悬浮搜索/AI问答面板 ----
var searchPanel = document.getElementById('searchPanel');
if (searchPanel) searchPanel.addEventListener('click', function(e){
  if (e.target === searchPanel) closeSearchPanel();
});
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape' && document.getElementById('searchPanel').classList.contains('open')){
    closeSearchPanel();
  }
});
doPanelSearch();

// ---- 悬浮按钮拖动功能 ----
(function(){
  var btn = document.getElementById('fabSearch');
  if (!btn) return;

  var isDragging = false;
  var startX, startY, startLeft, startTop;
  var hasMoved = false;
  var suppressClick = false;

  // 从 localStorage 恢复位置
  var savedPos = localStorage.getItem('fabSearchPos');
  if (savedPos) {
    try {
      var pos = JSON.parse(savedPos);
      btn.style.left = pos.left + 'px';
      btn.style.top = pos.top + 'px';
      btn.style.right = 'auto';
    } catch(e) {}
  }

  function getEventPos(e) {
    if (e.touches && e.touches.length > 0) {
      return { x: e.touches[0].clientX, y: e.touches[0].clientY };
    }
    return { x: e.clientX, y: e.clientY };
  }

  function onStart(e) {
    isDragging = true;
    hasMoved = false;
    var pos = getEventPos(e);
    startX = pos.x;
    startY = pos.y;
    var rect = btn.getBoundingClientRect();
    startLeft = rect.left;
    startTop = rect.top;
    // 拖动开始时移除贴边状态
    btn.classList.remove('edge-left', 'edge-right');
    btn.style.left = startLeft + 'px';
    btn.style.right = 'auto';
    btn.classList.add('dragging');
  }

  function onMove(e) {
    if (!isDragging) return;
    var pos = getEventPos(e);
    var dx = pos.x - startX;
    var dy = pos.y - startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      hasMoved = true;
      suppressClick = true;
    }
    if (!hasMoved) return;  // 还没开始拖动，不移动
    var newLeft = startLeft + dx;
    var newTop = startTop + dy;
    // 限制在视口范围内
    var maxLeft = window.innerWidth - btn.offsetWidth - 5;
    var maxTop = window.innerHeight - btn.offsetHeight - 5;
    newLeft = Math.max(5, Math.min(newLeft, maxLeft));
    newTop = Math.max(5, Math.min(newTop, maxTop));
    btn.style.left = newLeft + 'px';
    btn.style.top = newTop + 'px';
    btn.style.right = 'auto';
    e.preventDefault();
  }

  function onEnd(e) {
    if (!isDragging) return;
    isDragging = false;
    btn.classList.remove('dragging');
    if (hasMoved) {
      var rect = btn.getBoundingClientRect();
      var edgeThreshold = 60;
      // 靠边自动隐藏
      if (rect.left < edgeThreshold) {
        btn.classList.add('edge-left');
        btn.style.left = '0px';
        btn.style.right = 'auto';
      } else if (rect.left + rect.width > window.innerWidth - edgeThreshold) {
        btn.classList.add('edge-right');
        btn.style.right = '0px';
        btn.style.left = 'auto';
      } else {
        btn.classList.remove('edge-left', 'edge-right');
      }
      // 保存位置
      var newRect = btn.getBoundingClientRect();
      localStorage.setItem('fabSearchPos', JSON.stringify({
        left: newRect.left,
        top: newRect.top,
        edge: btn.classList.contains('edge-left') ? 'left' : (btn.classList.contains('edge-right') ? 'right' : null)
      }));
      // 拖动后阻止 click 事件
      setTimeout(function(){ suppressClick = false; }, 100);
    }
  }

  // 点击事件（拖动时被 suppressClick 阻止）
  btn.addEventListener('click', function(e){
    if (suppressClick) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    openSearchPanel('search');
  });

  btn.addEventListener('mousedown', onStart);
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onEnd);
  btn.addEventListener('touchstart', onStart, { passive: false });
  document.addEventListener('touchmove', onMove, { passive: false });
  document.addEventListener('touchend', onEnd);
})();

// ---- 播放器按钮拖动功能 ----
(function(){
  var btn = document.getElementById('playerLaunch');
  if (!btn) return;

  var isDragging = false;
  var startX, startY, startLeft, startTop;
  var hasMoved = false;
  var suppressClick = false;

  // 从 localStorage 恢复位置
  var savedPos = localStorage.getItem('playerLaunchPos');
  if (savedPos) {
    try {
      var pos = JSON.parse(savedPos);
      btn.style.left = pos.left + 'px';
      btn.style.top = pos.top + 'px';
      btn.style.right = 'auto';
      btn.style.bottom = 'auto';
    } catch(e) {}
  }

  function getEventPos(e) {
    if (e.touches && e.touches.length > 0) {
      return { x: e.touches[0].clientX, y: e.touches[0].clientY };
    }
    return { x: e.clientX, y: e.clientY };
  }

  function onStart(e) {
    isDragging = true;
    hasMoved = false;
    var pos = getEventPos(e);
    startX = pos.x;
    startY = pos.y;
    var rect = btn.getBoundingClientRect();
    startLeft = rect.left;
    startTop = rect.top;
    // 拖动开始时移除贴边状态
    btn.classList.remove('edge-left', 'edge-right');
    btn.style.left = startLeft + 'px';
    btn.style.right = 'auto';
    btn.classList.add('dragging');
  }

  function onMove(e) {
    if (!isDragging) return;
    var pos = getEventPos(e);
    var dx = pos.x - startX;
    var dy = pos.y - startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      hasMoved = true;
      suppressClick = true;
    }
    if (!hasMoved) return;
    var newLeft = startLeft + dx;
    var newTop = startTop + dy;
    var maxLeft = window.innerWidth - btn.offsetWidth - 5;
    var maxTop = window.innerHeight - btn.offsetHeight - 5;
    newLeft = Math.max(5, Math.min(newLeft, maxLeft));
    newTop = Math.max(5, Math.min(newTop, maxTop));
    btn.style.left = newLeft + 'px';
    btn.style.top = newTop + 'px';
    btn.style.right = 'auto';
    btn.style.bottom = 'auto';
    e.preventDefault();
  }

  function onEnd(e) {
    if (!isDragging) return;
    isDragging = false;
    btn.classList.remove('dragging');
    if (hasMoved) {
      var rect = btn.getBoundingClientRect();
      var edgeThreshold = 60;
      // 靠边自动隐藏
      if (rect.left < edgeThreshold) {
        btn.classList.add('edge-left');
        btn.style.left = '0px';
        btn.style.right = 'auto';
      } else if (rect.left + rect.width > window.innerWidth - edgeThreshold) {
        btn.classList.add('edge-right');
        btn.style.right = '0px';
        btn.style.left = 'auto';
      } else {
        btn.classList.remove('edge-left', 'edge-right');
      }
      // 保存位置
      var newRect = btn.getBoundingClientRect();
      localStorage.setItem('playerLaunchPos', JSON.stringify({
        left: newRect.left,
        top: newRect.top,
        edge: btn.classList.contains('edge-left') ? 'left' : (btn.classList.contains('edge-right') ? 'right' : null)
      }));
      setTimeout(function(){ suppressClick = false; }, 100);
    }
  }

  // 点击事件（拖动时被阻止）
  btn.addEventListener('click', function(e){
    if (suppressClick) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    // 打开播放器
    document.getElementById('player').classList.add('show');
    document.getElementById('playerMini').classList.remove('show');
    refreshLaunch();
  });

  btn.addEventListener('mousedown', onStart);
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onEnd);
  btn.addEventListener('touchstart', onStart, { passive: false });
  document.addEventListener('touchmove', onMove, { passive: false });
  document.addEventListener('touchend', onEnd);
})();

// ---- 划线系统：选中文字弹出工具栏，已划线点击取消 ----
// 用 selectionchange 检测选区（比 mouseup/touchend 更可靠，尤其手机端长按选中）
document.addEventListener('selectionchange', function(){
  var sel = window.getSelection();
  if (!sel || sel.rangeCount === 0){ hideSelToolbar(); return; }
  var text = sel.toString().trim();
  if (!text || text.length < 2){ hideSelToolbar(); return; }
  var range = sel.getRangeAt(0);
  var container = range.commonAncestorContainer;
  var el = container.nodeType === 1 ? container : container.parentElement;
  if (el && el.closest('.article')){
    showSelToolbar();
  } else {
    hideSelToolbar();
  }
});
// 手机端补充：touchend 后延迟检查选区（部分浏览器 selectionchange 触发不稳定）
document.addEventListener('touchend', function(e){
  if (!e.target.closest('.article')) return;
  setTimeout(function(){
    var sel = window.getSelection();
    if (sel && sel.rangeCount > 0){
      var text = sel.toString().trim();
      if (text && text.length >= 2) showSelToolbar();
    }
  }, 300);
});
// 点击非工具栏区域隐藏
document.addEventListener('mousedown', function(e){
  if (selToolbar && !selToolbar.contains(e.target)) hideSelToolbar();
  if (hlToolbar && !hlToolbar.contains(e.target)) hideHlToolbar();
});
// 已划线文字点击 → 弹出操作菜单（取消划线/复制/分享）
var hlToolbar = null;
function initHlToolbar(){
  if (hlToolbar) return;
  hlToolbar = document.createElement('div');
  hlToolbar.className = 'sel-toolbar hl-toolbar';
  hlToolbar.style.display = 'none';
  hlToolbar.innerHTML = '<button data-act="remove">取消划线</button>'
    + '<div class="st-sep"></div>'
    + '<button data-act="copy">复制</button>'
    + '<div class="st-sep"></div>'
    + '<button data-act="share">分享</button>';
  document.body.appendChild(hlToolbar);
  hlToolbar.addEventListener('mousedown', function(e){ e.preventDefault(); });
  hlToolbar.querySelectorAll('button').forEach(function(b){
    b.onclick = function(){
      var act = b.dataset.act;
      var hl = hlToolbar._target;
      if (!hl){ hideHlToolbar(); return; }
      var text = hl.textContent;
      if (act === 'remove'){
        var parent = hl.parentNode;
        while (hl.firstChild) parent.insertBefore(hl.firstChild, hl);
        parent.removeChild(hl);
        parent.normalize();
        removeHighlight(currentSlug, text);
        toast('已取消划线');
      } else if (act === 'copy'){
        copyText(text); toast('已复制');
      } else if (act === 'share'){
        shareHighlight(text);
      }
      hideHlToolbar();
    };
  });
}




function showHlToolbar(hl){
  initHlToolbar();
  hlToolbar._target = hl;
  var rect = hl.getBoundingClientRect();
  hlToolbar.style.display = 'flex';
  var tbW = hlToolbar.offsetWidth;
  var left = rect.left + rect.width / 2 - tbW / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tbW - 8));
  var isMobile = window.innerWidth <= 760;
  var top = isMobile ? rect.bottom + 8 : rect.top - hlToolbar.offsetHeight - 8;
  if (top < 8 || top + hlToolbar.offsetHeight > window.innerHeight - 8) top = rect.bottom + 8;
  hlToolbar.style.left = left + 'px';
  hlToolbar.style.top = top + 'px';
}
function hideHlToolbar(){ if (hlToolbar) hlToolbar.style.display = 'none'; }
document.addEventListener('click', function(e){
  var hl = e.target.closest('.hl');
  if (hl && hl.closest('.article')){
    e.preventDefault();
    e.stopPropagation();
    showHlToolbar(hl);
  }
});

// ---- 阅读进度记忆：记录每篇文章滚动位置，下次打开自动恢复 ----
var SCROLL_KEY = 'longchen-scroll-';
var scrollTimer = null;
window.addEventListener('scroll', function(){
  if (!currentSlug || currentSlug === 'index') return;
  if (scrollTimer) clearTimeout(scrollTimer);
  scrollTimer = setTimeout(function(){
    localStorage.setItem(SCROLL_KEY + currentSlug, String(window.scrollY));
  }, 300);
});

// 目录弹层：插入 DOM 并绑定关闭/遮罩点击
var dirPopEl = document.createElement('div');
dirPopEl.id = 'dirPop';
dirPopEl.className = 'dir-pop';
dirPopEl.innerHTML = '<div class="dir-pop-mask"></div>'
  + '<div class="dir-pop-panel">'
  + '<div class="dir-pop-head"><span id="dirPopTitle"></span><button class="dir-pop-x" title="关闭">✕</button></div>'
  + '<div class="dir-pop-body" id="dirPopBody"></div>'
  + '</div>';
document.body.appendChild(dirPopEl);
document.querySelector('#dirPop .dir-pop-mask').onclick = closeDirPop;
document.querySelector('#dirPop .dir-pop-x').onclick = closeDirPop;

// ---- Hash 路由：读取 URL 中的 #/文章路径 定位文章；支持浏览器前进/后退 ----
function slugFromHash(){
  if (location.hash && location.hash.indexOf('#/') === 0){
    var h = location.hash.slice(2).split('/').map(function(s){
      try { return decodeURIComponent(s); } catch(e){ return s; }
    }).join('/');
    return h;  // 不管页面是否存在都返回，由 show() 处理 404
  }
  return null;
}
window.addEventListener('hashchange', function(){
  var s = slugFromHash();
  if (s) show(s);
  else { var home = TREE.children && TREE.children.find(function(c){ return c.is_index; }); show(home ? home.slug : PAGES[0].slug); }
});
var initSlug = slugFromHash();
if (initSlug){ show(initSlug); }
else { var home = TREE.children && TREE.children.find(function(c){ return c.is_index; }); show(home ? home.slug : PAGES[0].slug); }
// 恢复上次播放的音频（仅加载，不自动播放）
setTimeout(function(){
  try {
    var savedIdx = parseInt(localStorage.getItem('longchen-audio-cur') || '-1', 10);
    if (savedIdx >= 0 && savedIdx < AUDIO_TRACKS.length) {
      curIdx = savedIdx;
      var t = AUDIO_TRACKS[savedIdx];
      playerAudio.src = t.src;
      var savedPos = parseFloat(localStorage.getItem('longchen-audio-pos-' + savedIdx) || '0');
      if (savedPos > 0) playerAudio.currentTime = savedPos;
      document.getElementById('pStatusText').innerHTML = '上次播放：<b>' + esc(t.title) + '</b>' + (savedPos > 0 ? '（点击继续）' : '');
      document.getElementById('pPlay').textContent = '▶';
      renderPlist();
      updatePlayBtns();
    }
  } catch(e){}
}, 1000);

// ---- 返回顶部按钮 ----
window.addEventListener('scroll', function(){
  var btn = document.getElementById('backToTop');
  if (!btn) return;
  if (window.scrollY > 400) btn.classList.add('visible');
  else btn.classList.remove('visible');
});
document.addEventListener('click', function(e){
  if (e.target.id === 'backToTop'){
    window.scrollTo({top:0, behavior:'smooth'});
  }
});
// ---- 页面访问次数统计（localStorage 本地计数，每页独立）----
// 说明：纯静态站无后端，用 localStorage 记录每个页面在本设备的访问次数。
// 如需跨用户统计，可接入 GoatCounter（免费）等服务。
function trackPageView(){
  try {
    var slug = currentSlug || 'index';
    var key = 'longchen-pv-' + slug;
    var count = parseInt(localStorage.getItem(key) || '0', 10) + 1;
    localStorage.setItem(key, String(count));
    // 全站总访问
    var totalKey = 'longchen-pv-total';
    var total = parseInt(localStorage.getItem(totalKey) || '0', 10) + 1;
    localStorage.setItem(totalKey, String(total));
    return count;
  } catch(e){ return 0; }
}
function showPageViews(){
  var box = document.getElementById('pageViews');
  if (!box) return;
  try {
    var slug = currentSlug || 'index';
    var count = parseInt(localStorage.getItem('longchen-pv-' + slug) || '0', 10);
    var total = parseInt(localStorage.getItem('longchen-pv-total') || '0', 10);
    box.textContent = '本页已访问 ' + count + ' 次 · 全站累计 ' + total + ' 次';
    box.style.display = 'inline-block';
  } catch(e){}
}
trackPageView();
</script>
<footer class="site-footer">
  <div class="footer-inner" style="flex-direction:column; align-items:flex-start; gap:.6rem">
    <span class="footer-copy">© 2026 龙的传人｜Longchen Nyingtik</span>
  </div>
</footer>
<button class="back-top" id="backTop" title="回到顶部">↑</button>
<script>
document.getElementById('backTop').onclick = function(){ window.scrollTo({top:0, behavior:'smooth'}); };
window.addEventListener('scroll', function(){
  document.getElementById('backTop').style.opacity = window.scrollY > 300 ? '1' : '0';
});
</script>
@@WATCH_SCRIPT@@
<script>
/* ===== 文章内容按需加载模块 =====
 * 在原始show函数之后加载，重写show函数实现按需加载
 */
(function(){
  // 已加载的文章内容缓存
  var pageContentCache = {};
  // 正在加载的文章，避免重复请求
  var pageLoading = {};
  // 保存原始的show函数
  var originalShow = window.show;

  // 生成安全的文件名（与构建器一致）
  function getSafeFilename(slug) {
    return slug.replace(/\//g, "__").replace(/ /g, "_").replace(/[?？:："'<>*|]/g, "");
  }

  // 加载文章内容
  function loadPageContent(slug) {
    return new Promise(function(resolve, reject) {
      // 已缓存，直接返回
      if (pageContentCache[slug]) {
        resolve(pageContentCache[slug]);
        return;
      }
      // 正在加载，等待完成
      if (pageLoading[slug]) {
        pageLoading[slug].push({resolve: resolve, reject: reject});
        return;
      }
      // 开始加载
      pageLoading[slug] = [{resolve: resolve, reject: reject}];
      var url = "pages/" + getSafeFilename(slug) + ".json";
      fetch(url, {cache: "force-cache"})
        .then(function(r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function(data) {
          pageContentCache[slug] = data;
          var waiters = pageLoading[slug] || [];
          delete pageLoading[slug];
          waiters.forEach(function(w) { w.resolve(data); });
        })
        .catch(function(err) {
          delete pageLoading[slug];
          var waiters = pageLoading[slug] || [];
          waiters.forEach(function(w) { w.reject(err); });
        });
    });
  }

  // 重写show函数
  window.show = function(slug) {
    var p = window.bySlug ? window.bySlug[slug] : null;
    if (!p) {
      // 没有找到页面，调用原始show函数处理404
      if (originalShow) originalShow(slug);
      return;
    }

    // 如果不需要按需加载，或者是目录页，直接调用原始show函数
    if (!p._need_load || p.is_index || slug === "index") {
      if (originalShow) originalShow(slug);
      return;
    }

    // 需要按需加载
    // 先显示加载状态（简化版，直接设置内容）
    var contentEl = document.getElementById('content');
    if (contentEl) {
      contentEl.innerHTML = '<div class="article"><div style="text-align:center;padding:3rem 0;color:var(--ink-faint);"><div style="font-size:2rem;margin-bottom:1rem;">📖</div><div>正在加载文章内容...</div></div></div>';
    }

    // 加载文章内容
    loadPageContent(slug).then(function(data) {
      // 加载成功，把内容赋值给p对象，然后调用原始show函数
      p.html = data.html;
      p.meta = data.meta || p.meta;
      p.tags = data.tags || p.tags;
      p._need_load = false; // 标记已加载，避免重复加载
      // 调用原始show函数渲染
      if (originalShow) originalShow(slug);
    }).catch(function(err) {
      // 加载失败
      if (contentEl) {
        contentEl.innerHTML = '<div class="article"><div style="text-align:center;padding:3rem 0;color:var(--ink-faint);"><div style="font-size:2rem;margin-bottom:1rem;">⚠️</div><div>文章内容加载失败</div><div style="font-size:.85rem;margin-top:.5rem;">' + (err.message || '') + '</div><button onclick="location.reload()" style="margin-top:1rem;padding:.5rem 1rem;border-radius:8px;border:1px solid var(--accent);background:var(--accent-soft);color:var(--accent-deep);cursor:pointer;">重新加载</button></div></div>';
      }
    });
  };

  // 暴露loadPageContent函数供外部使用
  window.loadPageContent = loadPageContent;
})();

</script>
<script>
/* ===== 文章内容按需加载模块 =====
 * 在原始show函数之后加载，重写show函数实现按需加载
 */
(function(){
  // 已加载的文章内容缓存
  var pageContentCache = {};
  // 正在加载的文章，避免重复请求
  var pageLoading = {};
  // 保存原始的show函数
  var originalShow = window.show;

  // 生成安全的文件名（与构建器一致）
  function getSafeFilename(slug) {
    return slug.replace(/\//g, "__").replace(/ /g, "_").replace(/[?？:："'<>*|]/g, "");
  }

  // 加载文章内容
  function loadPageContent(slug) {
    return new Promise(function(resolve, reject) {
      // 已缓存，直接返回
      if (pageContentCache[slug]) {
        resolve(pageContentCache[slug]);
        return;
      }
      // 正在加载，等待完成
      if (pageLoading[slug]) {
        pageLoading[slug].push({resolve: resolve, reject: reject});
        return;
      }
      // 开始加载
      pageLoading[slug] = [{resolve: resolve, reject: reject}];
      var url = "pages/" + getSafeFilename(slug) + ".json";
      fetch(url, {cache: "force-cache"})
        .then(function(r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function(data) {
          pageContentCache[slug] = data;
          var waiters = pageLoading[slug] || [];
          delete pageLoading[slug];
          waiters.forEach(function(w) { w.resolve(data); });
        })
        .catch(function(err) {
          delete pageLoading[slug];
          var waiters = pageLoading[slug] || [];
          waiters.forEach(function(w) { w.reject(err); });
        });
    });
  }

  // 重写show函数
  window.show = function(slug) {
    var p = window.bySlug ? window.bySlug[slug] : null;
    if (!p) {
      // 没有找到页面，调用原始show函数处理404
      if (originalShow) originalShow(slug);
      return;
    }

    // 如果不需要按需加载，或者是目录页，直接调用原始show函数
    if (!p._need_load || p.is_index || slug === "index") {
      if (originalShow) originalShow(slug);
      return;
    }

    // 需要按需加载
    // 先显示加载状态（简化版，直接设置内容）
    var contentEl = document.getElementById('content');
    if (contentEl) {
      contentEl.innerHTML = '<div class="article"><div style="text-align:center;padding:3rem 0;color:var(--ink-faint);"><div style="font-size:2rem;margin-bottom:1rem;">📖</div><div>正在加载文章内容...</div></div></div>';
    }

    // 加载文章内容
    loadPageContent(slug).then(function(data) {
      // 加载成功，把内容赋值给p对象，然后调用原始show函数
      p.html = data.html;
      p.meta = data.meta || p.meta;
      p.tags = data.tags || p.tags;
      p._need_load = false; // 标记已加载，避免重复加载
      // 调用原始show函数渲染
      if (originalShow) originalShow(slug);
    }).catch(function(err) {
      // 加载失败
      if (contentEl) {
        contentEl.innerHTML = '<div class="article"><div style="text-align:center;padding:3rem 0;color:var(--ink-faint);"><div style="font-size:2rem;margin-bottom:1rem;">⚠️</div><div>文章内容加载失败</div><div style="font-size:.85rem;margin-top:.5rem;">' + (err.message || '') + '</div><button onclick="location.reload()" style="margin-top:1rem;padding:.5rem 1rem;border-radius:8px;border:1px solid var(--accent);background:var(--accent-soft);color:var(--accent-deep);cursor:pointer;">重新加载</button></div></div>';
      }
    });
  };

  // 暴露loadPageContent函数供外部使用
  window.loadPageContent = loadPageContent;
})();

</script>
</body>
</html>
"""


def main():
    pages = discover_pages()
    if not pages:
        print("content 目录下没有找到 md 文件"); sys.exit(1)

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

    # 首页「最近更新」区块：自动扫描 content/ 下的文章和音频文件，按修改时间排序生成
    home_update_html = ""
    home_update_date = ""
    recent_items = []
    for root, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not is_excluded_dir(d)]
        for fname in files:
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, CONTENT_DIR).replace('\\', '/')
            # 跳过 index.md、本次更新内容.md、更新日志.md
            if fname in ('index.md', '本次更新内容.md', '更新日志.md'):
                continue
            # 只处理 .md 文章和音频文件
            if fname.endswith('.md'):
                mtime = os.path.getmtime(fpath)
                title = fname[:-3]
                slug = rel_path[:-3]
                slug = re.sub(r"🔊\s*", "", slug)  # 与文章页面slug保持一致，去掉🔊
                # 尝试从 frontmatter 读取标题
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    meta, body = parse_frontmatter(raw)
                    if meta.get('title'):
                        title = meta['title']
                except:
                    pass
                recent_items.append({'mtime': mtime, 'title': title, 'slug': slug, 'type': 'article'})
            elif fname.endswith(('.mp3', '.m4a', '.wav', '.ogg')):
                mtime = os.path.getmtime(fpath)
                title = os.path.splitext(fname)[0]
                recent_items.append({'mtime': mtime, 'title': title, 'slug': '', 'type': 'audio'})
    # 按修改时间倒序排列，取最近10条
    recent_items.sort(key=lambda x: x['mtime'], reverse=True)
    recent_items = recent_items[:10]
    if recent_items:
        html_parts = ['<ul>']
        display_items = recent_items[:3]  # 最多显示3项
        for item in display_items:
            icon = '📄' if item['type'] == 'article' else '🎧'
            if item['slug']:
                html_parts.append(f'<li>{icon} <a href="#/{item["slug"]}" style="color:var(--accent);">{item["title"]}</a></li>')
            else:
                html_parts.append(f'<li>{icon} {item["title"]}</li>')
        if len(recent_items) > 3:
            html_parts.append(f'<li style="color:var(--ink-faint);font-size:.9em;">等 {len(recent_items)} 项内容更新</li>')
        html_parts.append('</ul>')
        home_update_html = ''.join(html_parts)
        home_update_date = datetime.datetime.fromtimestamp(recent_items[0]['mtime']).strftime('%Y-%m-%d')

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
    # 扫描法音海报文件，生成压缩版 WebP（比 PNG 小 60-80%，加载更快）
    # 规范化标题用于海报匹配（去除版本后缀、"短"字等，让"度母短仪轨"匹配"度母仪轨"海报）
    def normalize_poster_title(title):
        t = re.sub(r'[\s\(\)（）\[\]【】]', '', title)
        t = re.sub(r'(回音版|快|慢|21|42|7|8|16分钟|25分钟版|5分钟|7分钟)$', '', t)
        t = re.sub(r'短(仪轨|心咒|咒)$', r'\1', t)
        return t
    poster_dir = os.path.join(CONTENT_DIR, "assets", "法音海报")
    poster_dist_dir = os.path.join(DIST_DIR, "assets", "法音海报")
    poster_map = {}
    if os.path.isdir(poster_dir):
        os.makedirs(poster_dist_dir, exist_ok=True)
        for pname in os.listdir(poster_dir):
            if not pname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            key = os.path.splitext(pname)[0]
            norm_key = normalize_poster_title(key)
            src_path = os.path.join(poster_dir, pname)
            webp_name = key + ".webp"
            dst_path = os.path.join(poster_dist_dir, webp_name)
            try:
                from PIL import Image
                img = Image.open(src_path)
                # 详情页用：宽度限制 500px，质量 80
                max_w = 500
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                img.save(dst_path, "WEBP", quality=80, method=6)
                poster_url = "assets/法音海报/" + webp_name
                poster_map[key] = poster_url
                poster_map[norm_key] = poster_url
            except Exception as e:
                # 压缩失败则用原图
                shutil.copy2(src_path, os.path.join(poster_dist_dir, pname))
                poster_url = "assets/法音海报/" + pname
                poster_map[key] = poster_url
                poster_map[norm_key] = poster_url
    # 建立上师开示文章的目录顺序映射（用于音频排序）
    article_order = {}
    _article_dir = os.path.join(CONTENT_DIR, "上师开示")
    if os.path.isdir(_article_dir):
        _idx = 0
        for _dp, _dn, _fn in os.walk(_article_dir):
            _dn.sort(key=natural_sort_key)  # 子目录按自然排序
            for _f in sorted(_fn, key=natural_sort_key):
                if _f.endswith(".md") and _f != "index.md":
                    _title = re.sub(r"[\"'“”\s]", "", _f[:-3]).strip()
                    article_order[_title] = _idx
                    _idx += 1
    # 音频文件名到文章标题的别名映射（音频文件名与文章标题不一致时使用）
    audio_title_alias = {
        "什么样的老师适合你": "找一位什么样的上师最好🔊",
        "如何反观与自省": "修行人如何自我反观🔊",
        "成就的必由之路": "成就的必由之路——一师一法一本尊🔊",
        "选好你的救命稻草": "唯一的救命稻草：选好上师🔊",
    }
    def audio_sort_key(fname):
        _title = re.sub(r"[\"'“”\s]", "", fname[:-4] if fname.lower().endswith(".mp3") else fname).strip()
        _folder = audio_folder_rel(fname)
        # 上师开示（AI朗读）的音频按文章顺序排序
        if "上师开示" in _folder:
            # 先查直接匹配，再查别名映射
            _match_title = _title
            if _match_title not in article_order and _title in audio_title_alias:
                _match_title = audio_title_alias[_title]
            if _match_title in article_order:
                return (0, article_order[_match_title], _title)
            # 没有对应文章的音频放到最后
            return (2, _title)
        return (1, _title)
    audio_tracks = []
    for fname in sorted(LOCAL_AUDIO.keys(), key=audio_sort_key):
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
            "poster": poster_map.get(normalize_poster_title(title), poster_map.get(title, "")),
        }
        t["group"] = audio_group(fname)
        t["folder"] = audio_folder_rel(fname)
        audio_tracks.append(t)

    # 为有海报的经咒自动生成独立详情页（参考多智钦寺网站样式）+ 海报压缩
    try:
        from PIL import Image
        HAS_PIL = True
    except ImportError:
        HAS_PIL = False
        print("提示：未安装 Pillow，海报将使用原图（不压缩）")
    _poster_dist_dir = os.path.join(DIST_DIR, "assets", "法音海报")
    os.makedirs(_poster_dist_dir, exist_ok=True)
    mantra_detail_slugs = set()
    for _i, _t in enumerate(audio_tracks):
        if not _t.get("poster"):
            continue
        _title = _t["title"]
        _slug = "法音详情/" + _title
        if _slug in mantra_detail_slugs:
            continue
        mantra_detail_slugs.add(_slug)
        # 生成压缩版 WebP（最大宽度 800px，质量 80%，大幅减小加载体积）
        _poster_src = os.path.join(CONTENT_DIR, _t["poster"].replace("assets/assets/", "assets/"))
        _webp_url = _t["poster"]
        if os.path.exists(_poster_src) and HAS_PIL:
            _webp_name = _title + ".webp"
            _webp_path = os.path.join(_poster_dist_dir, _webp_name)
            try:
                _img = Image.open(_poster_src)
                _max_w = 800
                if _img.width > _max_w:
                    _ratio = _max_w / _img.width
                    _img = _img.resize((_max_w, int(_img.height * _ratio)), Image.LANCZOS)
                _img.save(_webp_path, "WEBP", quality=80, method=6)
                _webp_url = "assets/法音海报/" + _webp_name
                _t["poster_webp"] = _webp_url
            except Exception as _e:
                print("海报压缩失败 %s: %s" % (_title, _e))
        _t["detail_slug"] = _slug  # 供 JS 端 Index 页链接用
        _detail_html = (
            '<div class="mantra-detail">'
            + '<h1 class="mantra-detail-title">' + _title + '</h1>'
            + '<div class="mantra-detail-player">'
            + '<audio controls preload="none" src="' + _t["src"] + '"></audio>'
            + '<a class="mantra-detail-download" href="' + _t["src"] + '" download="' + _t["file"] + '" title="下载音频">⬇</a>'
            + '</div>'
            + '<p class="mantra-detail-author">- 第五世多智钦·龙洋仁波切亲诵 -</p>'
            + '<div class="mantra-detail-poster"><img src="' + _webp_url + '" alt="' + _title + '" loading="lazy" onclick="showPosterBig(this.src, this.alt)"></div>'
            + '<p class="mantra-detail-tip">点击海报可查看大图</p>'
            + '</div></div>'
        )
        pages.append({
            "slug": _slug,
            "title": _title,
            "rel": _slug + ".md",
            "dir": "法音详情",
            "is_index": False,
            "is_audio_detail": True,
            "audio_idx": _i,
            "meta": {},
            "html": _detail_html,
            "hide_from_nav": True,
        })
    # 重新生成 tree（包含详情页，但渲染时过滤 is_audio_detail / hide_from_nav）
    tree = build_tree(pages)

    # 生成 AI 问答知识库索引：直接遍历 Obsidian 中所有非 index 的 .md 文件
    knowledge_base = []
    for root, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not is_excluded_dir(d)]
        for fname in files:
            if not fname.endswith('.md') or fname == 'index.md':
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw = f.read()
                # 去掉 frontmatter
                if raw.startswith('---'):
                    end = raw.find('---', 3)
                    if end > 0:
                        raw = raw[end+3:]
                # 去掉 Obsidian 语法，提取纯文本
                text = re.sub(r'\[\[[^\]]+\]\]', '', raw)  # 去掉 [[链接]]
                text = re.sub(r'!\[\[[^\]]+\]\]', '', text)  # 去掉 ![[图片]]
                text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)  # 去掉标题标记
                text = re.sub(r'[*_>`~-]', '', text)  # 去掉markdown格式标记
                text = re.sub(r'\s+', ' ', text).strip()
                # 计算相对路径作为slug
                rel_path = os.path.relpath(fpath, CONTENT_DIR).replace('\\', '/')
                slug = rel_path[:-3] if rel_path.endswith('.md') else rel_path
                title = fname[:-3] if fname.endswith('.md') else fname
                if text or title:
                    knowledge_base.append({
                        "slug": slug,
                        "title": title,
                        "content": text[:3000] if text else title  # 每篇截取前3000字
                    })
            except Exception as e:
                print(f"  跳过文件 {fname}: {e}")
    print(f"AI知识库索引: {len(knowledge_base)} 篇文章")

    html_out = PAGE_TEMPLATE
    html_out = html_out.replace("@@SITE_TITLE_JSON@@", json.dumps(site_title, ensure_ascii=False))
    html_out = html_out.replace("@@AUDIO_ALBUM_JSON@@", json.dumps(CHANGLESI_ALBUM, ensure_ascii=False))
    html_out = html_out.replace("@@AUDIO_TRACKS_JSON@@", json.dumps(audio_tracks, ensure_ascii=False))
    # 按需加载：把非目录页的文章内容拆分成单独JSON文件
    pages_dir = os.path.join(DIST_DIR, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    pages_meta = []
    for p in pages:
        if p.get("is_index") or p["slug"] == "index":
            # 目录页和首页保留html内容
            pages_meta.append(p)
        else:
            # 非目录页：把html内容保存到单独JSON文件，PAGES只保留元数据
            safe_name = p["slug"].replace("/", "__").replace(" ", "_").replace("?？:：\"'<>*|", "")
            json_path = os.path.join(pages_dir, safe_name + ".json")
            with open(json_path, 'w', encoding='utf-8') as jf:
                json.dump({"html": p.get("html", ""), "meta": p.get("meta", {}), "tags": p.get("tags", [])}, jf, ensure_ascii=False)
            meta_page = {k: v for k, v in p.items() if k != "html"}
            meta_page["_need_load"] = True
            pages_meta.append(meta_page)
    print(f"文章内容拆分: {len(pages) - len([p for p in pages if p.get('is_index') or p['slug'] == 'index'])} 篇文章已拆分为单独JSON文件")
    html_out = html_out.replace("@@PAGES_JSON@@", json.dumps(pages_meta, ensure_ascii=False))
    html_out = html_out.replace("@@TREE_JSON@@", json.dumps(tree, ensure_ascii=False))
    html_out = html_out.replace("@@KNOWLEDGE_BASE_JSON@@", json.dumps(knowledge_base, ensure_ascii=False))
    html_out = html_out.replace("@@HOME_UPDATE_JSON@@", json.dumps(home_update_html, ensure_ascii=False))
    html_out = html_out.replace("@@HOME_UPDATE_DATE@@", home_update_date)
    html_out = html_out.replace("@@SITE_TITLE@@", site_title)
    html_out = html_out.replace("@@BUILD_TIME@@", time.strftime("%Y-%m-%d %H:%M"))
    # 热更新脚本：仅 watch 模式注入，定期检查构建时间变化并自动刷新
    watch_script = ""
    if WATCH_MODE:
        watch_script = """"""
    html_out = html_out.replace("@@WATCH_SCRIPT@@", watch_script)
    # 内联二维码生成库（qrcode.min.js，用于分享卡片生成文章链接二维码）
    qrcode_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qrcode.min.js")
    if os.path.exists(qrcode_path):
        with open(qrcode_path, "r", encoding="utf-8") as f:
            qrcode_lib = f.read()
    else:
        qrcode_lib = "/* qrcode.min.js not found */"
    # 确保 qrcode 暴露为全局变量（UMD 库在浏览器中可能不自动挂载）
    qrcode_lib += "\n;window.qrcode = (typeof qrcode !== 'undefined') ? qrcode : (window.qrcode || null);\n"
    html_out = html_out.replace("@@QRCODE_LIB@@", qrcode_lib)

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
        _dn[:] = [d for d in _dn if not is_excluded_dir(d)]
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

    # 复制管理后台 admin.html 到 dist/admin/index.html
    admin_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")
    if os.path.exists(admin_src):
        admin_dir = os.path.join(DIST_DIR, "admin")
        os.makedirs(admin_dir, exist_ok=True)
        shutil.copy2(admin_src, os.path.join(admin_dir, "index.html"))
        print("管理后台已复制: dist/admin/index.html")

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


# ---- 热更新模式：文件变化自动重建 + 浏览器自动刷新 ----
WATCH_MODE = False

def watch_and_serve():
    import http.server, socketserver, threading, time
    global WATCH_MODE
    WATCH_MODE = True
    PORT = 8765

    # 先构建一次
    print("=== 首次构建 ===")
    main()

    # 记录 content/ 目录下所有文件的修改时间
    def get_mtimes():
        mtimes = {}
        for dp, dn, fn in os.walk(CONTENT_DIR):
            dn[:] = [d for d in dn if not is_excluded_dir(d)]
            for f in fn:
                fp = os.path.join(dp, f)
                try:
                    mtimes[fp] = os.path.getmtime(fp)
                except:
                    pass
        # 也监控 build_site.py 自身
        mtimes[os.path.abspath(__file__)] = os.path.getmtime(os.path.abspath(__file__))
        return mtimes

    last_mtimes = get_mtimes()

    # 启动 HTTP 服务器
    os.chdir(DIST_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), handler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    print("\n=== 热更新模式已启动 ===")
    print("预览地址: http://localhost:%d" % PORT)
    print("监控目录: %s" % CONTENT_DIR)
    print("按 Ctrl+C 退出\n")

    try:
        while True:
            time.sleep(1)
            current_mtimes = get_mtimes()
            changed = False
            for fp, mt in current_mtimes.items():
                if fp not in last_mtimes or last_mtimes[fp] != mt:
                    changed = True
                    print("检测到变化: %s" % os.path.basename(fp))
                    break
            if changed:
                print("重新构建...")
                try:
                    main()
                    print("构建完成，浏览器将自动刷新\n")
                except Exception as e:
                    print("构建失败: %s\n" % e)
                last_mtimes = get_mtimes()
    except KeyboardInterrupt:
        print("\n退出热更新模式")
        httpd.shutdown()


if __name__ == "__main__":
    import sys as _sys
    if "--watch" in _sys.argv or "-w" in _sys.argv:
        watch_and_serve()
    else:
        main()
