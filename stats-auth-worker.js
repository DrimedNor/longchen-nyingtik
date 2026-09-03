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
      'Access-Control-Allow-Headers': 'Content-Type, X-Device-ID',
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
        // 国外访问不统计，直接返回不需要限制
        if (!isChina) {
          return new Response(JSON.stringify({ 
            success: true, 
            country: country,
            isChina: false,
            needPassword: false,
            needRegister: false,
            message: '国外访问，不设限制'
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 国内访问：记录设备
        if (deviceId) {
          await recordDevice(env.STATS_KV, deviceId, clientIP, country);
        }
        
        const status = await getAccessStatus(env);
        return new Response(JSON.stringify({ 
          success: true, 
          country: country,
          isChina: true,
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
      
      // 路由：用户注册申请
      if (path === '/api/register' || path === '/register') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json();
        const { nickname, reason, contact } = body;
        
        if (!nickname || !reason) {
          return new Response(JSON.stringify({ success: false, message: '请填写昵称和申请理由' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        // 生成注册申请 ID
        const regId = 'reg_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        const registration = {
          id: regId,
          nickname,
          reason,
          contact: contact || '',
          deviceId: deviceId,
          ip: clientIP,
          country: country,
          status: 'pending', // pending / approved / rejected
          createdAt: new Date().toISOString(),
        };
        
        // 保存注册申请
        await env.STATS_KV.put('reg_' + regId, JSON.stringify(registration));
        
        // 添加到待审核列表
        const pendingList = await env.STATS_KV.get('pending_registrations', 'json') || [];
        pendingList.push(regId);
        await env.STATS_KV.put('pending_registrations', JSON.stringify(pendingList));
        
        return new Response(JSON.stringify({ 
          success: true, 
          message: '注册申请已提交，请等待管理员审核',
          regId: regId
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：用户登录（审核通过后）
      if (path === '/api/login' || path === '/login') {
        if (request.method !== 'POST') {
          return new Response(JSON.stringify({ error: 'Method not allowed' }), {
            status: 405,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        
        const body = await request.json();
        const { regId } = body;
        
        if (!regId) {
          return new Response(JSON.stringify({ success: false, message: '请提供注册 ID' }), {
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
        
        if (reg.status === 'approved') {
          return new Response(JSON.stringify({ 
            success: true, 
            message: '登录成功',
            nickname: reg.nickname
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } else if (reg.status === 'pending') {
          return new Response(JSON.stringify({ success: false, message: '注册申请正在审核中，请耐心等待' }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        } else {
          return new Response(JSON.stringify({ success: false, message: '注册申请已被拒绝，请联系管理员' }), {
            status: 403,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
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
      
      // 默认：404
      return new Response(JSON.stringify({ 
        error: 'Not found', 
        paths: ['/api/track', '/api/stats', '/api/verify-password', '/api/register', '/api/login', '/api/admin/pending', '/api/admin/review'] 
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

/**
 * 记录设备（累计，不重置）
 */
async function recordDevice(kv, deviceId, ip, country) {
  if (!kv || !deviceId) return;
  
  const key = 'unique_devices';
  const existing = await kv.get(key, 'json');
  const deviceSet = new Set(existing || []);
  
  if (!deviceSet.has(deviceId)) {
    deviceSet.add(deviceId);
    await kv.put(key, JSON.stringify([...deviceSet]));
    
    // 记录设备详情
    await kv.put('device_' + deviceId, JSON.stringify({
      deviceId,
      firstIp: ip,
      country: country,
      firstSeen: new Date().toISOString(),
    }));
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
  
  return {
    deviceCount: deviceCount,
    deviceThreshold: deviceThreshold,
    registerThreshold: registerThreshold,
    passwordEnabled: passwordEnabled,
    registerEnabled: registerEnabled,
    needPassword: passwordEnabled, // 一旦启用，永久需要密码或注册登录
    needRegister: registerEnabled, // 一旦启用，需要注册审核
  };
}
