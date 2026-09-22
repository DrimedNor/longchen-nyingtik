#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""手机端排版渲染复验：375px 视口逐页真实渲染，量出「右边界超出视口」的元素。

为什么必须有这一步（2026-09-22 教益）：
    静态扫描只能看到「已知形态」的坏串；真实渲染才能发现任何把容器撑宽的原因。
    本次 6 个坏页中，静态扫描能命中全部，但「撑宽机制」（flex 子项 min-width:auto）
    只有渲染才能证实。故本脚本是发布前的最终证据。

用法：
    python verify_mobile_layout.py            # 全部页面（约 90 秒）
    python verify_mobile_layout.py --width 360
    python verify_mobile_layout.py --only 读开示    # 只扫某个一级栏目

前置：需先构建（python build_site.py）产出 dist/；需要 node 与 playwright-cli。
      缺依赖时打印 SKIP 并以 0 退出，不阻断发布，但会在结论里标明「未验证」。
"""
import http.server
import io
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
CONTENT = os.path.join(ROOT, "content")
SKIP_DIRS = ("不推送", "_backup", ".obsidian")
PORT = 8811


def find_node():
    for c in [shutil.which("node"),
              r"D:\Program Files\nodejs\node.exe",
              os.path.expanduser(r"~\.workbuddy\binaries\node\versions\22.22.2-3\node.exe")]:
        if c and os.path.exists(c):
            return c
    return None


def find_cli():
    for c in [os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\@playwright\cli\playwright-cli.js"),
              os.path.join(ROOT, "node_modules", "@playwright", "cli", "playwright-cli.js")]:
        if os.path.exists(c):
            return c
    return None


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIST, **kw)

    def log_message(self, *a):
        pass


def routes(only):
    out = []
    for dp, dn, fn in os.walk(CONTENT):
        base = os.path.basename(dp)
        if any(s in dp for s in SKIP_DIRS) or base.startswith("."):
            continue
        for f in sorted(fn):
            if not f.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dp, f), CONTENT)[:-3]
            segs = rel.split(os.sep)
            if only and segs[0] != only:
                continue
            out.append({"hash": "#/" + "/".join(segs), "title": f[:-3]})
    out.sort(key=lambda r: r["hash"])
    return out


PROBE = r"""
async page => {
  await page.setViewportSize({ width: @@W@@, height: 780 });
  const res = @@ROUTES@@;
  const R = { total: res.length, bad: [], ok: 0, fail: [] };
  await page.goto('http://127.0.0.1:@@PORT@@/', { waitUntil: 'load' });
  await page.waitForTimeout(900);
  for (const r of res) {
    try {
      await page.evaluate(h => { location.hash = h; }, r.hash);
      await page.waitForTimeout(300);
      const m = await page.evaluate(() => {
        const vw = window.innerWidth;
        const content = document.getElementById('content');
        if (!content) return { noContent: true };
        const out = { vw: vw, items: [], cls: {} };
        for (const el of content.querySelectorAll('*')) {
          const b = el.getBoundingClientRect();
          if (b.width === 0 && b.height === 0) continue;
          if (b.right > vw + 1) {
            const key = el.tagName.toLowerCase() + '.' + (String(el.className || '').split(' ')[0] || '');
            out.cls[key] = (out.cls[key] || 0) + 1;
            if (out.items.length < 3) out.items.push({
              k: key, w: Math.round(b.width), right: Math.round(b.right),
              txt: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60)});
          }
        }
        out.h1 = (content.querySelector('h1') || {}).textContent || '';
        out.contentW = Math.round(content.getBoundingClientRect().width);
        return out;
      });
      if (m.noContent) { R.fail.push(r.hash); continue; }
      if (Object.keys(m.cls).length) { m.hash = r.hash; R.bad.push(m); } else R.ok++;
    } catch (e) { R.fail.push(r.hash + ' :: ' + String(e).slice(0, 60)); }
  }
  return '###JSON_START###' + JSON.stringify(R) + '###JSON_END###';
}
"""


def parse_block(out):
    A, B = "###JSON_START###", "###JSON_END###"
    i, j = out.find(A), out.find(B)
    if i < 0 or j < 0:
        return None
    inner = out[i + len(A):j]
    for f in (json.loads, lambda s: json.loads(json.loads('"' + s + '"'))):
        try:
            return f(inner)
        except Exception:
            pass
    return None


def main():
    w = 375
    only = None
    for i, a in enumerate(sys.argv):
        if a == "--width" and i + 1 < len(sys.argv):
            w = int(sys.argv[i + 1])
        if a == "--only" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1]

    if not os.path.isdir(DIST):
        print("!! dist/ 不存在，请先运行 python build_site.py")
        return 2
    node, cli = find_node(), find_cli()
    res = routes(only)
    print("=" * 78)
    print("手机端排版渲染复验：宽度 %dpx，页面 %d 个" % (w, len(res)))
    print("=" * 78)
    if not (node and cli):
        print("SKIP：未找到 node 或 playwright-cli（node=%s cli=%s）" % (bool(node), bool(cli)))
        print("结论：未验证（请在有 playwright 的机器上补跑）")
        return 0

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def pcli(*a, timeout=1800):
        p = subprocess.run([node, cli] + list(a), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, cwd=ROOT)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    try:
        pcli("open", "about:blank")
        probe = (PROBE.replace("@@ROUTES@@", json.dumps(res, ensure_ascii=False))
                      .replace("@@PORT@@", str(PORT)).replace("@@W@@", str(w)))
        rc, out = pcli("run-code", probe)
        R = parse_block(out)
        if not R:
            print("!! 未取到结果：\n%s" % out[-2000:])
            return 2
        print("正常 %d / 有问题 %d / 渲染失败 %d" % (R["ok"], len(R["bad"]), len(R["fail"])))
        for b in sorted(R["bad"], key=lambda x: -x["contentW"]):
            print("\n── %s" % b["hash"])
            print("   正文容器 %spx（正常为视口宽 - 32）  h1=%s" % (b["contentW"], b["h1"][:34]))
            for k, v in sorted(b["cls"].items(), key=lambda kv: -kv[1]):
                print("     · %s ×%d" % (k, v))
            for it in b["items"]:
                print("       <%s> 宽=%s 右边界=%s | %s" % (it["k"], it["w"], it["right"], it["txt"]))
        if R["fail"]:
            print("\n渲染失败：%s" % R["fail"][:8])
        ok = not R["bad"] and not R["fail"]
        print("\n结论：%s" % ("通过 ✓" if ok else "不通过 ✗"))
        return 0 if ok else 1
    finally:
        try:
            pcli("close")
        except Exception:
            pass
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
