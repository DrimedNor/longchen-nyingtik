#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""播放器端到端实跑（2026-09-22，第 2 版）：交互可点性 + 自动连播 + 标识符完整性。

为什么必须有（铁律 7）：
    09-19 的连播 bug ——「把函数名当开关用」（autoNext = true 覆盖了函数）
    语法、构建、门禁、部署全绿，只有真播才暴露，潜伏 14 天。
    本次首跑即又抓到两个同类缺陷（needsKeepAlive 未定义 / getElementById('audioPlayer') 死代码），
    再次证明：凡动播放器，发布前后都必须真点、真播、真读异常。

本版相对第 1 版的修正（第 1 版自身有 bug，教训见 §"验证脚本自身会骗人"）：
  · 第 1 版用 getElementById('audioPlayer') 取 duration —— 该元素根本不存在（产品缺陷本身），
    导致 duration=-1、连播未验证。本版改用全局 playerAudio。
  · 第 1 版报「播放模式点击无效」为假象：未先关闭新人引导遮罩 .spotlight-overlay
    （z-index 9999 全屏模态），也未做 elementFromPoint 命中诊断。
    本版：先关引导 → 每次点击前记录命中元素 → 点击后比对状态变量（playMode）而不只看文案。

覆盖：
  A. 起播：点「▶ 播放全部」→ 播放器展开、audio 进入播放
  B. 自动连播：seek 到结尾 → 是否自动跳下一集（核心，铁律 7 指定）
  C. 320px 三个底部控件可点且状态生效（模式 / 播放列表 / 倍速），含遮挡诊断
  D. 标识符完整性：needsKeepAlive 已定义（强制为 true 后模拟 timeupdate 不抛错）
  E. 全程 pageerror 去重计数

位置：**仓库根**（正式发布门禁；2026-09-22 由 _archive/zl/ 提升 —— _archive 在 .gitignore 内，
      放在那里等于「只在本机有效」，无法作为团队门禁）。
用法：python verify_player_e2e.py
前置：python build_site.py；node + playwright-cli。
"""
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading

ROOT = r"D:\Users\Drime\Projects\龙的传人-website"
DIST = os.path.join(ROOT, "dist")
CONTENT = os.path.join(ROOT, "content")
PORT = 8838
SKIP = ("不推送", "_backup", ".obsidian")


def find_node():
    for c in [r"D:\Program Files\nodejs\node.exe",
              os.path.expanduser(r"~\.workbuddy\binaries\node\versions\22.22.2-3\node.exe")]:
        if c and os.path.exists(c):
            return c
    return None


def find_cli():
    c = os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\@playwright\cli\playwright-cli.js")
    return c if os.path.exists(c) else None


class _Limited:
    """把文件对象限制为只读 n 字节（用于 206 分片响应）。"""

    def __init__(self, fp, n):
        self.fp, self.n = fp, n

    def read(self, amt=None):
        if self.n <= 0:
            return b""
        if amt is None or amt > self.n:
            amt = self.n
        d = self.fp.read(amt)
        self.n -= len(d)
        return d

    def close(self):
        self.fp.close()


class Quiet(http.server.SimpleHTTPRequestHandler):
    """静默 + **支持 HTTP Range** 的本地服务器。

    ⚠️ 2026-09-22 教训：标准库 SimpleHTTPRequestHandler 不支持 Range（不返回 206）⇒
    Chromium 的 <audio> 无法 seek 到未缓冲位置，`currentTime = dur - 0.4` 会被静默重置为 0。
    表现极具迷惑性：seek 后 t=0 且仍在播放 → 看起来像"连播失效/同一集重播"，
    实则**验证环境缺陷，不是产品缺陷**（若不加这一段，就会误判并去改没坏的产品代码）。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIST, **kw)

    def log_message(self, *a):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404)
            return None
        size = os.fstat(f.fileno()).st_size
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if not m:
            f.close()
            self.send_error(400)
            return None
        start = int(m.group(1)) if m.group(1) else 0
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", "bytes */%d" % size)
            self.end_headers()
            return None
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        f.seek(start)
        return _Limited(f, end - start + 1)


def candidates():
    out = []
    for dp, dn, fn in os.walk(CONTENT):
        if any(s in dp for s in SKIP):
            continue
        for f in sorted(fn):
            if not f.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dp, f), CONTENT)[:-3]
            segs = rel.split(os.sep)
            if not segs[0].startswith("1."):
                continue
            out.append("#/" + "/".join(segs))
    return out[:24]


PROBE = r"""
async page => {
  const R = { found: null, tracks: 0, errors: {}, chain: {}, ui: {}, ident: {}, notes: [] };
  page.on('pageerror', e => {
    const k = String(e).slice(0, 110);
    R.errors[k] = (R.errors[k] || 0) + 1;
  });
  await page.setViewportSize({ width: 320, height: 780 });
  await page.goto('http://127.0.0.1:@@PORT@@/', { waitUntil: 'load' });
  await page.waitForTimeout(1500);

  // 关掉新人引导遮罩（z-index:9999 全屏模态，会挡住播放器的所有底部控件）
  const killSpot = async () => {
    return await page.evaluate(() => {
      const o = document.querySelector('.spotlight-overlay');
      if (o) { o.click(); return true; }
      return false;
    });
  };
  R.notes.push('引导遮罩：' + ((await killSpot()) ? '已关闭' : '未出现'));

  // ---- 找一个含多集音频的页面 ----
  for (const h of @@CANDS@@) {
    try {
      await page.evaluate(x => { location.hash = x; }, h);
      await page.waitForTimeout(480);
      await killSpot();
      const ok = await page.evaluate(() => {
        const b = document.querySelector('.dir-play-all-btn');
        return !!(b && typeof AUDIO_TRACKS !== 'undefined' && AUDIO_TRACKS.length > 1);
      });
      if (ok) { R.found = h; break; }
    } catch (e) { /* 下一个 */ }
  }
  if (!R.found) { R.notes.push('未找到含 ≥2 集音频的页面'); return '###JSON_START###' + JSON.stringify(R) + '###JSON_END###'; }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(250);
  R.tracks = await page.evaluate(() => AUDIO_TRACKS.length);

  // 给每个目标控件做命中诊断（真缺陷 vs 测试假象的分水岭）
  const hit = (sel) => page.evaluate(s => {
    const el = document.querySelector(s);
    if (!el) return { sel: s, missing: true };
    const b = el.getBoundingClientRect();
    const cx = Math.round(b.left + b.width / 2), cy = Math.round(b.top + b.height / 2);
    const top = document.elementFromPoint(cx, cy);
    const d = n => n ? (n.tagName.toLowerCase() + '#' + (n.id || '') + '.' +
                        String(n.className || '').split(' ')[0]) : '(null)';
    return { sel: s, cx: cx, cy: cy, hit: d(top),
             self: !!(top && (top === el || el.contains(top))) };
  }, sel);

  // ---- A. 点「▶ 播放全部」并验证起播 ----
  await page.click('.dir-play-all-btn', { force: true });
  await page.waitForTimeout(2500);
  const s1 = await page.evaluate(() => ({
    show: document.getElementById('player').classList.contains('show'),
    txt: document.getElementById('pStatusText').textContent.trim(),
    dur: (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.duration : -1,
    paused: (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.paused : true,
    rate: (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.playbackRate : -1,
    src: (typeof playerAudio !== 'undefined' && playerAudio) ? String(playerAudio.currentSrc || playerAudio.src || '').slice(-60) : ''
  }));
  R.chain.start = s1;

  // ---- D. 标识符完整性：needsKeepAlive 必须已定义；强制启用后不应抛错 ----
  R.ident.needsKeepAlive = await page.evaluate(() => {
    try { return { defined: typeof needsKeepAlive !== 'undefined', value: needsKeepAlive }; }
    catch (e) { return { defined: false, err: String(e).slice(0, 90) }; }
  });
  R.ident.forced = await page.evaluate(() => {
    const out = { ok: false, err: null, definedAfter: true };
    try {
      needsKeepAlive = true;                       // 模拟 iOS
      playerAudio.dispatchEvent(new Event('timeupdate'));
      out.ok = true;
    } catch (e) { out.err = String(e).slice(0, 120); }
    try { needsKeepAlive = false; } catch (e) {}
    return out;
  });

  // ---- C. 320px 三个底部控件可点性（含命中诊断）----
  // ⚠️ 引导遮罩 .spotlight-overlay 是【延迟出现】的全屏模态（z-index 9999），会吃掉
  //   它出现后的第一次点击 —— 首跑据此误报"播放模式点击无效"（实测命中 overlay、自身=False）。
  //   故每次点击前都必须先关掉它，否则"点击无效"是测试假象。
  const clickSafe = async (sel) => { await killSpot(); await page.waitForTimeout(140); await page.click(sel, { force: true }); };
  await killSpot();
  await page.waitForTimeout(140);
  const hMode = await hit('#pMode');
  const m0 = await page.evaluate(() => ({ txt: document.getElementById('pMode').textContent.trim(),
                                          mode: typeof playMode !== 'undefined' ? playMode : null }));
  await page.click('#pMode', { force: true });
  await page.waitForTimeout(340);
  const m1 = await page.evaluate(() => ({ txt: document.getElementById('pMode').textContent.trim(),
                                          mode: typeof playMode !== 'undefined' ? playMode : null }));
  R.ui.mode = { hit: hMode, before: m0, after: m1, ok: m1.txt !== m0.txt };

  await killSpot();
  const hToggle = await hit('#pPlToggle');
  await clickSafe('#pPlToggle');
  await page.waitForTimeout(480);
  const pl = await page.evaluate(() => ({
    open: document.getElementById('player').classList.contains('pl-open'),
    items: document.querySelectorAll('#pPlaylist .pl-item').length
  }));
  R.ui.playlist = { hit: hToggle, open: pl.open, items: pl.items,
                    ok: pl.open && pl.items > 0 };
  await clickSafe('#pPlToggle');
  await page.waitForTimeout(380);

  await killSpot();
  const hSpeed = await hit('#pSpeed');
  await clickSafe('#pSpeed');
  await page.waitForTimeout(340);
  const menu = await page.evaluate(() => getComputedStyle(document.getElementById('pSpeedMenu')).display !== 'none');
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('#pSpeedMenu .sp-item')]
      .find(e => e.getAttribute('data-rate') === '1.5');
    if (el) el.click();
  });
  await page.waitForTimeout(340);
  const sp = await page.evaluate(() => ({
    rate: (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.playbackRate : -1,
    btn: document.getElementById('pSpeed').textContent.trim()
  }));
  R.ui.speed = { hit: hSpeed, menuOpened: menu, rate: sp.rate, btn: sp.btn,
                 ok: menu && sp.rate === 1.5 };

  // ---- A2. 连播：seek 到结尾，看是否自动跳下一集 ----
  // 判定用 curIdx（索引变量）而非只看标题文本 —— 标题可能因列表同名/未刷新而假阴性。
  const snapPlay = () => page.evaluate(() => ({
    idx: (typeof curIdx !== 'undefined') ? curIdx : null,
    txt: document.getElementById('pStatusText').textContent.trim(),
    file: (typeof playerAudio !== 'undefined' && playerAudio)
          ? decodeURIComponent(String(playerAudio.currentSrc || '').split('/').pop()).slice(0, 44) : '',
    t: (typeof playerAudio !== 'undefined' && playerAudio) ? Math.round(playerAudio.currentTime) : -1,
    paused: (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.paused : null
  }));
  await page.evaluate(() => { if (typeof playerAudio !== 'undefined' && playerAudio) playerAudio.playbackRate = 1; });
  // ⚠️ 顺序依赖陷阱（第 3 个测试脚本 bug）：上面 [C] 段点了一次 #pMode → 模式已变成「逆序」。
  //    逆序模式下 curIdx=0（第一集）没有上一首 → autoNext 按设计返回 -1 → 停在原地。
  //    实测插桩显示 autoNext(0)→-1、playTrack 未被调用，一度误判为"连播失效"。
  //    凡测连播/自动切换，必须先把被测状态复位（模式=顺序），否则测的是另一条分支。
  await page.evaluate(() => { playMode = 0; updateModeBtn(); });
  await page.waitForTimeout(200);
  let dur = await page.evaluate(() => (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.duration : -1);
  for (let i = 0; i < 24 && !(dur > 1 && isFinite(dur)); i++) {
    await page.waitForTimeout(500);
    dur = await page.evaluate(() => (typeof playerAudio !== 'undefined' && playerAudio) ? playerAudio.duration : -1);
  }
  R.chain.duration = dur;
  const p1 = await snapPlay();
  R.chain.before = p1;
  // 插桩：ended 是否触发 / playTrack 被调用 / autoNext 返回值 —— 区分
  //   「handler 逻辑错」与「无头环境不产生 ended」（后者是环境限制，不是产品缺陷）
  await page.evaluate(() => {
    window.__p2 = { ended: 0, calls: [], next: [] };
    playerAudio.addEventListener('ended', function () { window.__p2.ended++; });
    const o1 = window.playTrack;
    window.playTrack = function (i) { window.__p2.calls.push(i); return o1.apply(this, arguments); };
    const o2 = window.autoNext;
    window.autoNext = function (c) { const r = o2.apply(this, arguments); window.__p2.next.push([c, r]); return r; };
  });
  if (dur > 1 && isFinite(dur)) {
    // seek 自检必须在【同一次 evaluate 内】设置并立即读取：
    // 若分两次读，seek 成功 → ended → 已切下一集 → currentTime 归 0 → 误判"seek 未生效"。
    const seekCheck = await page.evaluate(d => {
      playerAudio.currentTime = Math.max(0, d - 0.4);
      const ok = playerAudio.currentTime > d * 0.5;
      playerAudio.play().catch(function(){});
      return { t: Math.round(playerAudio.currentTime), ok: ok };
    }, dur);
    R.chain.seekOk = seekCheck.ok;
    R.chain.seekT = seekCheck.t;
    let p2 = p1;
    for (let i = 0; i < 26; i++) {
      await page.waitForTimeout(500);
      p2 = await snapPlay();
      if (p2.idx !== p1.idx || p2.txt !== p1.txt) break;
    }
    R.chain.after = {
      idx: p2.idx, title: p2.txt, file: p2.file, paused: p2.paused, t: p2.t,
      changed: (p2.idx !== p1.idx) || (p2.txt !== p1.txt)
    };
    R.chain.probe = await page.evaluate(() => window.__p2);
    // 对照实验：真实 ended 没来（或无头环境不产生）时，手动派发一次 ended，
    // 若此时能切集 ⇒ handler 逻辑正常，问题在"事件未触发"（环境）；反之 ⇒ handler 有缺陷。
    if (!R.chain.after.changed) {
      await page.evaluate(() => playerAudio.dispatchEvent(new Event('ended')));
      await page.waitForTimeout(1500);
      const p3 = await snapPlay();
      R.chain.afterManualEnded = {
        idx: p3.idx, txt: p3.txt, file: p3.file, t: p3.t,
        changed: (p3.idx !== p1.idx) || (p3.txt !== p1.txt)
      };
    }
  } else {
    R.notes.push('无法取得有效 duration → 连播未验证');
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
    node, cli = find_node(), find_cli()
    if not (os.path.isdir(DIST) and node and cli):
        print("SKIP：缺 dist/ 或 node/playwright-cli")
        return 0
    cands = candidates()
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def pcli(*a, timeout=1500):
        p = subprocess.run([node, cli] + list(a), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, cwd=ROOT)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    try:
        pcli("open", "about:blank")
        probe = (PROBE.replace("@@CANDS@@", json.dumps(cands, ensure_ascii=False))
                      .replace("@@PORT@@", str(PORT)))
        rc, out = pcli("run-code", probe)
        R = parse_block(out)
        if not R:
            print("!! 未取到结果：\n%s" % out[-2500:])
            return 2
        print("=" * 78)
        print("播放器端到端实跑（320px）")
        print("=" * 78)
        print("\n连播页：%s   总集数：%s" % (R["found"], R["tracks"]))
        if R["notes"]:
            for n in R["notes"]:
                print("提示：%s" % n)

        c = R["chain"]
        print("\n[A] 起播（点「▶ 播放全部」）：")
        s = c.get("start", {})
        print("   播放器展开=%s  标题=%r" % (s.get("show"), s.get("txt")))
        print("   duration=%s  paused=%s  rate=%s" % (s.get("dur"), s.get("paused"), s.get("rate")))
        print("   src=…%s" % s.get("src", ""))

        print("\n[B] 自动连播（seek 到结尾，看是否跳下一集）：")
        if "after" in c:
            b4, a = c["before"], c["after"]
            print("   seek 自检：目标 %ss → 实测 %ss  %s"
                  % (round(c.get("duration", 0), 1), c.get("seekT"),
                     "✓ 生效（服务器支持 Range）" if c.get("seekOk") else "✗ 未生效（服务器不支持 Range，结论不可用）"))
            print("   seek 前：idx=%s  %r  %s" % (b4["idx"], b4["txt"], b4["file"]))
            print("   seek 后：idx=%s  %r  %s" % (a["idx"], a["title"], a["file"]))
            print("   自动连播：%s" % ("✓ 已跳到下一集" if a["changed"] else "✗ 未跳（连播失效）"))
            print("   paused=%s  currentTime=%s" % (a["paused"], a["t"]))
            pr = c.get("probe") or {}
            print("   插桩：ended 触发 %s 次   playTrack 调用 %s   autoNext(入参→返回) %s"
                  % (pr.get("ended"), pr.get("calls"), pr.get("next")))
            me = c.get("afterManualEnded")
            if me:
                print("   对照（手动派发 ended）：idx=%s  %r  %s" % (me["idx"], me["txt"], me["file"]))
                print("      → %s" % ("✓ 切集成功 ⇒ handler 逻辑正常，真实 ended 未触发（无头环境限制）"
                                      if me["changed"] else
                                      "✗ 手动派发也不切 ⇒ ended handler 真有缺陷"))
        else:
            print("   （未执行）")

        print("\n[C] 320px 底部控件可点性：")
        u = R["ui"]
        if "mode" in u:
            print("   模式   ：命中=%s 自身=%s  '%s→%s'  playMode %s→%s  %s"
                  % (u["mode"]["hit"].get("hit"), u["mode"]["hit"].get("self"),
                     u["mode"]["before"]["txt"], u["mode"]["after"]["txt"],
                     u["mode"]["before"]["mode"], u["mode"]["after"]["mode"],
                     "✓" if u["mode"]["ok"] else "✗"))
        if "playlist" in u:
            print("   列表   ：命中=%s 自身=%s  展开=%s 条目=%s  %s"
                  % (u["playlist"]["hit"].get("hit"), u["playlist"]["hit"].get("self"),
                     u["playlist"]["open"], u["playlist"]["items"],
                     "✓" if u["playlist"]["ok"] else "✗"))
        if "speed" in u:
            print("   倍速   ：命中=%s 自身=%s  菜单=%s rate=%s 按钮=%r  %s"
                  % (u["speed"]["hit"].get("hit"), u["speed"]["hit"].get("self"),
                     u["speed"]["menuOpened"], u["speed"]["rate"], u["speed"]["btn"],
                     "✓" if u["speed"]["ok"] else "✗"))

        print("\n[D] 标识符完整性（needsKeepAlive）：")
        ni = R["ident"].get("needsKeepAlive", {})
        fo = R["ident"].get("forced", {})
        print("   已定义=%s 值=%s" % (ni.get("defined"), ni.get("value")))
        print("   强制为 true 后派发 timeupdate：ok=%s 异常=%s" % (fo.get("ok"), fo.get("err")))

        if R["errors"]:
            print("\n[E] pageerror（去重计数）：")
            for k, v in sorted(R["errors"].items(), key=lambda kv: -kv[1]):
                print("   ×%-4d %s" % (v, k))
        else:
            print("\n[E] pageerror：无 ✓")

        ok = (c.get("seekOk") and c.get("after", {}).get("changed") and not R["errors"]
              and u.get("mode", {}).get("ok") and u.get("speed", {}).get("ok")
              and u.get("playlist", {}).get("ok") and ni.get("defined"))
        print("\n结论：%s" % ("端到端通过 ✓" if ok else "不通过 ✗"))
        return 0 if ok else 1
    finally:
        try:
            pcli("close")
        except Exception:
            pass
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
