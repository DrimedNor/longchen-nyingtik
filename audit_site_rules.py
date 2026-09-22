#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""站点规则静态体检（对应《网站功能设计规则总纲》的 [门禁] 项）
================================================================
用途：把「靠人记」的规则变成「跑一次就知道」的检查。
只读——不改动仓库任何文件。

用法：
    python audit_site_rules.py            # 体检（有 ERR 时退出码 1）
    python audit_site_rules.py --full     # 追加需要 dist/ 的项

覆盖规则：
    SEC-2  安全头七项齐备
    SEC-3  浏览器侧跨源调用必须在 CSP connect-src 放行   ← 本脚本的立身之本
    TRK-1  埋点域在 connect-src
    CNT-2  content/ 一级栏目集合
    CNT-6 / FRG-2  TOP_ORDER 与 ORDER 必须同值
    CNT-7 / FRG-3  TOP_LABELS 与 META 必须同键同值
    FRG-4  引导语平行定义（TEACHING_INTROS vs DIR_INTROS）
    FRG-5  pages_meta 重复计算
    FRG-6  ADMIN_DEVICE_IDS 跨 toml 一致
    FRG-7  根 _headers 失效遗留
    FRG-9  AI 端点三处一致
    LAY-1 / LAY-2  正文容器可压缩 + overflow-wrap
    AUD-5  AGG_PREFIXES 指向听法音
    AUTH-2 dist/_routes.json 门槛不被绕过
    CAC-1..4 缓存策略
    API-7  Worker CORS 口径一致
    IMG-2  dist/assets 图库数量一致（--full）
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ERRORS, WARNS, OKS = [], [], []


def err(rid, msg, hint=""):
    ERRORS.append((rid, msg, hint))


def warn(rid, msg, hint=""):
    WARNS.append((rid, msg, hint))


def ok(rid, msg, hint=""):
    OKS.append((rid, msg, hint))


def rd(*parts):
    p = os.path.join(ROOT, *parts)
    if not os.path.exists(p):
        return None
    return io.open(p, encoding="utf-8", errors="replace").read()


def js_block(text, varname):
    """取 `var NAME = {...}` 或 `var NAME = [...];` 的字面量文本。"""
    m = re.search(r"var\s+%s\s*=\s*" % re.escape(varname), text)
    if not m:
        return None
    i = m.end()
    if i >= len(text) or text[i] not in "[{":
        return None
    open_ch, close_ch = text[i], ("}" if text[i] == "{" else "]")
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return None


def js_strings(block):
    """从字面量里抽出所有单/双引号字符串（按出现顺序）。"""
    return re.findall(r"'([^']*)'|\"([^\"]*)\"", block or "")


def pair_list(block):
    """取 {a:b, c:d} 形式，返回 (keys, [(k,v)...])。"""
    out = []
    for a, b in js_strings(block):
        if a:
            out.append(a)
    # 键值对：用正则单独抓 k:v
    pairs = re.findall(r"'([^']*)'\s*:\s*'([^']*)'|\"([^\"]*)\"\s*:\s*'([^']*)'", block or "")
    norm = [(p[0] or p[2], p[1] or p[3]) for p in pairs]
    return out, norm


# ---------------------------------------------------------------- SEC
def check_security_headers():
    h = rd("cloudflare", "_headers")
    if h is None:
        return err("SEC-1", "cloudflare/_headers 缺失", "这是**生效**的响应头文件")
    ok("SEC-1", "cloudflare/_headers 存在（%d 字节）" % len(h.encode("utf-8")))
    need = ["X-Robots-Tag", "X-Content-Type-Options", "Referrer-Policy",
            "X-Frame-Options", "Strict-Transport-Security",
            "Permissions-Policy", "Content-Security-Policy"]
    miss = [n for n in need if n + ":" not in h]
    if miss:
        err("SEC-2", "安全头缺项：%s" % "、".join(miss), "对照总纲 §8-SEC-2 补齐")
    else:
        ok("SEC-2", "安全头七项齐备")


def csp_connect_hosts(src_csp):
    """只在 Content-Security-Policy 头行里找 connect-src（避免命中注释文字）。"""
    line = ""
    for ln in (src_csp or "").splitlines():
        if ln.strip().startswith("Content-Security-Policy:"):
            line = ln
            break
    m = re.search(r"connect-src([^;]*)", line)
    if not m:
        return None
    hosts = set()
    for tok in m.group(1).split():
        if tok.startswith("http"):
            hosts.add(tok.rstrip("/"))
    return hosts


def browser_side_connect_targets():
    """浏览器侧会发起的跨源目标（fetch/sendBeacon/WebSocket/端点常量）。"""
    files = ["build_site.py", "admin.html", "practice-page.js", "practice-core.js",
             "sw.js", "lazyload.js"]
    targets = {}
    varpat = re.compile(
        r"(?:var|let|const)\s+([A-Za-z_][\w]*)\s*=\s*'(https?://[^']+)'")
    callpat = re.compile(r"\b(fetch|sendBeacon|WebSocket)\s*\(\s*'?(https?://[^'\s)\"`]+)")
    for f in files:
        t = rd(f)
        if t is None:
            continue
        for name, url in varpat.findall(t):
            if any(k in name.upper() for k in ("ENDPOINT", "API_BASE", "API_URL", "WORKER", "SITE", "HOST")):
                targets.setdefault(url, set()).add("%s:%s" % (f, name))
        for fn, url in callpat.findall(t):
            targets.setdefault(url, set()).add("%s:%s()" % (f, fn))
    return targets


def check_csp_connect():
    h = rd("cloudflare", "_headers")
    if not h:
        return
    hosts = csp_connect_hosts(h)
    if hosts is None:
        return err("SEC-3", "CSP 未声明 connect-src", "默认回落 default-src，跨源调用会被拦")
    tg = browser_side_connect_targets()
    missing = {}
    for url, where in tg.items():
        origin = re.match(r"(https?://[^/]+)", url).group(1)
        if origin in hosts:
            continue
        # 本站自有域：'self' 已覆盖
        if origin in ("https://longchen-nyingtik.wiki", "http://longchen-nyingtik.wiki"):
            continue
        missing.setdefault(origin, set()).update(where)
    if missing:
        for origin, where in sorted(missing.items()):
            err("SEC-3", "浏览器侧跨源目标未在 CSP connect-src 放行：%s" % origin,
                "出现在 %s\nCSP 会静默拦截（服务端无日志、curl 不执行 CSP）⇒ 功能降级但不报错"
                % ", ".join(sorted(where)))
    else:
        ok("SEC-3", "浏览器侧跨源目标 %d 个，全部已在 connect-src 放行" % len(tg))
    if "https://stats.longchen-nyingtik.wiki" in hosts:
        ok("TRK-1", "统计 Worker 域已在 connect-src 放行")
    else:
        err("TRK-1", "统计 Worker 域不在 connect-src", "埋点会静默丢数")


# ---------------------------------------------------------------- CNT / FRG
def check_content_dirs():
    c = os.path.join(ROOT, "content")
    if not os.path.isdir(c):
        return
    def publishable(d):
        if d.startswith(".") or d.startswith("_backup"):
            return False
        if "不推送" in d or d == "assets":
            return False
        return True

    tops = sorted(d for d in os.listdir(c)
                  if os.path.isdir(os.path.join(c, d)) and publishable(d))
    expect = {"1. 听法音", "2. 读开示", "3. 知传承", "4. 阅典籍", "5. 瞻法照", "9. 关于本站"}
    getop = set(tops)
    if getop == expect:
        ok("CNT-2", "content/ 一级栏目与约定一致（%d 个）" % len(tops))
    else:
        extra = getop - expect
        lack = expect - getop
        warn("CNT-2", "content/ 一级目录与约定有差异",
             "多出：%s；缺少：%s" % ("、".join(sorted(extra)) or "无",
                                    "、".join(sorted(lack)) or "无"))


def meta_titles(block):
    """从 META = {'dir': {icon:.., title:'X', ..}} 里取 {dir: title}。"""
    out = {}
    for m in re.finditer(r"'([^']+)'\s*:\s*\{([^}]*)\}", block or ""):
        key, body = m.group(1), m.group(2)
        t = re.search(r"title\s*:\s*'([^']*)'", body)
        if t:
            out[key] = t.group(1)
    return out


def check_parallel_arrays(src):
    top = js_block(src, "TOP_ORDER")
    order = js_block(src, "ORDER")
    if top and order:
        a = [x[0] or x[1] for x in js_strings(top)]
        b = [x[0] or x[1] for x in js_strings(order)]
        if a == b:
            ok("CNT-6/FRG-2", "TOP_ORDER 与 ORDER 同值（%d 项）" % len(a))
        else:
            err("CNT-6/FRG-2", "TOP_ORDER 与 ORDER 不一致", "导航与首页板块顺序会打架：\n"
                "      TOP_ORDER = %s\n      ORDER     = %s" % (a, b))
    tl = js_block(src, "TOP_LABELS")
    meta = js_block(src, "META")
    if tl and meta:
        _, p1 = pair_list(tl)
        d1 = dict(p1)
        d2 = meta_titles(meta)
        if d1 == d2:
            ok("CNT-7/FRG-3", "TOP_LABELS 与 META 显示名一致（%d 项）" % len(d1))
        else:
            diff = []
            for k in set(d1) | set(d2):
                if d1.get(k) != d2.get(k):
                    diff.append("%s: TOP_LABELS=%r META=%r" % (k, d1.get(k), d2.get(k)))
            err("CNT-7/FRG-3", "TOP_LABELS 与 META 不一致", "；".join(diff))


def check_intro_duplication(src):
    ti = js_block(src, "TEACHING_INTROS")
    di = js_block(src, "DIR_INTROS")
    if ti and di:
        _, p1 = pair_list(ti)
        d1 = dict(p1)
        _, p2 = pair_list(di)
        d2 = dict(p2)
        dup = [k for k in d1 if k in d2 and d1[k] == d2[k]]
        if dup:
            warn("FRG-4", "引导语平行定义 %d 处（改文案需两处同步）" % len(dup),
                 "键：%s" % "、".join(dup))
        else:
            ok("FRG-4", "未见引导语逐字重复")
    oth = js_block(src, "OTHER_INTROS")
    if oth and di:
        _, p1 = pair_list(oth)
        _, p2 = pair_list(di)
        d1, d2 = dict(p1), dict(p2)
        dup = [k for k in d1 if k in d2]
        if dup:
            warn("FRG-4b", "OTHER_INTROS 与 DIR_INTROS 重叠 %d 处" % len(dup),
                 "键：%s" % "、".join(dup))


def check_pages_meta(src):
    n = len(re.findall(r"pages_meta\s*=", src))
    if n > 1:
        warn("FRG-5", "pages_meta 被赋值 %d 次（重复计算）" % n, "建议收敛为一次")
    else:
        ok("FRG-5", "pages_meta 仅赋值 %d 次" % n)


def check_admin_device_ids():
    a = rd("wrangler.toml")
    b = rd("wrangler-stats.toml")
    if a is None or b is None:
        return
    ra = re.search(r"ADMIN_DEVICE_IDS\s*=\s*\"([^\"]*)\"", a)
    rb = re.search(r"ADMIN_DEVICE_IDS\s*=\s*\"([^\"]*)\"", b)
    if not (ra and rb):
        warn("FRG-6", "未在两个 toml 中同时找到 ADMIN_DEVICE_IDS", "可能已改配置方式，请核对本规则")
        return
    if ra.group(1) == rb.group(1):
        ok("FRG-6", "ADMIN_DEVICE_IDS 两处一致")
    else:
        err("FRG-6", "ADMIN_DEVICE_IDS 两处不一致",
            "wrangler.toml 与 wrangler-stats.toml 不同 ⇒ 设备免密可能半失效")


def check_stale_headers():
    h = rd("_headers")
    if h is None:
        ok("FRG-7", "根 _headers 已不存在（无误导源）")
    else:
        has_csp = "Content-Security-Policy" in h
        warn("FRG-7", "仓库根 _headers 仍存在（%d 字节，CSP=%s）" % (len(h.encode("utf-8")),
                                                                  "有" if has_csp else "无"),
             "它不是生效文件（build_site.py 只读 cloudflare/_headers）⇒ 改它等于没改；建议归档")


def check_ai_endpoint():
    bs = rd("build_site.py")
    wt = rd("wrangler.toml")
    wk = rd("ai-ask-worker.js")
    urls = {}
    if bs:
        m = re.search(r"AI_API_ENDPOINT\s*=\s*'([^']+)'", bs)
        if m:
            urls["build_site.py"] = m.group(1)
    if wt:
        m = re.search(r'(?:pattern|route)\s*=\s*"(?:https?://)?([^"/]+)', wt)
        if m:
            urls["wrangler.toml"] = m.group(1)
    if wk:
        m = re.search(r"https://([a-z0-9.\-]*ai[a-z0-9.\-]*longchen[a-z0-9.\-]*)", wk)
        if m:
            urls["ai-ask-worker.js"] = m.group(1)
    hosts = set()
    for v in urls.values():
        hosts.add(re.sub(r"^https?://", "", v).split("/")[0])
    if len(hosts) <= 1:
        ok("FRG-9", "AI 端点三处一致：%s" % (list(hosts)[0] if hosts else "（未识别）"))
    else:
        warn("FRG-9", "AI 端点存在多个主机名：%s" % "、".join(sorted(hosts)),
             "核对 %s" % urls)


# ---------------------------------------------------------------- LAY / AUD
def check_layout_css(src):
    m = re.search(r"\.content\{([^}]*)\}", src)
    if m:
        body = m.group(1)
        if "min-width:0" in body.replace(" ", "") and "flex:1" in body.replace(" ", ""):
            ok("LAY-1", ".content 含 flex:1 + min-width:0（可压缩）")
        else:
            err("LAY-1", ".content 缺 flex:1 或 min-width:0",
                "flex 子项默认 min-width:auto ⇒ 长串会把正文撑出视口")
    else:
        warn("LAY-1", "未定位到 .content 规则", "选择器可能已变，请人工核对")
    m = re.search(r"#content\{([^}]*)\}", src)
    if m and "overflow-wrap:anywhere" in m.group(1).replace(" ", ""):
        ok("LAY-2", "#content 含 overflow-wrap:anywhere")
    else:
        err("LAY-2", "#content 缺 overflow-wrap:anywhere")


def check_audio_agg(src):
    m = re.search(r"AGG_PREFIXES\s*=\s*\(([^)]*)\)", src)
    if m and "AUDIO_TOP_DIR" in m.group(1):
        ok("AUD-5", "AGG_PREFIXES 指向 AUDIO_TOP_DIR")
    elif m:
        warn("AUD-5", "AGG_PREFIXES 未使用 AUDIO_TOP_DIR：%s" % m.group(1).strip())
    m = re.search(r"AUDIO_TOP_DIR\s*=\s*'([^']+)'", src)
    if m:
        p = os.path.join(ROOT, "content", m.group(1))
        if os.path.isdir(p):
            ok("AUD-5b", "AUDIO_TOP_DIR 指向存在的目录：%s" % m.group(1))
        else:
            err("AUD-5b", "AUDIO_TOP_DIR 指向不存在的目录：%s" % m.group(1), "内容会整块消失")


# ---------------------------------------------------------------- AUTH / CAC
def check_routes_json(full):
    p = os.path.join(ROOT, "dist", "_routes.json")
    if not os.path.exists(p):
        if full:
            warn("AUTH-2", "dist/_routes.json 不存在（未构建？）", "中间件会漏掉静态资源")
        return
    t = io.open(p, encoding="utf-8", errors="replace").read()
    inc = re.search(r'"include"\s*:\s*(\[[^\]]*\])', t)
    exc = re.search(r'"exclude"\s*:\s*(\[[^\]]*\])', t)
    inc_v = inc.group(1).replace(" ", "") if inc else ""
    exc_v = exc.group(1).replace(" ", "") if exc else ""
    if inc_v == '["/*"]' and exc_v == "[]":
        ok("AUTH-2", "dist/_routes.json 覆盖全部路径且不排除静态资源")
    else:
        err("AUTH-2", "dist/_routes.json 可能放过静态资源", t.strip()[:120])


def check_cache_headers():
    h = rd("cloudflare", "_headers")
    if not h:
        return
    want = [("/assets/*", "private, no-store"), ("/audio/*", "private, no-store"),
            ("/index.html", "no-store"), ("/sw.js", "no-cache")]
    bad = []
    for path, cc in want:
        m = re.search(re.escape(path) + r"\s*\n\s*Cache-Control:\s*([^\n]+)", h)
        if not m:
            bad.append("%s 无缓存规则" % path)
        elif cc not in m.group(1):
            bad.append("%s 期望含 %r，实际 %r" % (path, cc, m.group(1).strip()))
    if bad:
        warn("CAC-1..4", "缓存策略与规则不一", "；".join(bad))
    else:
        ok("CAC-1..4", "关键路径缓存策略符合规则")


def check_cors_consistency():
    a = rd("stats-auth-worker.js")
    b = rd("ai-ask-worker.js")
    if a is None or b is None:
        return
    def cors_kind(t):
        """判定 CORS 口径：通配 / 白名单 / 未识别。"""
        if re.search(r"Access-Control-Allow-Origin['\"]?\s*:\s*['\"]\*['\"]", t):
            return "通配 *"
        if re.search(r"Access-Control-Allow-Origin", t) and (
                "endsWith(" in t or "allowed.includes" in t or "ALLOW" in t.upper()):
            return "白名单"
        return "未识别"

    v1 = cors_kind(a)
    v2 = cors_kind(b)
    if v1 == v2:
        ok("API-7", "两个 Worker 的 CORS 口径一致：%s" % v1)
    else:
        warn("API-7", "两个 Worker CORS 口径不一致",
             "stats=%r  而  ai-ask=%r" % (v1, v2))


def check_gallery_assets(full):
    if not full:
        return
    src = os.path.join(ROOT, "content", "assets")
    dst = os.path.join(ROOT, "dist", "assets")
    if not os.path.isdir(src):
        return
    n1 = sum(len(f) for _, _, f in os.walk(src))
    if not os.path.isdir(dst):
        err("IMG-2", "dist/assets 不存在（图库未复制进构建产物）", "相册会全部裂图")
        return
    n2 = sum(len(f) for _, _, f in os.walk(dst))
    if n1 == n2:
        ok("IMG-2", "dist/assets 文件数与源一致（%d）" % n1)
    else:
        err("IMG-2", "dist/assets 文件数不一致", "源 %d，产物 %d" % (n1, n2))


# ---------------------------------------------------------------- main
# ---- JS-1 / JS-2：标识符完整性（2026-09-22 新增）----------------------------
# 为什么加这两条：09-22 一次端到端实跑就抓到两个同类缺陷 ——
#   ① `timeupdate` 监听器里 `if (!needsKeepAlive)`，而 needsKeepAlive 全仓库从未定义
#      → 每秒数次 ReferenceError，iOS 连播兜底从未生效（潜伏已久）
#   ② `getElementById('audioPlayer')`，而音频元素是 createElement 出来的、没有 id
#      → 查询永远返回 null，那段「停止当前播放」是死代码
# 两者语法、构建、静态门禁、部署全绿，只有真播才暴露（类型同 09-19 的 autoNext）。
# 故把形态固定下来做静态检查：让同类缺陷在改完当场就红，而不是等用户听见。

BUILTIN = set("""this window document navigator location console localStorage sessionStorage
JSON Math Date Object Array String Number Boolean RegExp Error Promise Map Set WeakMap WeakSet
setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame
fetch alert confirm prompt atob btoa encodeURIComponent decodeURIComponent parseInt parseFloat
isNaN isFinite escape unescape arguments undefined null void typeof new delete in instanceof
Event EventTarget HTMLElement Node Element Audio Image URL Blob FormData XMLHttpRequest
performance screen history matchMedia getComputedStyle addEventListener removeEventListener
dispatchEvent CustomEvent MutationObserver IntersectionObserver ResizeObserver AbortController
crypto AudioContext MediaMetadata MediaSession Notification OfflineAudioContext
solarlunar qrcode QRCode SolarLunar ChineseLunar
""".split())

# 出现在非 JS 区域（CSS / HTML）里的 `!xxx`，不是标识符引用
NON_JS_BANG = {"important", "DOCTYPE", "doctype"}


def strip_js_comments(s):
    """剥掉 /* */ 与 // 行注释。

    为什么必须剥：修复说明、规则注释里常引用旧写法（如本次注释里就写了
    getElementById('audioPlayer')），不剥注释会把「文档里提到的旧写法」当成「仍在引用」而误报。
    """
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r'(?<![:/"])//[^\n]*', "", s)
    return s


def defined_identifiers(src):
    """收集全部已定义名（var/let/const/function + 形参 + 箭头函数参 + catch 参）。"""
    names = set()
    for pat in (r"\bvar\s+([A-Za-z_$][\w$]*)", r"\blet\s+([A-Za-z_$][\w$]*)",
                r"\bconst\s+([A-Za-z_$][\w$]*)", r"\bfunction\s+([A-Za-z_$][\w$]*)"):
        names |= set(re.findall(pat, src))
    for m in re.finditer(r"function\s*[\w$]*\s*\(([^)]*)\)", src):
        for p in m.group(1).split(","):
            p = p.strip().split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p or ""):
                names.add(p)
    for m in re.finditer(r"\(([^()]*)\)\s*=>", src):
        for p in m.group(1).split(","):
            p = p.strip().split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", p or ""):
                names.add(p)
    names |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*=>", src))
    names |= set(re.findall(r"catch\s*\(\s*([\w$]+)", src))
    return names


def check_js_identifiers(src):
    """JS-2：以 `!NAME` 形式引用的标识符必须有定义。"""
    clean = strip_js_comments(src)
    defined = defined_identifiers(clean) | BUILTIN
    bad = {}
    for m in re.finditer(r"!\s*([A-Za-z_$][\w$]*)", clean):
        n = m.group(1)
        if n in defined or n in NON_JS_BANG:
            continue
        bad[n] = bad.get(n, 0) + 1
    if bad:
        err("JS-2", "以下标识符以 `!NAME` 形式被引用，但全文件未见定义：%s"
            % "、".join("%s×%d" % kv for kv in sorted(bad.items())),
            "典型症状：相关回调每次执行都抛 ReferenceError，功能静默失效"
            "（控制台刷错但页面看着正常）。\n"
            "修法：补上定义，或删掉该分支。参照 2026-09-22 needsKeepAlive 案例。")
    else:
        ok("JS-2", "`!NAME` 引用的标识符均有定义")


def all_known_ids():
    """收集"视为存在"的 id：build_site.py 全文 + dist 下全部 html/js。

    为什么必须是「全文 + 全部产物」而不是只看 dist/index.html：
      ① 日历 DOM 是以 JS 字符串注入 index.html 的，写成转义形式 id=\\"zLayers\\"，
         只匹配 id="X" 会漏（2026-09-22 首跑据此误报 3 个 id）；
      ② 功课页 DOM 在 dist/practice.html（pgRoot 就只在那里），只比 index 会误报。
    故用宽松正则 id=\\?["']X 扫全部来源。
    """
    ids = set()
    src = rd("build_site.py")
    if src:
        ids |= set(re.findall(r'id=\\?["\']([^"\'\\]+)', src))
    for root, _, files in os.walk(os.path.join(ROOT, "dist")):
        for f in files:
            if f.endswith((".html", ".js")):
                try:
                    t = io.open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                ids |= set(re.findall(r'id=\\?["\']([^"\'\\]+)', t))
    return ids


def check_dom_ids(src):
    """JS-1：getElementById / querySelector('#id') 引用的 id 必须存在。

    当前级别说明（2026-09-22 首跑实测）：
      真实渲染核对（_archive/zl/check_dom_ids_live.py）确认 6 处**静态无、渲染也无** ——
      全部是「id 名字写错」的残留：backToTop↔backTop、aiAskFab↔fabSearch、
      searchTabContent/aiTabContent（面板里根本没这两个容器）、shareArticleBtn、pageViews。
      逐一核对调用方后确认均为**死代码或失效绑定，无用户可见故障**（零调用 / 另有可用实现），
      唯二风险是 searchTabContent/aiTabContent 一旦被调用会抛 TypeError（地雷）。
      故登记为在册违规 V-06 待清，本检查**暂列警告**；V-06 清零后应升为【错误】。
    """
    html = rd("dist", "index.html")
    if html is None:
        warn("JS-1", "dist/index.html 不存在（先构建再跑）")
        return
    known = all_known_ids()
    clean = strip_js_comments(src)
    dyn = set(re.findall(r"\.id\s*=\s*['\"]([^'\"]+)['\"]", clean))
    dyn |= set(re.findall(r"setAttribute\(\s*['\"]id['\"]\s*,\s*['\"]([^'\"]+)['\"]", clean))
    refs = set(re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]", clean))
    refs |= set(re.findall(r"querySelector(?:All)?\(\s*['\"]#([A-Za-z][\w-]*)['\"]", clean))
    missing = sorted(refs - known - dyn)
    if missing:
        warn("JS-1", "以下 id 被 getElementById/querySelector 引用，但全线产物中不存在（%d 个）：%s"
             % (len(missing), "、".join(missing)),
             "多为「id 名字写错」的残留：查询永远返回 null → 相关代码静默失效或成地雷。\n"
             "注意：JS 动态创建后赋 id 的元素需写成 .id='X' 或 setAttribute('id','X') 才算已存在。\n"
             "参照 2026-09-22 案例（audioPlayer→playerAudio 已修；余 6 处登记为总纲 V-06）。")
    else:
        ok("JS-1", "getElementById / querySelector('#id') 引用 %d 个 id，全部存在" % len(refs))


def main():
    full = "--full" in sys.argv
    src = rd("build_site.py")
    print("=" * 78)
    print("龙的传人 站点规则静态体检    (%s)" % ("含 dist/ 项" if full else "静态项"))
    print("=" * 78)

    check_security_headers()
    check_csp_connect()
    check_content_dirs()
    if src is None:
        err("BLD-1", "build_site.py 未找到")
    else:
        check_parallel_arrays(src)
        check_intro_duplication(src)
        check_pages_meta(src)
        check_layout_css(src)
        check_audio_agg(src)
        check_js_identifiers(src)
        check_dom_ids(src)
    check_admin_device_ids()
    check_stale_headers()
    check_ai_endpoint()
    check_routes_json(full)
    check_cache_headers()
    check_cors_consistency()
    check_gallery_assets(full)

    def dump(title, items, mark):
        if not items:
            return
        print()
        print("%s %d 条" % (title, len(items)))
        for rid, msg, hint in items:
            print("  %s [%s] %s" % (mark, rid, msg))
            if hint:
                for line in hint.split("\n"):
                    print("        %s" % line)

    dump("【通过】", OKS, "✓")
    dump("【警告】", WARNS, "!")
    dump("【错误】", ERRORS, "x")

    print()
    print("-" * 78)
    n = len(ERRORS)
    print("结论：%s    （通过 %d / 警告 %d / 错误 %d）"
          % ("不通过 ✗" if n else "通过 ✓", len(OKS), len(WARNS), n))
    if n:
        print("提示：错误项对应《网站功能设计规则总纲》的 [门禁] 条款，修好后再发布。")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
