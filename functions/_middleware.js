/**
 * 龙的传人网站 · 全站访问门槛（Cloudflare Pages Functions 根级中间件）
 * ============================================================================
 * 目标（2026-09-12 小谦要求）：
 *   1. 所有页面与静态资源（含 knowledge.json / pages\/*.json / audio\/*.mp3）
 *      一律先过登录鉴权，匿名用户与搜索引擎爬虫拿不到任何内容；
 *   2. 站内不出现任何注册入口或注册链接，注册只能通过管理员生成的邀请链接
 *      （/invite/<邀请码>）进入；
 *   3. 新注册用户状态为 pending，必须由管理员审核通过后才能登录。
 *
 * 实现要点：
 *   - 本文件在 functions/ 根目录 → Cloudflare Pages 对所有请求先跑它。
 *     必须同时提供 dist/_routes.json（include:["/*"], exclude:[]），
 *     否则 wrangler 会自动生成排除静态资源的规则，静态文件将绕过本中间件。
 *   - 会话校验统一交给统计 Worker（stats.longchen-nyingtik.wiki）在 KV 里查，
 *     本文件不持有任何密钥；结果不缓存，保证退出/驳回后立即失效（fail closed）。
 *   - 登录/注册/登出走同源 /__auth/* 代理，会话 Cookie 才能落在本站主域上
 *     （第一方 httpOnly Cookie，跨站 Cookie 会被浏览器拦）。
 * ============================================================================
 */

const WORKER = "https://stats.longchen-nyingtik.wiki";
const COOKIE_NAME = "lct_session";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 天

const ROBOTS_HEADER = "noindex, nofollow, noarchive, nosnippet, noimageindex";

// 放行（不要求登录）的路径：
//   /robots.txt —— 必须公开，否则爬虫读不到 Disallow 指令
//   /admin/*    —— 管理后台，页面本身不含站内内容，由 ADMIN_PASSWORD 在 API 层把守
//                  （且它必须在登录门槛之外：主人尚无账号时也要能进去审核/发邀请）
function isPublicPath(path) {
  if (path === "/robots.txt") return true;
  if (path === "/admin" || path === "/admin/" || path.startsWith("/admin/")) return true;
  // 藏历独立页（2026-09-19 小谦指示）：公开——纯节日历表数据，无站内内容、无用户数据；
  // 收藏/分享/扫码直达。noindex 照常由 withNoindex 盖章。
  //注意：Cloudflare Pages 对 /zangli.html 会做「去扩展名」308 重定向到 /zangli，两种形态都要放行。
  if (path === "/zangli.html" || path === "/zangli" || path === "/zangli/") return true;
  return false;
}

function withNoindex(res) {
  const headers = new Headers(res.headers);
  headers.set("X-Robots-Tag", ROBOTS_HEADER);
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  });
}

function getCookie(request, name) {
  const raw = request.headers.get("Cookie") || "";
  const parts = raw.split(";");
  for (const part of parts) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    if (part.slice(0, idx).trim() === name) {
      return part.slice(idx + 1).trim();
    }
  }
  return "";
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": ROBOTS_HEADER,
    },
  });
}

function html(body, status) {
  return new Response(body, {
    status: status || 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": ROBOTS_HEADER,
    },
  });
}

// ---------------------------------------------------------------------------
// 会话校验：每次请求交给统计 Worker 查 KV。
// 2026-09-19 2-1 C+ 升级：加入进程内「会话旁路缓存」（30 秒 TTL）
// ——媒体改为全量回源鉴权（no-store）后，为摊薄 KV 读成本而设：
//   同一 isolate 内同 token 的重复请求 30 秒内不再跨 Worker 打 KV。
// 登出语义保住：/__auth/logout 路由显式清 memo（见 logout 处）；管理员删号场景
// 最长 30 秒残留（权衡记录：配额收益 >> 30 秒吊销窗口，於回执注明）。
// Worker 不可达时按「未登录」处理（fail closed），绝不因异常放行内容（缓存命中不放大此面）。
// ---------------------------------------------------------------------------
const SESS_MEMO = new Map(); // token -> { user, exp }
const SESS_MEMO_TTL = 30 * 1000;
const SESS_MEMO_MAX = 200;

async function verifySession(token, opts) {
  if (!token) return null;
  const now = Date.now();
  const hit = SESS_MEMO.get(token);
  if (hit && hit.exp > now) return hit.user;
  let res;
  try {
    res = await fetch(WORKER + "/api/session/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
  } catch (e) {
    return null;
  }
  if (!res.ok) return null;
  try {
    const data = await res.json();
    const user = data && data.success ? data.user : null;
    if (user) {
      if (SESS_MEMO.size >= SESS_MEMO_MAX) {
        // 简单淘汰：清掉最旧的一半（Map 迭代序＝插入序）
        let n = Math.floor(SESS_MEMO_MAX / 2);
        for (const k of SESS_MEMO.keys()) {
          SESS_MEMO.delete(k);
          if (--n <= 0) break;
        }
      }
      SESS_MEMO.set(token, { user: user, exp: now + SESS_MEMO_TTL });
    }
    return user;
  } catch (e) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// 页面模板（全部内联，不依赖任何静态资源，因此登录/注册页无需放行其它路径）
// ---------------------------------------------------------------------------
const PAGE_CSS = `
:root{--bg:#f6f1e6;--surface:#fffdf8;--ink:#3b2f28;--ink-soft:#6f6258;--accent:#8a1f1c;--accent-deep:#6d1614;--line:#e2d8c4}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",serif}
.wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1.5rem}
.card{width:100%;max-width:26rem;background:var(--surface);border:1px solid var(--line);
  border-radius:14px;padding:2rem 1.6rem;box-shadow:0 8px 30px rgba(90,70,40,.08)}
.lock{font-size:1.8rem;text-align:center;margin-bottom:.6rem}
h1{font-size:1.15rem;font-weight:600;margin:0 0 .4rem;text-align:center;letter-spacing:.04em}
.desc{font-size:.86rem;color:var(--ink-soft);line-height:1.7;margin:0 0 1.3rem;text-align:center}
label{display:block;font-size:.82rem;color:var(--ink-soft);margin:.85rem 0 .3rem}
input,textarea{width:100%;padding:.7rem .8rem;font-size:1rem;font-family:inherit;color:var(--ink);
  background:#fff;border:1px solid var(--line);border-radius:8px;outline:none}
input:focus,textarea:focus{border-color:var(--accent)}
button{width:100%;margin-top:1.3rem;padding:.8rem;font-size:1rem;font-family:inherit;
  color:#fff;background:var(--accent);border:none;border-radius:8px;cursor:pointer;letter-spacing:.05em}
button:hover{background:var(--accent-deep)}
button:disabled{opacity:.6;cursor:default}
.msg{margin-top:1rem;font-size:.84rem;line-height:1.6;text-align:center;min-height:1.2em}
.msg.err{color:#b3261e}
.msg.ok{color:#2e7d32}
.foot{margin-top:1.4rem;font-size:.74rem;color:#9c9084;text-align:center;line-height:1.7}
`;

function pageShell(title, inner) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet, noimageindex">
<title>${esc(title)}</title>
<style>${PAGE_CSS}</style>
</head>
<body>
<div class="wrap"><div class="card">${inner}</div></div>
</body>
</html>`;
}

function loginPageHTML(message) {
  return pageShell(
    "龙的传人｜登录",
    `<div class="lock">🔒</div>
<label for="u">用户名</label>
<input id="u" type="text" autocomplete="username" autocapitalize="off" spellcheck="false">
<label for="p">密码</label>
<input id="p" type="password" autocomplete="current-password">
<button id="go">进入网站</button>
<div class="msg err" id="m">${esc(message || "")}</div>
<script>
(function(){
  // 保险措施：匿名访客落到登录页时，顺手清掉本机旧版留下的 Service Worker 缓存，
  // 避免曾在旧版访问过的设备从本地缓存里继续看到已下载的音频/页面。
  try{
    if(window.caches){caches.keys().then(function(ks){ks.forEach(function(k){caches.delete(k);});});}
    if(navigator.serviceWorker&&navigator.serviceWorker.getRegistrations){
      navigator.serviceWorker.getRegistrations().then(function(rs){rs.forEach(function(r){r.unregister();});});
    }
  }catch(e){}
  var u=document.getElementById('u'),p=document.getElementById('p'),b=document.getElementById('go'),m=document.getElementById('m');
  function fail(t){m.className='msg err';m.textContent=t;}
  // 登录前后清干净本机缓存与 Service Worker。
  // 2026-09-14 修复：此前只在「匿名落到登录页」时清一次，输密码那一刻不清，
  //   导致旧 SW 仍可接管跳转后的首页请求、回放 401/旧登录页，表现为"输密码登不上"。
  async function purge(){
    try{
      if(window.caches){
        var ks=await caches.keys();
        await Promise.all(ks.map(function(k){return caches.delete(k);}));
      }
    }catch(e){}
    try{
      if(navigator.serviceWorker&&navigator.serviceWorker.getRegistrations){
        var rs=await navigator.serviceWorker.getRegistrations();
        await Promise.all(rs.map(function(r){return r.unregister();}));
      }
    }catch(e){}
  }
  async function go(){
    if(!u.value.trim()||!p.value){fail('请输入用户名和密码');return;}
    b.disabled=true;b.textContent='登录中…';
    try{
      var r=await fetch('/__auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
        cache:'no-store',
        body:JSON.stringify({username:u.value.trim(),password:p.value})});
      var d=await r.json();
      if(d&&d.success){
        try{ localStorage.setItem('longchen-access-granted','true'); }catch(e){}
        await purge();                      // 关键：跳转前清干净，杜绝旧缓存回放
        location.replace('/?v='+Date.now()); // 带时间戳绕过任何中间层缓存
        return;
      }
      await purge();
      fail((d&&d.message)||'登录失败，请重试');
    }catch(e){fail('网络错误，请稍后重试');}
    b.disabled=false;b.textContent='进入网站';
  }
  b.addEventListener('click',go);
  p.addEventListener('keydown',function(e){if(e.key==='Enter')go();});
  u.addEventListener('keydown',function(e){if(e.key==='Enter')p.focus();});
  u.focus();
})();
</script>`,
  );
}

function registerPageHTML(code, codeState) {
  const disabled = codeState === "ok" ? "" : "disabled";
  const notice =
    codeState === "ok"
      ? `<div class="msg" id="m">请填写以下信息提交申请，管理员审核通过后即可登录。</div>`
      : codeState === "missing"
        ? `<div class="msg err" id="m">邀请链接不完整，请使用主人发给你的完整链接。</div>`
        : `<div class="msg err" id="m">邀请链接无效或已失效，请向站点主人索取新的链接。</div>`;

  const form =
    codeState === "ok"
      ? `<label>邀请码</label>
<input type="text" id="code" value="${esc(code)}" readonly>
<label for="u">用户名（登录用，英文/数字）</label>
<input id="u" type="text" autocomplete="username" autocapitalize="off" spellcheck="false">
<label for="p">密码（至少 6 位）</label>
<input id="p" type="password" autocomplete="new-password">
<label for="n">怎么称呼你</label>
<input id="n" type="text">
<label for="r">申请说明（可选）</label>
<textarea id="r" rows="3" placeholder="简单介绍一下，便于主人确认"></textarea>
<button id="go">提交申请</button>`
      : "";

  return pageShell(
    "龙的传人｜注册申请",
    `<div class="lock">📨</div>
<h1>注册申请</h1>
<p class="desc">本站仅服务身边认识的师兄，注册需邀请链接并人工审核。</p>
${form}
${notice}
<script>
(function(){
  var b=document.getElementById('go');
  if(!b)return;
  var m=document.getElementById('m');
  function fail(t){m.className='msg err';m.textContent=t;}
  function ok(t){m.className='msg ok';m.textContent=t;}
  b.addEventListener('click',async function(){
    var code=(document.getElementById('code')||{}).value||'';
    var u=document.getElementById('u').value.trim();
    var p=document.getElementById('p').value;
    var n=document.getElementById('n').value.trim();
    var r=document.getElementById('r').value.trim();
    if(!u||!p||!n){fail('用户名、密码、称呼都要填');return;}
    if(p.length<6){fail('密码至少 6 位');return;}
    b.disabled=true;b.textContent='提交中…';
    try{
      var resp=await fetch('/__auth/register',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({inviteCode:code,username:u,password:p,nickname:n,reason:r})});
      var d=await resp.json();
      if(d&&d.success){
        ok('申请已提交，请等待管理员审核通过后再登录。');
        b.textContent='已提交';
      }else{
        fail((d&&d.message)||'提交失败，请重试');
        b.disabled=false;b.textContent='提交申请';
      }
    }catch(e){fail('网络错误，请稍后重试');b.disabled=false;b.textContent='提交申请';}
  });
})();
</script>`,
  );
}

function logoutPageHTML() {
  return pageShell(
    "龙的传人｜已退出",
    `<div class="lock">👋</div>
<h1>已退出登录</h1>
<p class="desc">已清除登录状态与本地缓存。</p>
<button onclick="location.replace('/login')">返回登录页</button>
<script>
(async function(){
  try{ localStorage.removeItem('longchen-access-granted'); }catch(e){}
  try{
    if(window.caches){var ks=await caches.keys();await Promise.all(ks.map(function(k){return caches.delete(k);}));}
    if(navigator.serviceWorker&&navigator.serviceWorker.getRegistrations){
      var rs=await navigator.serviceWorker.getRegistrations();
      await Promise.all(rs.map(function(r){return r.unregister();}));
    }
  }catch(e){}
})();
</script>`,
  );
}

// ---------------------------------------------------------------------------
// /__auth/* 同源鉴权代理（把会话 Cookie 落在本站主域上）
// ---------------------------------------------------------------------------
async function handleAuth(request, url) {
  const path = url.pathname;

  if (path === "/__auth/login") {
    if (request.method !== "POST") return json({ success: false, message: "Method not allowed" }, 405);
    const body = await request.text();
    const res = await fetch(WORKER + "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const data = await res.json().catch(() => ({ success: false, message: "服务异常" }));
    const headers = {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": ROBOTS_HEADER,
    };
    if (res.ok && data && data.success && data.token) {
      headers["Set-Cookie"] =
        COOKIE_NAME +
        "=" +
        data.token +
        "; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=" +
        COOKIE_MAX_AGE;
      return new Response(JSON.stringify({ success: true }), { status: 200, headers });
    }
    return new Response(
      JSON.stringify({ success: false, message: (data && data.message) || "登录失败" }),
      { status: res.status === 200 ? 401 : res.status, headers },
    );
  }

  if (path === "/__auth/register") {
    if (request.method !== "POST") return json({ success: false, message: "Method not allowed" }, 405);
    const body = await request.text();
    const res = await fetch(WORKER + "/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Robots-Tag": ROBOTS_HEADER,
      },
    });
  }

  if (path === "/__auth/invite") {
    const code = url.searchParams.get("code") || "";
    const res = await fetch(WORKER + "/api/invite/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inviteCode: code }),
    });
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Robots-Tag": ROBOTS_HEADER,
      },
    });
  }

  if (path === "/__auth/logout") {
    const token = getCookie(request, COOKIE_NAME);
    if (token) {
      SESS_MEMO.delete(token);
      await fetch(WORKER + "/api/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      }).catch(() => {});
    }
    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Set-Cookie": COOKIE_NAME + "=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
        "X-Robots-Tag": ROBOTS_HEADER,
      },
    });
  }

  if (path === "/__auth/me") {
    const user = await verifySession(getCookie(request, COOKIE_NAME));
    if (!user) return json({ success: false, message: "未登录" }, 401);
    return json({ success: true, user });
  }

  return json({ success: false, message: "Not found" }, 404);
}

// ---------------------------------------------------------------------------
// 中间件入口
// ---------------------------------------------------------------------------
export async function onRequest(context) {
  const { request, next } = context;
  const url = new URL(request.url);
  const path = url.pathname;

  // 1) 同源鉴权接口
  if (path.startsWith("/__auth/")) return handleAuth(request, url);

  // 2) 登录页（匿名可达，但不含任何站内内容）
  if (path === "/login" || path === "/login/") return html(loginPageHTML(""), 200);

  // 3) 退出登录
  if (path === "/logout" || path === "/logout/") {
    const token = getCookie(request, COOKIE_NAME);
    if (token) {
      // 2026-09-19：页面登出同样清会话旁路缓存，否则 30s 内仍可能命中旧 memo
      SESS_MEMO.delete(token);
      await fetch(WORKER + "/api/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      }).catch(() => {});
    }
    const res = html(logoutPageHTML(), 200);
    res.headers.set(
      "Set-Cookie",
      COOKIE_NAME + "=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
    );
    return res;
  }

  // 4) 邀请链接注册页：站点唯一的注册入口，仅凭邀请码可达
  if (path === "/invite" || path.startsWith("/invite/")) {
    const code = decodeURIComponent(path.replace(/^\/invite\/?/, "")).trim();
    let codeState = "missing";
    if (code) {
      codeState = "invalid";
      try {
        const res = await fetch(WORKER + "/api/invite/check", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ inviteCode: code }),
        });
        const data = await res.json();
        if (data && data.success) codeState = "ok";
      } catch (e) {
        codeState = "invalid";
      }
    }
    return html(registerPageHTML(code, codeState), codeState === "ok" ? 200 : 404);
  }

  // 4.5) 后台入口规范化（2026-09-21）
  //   ⚠️ 实测：Cloudflare 对 /admin/ 携带任意查询串一律返回 404（平台资产层行为），
  //     故一次性登记链接不能走查询串，token 统一改走 URL hash（hash 不发送到服务器）。
  //   本段把旧的 ?enroll= 形式 302 到 #enroll=，使已发出的旧链接仍然可用；
  //   同时把无斜杠的 /admin 归一到 /admin/，并丢弃其余无意义查询串（否则会落到 404）。
  if (path === "/admin" || path === "/admin/") {
    const tk = url.searchParams.get("enroll") || "";
    if (tk) {
      return new Response(null, {
        status: 302,
        headers: {
          Location: "/admin/#enroll=" + encodeURIComponent(tk),
          "Cache-Control": "no-store",
        },
      });
    }
    if (path === "/admin" || url.search) {
      return new Response(null, {
        status: path === "/admin" ? 308 : 302,
        headers: { Location: "/admin/", "Cache-Control": "no-store" },
      });
    }
  }

  // 5) robots.txt 与 /admin/ 放行（但要加盖 noindex 头）
  if (isPublicPath(path)) return withNoindex(await next());

  // 6) 其余一切：必须有有效会话
  const user = await verifySession(getCookie(request, COOKIE_NAME));
  if (!user) {
    const accept = request.headers.get("Accept") || "";
    if (accept.indexOf("text/html") !== -1) {
      return html(loginPageHTML(""), 401);
    }
    return new Response("401 Unauthorized：本站需登录后访问。", {
      status: 401,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Robots-Tag": ROBOTS_HEADER,
      },
    });
  }

  return withNoindex(await next());
}
