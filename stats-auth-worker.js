/**
 * 访问统计与密码验证 Worker
 * 
 * 功能：
 * 1. 记录累计独立设备数（以设备 ID 为主去重，同时记录 IP）
 * 2. 只统计国内（CN）访问，国外访问不计入统计、不设限制
 * 3. 累计国内设备数达到 10 后，永久启用密码保护
 * 4. 累计国内设备数达到 100 后，启用注册审核访问
 * 5. 提供注册、登录、管理员审核相关 API
 * 
 * 环境变量：
 * - ACCESS_PASSWORD：访问密码（设备数达到 10 后需要）
 * - DEVICE_THRESHOLD：设备数阈值，默认 10，达到后启用密码保护
 * - REGISTER_THRESHOLD：注册审核阈值，默认 100，达到后启用注册审核
 * - ADMIN_PASSWORD：管理员密码，用于审核后台
 * 
 * KV 命名空间绑定：
 * - STATS_KV：存储统计数据和用户数据
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    
    // CORS 头（2026-09-18 收窄：仅本站与预览域，严禁 *）
    const corsHeaders = (function () {
      const origin = request.headers.get('Origin') || '';
      const allowed = [
        'https://longchen-nyingtik.wiki',
        'https://www.longchen-nyingtik.wiki',
        // Pages 预览/部署子域（2c7b639f.longchen-nyingtik.pages.dev 形态）
        origin.endsWith('.longchen-nyingtik.pages.dev') ? origin : null,
      ].filter(Boolean);
      const hit = allowed.includes(origin);
      return {
        'Access-Control-Allow-Origin': hit ? origin : 'null',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, X-Device-ID, X-Admin-Token',
        'Vary': 'Origin',
      };
    })();
    
    // 处理 OPTIONS 预检请求
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }
    
    // 获取客户端信息
    const clientIP = request.headers.get('CF-Connecting-IP') || 
                     request.headers.get('X-Forwarded-For')?.split(',')[0] ||
                     'unknown';
    const country = request.cf?.country || 'UNKNOWN';
    const deviceId = request.headers.get('X-Device-ID') || '';
    
    // 判断是否为国内访问
    const isChina = country === 'CN';
    
    try {
      // 路由：记录访问（每个页面加载时调用）
      if (path === '/api/track' || path === '/track') {
        // 记录设备访问（所有IP都记录，用于统计）
        if (deviceId) {
          const geo = {
            country: country,
            region: request.cf?.region || '',
            city: request.cf?.city || '',
            postalCode: request.cf?.postalCode || '',
            latitude: request.cf?.latitude || '',
            longitude: request.cf?.longitude || '',
            timezone: request.cf?.timezone || '',
          };
          // 2026-09-07：采集 UA 与 Cloudflare bot 评分，供访问者动态分类
          const userAgent = request.headers.get('User-Agent') || '';
          const botScore = request.cf?.botManagement?.score; // 免费版可能为 undefined
          await recordDevice(env.STATS_KV, deviceId, clientIP, geo, userAgent, botScore);
        }
        
        // 所有IP都需要密码验证（不区分国内国外）
        const status = await getAccessStatus(env);
        return new Response(JSON.stringify({ 
          success: true, 
          country: country,
          isChina: isChina,
          ...status 
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：获取统计状态
      if (path === '/api/stats' || path === '/stats') {
        const status = await getAccessStatus(env);
        return new Response(JSON.stringify({ country, isChina, ...status }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：验证密码
      if (path === '/api/verify-password' || path === '/verify-password') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json();
        const inputPassword = body.password;
        const correctPassword = env.ACCESS_PASSWORD;
        
        if (!correctPassword) {
          return new Response(JSON.stringify({ success: true, message: '未设置密码' }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        if (inputPassword === correctPassword) {
          return new Response(JSON.stringify({ success: true, message: '验证通过' }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } else {
          return new Response(JSON.stringify({ success: false, message: '密码错误，请重试' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：用户注册（需要邀请码）
      if (path === '/api/register' || path === '/register') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json();
        const { username, password, nickname, inviteCode, reason } = body;
        
        if (!username || !password || !nickname || !inviteCode) {
          return new Response(JSON.stringify({ success: false, message: '请填写用户名、密码、昵称和邀请码' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 验证邀请码
        const invite = await env.STATS_KV.get('invite_' + inviteCode, 'json');
        if (!invite) {
          return new Response(JSON.stringify({ success: false, message: '邀请码无效' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        if (invite.status !== 'active') {
          return new Response(JSON.stringify({ success: false, message: '邀请码已失效' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        if (invite.expiresAt && new Date(invite.expiresAt) < new Date()) {
          return new Response(JSON.stringify({ success: false, message: '邀请码已过期' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        const inviteMaxUses = invite.maxUses === 0 ? Infinity : (invite.maxUses || 1);
        if ((invite.usedCount || 0) >= inviteMaxUses) {
          return new Response(JSON.stringify({ success: false, message: '邀请码使用次数已达上限' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 检查用户名是否已存在
        const existingUser = await env.STATS_KV.get('user_' + username, 'json');
        if (existingUser) {
          return new Response(JSON.stringify({ success: false, message: '用户名已被使用' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 密码哈希（2026-09-18：注册即 PBKDF2；弱哈希 simpleHash 仅保留用于存量比对）
        const passwordHash = await pbkdf2Hash(password);
        
        // 生成用户ID
        const userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        
        // 创建用户（状态为待审核）
        const user = {
          id: userId,
          username: username,
          passwordHash: passwordHash,
          nickname: nickname,
          inviteCode: inviteCode,
          reason: reason || '',
          deviceId: deviceId,
          ip: clientIP,
          country: country,
          status: 'pending', // pending / approved / rejected
          createdAt: new Date().toISOString(),
          lastLoginTime: null,
          loginCount: 0,
        };
        
        // 保存用户
        await env.STATS_KV.put('user_' + username, JSON.stringify(user));
        await env.STATS_KV.put('userid_' + userId, JSON.stringify(user));
        
        // 更新邀请码使用次数
        invite.usedCount = (invite.usedCount || 0) + 1;
        invite.usedBy = invite.usedBy || [];
        invite.usedBy.push({ username: username, time: new Date().toISOString() });
        await env.STATS_KV.put('invite_' + inviteCode, JSON.stringify(invite));
        
        // 添加到待审核列表
        const pendingList = await env.STATS_KV.get('pending_registrations', 'json') || [];
        pendingList.push(username);
        await env.STATS_KV.put('pending_registrations', JSON.stringify(pendingList));
        
        return new Response(JSON.stringify({ 
          success: true, 
          message: '注册申请已提交，请等待管理员审核通过后登录',
          username: username
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：用户登录（用户名+密码）
      if (path === '/api/login' || path === '/login') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json();
        const { username, password } = body;
        
        if (!username || !password) {
          return new Response(JSON.stringify({ success: false, message: '请输入用户名和密码' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const user = await env.STATS_KV.get('user_' + username, 'json');
        
        if (!user) {
          return new Response(JSON.stringify({ success: false, message: '用户不存在' }), {
            status: 404,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 验证密码（2026-09-18：PBKDF2/旧格式自适应；旧格式验证通过时惰性升级）
        const pwCheck = await verifyPassword(user.passwordHash, password);
        if (!pwCheck.ok) {
          return new Response(JSON.stringify({ success: false, message: '密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        if (user.status === 'pending') {
          return new Response(JSON.stringify({ success: false, message: '注册申请正在审核中，请耐心等待' }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        if (user.status === 'rejected') {
          return new Response(JSON.stringify({ success: false, message: '注册申请已被拒绝，请联系管理员' }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 更新登录信息；旧式 simpleHash 在验证通过后惰性升级 PBKDF2（对用户无感，硬约束防弱哈希存量）
        user.lastLoginTime = new Date().toISOString();
        user.loginCount = (user.loginCount || 0) + 1;
        if (pwCheck && pwCheck.rehash) {
          user.passwordHash = await pbkdf2Hash(password);
        }
        await env.STATS_KV.put('user_' + username, JSON.stringify(user));
        
        // 生成登录会话：写入 KV（30 天 TTL），Pages 中间件凭此 token 放行全站
        // 2026-09-18：token 改为 crypto.getRandomValues 强随机；不再用 simpleHash
        const token = 'sess_' + randomToken(32);
        await env.STATS_KV.put('session_' + token, JSON.stringify({
          username: user.username,
          nickname: user.nickname,
          status: user.status,
          ip: clientIP,
          deviceId: deviceId,
          createdAt: new Date().toISOString(),
        }), { expirationTtl: 60 * 60 * 24 * 30 });
        
        return new Response(JSON.stringify({ 
          success: true, 
          message: '登录成功',
          token: token,
          user: {
            id: user.id,
            username: user.username,
            nickname: user.nickname,
          }
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：会话校验（Pages 中间件每个请求调用，用于全站访问门槛）
      if (path === '/api/session/verify' || path === '/session/verify') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ success: false, message: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        const body = await request.json().catch(() => ({}));
        const session = body.token ? await env.STATS_KV.get('session_' + body.token, 'json') : null;
        if (!session) {
          return new Response(JSON.stringify({ success: false, message: '会话无效或已过期' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        // 用户被拒/删号时，已发会话立即失效
        const owner = await env.STATS_KV.get('user_' + session.username, 'json');
        if (!owner || owner.status !== 'approved') {
          await env.STATS_KV.delete('session_' + body.token).catch(() => {});
          return new Response(JSON.stringify({ success: false, message: '账号状态异常' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        return new Response(JSON.stringify({
          success: true,
          user: { username: session.username, nickname: session.nickname }
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }

      // 路由：退出登录（删除会话）
      if (path === '/api/logout' || path === '/logout') {
        const body = request.method === 'POST' ? await request.json().catch(() => ({})) : {};
        if (body.token) {
          await env.STATS_KV.delete('session_' + body.token).catch(() => {});
        }
        return new Response(JSON.stringify({ success: true, message: '已退出登录' }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }

      // 路由：邀请码校验（注册页在展示表单前先验一次）
      if (path === '/api/invite/check' || path === '/invite/check') {
        const body = request.method === 'POST' ? await request.json().catch(() => ({})) : {};
        const inviteCode = (body.inviteCode || '').trim();
        if (!inviteCode) {
          return new Response(JSON.stringify({ success: false, message: '缺少邀请码' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        const invite = await env.STATS_KV.get('invite_' + inviteCode, 'json');
        if (!invite) {
          return new Response(JSON.stringify({ success: false, message: '邀请码无效' }), {
            status: 404,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        if (invite.status !== 'active') {
          return new Response(JSON.stringify({ success: false, message: '邀请码已失效' }), {
            status: 410,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        if (invite.expiresAt && new Date(invite.expiresAt) < new Date()) {
          return new Response(JSON.stringify({ success: false, message: '邀请码已过期' }), {
            status: 410,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        const maxUses = invite.maxUses === 0 ? Infinity : (invite.maxUses || 1);
        if ((invite.usedCount || 0) >= maxUses) {
          return new Response(JSON.stringify({ success: false, message: '邀请码使用次数已达上限' }), {
            status: 410,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        return new Response(JSON.stringify({ success: true, note: invite.note || '' }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }

      // 路由：获取用户信息
      if (path === '/api/user/info' || path === '/user/info') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json();
        const { username } = body;
        
        if (!username) {
          return new Response(JSON.stringify({ success: false, message: '未登录' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const user = await env.STATS_KV.get('user_' + username, 'json');
        if (!user) {
          return new Response(JSON.stringify({ success: false, message: '用户不存在' }), {
            status: 404,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        return new Response(JSON.stringify({
          success: true,
          user: {
            id: user.id,
            username: user.username,
            nickname: user.nickname,
            status: user.status,
            createdAt: user.createdAt,
            lastLoginTime: user.lastLoginTime,
            loginCount: user.loginCount,
          }
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：用户发现记录（划线、收藏、阅读历史）
      if (path === '/api/user/discoveries' || path === '/user/discoveries') {
        const body = request.method === 'POST' ? await request.json() : {};
        const { username, action, data } = body;
        
        if (!username) {
          return new Response(JSON.stringify({ success: false, message: '未登录' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const discoveriesKey = 'discoveries_' + username;
        let discoveries = await env.STATS_KV.get(discoveriesKey, 'json') || {
          highlights: [],
          bookmarks: [],
          readingHistory: [],
        };
        
        if (request.method === 'GET' || !action || action === 'get') {
          // 获取发现记录
          return new Response(JSON.stringify({
            success: true,
            discoveries: discoveries
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        if (action === 'add_highlight') {
          // 添加划线
          const highlight = {
            id: 'hl_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6),
            ...data,
            createdTime: new Date().toISOString(),
          };
          discoveries.highlights.push(highlight);
        } else if (action === 'delete_highlight') {
          // 删除划线
          discoveries.highlights = discoveries.highlights.filter(h => h.id !== data.id);
        } else if (action === 'add_bookmark') {
          // 添加收藏
          const exists = discoveries.bookmarks.find(b => b.articleSlug === data.articleSlug);
          if (!exists) {
            discoveries.bookmarks.push({
              ...data,
              createdTime: new Date().toISOString(),
            });
          }
        } else if (action === 'delete_bookmark') {
          // 删除收藏
          discoveries.bookmarks = discoveries.bookmarks.filter(b => b.articleSlug !== data.articleSlug);
        } else if (action === 'add_reading_history') {
          // 添加阅读历史
          const exists = discoveries.readingHistory.find(r => r.articleSlug === data.articleSlug);
          if (exists) {
            exists.readTime = new Date().toISOString();
            exists.duration = (exists.duration || 0) + (data.duration || 0);
          } else {
            discoveries.readingHistory.unshift({
              ...data,
              readTime: new Date().toISOString(),
            });
          }
          // 只保留最近100条
          if (discoveries.readingHistory.length > 100) {
            discoveries.readingHistory = discoveries.readingHistory.slice(0, 100);
          }
        }
        
        // 保存
        await env.STATS_KV.put(discoveriesKey, JSON.stringify(discoveries));
        
        return new Response(JSON.stringify({
          success: true,
          discoveries: discoveries
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：管理员创建邀请码
      if (path === '/api/admin/invite/create' || path === '/admin/invite/create') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }

        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;
        
        const body = await request.json();
        const { code, maxUses, expiresAt, note } = body;
        
        const inviteCode = code || generateInviteCode();
        
        const invite = {
          code: inviteCode,
          maxUses: maxUses || 0, // 0表示不限次数
          usedCount: 0,
          usedBy: [],
          expiresAt: expiresAt || null,
          note: note || '',
          status: 'active',
          createdTime: new Date().toISOString(),
        };
        
        await env.STATS_KV.put('invite_' + inviteCode, JSON.stringify(invite));
        
        // 添加到邀请码列表
        const inviteList = await env.STATS_KV.get('invite_codes', 'json') || [];
        inviteList.push(inviteCode);
        await env.STATS_KV.put('invite_codes', JSON.stringify(inviteList));
        
        return new Response(JSON.stringify({
          success: true,
          inviteCode: inviteCode,
          message: '邀请码创建成功'
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：管理员获取邀请码列表
      if (path === '/api/admin/invite/list' || path === '/admin/invite/list') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;
        
        const inviteList = await env.STATS_KV.get('invite_codes', 'json') || [];
        const invites = [];
        
        for (const code of inviteList) {
          const invite = await env.STATS_KV.get('invite_' + code, 'json');
          if (invite) {
            invites.push(invite);
          }
        }
        
        return new Response(JSON.stringify({
          success: true,
          invites: invites
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      

      
      // 路由：接收页面浏览统计
      if (path === '/api/stats/page-view' && request.method === 'POST') {
        try {
          const body = await request.json();
          const { slug, duration } = body;
          const deviceId = request.headers.get('X-Device-ID') || '';
          // 管理员设备的访问不统计
          if (isAdminDevice(deviceId, env)) {
            return new Response(JSON.stringify({ success: true, message: '管理员设备，不统计' }), {
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          if (slug && duration && duration >= 60) {  // 时长小于1分钟忽略
            const key = 'page_stats_' + slug;
            const existing = await env.STATS_KV.get(key, 'json') || { slug, viewCount: 0, totalDuration: 0 };
            existing.viewCount = (existing.viewCount || 0) + 1;
            existing.totalDuration = (existing.totalDuration || 0) + duration;
            existing.lastViewed = new Date().toISOString();
            await env.STATS_KV.put(key, JSON.stringify(existing));
            // 维护统计列表
            const listKey = 'page_stats_list';
            const list = await env.STATS_KV.get(listKey, 'json') || [];
            if (!list.includes(slug)) {
              list.push(slug);
              await env.STATS_KV.put(listKey, JSON.stringify(list));
            }
          }
          return new Response(JSON.stringify({ success: true }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：接收音频播放统计
      if (path === '/api/stats/audio-play' && request.method === 'POST') {
        try {
          const body = await request.json();
          const { name, duration } = body;
          const deviceId = request.headers.get('X-Device-ID') || '';
          // 管理员设备的访问不统计
          if (isAdminDevice(deviceId, env)) {
            return new Response(JSON.stringify({ success: true, message: '管理员设备，不统计' }), {
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          if (name && duration && duration >= 60) {  // 时长小于1分钟忽略
            const key = 'audio_stats_' + name;
            const existing = await env.STATS_KV.get(key, 'json') || { name, playCount: 0, totalDuration: 0 };
            existing.playCount = (existing.playCount || 0) + 1;
            existing.totalDuration = (existing.totalDuration || 0) + duration;
            existing.lastPlayed = new Date().toISOString();
            await env.STATS_KV.put(key, JSON.stringify(existing));
            // 维护统计列表
            const listKey = 'audio_stats_list';
            const list = await env.STATS_KV.get(listKey, 'json') || [];
            if (!list.includes(name)) {
              list.push(name);
              await env.STATS_KV.put(listKey, JSON.stringify(list));
            }
          }
          return new Response(JSON.stringify({ success: true }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：接收用户点击统计（批量上报）
      if (path === '/api/stats/click' && request.method === 'POST') {
        try {
          const body = await request.json();
          const { clicks, deviceId } = body;
          // 管理员设备的点击不统计
          if (isAdminDevice(deviceId, env)) {
            return new Response(JSON.stringify({ success: true, message: '管理员设备，不统计' }), {
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          if (clicks && Array.isArray(clicks) && clicks.length > 0) {
            const clickSummary = {};
            clicks.forEach(function(c) {
              const key = (c.type || 'unknown') + '|' + (c.target || 'unknown') + '|' + (c.page || 'unknown');
              if (!clickSummary[key]) {
                clickSummary[key] = { type: c.type, target: c.target, page: c.page, count: 0 };
              }
              clickSummary[key].count++;
            });
            // 保存每个点击项的统计
            for (const key in clickSummary) {
              const item = clickSummary[key];
              const statKey = 'click_stats_' + key.replace(/[^a-z0-9]/gi, '_');
              const existing = await env.STATS_KV.get(statKey, 'json') || { type: item.type, target: item.target, page: item.page, count: 0, devices: {} };
              existing.count = (existing.count || 0) + item.count;
              existing.lastClicked = new Date().toISOString();
              if (deviceId) {
                existing.devices[deviceId] = (existing.devices[deviceId] || 0) + item.count;
              }
              await env.STATS_KV.put(statKey, JSON.stringify(existing));
              // 维护点击统计列表
              const listKey = 'click_stats_list';
              const list = await env.STATS_KV.get(listKey, 'json') || [];
              if (!list.includes(statKey)) {
                list.push(statKey);
                await env.STATS_KV.put(listKey, JSON.stringify(list));
              }
            }
          }
          return new Response(JSON.stringify({ success: true }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：管理员重命名设备
      if (path === '/api/admin/device/rename' && request.method === 'POST') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;
        try {
          const body = await request.json();
          const { deviceId, name } = body;
          if (!deviceId) {
            return new Response(JSON.stringify({ success: false, message: '缺少设备ID' }), {
              status: 400,
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          const deviceKey = 'device_' + deviceId;
          const deviceDetail = await env.STATS_KV.get(deviceKey, 'json');
          if (!deviceDetail) {
            return new Response(JSON.stringify({ success: false, message: '设备不存在' }), {
              status: 404,
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          deviceDetail.name = name || '';
          await env.STATS_KV.put(deviceKey, JSON.stringify(deviceDetail));
          return new Response(JSON.stringify({ success: true, device: deviceDetail }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：接收使用时长统计
      if (path === '/api/stats/duration' && request.method === 'POST') {
        try {
          const body = await request.json();
          const { deviceId, duration, page } = body;
          // 管理员设备的使用时长不统计
          if (isAdminDevice(deviceId, env)) {
            return new Response(JSON.stringify({ success: true, message: '管理员设备，不统计' }), {
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          if (deviceId && duration && duration > 0) {
            const today = new Date().toISOString().split('T')[0];
            
            // 记录设备累计使用时长
            const deviceKey = 'device_' + deviceId;
            const deviceDetail = await env.STATS_KV.get(deviceKey, 'json');
            if (deviceDetail) {
              deviceDetail.totalDuration = (deviceDetail.totalDuration || 0) + duration;
              deviceDetail.todayDuration = deviceDetail.todayDuration || {};
              deviceDetail.todayDuration[today] = (deviceDetail.todayDuration[today] || 0) + duration;
              // 只保留最近30天的每日数据
              const days = Object.keys(deviceDetail.todayDuration).sort();
              if (days.length > 30) {
                for (let i = 0; i < days.length - 30; i++) {
                  delete deviceDetail.todayDuration[days[i]];
                }
              }
              // 记录单次使用时长（最近50条）
              deviceDetail.sessionDurations = deviceDetail.sessionDurations || [];
              deviceDetail.sessionDurations.push({
                duration: duration,
                page: page || '',
                date: new Date().toISOString()
              });
              if (deviceDetail.sessionDurations.length > 50) {
                deviceDetail.sessionDurations = deviceDetail.sessionDurations.slice(-50);
              }
              // 更新访问者类型（2026-09-07 统一走动态分类：管理员/爬虫UA/累计时长综合判定）
              deviceDetail.visitorType = classifyVisitor(deviceDetail, env);
              await env.STATS_KV.put(deviceKey, JSON.stringify(deviceDetail)).catch(() => {});
            }
          }
          return new Response(JSON.stringify({ success: true }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：接收设备信息
      if (path === '/api/stats/device-info' && request.method === 'POST') {
        try {
          const body = await request.json();
          const { deviceId, deviceType, os, browser, screenWidth, screenHeight, language, isTouch, isWechat } = body;
          if (deviceId) {
            const deviceKey = 'device_' + deviceId;
            const deviceDetail = await env.STATS_KV.get(deviceKey, 'json');
            if (deviceDetail) {
              deviceDetail.deviceType = deviceType || deviceDetail.deviceType;
              deviceDetail.os = os || deviceDetail.os;
              deviceDetail.browser = browser || deviceDetail.browser;
              deviceDetail.screenWidth = screenWidth || deviceDetail.screenWidth;
              deviceDetail.screenHeight = screenHeight || deviceDetail.screenHeight;
              deviceDetail.language = language || deviceDetail.language;
              deviceDetail.isTouch = isTouch !== undefined ? isTouch : deviceDetail.isTouch;
              deviceDetail.isWechat = isWechat !== undefined ? isWechat : deviceDetail.isWechat;
              await env.STATS_KV.put(deviceKey, JSON.stringify(deviceDetail));
            }
          }
          return new Response(JSON.stringify({ success: true }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：记录设备标识（手机/电脑识别）
      if (path === '/api/stats/identify-device' && request.method === 'POST') {
        try {
          const body = await request.json();
          const { deviceId, identify } = body;
          if (deviceId && identify) {
            const deviceKey = 'device_' + deviceId;
            const deviceDetail = await env.STATS_KV.get(deviceKey, 'json');
            if (deviceDetail) {
              deviceDetail.identify = identify; // 'phone' 或 'pc'
              deviceDetail.identifyTime = new Date().toISOString();
              await env.STATS_KV.put(deviceKey, JSON.stringify(deviceDetail));
            }
          }
          return new Response(JSON.stringify({ success: true }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：管理员获取详细统计数据
      if (path === '/api/admin/stats' || path === '/admin/stats') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;

        // —— 性能优化（2026-09-06）：此前全部为串行 await（约90次KV读取，实测13秒），
        //    现改为两轮 Promise.all 并行读取，延迟从"次数×150ms"降为"两轮×150ms" ——
        // 第一轮：并行读取状态与 5 个索引 key
        const [status, deviceList, ipList, pendingList, pageStatsList, audioStatsList, clickStatsList] = await Promise.all([
          getAccessStatus(env),
          env.STATS_KV.get('unique_devices', 'json'),
          env.STATS_KV.get('unique_ips', 'json'),
          env.STATS_KV.get('pending_registrations', 'json'),
          env.STATS_KV.get('page_stats_list', 'json'),
          env.STATS_KV.get('audio_stats_list', 'json'),
          env.STATS_KV.get('click_stats_list', 'json'),
        ]);

        // 第二轮：并行读取所有详情 key（设备默认取最近 20 个，?devices=all 返回全部）
        const wantAllDevices = url.searchParams.get('devices') === 'all';
        const deviceIds = wantAllDevices ? (deviceList || []) : (deviceList || []).slice(-20);
        const devKeys = deviceIds.map(id => 'device_' + id);
        const ipKeys = (ipList || []).slice(-20).map(i => 'ip_' + i);
        const [devResults, ipResults, pageResults, audioResults, clickResults] = await Promise.all([
          Promise.all(devKeys.map(k => env.STATS_KV.get(k, 'json').catch(() => null))),
          Promise.all(ipKeys.map(k => env.STATS_KV.get(k, 'json').catch(() => null))),
          Promise.all((pageStatsList || []).map(s => env.STATS_KV.get('page_stats_' + s, 'json').catch(() => null))),
          Promise.all((audioStatsList || []).map(n => env.STATS_KV.get('audio_stats_' + n, 'json').catch(() => null))),
          Promise.all((clickStatsList || []).map(k => env.STATS_KV.get(k, 'json').catch(() => null))),
        ]);

        const recentDevices = devResults.filter(Boolean);
        const recentIps = ipResults.filter(Boolean);
        const pageStats = pageResults.filter(Boolean).sort((a, b) => (b.viewCount || 0) - (a.viewCount || 0));
        const audioStats = audioResults.filter(Boolean).sort((a, b) => (b.playCount || 0) - (a.playCount || 0));
        const clickStats = clickResults.filter(Boolean).sort((a, b) => (b.count || 0) - (a.count || 0));

        // —— 访问者动态分类（2026-09-07）：读取时实时计算，不再信任存量快照，历史 unknown 自动归位 ——
        recentDevices.forEach(d => { d.visitorType = classifyVisitor(d, env); });

        // 管理员设备强制并入（可能不在最近20台内，导致"我的设备"卡片显示为空）
        const adminIds = getAdminDeviceIds(env);
        const missingAdminIds = adminIds.filter(id => !devKeys.includes('device_' + id));
        if (missingAdminIds.length > 0) {
          const adminDevs = await Promise.all(missingAdminIds.map(id => env.STATS_KV.get('device_' + id, 'json').catch(() => null)));
          adminDevs.forEach(d => {
            if (d) { d.visitorType = classifyVisitor(d, env); recentDevices.push(d); }
          });
        }

        return new Response(JSON.stringify({
          success: true,
          ...status,
          recentDevices: recentDevices,
          recentIps: recentIps,
          pendingCount: (pendingList || []).length,
          pageStats: pageStats,
          audioStats: audioStats,
          clickStats: clickStats,
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：管理员获取待审核列表
      if (path === '/api/admin/pending' || path === '/admin/pending') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;
        
        const pendingList = await env.STATS_KV.get('pending_registrations', 'json') || [];
        const registrations = [];
        
        for (const regId of pendingList) {
          const reg = await env.STATS_KV.get('reg_' + regId, 'json');
          if (reg && reg.status === 'pending') {
            registrations.push(reg);
          }
        }
        
        return new Response(JSON.stringify({ success: true, registrations }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：管理员审核
      if (path === '/api/admin/review' || path === '/admin/review') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;

        const body = await request.json();
        const { regId, action } = body; // action: 'approve' or 'reject'
        
        if (!regId || !action) {
          return new Response(JSON.stringify({ success: false, message: '参数不完整' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const reg = await env.STATS_KV.get('reg_' + regId, 'json');
        if (!reg) {
          return new Response(JSON.stringify({ success: false, message: '注册申请不存在' }), {
            status: 404,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        reg.status = action === 'approve' ? 'approved' : 'rejected';
        reg.reviewedAt = new Date().toISOString();
        await env.STATS_KV.put('reg_' + regId, JSON.stringify(reg));
        
        // 从待审核列表移除
        const pendingList = await env.STATS_KV.get('pending_registrations', 'json') || [];
        const newPendingList = pendingList.filter(id => id !== regId);
        await env.STATS_KV.put('pending_registrations', JSON.stringify(newPendingList));
        
        return new Response(JSON.stringify({ 
          success: true, 
          message: action === 'approve' ? '已通过审核' : '已拒绝'
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：管理员回填访问者分类（2026-09-07 新增：遍历全部设备重算 visitorType 并写回，
      // 用于清洗历史 unknown 快照。注意消耗 KV 写配额：每台设备 1 次写，免费版每日 1000 次上限）
      if (path === '/api/admin/backfill-classify' && request.method === 'POST') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;

        try {
          const deviceList = await env.STATS_KV.get('unique_devices', 'json').catch(() => null) || [];
          const devResults = await Promise.all(deviceList.map(id => env.STATS_KV.get('device_' + id, 'json').catch(() => null)));

          let updated = 0, failed = 0, unchanged = 0;
          const typeCount = { admin: 0, real: 0, bot: 0, unknown: 0 };

          for (let i = 0; i < devResults.length; i++) {
            const dev = devResults[i];
            if (!dev) continue;
            const newType = classifyVisitor(dev, env);
            typeCount[newType] = (typeCount[newType] || 0) + 1;
            if (dev.visitorType === newType) { unchanged++; continue; }
            dev.visitorType = newType;
            try {
              await env.STATS_KV.put('device_' + deviceList[i], JSON.stringify(dev));
              updated++;
            } catch (e) {
              failed++; // KV 写配额耗尽时跳过，已改为读取时动态分类，不影响展示
            }
          }

          return new Response(JSON.stringify({
            success: true,
            total: deviceList.length,
            updated: updated,
            failed: failed,
            unchanged: unchanged,
            typeCount: typeCount,
            message: '回填完成：更新 ' + updated + ' 台' + (failed > 0 ? '，' + failed + ' 台因写入配额跳过（展示不受影响，分类为读取时动态计算）' : '')
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 500,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }

      // 路由：管理员清理历史统计数据
      if (path === '/api/admin/clear-stats' && request.method === 'POST') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;
        
        try {
          const body = await request.json().catch(() => ({}));
          const { type } = body; // 'all' | 'page' | 'audio' | 'click' | 'ai'
          
          let deletedCount = 0;
          const prefixes = [];
          
          if (type === 'all' || !type) {
            prefixes.push('page_stats_', 'audio_stats_', 'click_stats_', 'ai_ask_');
          } else if (type === 'page') {
            prefixes.push('page_stats_');
          } else if (type === 'audio') {
            prefixes.push('audio_stats_');
          } else if (type === 'click') {
            prefixes.push('click_stats_');
          } else if (type === 'ai') {
            prefixes.push('ai_ask_');
          }
          
          // 分页列出并删除所有匹配的键
          for (const prefix of prefixes) {
            let cursor = '';
            do {
              const listResult = await env.STATS_KV.list({ prefix, cursor, limit: 1000 });
              for (const key of listResult.keys) {
                await env.STATS_KV.delete(key.name);
                deletedCount++;
              }
              cursor = listResult.list_complete ? '' : listResult.cursor;
            } while (cursor);
          }
          
          return new Response(JSON.stringify({ 
            success: true, 
            message: `已清理 ${deletedCount} 条历史统计数据`,
            deletedCount 
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 500,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：管理员手动设置密码保护状态
      if (path === '/api/admin/set-password-status' || path === '/admin/set-password-status') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }

        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;
        
        const body = await request.json();
        const { enabled } = body;
        
        if (typeof enabled !== 'boolean') {
          return new Response(JSON.stringify({ success: false, message: '参数错误，enabled 应为布尔值' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        await env.STATS_KV.put('password_enabled', enabled ? 'true' : 'false');
        
        return new Response(JSON.stringify({ 
          success: true, 
          message: enabled ? '密码保护已开启' : '密码保护已关闭',
          passwordEnabled: enabled
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：创建临时访问链接（管理员）
      if (path === '/api/admin/create-temp-link' || path === '/admin/create-temp-link') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 验证管理员密码（统一鉴权，含防爆破锁定）
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;

        const body = await request.json().catch(() => ({}));
        const duration = body.duration || 10; // 默认10分钟
        
        // 生成随机token
        const token = 'temp_' + Date.now() + '_' + Math.random().toString(36).substr(2, 16);
        const expiresAt = Date.now() + duration * 60 * 1000;
        
        // 存储到KV
        await env.STATS_KV.put('temp_token_' + token, JSON.stringify({
          token: token,
          createdAt: Date.now(),
          expiresAt: expiresAt,
          duration: duration
        }), { expirationTtl: duration * 60 + 60 }); // 多留60秒余量
        
        const tempLink = 'https://longchen-nyingtik.wiki/?temp=' + token;
        
        return new Response(JSON.stringify({ 
          success: true, 
          message: '临时链接已创建',
          token: token,
          link: tempLink,
          expiresAt: new Date(expiresAt).toISOString(),
          duration: duration
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：验证临时token
      if (path === '/api/verify-temp' || path === '/verify-temp') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json().catch(() => ({}));
        const token = body.token || '';
        
        if (!token) {
          return new Response(JSON.stringify({ success: false, message: '缺少token' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 从KV中获取token信息
        const tokenData = await env.STATS_KV.get('temp_token_' + token);
        if (!tokenData) {
          return new Response(JSON.stringify({ success: false, message: '临时链接无效或已过期' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        try {
          const data = JSON.parse(tokenData);
          if (Date.now() > data.expiresAt) {
            return new Response(JSON.stringify({ success: false, message: '临时链接已过期' }), {
              status: 401,
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          
          return new Response(JSON.stringify({ 
            success: true, 
            message: '验证通过',
            expiresAt: new Date(data.expiresAt).toISOString(),
            remainingSeconds: Math.floor((data.expiresAt - Date.now()) / 1000)
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, message: '临时链接数据错误' }), {
            status: 500,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：AI问答统计（2026-09-06 收紧：仅管理员可访问，防止访客提问内容泄露）
      if (path === '/api/stats/ai-ask' || path === '/stats/ai-ask') {
        const auth = await checkAdminAuth(request, env, url);
        if (!auth.ok) return auth.response;

        try {
          // 并行读取：汇总 + 最近7天每日统计 + 最近日志（此前为9次串行读取）
          const today = new Date();
          const dayKeys = [];
          for (let i = 6; i >= 0; i--) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            dayKeys.push(d.toISOString().split('T')[0]);
          }

          const [summary, dailyResults, recentLogs] = await Promise.all([
            env.STATS_KV.get('ai_ask_summary', 'json').catch(() => null),
            Promise.all(dayKeys.map(ds => env.STATS_KV.get('ai_ask_daily_' + ds, 'json').catch(() => null))),
            env.STATS_KV.get('ai_ask_recent_logs', 'json').catch(() => null),
          ]);

          const summaryData = summary || {
            totalCalls: 0, successCalls: 0, failedCalls: 0,
            totalTokens: 0, totalPromptTokens: 0, totalCompletionTokens: 0,
            totalResponseTime: 0, withContextCalls: 0, withoutContextCalls: 0,
            firstCallTime: null, lastCallTime: null
          };

          const dailyStats = dayKeys.map((dateStr, idx) => {
            const daily = dailyResults[idx];
            if (daily) {
              return {
                date: dateStr,
                totalCalls: daily.totalCalls || 0,
                successCalls: daily.successCalls || 0,
                failedCalls: daily.failedCalls || 0,
                totalTokens: daily.totalTokens || 0,
                uniqueUsers: daily.uniqueUsers || 0,
                hourlyCalls: daily.hourlyCalls || []
              };
            }
            return {
              date: dateStr,
              totalCalls: 0, successCalls: 0, failedCalls: 0,
              totalTokens: 0, uniqueUsers: 0, hourlyCalls: []
            };
          });

          const logs = recentLogs || [];
          
          // 从最近日志中提取用户统计
          const userMap = {};
          for (const log of logs) {
            if (!userMap[log.userId]) {
              userMap[log.userId] = {
                userId: log.userId,
                totalCalls: 0,
                successCalls: 0,
                failedCalls: 0,
                totalTokens: 0,
                lastCallTime: 0,
                recentQuestions: []
              };
            }
            userMap[log.userId].totalCalls++;
            if (log.success) userMap[log.userId].successCalls++;
            else userMap[log.userId].failedCalls++;
            userMap[log.userId].totalTokens += log.tokens || 0;
            if (log.timestamp > userMap[log.userId].lastCallTime) {
              userMap[log.userId].lastCallTime = log.timestamp;
            }
            if (log.question && userMap[log.userId].recentQuestions.length < 3) {
              userMap[log.userId].recentQuestions.push(log.question);
            }
          }
          const userStats = Object.values(userMap).sort((a, b) => b.totalCalls - a.totalCalls).slice(0, 20);
          
          // 4. 计算统计指标
          const avgTokens = summaryData.totalCalls > 0 ? Math.round(summaryData.totalTokens / summaryData.totalCalls) : 0;
          const avgResponseTime = summaryData.totalCalls > 0 ? Math.round(summaryData.totalResponseTime / summaryData.totalCalls) : 0;
          const successRate = summaryData.totalCalls > 0 ? ((summaryData.successCalls / summaryData.totalCalls) * 100).toFixed(1) : 0;

          return new Response(JSON.stringify({
            success: true,
            summary: {
              ...summaryData,
              avgTokens: avgTokens,
              avgResponseTime: avgResponseTime,
              successRate: parseFloat(successRate)
            },
            dailyStats: dailyStats,
            userStats: userStats,
            recentLogs: logs.slice(0, 20)
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), {
            status: 500,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 默认：404
      return new Response(JSON.stringify({ 
        error: 'Not found', 
        paths: ['/api/track', '/api/stats', '/api/verify-password', '/api/register', '/api/login', '/api/user/info', '/api/user/discoveries', '/api/admin/pending', '/api/admin/review', '/api/admin/invite/create', '/api/admin/invite/list', '/api/admin/create-temp-link', '/api/verify-temp', '/api/stats/ai-ask', '/api/stats/click', '/api/stats/page-view', '/api/stats/audio-play', '/api/admin/device/rename', '/api/stats/duration', '/api/stats/device-info', '/api/stats/identify-device'] 
      }), {
        status: 404,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
      
    } catch (error) {
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }
  },
};

// 简单哈希函数（用于密码，实际生产应使用bcrypt）
// ---------------------------------------------------------------------------
// 密码哈希（2026-09-18 升级）：PBKDF2-SHA256 + 惰性迁移
// 存储格式：
//   旧行内哈希：'h_xxxx_<len>'（simpleHash，弱；仅用于读旧比对）
//   新格式：'pbkdf2$<iterations>$<saltB64>$<hashB64>'（登录成功时惰性重哈希存量用户）
// Workers 原生支持 crypto.subtle（Web Crypto），PBKDF2-SHA256 10 万次约几十 ms
// ---------------------------------------------------------------------------
const PBKDF2_ITERATIONS = 100000;

function b64encode(bytes) {
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function b64decode(s) {
  const bin = atob(s);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}

// 新格式：'pbkdf2$<iterations>$<saltB64>$<hashB64>'
async function pbkdf2Hash(password, saltB64, iterations) {
  const fromB64 = !!saltB64;
  const salt = saltB64 ? b64decode(saltB64) : crypto.getRandomValues(new Uint8Array(16));
  const keyMaterial = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']
  );
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: salt, iterations: iterations || PBKDF2_ITERATIONS },
    keyMaterial,
    256
  );
  return ['pbkdf2', (iterations || PBKDF2_ITERATIONS), b64encode(salt), b64encode(new Uint8Array(bits))].join('$');
}
// 校验：按存储格式分派；能识别的格式都返回 { ok, rehash? }（rehash=旧格式验证通过后需要升级）
async function verifyPassword(stored, password) {
  if (typeof stored === 'string' && stored.indexOf('pbkdf2$') === 0) {
    const parts = stored.split('$');
    const iters = parseInt(parts[1], 10) || PBKDF2_ITERATIONS;
    const saltB64 = parts[2], want = parts[3];
    const got = await pbkdf2Hash(password, saltB64, iters);
    const gotHash = got.split('$')[3];
    let diff = want.length ^ gotHash.length;
    for (let i = 0; i < want.length && i < gotHash.length; i++) diff |= want.charCodeAt(i) ^ gotHash.charCodeAt(i);
    return { ok: diff === 0, rehash: false };
  }
  // 旧格式（simpleHash）
  const legacy = simpleHash(password);
  if (legacy === stored) return { ok: true, rehash: true };
  return { ok: false, rehash: false };
}
function randomToken(n) {
  const u = crypto.getRandomValues(new Uint8Array(n || 32));
  return b64encode(u).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function simpleHash(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return 'h_' + Math.abs(hash).toString(36) + '_' + str.length;
}

// 判断是否为管理员设备（用于统计剔除）
function isAdminDevice(deviceId, env) {
  if (!deviceId) return false;
  const adminDeviceIds = (env.ADMIN_DEVICE_IDS || '').split(',').map(s => s.trim()).filter(s => s);
  return adminDeviceIds.includes(deviceId);
}

/**
 * 访问者动态分类（2026-09-07 新增，第二阶段核心）
 * 取代"访问时写快照"的旧机制——每次读取统计时实时计算，历史 unknown 数据自动归位。
 * 优先级：
 *   1. deviceId 在管理员名单          → admin（金色）
 *   2. Cloudflare bot 评分存在且 <30  → bot（灰色）
 *   3. UA 命中爬虫特征库              → bot（灰色）
 *   4. 累计停留 ≥60 秒                → real（绿色）
 *   5. 其余                           → unknown（新访客，浅色）
 */
const BOT_UA_PATTERNS = /bot|crawl|spider|slurp|semrush|ahrefs|mj12|dotbot|petalbot|bytespider|yandex|baidu|sogou|360spy|headless|python-requests|python-urllib|curl\/|wget|scrapy|httpclient|okhttp|go-http|java\/|libwww|axios|node-fetch|postman/i;

function classifyVisitor(device, env) {
  if (!device) return 'unknown';
  // 1. 管理员名单优先
  if (isAdminDevice(device.deviceId, env)) return 'admin';
  // 2. Cloudflare bot 评分（1-99，<30 大概率机器人；字段缺失时跳过）
  if (typeof device.botScore === 'number' && device.botScore < 30) return 'bot';
  // 3. UA 爬虫特征
  const ua = device.userAgent || '';
  if (ua && BOT_UA_PATTERNS.test(ua)) return 'bot';
  // 4. 累计停留时长
  if ((device.totalDuration || 0) >= 60) return 'real';
  // 5. 新访客
  return 'unknown';
}

function getAdminDeviceIds(env) {
  return (env.ADMIN_DEVICE_IDS || '').split(',').map(s => s.trim()).filter(Boolean);
}

/**
 * 管理员统一鉴权（2026-09-06 新增，含防爆破锁定）
 * - 密码来源：X-Admin-Token 请求头（兼容 ?admin= 查询参数）
 * - 防爆破：同一 IP 15 分钟窗口内连续失败 5 次 → 锁定 15 分钟（KV 计数）
 * - 密码正确时自动清除失败计数
 * 返回 { ok: true } 或 { ok: false, response: Response }
 */
async function checkAdminAuth(request, env, url) {
  const json = (obj, status) => new Response(JSON.stringify(obj), {
    status,
    headers: {
      // 2026-09-18：管理响应同样收窄到本站（admin.html 与本 Worker 同站使用，无跨站调用方）
      'Access-Control-Allow-Origin': (request.headers.get('Origin') || '').endsWith('longchen-nyingtik.wiki')
        ? request.headers.get('Origin') : 'null',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-Device-ID, X-Admin-Token',
      'Vary': 'Origin',
      'Content-Type': 'application/json',
    },
  });

  const inputPass = request.headers.get('X-Admin-Token') || url.searchParams.get('admin') || '';
  // 2026-09-18：移除内置兜底（旧口令已入 git 历史视同泄露）。未配置 ADMIN_PASSWORD 时
  // 明确失败（500），绝不静默放行或落到仓库明文——口令只存 Cloudflare Secret
  if (!env.ADMIN_PASSWORD) {
    console.error('ADMIN_PASSWORD secret 未配置，拒绝管理请求');
    return { ok: false, response: json({ success: false, message: '服务端未配置管理口令（ADMIN_PASSWORD）' }, 500) };
  }
  const correctPass = env.ADMIN_PASSWORD;
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  const failKey = 'admin_fail_' + ip;

  // 1. 检查是否处于锁定期
  let failData = null;
  try { failData = await env.STATS_KV.get(failKey, 'json'); } catch (e) { failData = null; }
  if (failData && failData.lockedUntil && Date.now() < failData.lockedUntil) {
    const remainMin = Math.ceil((failData.lockedUntil - Date.now()) / 60000);
    return { ok: false, response: json({ success: false, message: '失败次数过多，已临时锁定，请 ' + remainMin + ' 分钟后再试' }, 429) };
  }

  // 2. 比对密码（KV 写失败不阻断鉴权：拒绝访问是目的，失败计数尽力而为）
  if (inputPass !== correctPass) {
    const count = ((failData && failData.windowEnd && Date.now() < failData.windowEnd) ? failData.count : 0) + 1;
    if (count >= 5) {
      const until = Date.now() + 15 * 60 * 1000;
      await env.STATS_KV.put(failKey, JSON.stringify({ count: count, windowEnd: until, lockedUntil: until }), { expirationTtl: 16 * 60 }).catch(() => {});
      return { ok: false, response: json({ success: false, message: '密码错误次数过多，已锁定 15 分钟' }, 429) };
    }
    await env.STATS_KV.put(failKey, JSON.stringify({ count: count, windowEnd: Date.now() + 15 * 60 * 1000 }), { expirationTtl: 16 * 60 }).catch(() => {});
    return { ok: false, response: json({ success: false, message: '管理员密码错误（再错 ' + (5 - count) + ' 次将锁定 15 分钟）' }, 401) };
  }

  // 3. 密码正确，清除失败计数（尽力而为）
  if (failData) {
    await env.STATS_KV.delete(failKey).catch(() => {});
  }
  return { ok: true };
}

// 生成邀请码
function generateInviteCode() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let code = '';
  for (let i = 0; i < 8; i++) {
    code += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return code;
}

/**
 * 记录设备（累计，不重置）
 */
async function recordDevice(kv, deviceId, ip, geo, userAgent, botScore) {
  if (!kv || !deviceId) return;
  const country = geo?.country || 'UNKNOWN';

  // 说明：统计写入均为"尽力而为"（2026-09-06 加固）——免费版 KV 写入配额耗尽时
  // 静默放弃本条统计，绝不抛异常阻断 /api/track（否则主站访客请求会 500）。

  // 记录设备（去重）
  const key = 'unique_devices';
  const existing = await kv.get(key, 'json').catch(() => null);
  const deviceSet = new Set(existing || []);

  if (!deviceSet.has(deviceId)) {
    deviceSet.add(deviceId);
    await kv.put(key, JSON.stringify([...deviceSet])).catch(() => {});

    // 记录设备详情（含地理位置、UA、bot评分）
    await kv.put('device_' + deviceId, JSON.stringify({
      deviceId,
      firstIp: ip,
      country: country,
      region: geo?.region || '',
      city: geo?.city || '',
      timezone: geo?.timezone || '',
      firstSeen: new Date().toISOString(),
      lastSeen: new Date().toISOString(),
      visitCount: 1,
      userAgent: userAgent || '',
      botScore: (typeof botScore === 'number') ? botScore : null,
      visitorType: 'unknown', // 存量字段保留兼容，读取时由 classifyVisitor 动态计算
    })).catch(() => {});
  } else {
    // 已存在的设备：更新最近访问时间、访问次数、最新UA与bot评分
    const deviceDetail = await kv.get('device_' + deviceId, 'json').catch(() => null);
    if (deviceDetail) {
      deviceDetail.lastSeen = new Date().toISOString();
      deviceDetail.visitCount = (deviceDetail.visitCount || 0) + 1;
      if (userAgent) deviceDetail.userAgent = userAgent;
      if (typeof botScore === 'number') deviceDetail.botScore = botScore;
      await kv.put('device_' + deviceId, JSON.stringify(deviceDetail)).catch(() => {});
    }
  }

  // 记录 IP（去重）
  if (ip && ip !== 'unknown') {
    const ipKey = 'unique_ips';
    const existingIps = await kv.get(ipKey, 'json').catch(() => null);
    const ipSet = new Set(existingIps || []);

    if (!ipSet.has(ip)) {
      ipSet.add(ip);
      await kv.put(ipKey, JSON.stringify([...ipSet])).catch(() => {});

      // 记录 IP 详情（含地理位置）
      await kv.put('ip_' + ip, JSON.stringify({
        ip,
        country: country,
        region: geo?.region || '',
        city: geo?.city || '',
        postalCode: geo?.postalCode || '',
        latitude: geo?.latitude || '',
        longitude: geo?.longitude || '',
        timezone: geo?.timezone || '',
        firstSeen: new Date().toISOString(),
        lastSeen: new Date().toISOString(),
        visitCount: 1,
        deviceId: deviceId,
      })).catch(() => {});
    } else {
      // 已存在的 IP：更新最近访问时间和访问次数
      const ipDetail = await kv.get('ip_' + ip, 'json').catch(() => null);
      if (ipDetail) {
        ipDetail.lastSeen = new Date().toISOString();
        ipDetail.visitCount = (ipDetail.visitCount || 0) + 1;
        await kv.put('ip_' + ip, JSON.stringify(ipDetail)).catch(() => {});
      }
    }
  }
}

/**
 * 获取访问状态（2026-09-06 优化：4个KV读取并行化，此函数被每次页面加载的 /api/track 调用）
 */
async function getAccessStatus(env) {
  const kv = env.STATS_KV;
  const deviceThreshold = parseInt(env.DEVICE_THRESHOLD || '10');
  const registerThreshold = parseInt(env.REGISTER_THRESHOLD || '100');

  // 并行读取设备数、密码开关、注册开关、IP数
  const [devices, pwdFlag, regFlag, ips] = await Promise.all([
    kv ? kv.get('unique_devices', 'json') : Promise.resolve(null),
    kv ? kv.get('password_enabled') : Promise.resolve(null),
    kv ? kv.get('register_enabled') : Promise.resolve(null),
    kv ? kv.get('unique_ips', 'json') : Promise.resolve(null),
  ]);

  const deviceCount = devices ? devices.length : 0;
  const ipCount = ips ? ips.length : 0;
  let passwordEnabled = pwdFlag === 'true';
  let registerEnabled = regFlag === 'true';

  // 如果累计设备数达到阈值且尚未启用，永久启用（写操作仅在首次触发时发生，失败不阻断）
  if (deviceCount >= deviceThreshold && !passwordEnabled && kv) {
    await kv.put('password_enabled', 'true').catch(() => {});
    passwordEnabled = true;
  }

  // 如果累计设备数达到注册阈值且尚未启用，启用注册审核
  if (deviceCount >= registerThreshold && !registerEnabled && kv) {
    await kv.put('register_enabled', 'true').catch(() => {});
    registerEnabled = true;
  }

  return {
    deviceCount: deviceCount,
    ipCount: ipCount,
    deviceThreshold: deviceThreshold,
    registerThreshold: registerThreshold,
    passwordEnabled: passwordEnabled,
    registerEnabled: registerEnabled,
    needPassword: passwordEnabled, // 一旦启用，永久需要密码或注册登录
    needRegister: registerEnabled, // 一旦启用，需要注册审核
  };
}
