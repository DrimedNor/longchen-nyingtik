#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""JS 语法门禁（仓库根）—— 把 dist/*.html 里每个内联 <script> 块交给真 JS 引擎解析。

为什么需要它（2026-09-22 实测教训）：
  当晚给修行日历页加「日历库按需加载器」时，把 HTML 注释 `<!-- ... -->` 连同
  一对 `<script></script>` 写进了**已有 script 块内部**：
    · JS 里 `<!--` 只等于「单行」注释（Annex B 遗留语法），其后几行成了裸文本；
    · 多出的 `<script>` 造成嵌套，一个 `</script>` 提前闭合了首屏主 script。
  结果是**全站白屏**。而当时：
    · `build_site.py` 正常退出、产物正常写出；
    · `audit_site_rules.py` 全绿；
    · `verify_mobile_layout.py`（含 pageerror 捕获）也没报——
      因为缺陷在**首屏主 script**、而它扫的是路由页，且当时未覆盖该组合。
  ⇒ 「构建通过 / 门禁通过」都不能证明「JS 能被解析」。
     本脚本把这条缺口补上：**凡内联脚本，一律用 node --check 真解析一遍。**

判据：每个无 src 的 <script> 块都必须能被 node --check 通过。
用法：python check_js_syntax.py [--file dist/index.html ...]   （默认扫 dist 下全部 .html）
退出码：0 = 全通过；1 = 有块解析失败（错误级，不许发布）
"""
import argparse
import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

SCRIPT_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)


def find_node():
    for c in [r"C:\Users\Drime\.workbuddy\binaries\node\versions\22.22.2-3\node.exe",
              r"C:\Users\Drime\.workbuddy\binaries\node\versions\24.14.0\node.exe",
              r"D:\Program Files\nodejs\node.exe"]:
        if os.path.exists(c):
            return c
    return None


def iter_html_files(explicit):
    if explicit:
        for f in explicit:
            yield f if os.path.isabs(f) else os.path.join(ROOT, f)
        return
    if not os.path.isdir(DIST):
        return
    for name in sorted(os.listdir(DIST)):
        if name.lower().endswith((".html", ".htm")):
            yield os.path.join(DIST, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", default=None,
                    help="只检查指定 html（可多次）；默认扫 dist 下全部 .html")
    args = ap.parse_args()

    node = find_node()
    if not node:
        print("SKIP：未找到 node，无法做 JS 语法校验")
        return 0

    files = list(iter_html_files(args.file))
    if not files:
        print("SKIP：没有可检查的 html（dist 未构建？）")
        return 0

    total_blocks = 0
    bad = []
    tmpdir = tempfile.mkdtemp(prefix="jscheck_")

    for path in files:
        if not os.path.exists(path):
            print("  ! 文件不存在：%s" % path)
            continue
        try:
            html = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception as e:
            print("  ! 读取失败 %s：%s" % (path, e))
            bad.append((path, -1, "读取失败: %s" % e))
            continue

        blocks = list(SCRIPT_RE.finditer(html))
        for bi, m in enumerate(blocks):
            attrs = m.group("attrs") or ""
            if re.search(r"\bsrc\s*=", attrs, re.I):
                continue                      # 外链脚本由浏览器自行加载，不在本门禁范围
            body = m.group("body")
            if not body.strip():
                continue
            total_blocks += 1
            line_no = html[:m.start()].count("\n") + 1
            jsf = os.path.join(tmpdir, "b.js")
            with io.open(jsf, "w", encoding="utf-8") as f:
                f.write(body)
            p = subprocess.run([node, "--check", jsf], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if p.returncode != 0:
                err = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
                msg = err[0] if err else "node --check 失败"
                for ln in err[:6]:
                    if "SyntaxError" in ln:
                        msg = ln.strip()
                        break
                bad.append((os.path.relpath(path, ROOT), line_no,
                            "%s（块 %d，%d 字节）" % (msg, bi, len(body.encode("utf-8")))))

    print("=" * 78)
    print("JS 语法门禁：内联 script 块 %d 个，来自 %d 个 html" % (total_blocks, len(files)))
    if bad:
        print("\n【错误】以下内联脚本无法被 JS 引擎解析（错误级，不许发布）：")
        for f, ln, msg in bad:
            print("  ✗ %s : 第 %s 行附近 —— %s" % (f, ln, msg))
        print("\n结论：不通过 ✗（错误 %d）" % len(bad))
        return 1
    print("\n【通过】全部内联脚本均可被 node --check 解析")
    print("结论：通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
