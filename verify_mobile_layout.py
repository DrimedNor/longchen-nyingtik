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
  const R = { total: res.length, bad: [], ok: 0, fail: [], fixed: [] };
  await page.goto('http://127.0.0.1:@@PORT@@/', { waitUntil: 'load' });
  await page.waitForTimeout(900);

  /* ---- 固定组件专项（2026-09-22 补盲区）-------------------------------------
     为什么必须单列：本探针原先只遍历 `#content *`，而播放器 .player、迷你条
     .player-mini、悬浮按钮 .fab-search、启动胶囊 .player-launch 都是 body 直接子级的
     position:fixed 元素 → 全部落在扫描根之外。实测代价：播放器 .p-speed 在 320/360/375
     三个视口越界（最多 51px），门禁连报三次"通过"。
     教训：门禁的覆盖面 = 它的扫描根；新增任何全局固定元素，都要能被这里看见。
     两类判定（缺一不可）：
       ① 越界：right > vw 或 left < 0 → 内容被挤出视口（visible 可见）
       ② 压扁：圆形按钮 width ≠ height → flex 主轴 shrink 把圆压成椭圆。
          为什么需要 ②：被压缩的元素不越界，right>vw 抓不到；而压扁后容器 need≈inner，
          连"need>inner"这类判据也失效。圆钮的 width!=height 是唯一稳定信号。
     ------------------------------------------------------------------------- */
  const SCANFIX = () => {
    const vw = window.innerWidth;
    const isFx = el => getComputedStyle(el).position === 'fixed';
    const roots = [...document.body.querySelectorAll('*')].filter(isFx).filter(el => {
      let p = el.parentElement;
      while (p && p !== document.body) { if (isFx(p)) return false; p = p.parentElement; }
      return true;
    });
    const extra = ['.topbar'].map(s => document.querySelector(s)).filter(Boolean);
    const items = [], seen = {};
    for (const root of roots.concat(extra)) {
      for (const el of [root, ...root.querySelectorAll('*')]) {
        const b = el.getBoundingClientRect();
        if (b.width === 0 && b.height === 0) continue;
        /* 完全落在视口外 = 设计性隐藏/移出态，跳过：
           侧边抽屉 .sidebar 收起时是 left:-260/right:0（从左侧滑出），
           「从左侧滑入的面板」同理。若只判 left<0 会把抽屉整个当成缺陷（首跑实测误报 8 条）。 */
        if (b.right <= 0 || b.left >= vw) continue;
        if (b.right > vw + 1 || b.left < -1) {
          const key = el.tagName.toLowerCase() + '.' + (String(el.className || '').split(' ')[0] || '');
          const sig = key + '|' + Math.round(b.right);
          if (seen[sig]) continue;
          seen[sig] = 1;
          items.push({ k: key, w: Math.round(b.width), l: Math.round(b.left),
                       right: Math.round(b.right),
                       txt: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) });
        }
      }
    }
    const squish = [];
    for (const sel of ['.p-btn', '.pm-btn']) {
      for (const el of document.querySelectorAll(sel)) {
        const b = el.getBoundingClientRect();
        if (b.width === 0) continue;
        if (Math.abs(b.width - b.height) > 0.6) {
          squish.push({ k: sel + ' 压扁', id: el.id || '', w: Math.round(b.width),
                        h: Math.round(b.height) });
        }
      }
    }
    for (const sel of ['.p-controls', '.p-footer', '.p-time-row', '.p-status']) {
      const c = document.querySelector(sel);
      if (!c) continue;
      const cs = getComputedStyle(c);
      const kids = [...c.children].filter(k => getComputedStyle(k).display !== 'none');
      if (!kids.length) continue;
      const gap = parseFloat(cs.columnGap) || 0;
      let sum = 0;
      for (const k of kids) sum += k.getBoundingClientRect().width;
      const inner = c.getBoundingClientRect().width
                    - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const need = sum + gap * (kids.length - 1);
      if (need > inner + 1) {
        squish.push({ k: sel + ' 需宽>可用宽', need: Math.round(need), inner: Math.round(inner) });
      }
    }
    return { items: items, squish: squish };
  };

  const fx = [];
  fx.push(Object.assign({ state: 'default' }, await page.evaluate(SCANFIX)));
  await page.evaluate(() => { const e = document.getElementById('player'); if (e) e.classList.add('show'); });
  await page.waitForTimeout(220);
  fx.push(Object.assign({ state: 'player-open' }, await page.evaluate(SCANFIX)));
  await page.evaluate(() => { const e = document.getElementById('player'); if (e) e.classList.remove('show'); });
  await page.evaluate(() => { const e = document.getElementById('playerMini'); if (e) e.classList.add('show'); });
  await page.waitForTimeout(220);
  fx.push(Object.assign({ state: 'mini' }, await page.evaluate(SCANFIX)));
  await page.evaluate(() => { const e = document.getElementById('playerMini'); if (e) e.classList.remove('show'); });
  R.fixed = fx.filter(s => s.items.length || s.squish.length);

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
        print("正常 %d / 有问题 %d / 渲染失败 %d / 固定组件问题 %d"
              % (R["ok"], len(R["bad"]), len(R["fail"]), len(R.get("fixed") or [])))
        for b in sorted(R["bad"], key=lambda x: -x["contentW"]):
            print("\n── %s" % b["hash"])
            print("   正文容器 %spx（正常为视口宽 - 32）  h1=%s" % (b["contentW"], b["h1"][:34]))
            for k, v in sorted(b["cls"].items(), key=lambda kv: -kv[1]):
                print("     · %s ×%d" % (k, v))
            for it in b["items"]:
                print("       <%s> 宽=%s 右边界=%s | %s" % (it["k"], it["w"], it["right"], it["txt"]))
        if R.get("fixed"):
            print("\n【固定组件】（播放器 / 迷你条 / 悬浮按钮 / 顶栏）")
            for s in R["fixed"]:
                print("  ── 状态：%s" % s["state"])
                for it in s["items"]:
                    print("     · 越界 %-14s 宽=%s 左=%s 右=%s | %s"
                          % (it["k"], it["w"], it["l"], it["right"], it["txt"]))
                for q in s["squish"]:
                    if "need" in q:
                        print("     · 压挤 %-22s 需 %spx / 可用 %spx" % (q["k"], q["need"], q["inner"]))
                    else:
                        print("     · 压挤 %-22s %s 宽=%s 高=%s" % (q["k"], q.get("id", ""), q["w"], q["h"]))
        if R["fail"]:
            print("\n渲染失败：%s" % R["fail"][:8])
        ok = not R["bad"] and not R["fail"] and not R.get("fixed")
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
