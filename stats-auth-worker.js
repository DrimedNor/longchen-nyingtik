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
    
    // CORS 头
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-Device-ID, X-Admin-Password',
    };
    
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
          await recordDevice(env.STATS_KV, deviceId, clientIP, geo);
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
        
        // 检查用户名是否已存在
        const existingUser = await env.STATS_KV.get('user_' + username, 'json');
        if (existingUser) {
          return new Response(JSON.stringify({ success: false, message: '用户名已被使用' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 简单密码哈希（实际生产应使用bcrypt，这里用简单哈希）
        const passwordHash = simpleHash(password);
        
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
        
        // 验证密码
        const passwordHash = simpleHash(password);
        if (user.passwordHash !== passwordHash) {
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
        
        // 更新登录信息
        user.lastLoginTime = new Date().toISOString();
        user.loginCount = (user.loginCount || 0) + 1;
        await env.STATS_KV.put('user_' + username, JSON.stringify(user));
        
        // 生成登录token（简单实现，实际应使用JWT）
        const token = simpleHash(username + Date.now() + Math.random());
        
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
        
        const adminPassword = request.headers.get('X-Admin-Password');
        if (adminPassword !== (env.ADMIN_PASSWORD || 'admin610')) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
        const adminPassword = request.headers.get('X-Admin-Password');
        if (adminPassword !== (env.ADMIN_PASSWORD || 'admin610')) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
        const adminPass = request.headers.get('X-Admin-Password') || url.searchParams.get('admin');
        if (adminPass !== (env.ADMIN_PASSWORD || 'admin610')) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
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
              // 更新访问者类型：总停留时间<60秒为爬虫，否则为真实用户
              if (deviceDetail.totalDuration >= 60) {
                deviceDetail.visitorType = 'real';
              } else {
                deviceDetail.visitorType = 'bot';
              }
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
        const adminPass = request.headers.get('X-Admin-Password') || url.searchParams.get('admin');
        if (adminPass !== env.ADMIN_PASSWORD) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const status = await getAccessStatus(env);
        
        // 获取设备列表（最近 20 个）
        const deviceList = await env.STATS_KV.get('unique_devices', 'json') || [];
        const recentDevices = [];
        for (let i = Math.max(0, deviceList.length - 20); i < deviceList.length; i++) {
          const dev = await env.STATS_KV.get('device_' + deviceList[i], 'json');
          if (dev) recentDevices.push(dev);
        }
        
        // 获取 IP 列表（最近 20 个）
        const ipList = await env.STATS_KV.get('unique_ips', 'json') || [];
        const recentIps = [];
        for (let i = Math.max(0, ipList.length - 20); i < ipList.length; i++) {
          const ipInfo = await env.STATS_KV.get('ip_' + ipList[i], 'json');
          if (ipInfo) recentIps.push(ipInfo);
        }
        
        // 获取已通过和已拒绝的注册数
        const pendingList = await env.STATS_KV.get('pending_registrations', 'json') || [];
        
        // 获取页面浏览统计
        const pageStatsList = await env.STATS_KV.get('page_stats_list', 'json') || [];
        const pageStats = [];
        for (const slug of pageStatsList) {
          const stat = await env.STATS_KV.get('page_stats_' + slug, 'json');
          if (stat) pageStats.push(stat);
        }
        pageStats.sort((a, b) => (b.viewCount || 0) - (a.viewCount || 0));
        
        // 获取音频播放统计
        const audioStatsList = await env.STATS_KV.get('audio_stats_list', 'json') || [];
        const audioStats = [];
        for (const name of audioStatsList) {
          const stat = await env.STATS_KV.get('audio_stats_' + name, 'json');
          if (stat) audioStats.push(stat);
        }
        audioStats.sort((a, b) => (b.playCount || 0) - (a.playCount || 0));
        
        // 获取点击统计
        const clickStatsList = await env.STATS_KV.get('click_stats_list', 'json') || [];
        const clickStats = [];
        for (const key of clickStatsList) {
          const stat = await env.STATS_KV.get(key, 'json');
          if (stat) clickStats.push(stat);
        }
        clickStats.sort((a, b) => (b.count || 0) - (a.count || 0));
        
        return new Response(JSON.stringify({ 
          success: true, 
          ...status,
          recentDevices: recentDevices,
          recentIps: recentIps,
          pendingCount: pendingList.length,
          pageStats: pageStats,
          audioStats: audioStats,
          clickStats: clickStats,
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：管理员获取待审核列表
      if (path === '/api/admin/pending' || path === '/admin/pending') {
        const adminPass = request.headers.get('X-Admin-Password') || url.searchParams.get('admin');
        if (adminPass !== env.ADMIN_PASSWORD) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
        
        const adminPass = request.headers.get('X-Admin-Password');
        if (adminPass !== env.ADMIN_PASSWORD) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
      
      // 路由：管理员清理历史统计数据
      if (path === '/api/admin/clear-stats' && request.method === 'POST') {
        const adminPass = request.headers.get('X-Admin-Password') || url.searchParams.get('admin');
        if (adminPass !== (env.ADMIN_PASSWORD || 'admin610')) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
        
        const adminPass = request.headers.get('X-Admin-Password');
        if (adminPass !== env.ADMIN_PASSWORD) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
        
        // 验证管理员密码
        const adminPassword = request.headers.get('X-Admin-Password') || '';
        const correctAdminPassword = env.ADMIN_PASSWORD;
        if (correctAdminPassword && adminPassword !== correctAdminPassword) {
          return new Response(JSON.stringify({ success: false, message: '管理员密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
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
      
      // 路由：AI问答统计
      if (path === '/api/stats/ai-ask' || path === '/stats/ai-ask') {
        try {
          // 1. 获取汇总统计
          const summary = await env.STATS_KV.get('ai_ask_summary', 'json').catch(() => null) || {
            totalCalls: 0, successCalls: 0, failedCalls: 0,
            totalTokens: 0, totalPromptTokens: 0, totalCompletionTokens: 0,
            totalResponseTime: 0, withContextCalls: 0, withoutContextCalls: 0,
            firstCallTime: null, lastCallTime: null
          };
          
          // 2. 获取最近7天的每日统计
          const dailyStats = [];
          const today = new Date();
          for (let i = 6; i >= 0; i--) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            const dateStr = d.toISOString().split('T')[0];
            const daily = await env.STATS_KV.get(`ai_ask_daily_${dateStr}`, 'json').catch(() => null);
            if (daily) {
              dailyStats.push({
                date: dateStr,
                totalCalls: daily.totalCalls || 0,
                successCalls: daily.successCalls || 0,
                failedCalls: daily.failedCalls || 0,
                totalTokens: daily.totalTokens || 0,
                uniqueUsers: daily.uniqueUsers || 0,
                hourlyCalls: daily.hourlyCalls || []
              });
            } else {
              dailyStats.push({
                date: dateStr,
                totalCalls: 0, successCalls: 0, failedCalls: 0,
                totalTokens: 0, uniqueUsers: 0, hourlyCalls: []
              });
            }
          }
          
          // 3. 获取用户统计（通过汇总中的uniqueUsers无法直接获取列表，需要从最近日志中提取）
          const recentLogs = await env.STATS_KV.get('ai_ask_recent_logs', 'json').catch(() => []) || [];
          
          // 从最近日志中提取用户统计
          const userMap = {};
          for (const log of recentLogs) {
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
          const avgTokens = summary.totalCalls > 0 ? Math.round(summary.totalTokens / summary.totalCalls) : 0;
          const avgResponseTime = summary.totalCalls > 0 ? Math.round(summary.totalResponseTime / summary.totalCalls) : 0;
          const successRate = summary.totalCalls > 0 ? ((summary.successCalls / summary.totalCalls) * 100).toFixed(1) : 0;
          
          return new Response(JSON.stringify({
            success: true,
            summary: {
              ...summary,
              avgTokens: avgTokens,
              avgResponseTime: avgResponseTime,
              successRate: parseFloat(successRate)
            },
            dailyStats: dailyStats,
            userStats: userStats,
            recentLogs: recentLogs.slice(0, 20)
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
async function recordDevice(kv, deviceId, ip, geo) {
  if (!kv || !deviceId) return;
  const country = geo?.country || 'UNKNOWN';
  
  // 记录设备（去重）
  const key = 'unique_devices';
  const existing = await kv.get(key, 'json');
  const deviceSet = new Set(existing || []);
  
  if (!deviceSet.has(deviceId)) {
    deviceSet.add(deviceId);
    await kv.put(key, JSON.stringify([...deviceSet]));
    
    // 记录设备详情（含地理位置）
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
      visitorType: 'unknown', // admin / bot / real
    }));
  } else {
    // 已存在的设备：更新最近访问时间和访问次数
    const deviceDetail = await kv.get('device_' + deviceId, 'json');
    if (deviceDetail) {
      deviceDetail.lastSeen = new Date().toISOString();
      deviceDetail.visitCount = (deviceDetail.visitCount || 0) + 1;
      await kv.put('device_' + deviceId, JSON.stringify(deviceDetail));
    }
  }
  
  // 记录 IP（去重）
  if (ip && ip !== 'unknown') {
    const ipKey = 'unique_ips';
    const existingIps = await kv.get(ipKey, 'json');
    const ipSet = new Set(existingIps || []);
    
    if (!ipSet.has(ip)) {
      ipSet.add(ip);
      await kv.put(ipKey, JSON.stringify([...ipSet]));
      
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
      }));
    } else {
      // 已存在的 IP：更新最近访问时间和访问次数
      const ipDetail = await kv.get('ip_' + ip, 'json');
      if (ipDetail) {
        ipDetail.lastSeen = new Date().toISOString();
        ipDetail.visitCount = (ipDetail.visitCount || 0) + 1;
        await kv.put('ip_' + ip, JSON.stringify(ipDetail));
      }
    }
  }
}

/**
 * 获取访问状态
 */
async function getAccessStatus(env) {
  const kv = env.STATS_KV;
  const deviceThreshold = parseInt(env.DEVICE_THRESHOLD || '10');
  const registerThreshold = parseInt(env.REGISTER_THRESHOLD || '100');
  
  let deviceCount = 0;
  if (kv) {
    const existing = await kv.get('unique_devices', 'json');
    deviceCount = existing ? existing.length : 0;
  }
  
  // 检查是否已永久启用密码保护
  let passwordEnabled = false;
  if (kv) {
    const flag = await kv.get('password_enabled');
    passwordEnabled = flag === 'true';
  }
  
  // 检查是否已启用注册审核
  let registerEnabled = false;
  if (kv) {
    const flag = await kv.get('register_enabled');
    registerEnabled = flag === 'true';
  }
  
  // 如果累计设备数达到阈值且尚未启用，永久启用
  if (deviceCount >= deviceThreshold && !passwordEnabled && kv) {
    await kv.put('password_enabled', 'true');
    passwordEnabled = true;
  }
  
  // 如果累计设备数达到注册阈值且尚未启用，启用注册审核
  if (deviceCount >= registerThreshold && !registerEnabled && kv) {
    await kv.put('register_enabled', 'true');
    registerEnabled = true;
  }
  
  // 统计 IP 数
  let ipCount = 0;
  if (kv) {
    const existingIps = await kv.get('unique_ips', 'json');
    ipCount = existingIps ? existingIps.length : 0;
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
