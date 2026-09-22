#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""正文排版静态门禁：扫描 content/ 下正文里的「未转换的源格式残留」与「超长不可断行串」。

背景（2026-09-22）：
    手机端出现「正文右侧被整齐切掉」的根因不是元素没有 max-width:100%，
    而是正文里混入了超长且**没有断行机会**的字符串（本地路径 / 裸 URL / 目录点线），
    它把 .layout > .content 这个 flex 子项的 min-content 撑大；
    flex 子项默认 min-width:auto（不可压缩），于是整个正文容器超出视口，
    再被 html,body{overflow-x:hidden} 裁掉 —— 表现为「显示不全」。

用法：
    python check_article_layout.py            # 检查（有阻断项时退出码 1）
    python check_article_layout.py --warn     # 警告项也计入退出码

约定：
    · 先剥掉 YAML frontmatter（source_url 等字段本身不渲染，不应误报）
    · 阻断级 = 确定性错误（构建器不会转换这些写法，必然出问题）
    · 警告级 = 建议优化（现由 CSS #content{overflow-wrap:anywhere} 兜底，不再必然溢出）
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content")
SKIP_DIRS = ("不推送", "_backup", ".obsidian")

# ---- 阻断级：未转换的源格式残留 -------------------------------------------
RE_WINPATH = re.compile(r"file:///[^\s)\]]+")
RE_PLACEHOLDER = re.compile(r"\[(图|图片|视频|音频|文件)\s*[:：][^\]]*\]")
RE_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")       # markdown 图片语法，构建器不转换
RE_DOTLEADER = re.compile(r"[.·]{40,}")               # 目录点线（不可断行）

# ---- 警告级：超长不可断行串 -----------------------------------------------
# 断行机会 = 空白、CJK 字符、连字符、以及 / ? & # 等；其余 ASCII 连成一段。
# （连字符在 CSS 里是可断行点，故一并视为分隔符，避免把梵文转写术语误报。）
RE_TOKEN = re.compile(r"[A-Za-z0-9_\-\.\:%~+,\\@()\[\]{}<>|'\"]{34,}")
BREAK_CHARS = "/?&#-"


def strip_frontmatter(text):
    if text.startswith("---"):
        m = re.match(r"^---\r?\n.*?\r?\n---\r?\n", text, re.S)
        if m:
            return " " * 0 + text[m.end():], text[:m.end()].count("\n")
    return text, 0


def segments(line):
    """把一行拆成「无断行机会」的片段。"""
    out = []
    for m in RE_TOKEN.finditer(line):
        tok = m.group(0)
        for part in re.split("[" + re.escape(BREAK_CHARS) + "]", tok):
            if len(part) >= 34:
                out.append((part, m.start()))
    return out


def iter_md():
    for dp, dn, fn in os.walk(CONTENT):
        base = os.path.basename(dp)
        if any(s in dp for s in SKIP_DIRS) or base.startswith("."):
            continue
        for f in sorted(fn):
            if f.endswith(".md"):
                yield os.path.join(dp, f)


def main():
    warn_as_error = "--warn" in sys.argv
    block, warn = [], []
    for p in iter_md():
        rel = os.path.relpath(p, ROOT)
        raw = io.open(p, encoding="utf-8", errors="replace").read()
        body, off = strip_frontmatter(raw)
        for ln, line in enumerate(body.splitlines(), start=off + 1):
            for rx, code, desc in (
                (RE_WINPATH, "B1", "本地临时路径（WPS/复制粘贴死链）"),
                (RE_PLACEHOLDER, "B2", "未转换的 [图:]/[视频:] 占位符"),
                (RE_MD_IMG, "B3", "未转换的 markdown 图片语法 ![](...)"),
                (RE_DOTLEADER, "B4", "目录点线（≥40 连续点，不可断行）"),
            ):
                m = rx.search(line)
                if m:
                    block.append((code, desc, rel, ln, m.group(0)[:70]))
            for seg, _pos in segments(line):
                warn.append(("W1", "超长不可断行串（%d 字符）" % len(seg), rel, ln, seg[:70]))

    print("=" * 78)
    print("正文排版静态检查")
    print("=" * 78)
    if block:
        print("\n【阻断】未转换的源格式残留：%d 处" % len(block))
        for code, desc, rel, ln, hit in block:
            print("  %s %s" % (code, rel))
            print("      第 %d 行  %s" % (ln, desc))
            print("      → %s" % hit)
    else:
        print("\n【阻断】无 ✓")
    if warn:
        print("\n【警告】超长不可断行串：%d 处（建议改为链接或缩短；CSS 已兜底）" % len(warn))
        for code, desc, rel, ln, hit in warn[:30]:
            print("  %s %s 第 %d 行  %s" % (code, rel, ln, hit))
        if len(warn) > 30:
            print("  …（另 %d 处）" % (len(warn) - 30))
    else:
        print("\n【警告】无 ✓")

    print("\n提示：静态检查通过后，发布前还须跑 `python verify_mobile_layout.py`")
    print("      （375px 真实渲染复验，能发现静态扫描看不到的溢出）")
    fail = bool(block) or (warn_as_error and bool(warn))
    print("\n结论：%s" % ("不通过 ✗" if fail else "通过 ✓"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
