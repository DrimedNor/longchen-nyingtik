/**
 * 访问统计与密码验证 Worker
 * 
 * 功能：
 * 1. 记录累计独立 IP 数（存储在 KV 中，不重置）
 * 2. 一旦累计独立 IP 达到阈值，永久启用密码保护
 * 3. 提供 /api/stats 接口返回统计状态和是否需要密码
 * 4. 提供 /api/verify-password 接口验证访问密码
 * 5. 提供 /api/track 接口记录访问 IP
 * 
 * 环境变量：
 * - ACCESS_PASSWORD：访问密码（启用密码保护后需要）
 * - IP_THRESHOLD：累计独立 IP 阈值，默认 10，达到后永久启用密码保护
 * 
 * KV 命名空间绑定：
 * - STATS_KV：存储统计数据
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    
    // CORS 头
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };
    
    // 处理 OPTIONS 预检请求
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }
    
    // 获取客户端 IP
    const clientIP = request.headers.get('CF-Connecting-IP') || 
                     request.headers.get('X-Forwarded-For')?.split(',')[0] ||
                     'unknown';
    
    try {
      // 路由：记录访问（每个页面加载时调用）
      if (path === '/api/track' || path === '/track') {
        await recordIP(env.STATS_KV, clientIP);
        const status = await getAccessStatus(env);
        return new Response(JSON.stringify({ success: true, ...status }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 路由：获取统计状态
      if (path === '/api/stats' || path === '/stats') {
        const status = await getAccessStatus(env);
        return new Response(JSON.stringify(status), {
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
          // 未设置密码，默认通过
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
      
      // 默认：404
      return new Response(JSON.stringify({ 
        error: 'Not found', 
        paths: ['/api/stats', '/api/verify-password', '/api/track'] 
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
 * 记录 IP 到 KV（累计，不重置）
 */
async function recordIP(kv, ip) {
  if (!kv) return;
  
  const key = 'unique_ips';
  const existing = await kv.get(key, 'json');
  const ipSet = new Set(existing || []);
  
  if (!ipSet.has(ip)) {
    ipSet.add(ip);
    await kv.put(key, JSON.stringify([...ipSet]));
  }
}

/**
 * 获取访问状态
 */
async function getAccessStatus(env) {
  const kv = env.STATS_KV;
  const threshold = parseInt(env.IP_THRESHOLD || '10');
  
  let uniqueIPCount = 0;
  if (kv) {
    const existing = await kv.get('unique_ips', 'json');
    uniqueIPCount = existing ? existing.length : 0;
  }
  
  // 检查是否已永久启用密码保护
  let passwordEnabled = false;
  if (kv) {
    const flag = await kv.get('password_enabled');
    passwordEnabled = flag === 'true';
  }
  
  // 如果累计 IP 达到阈值且尚未启用，永久启用密码保护
  if (uniqueIPCount >= threshold && !passwordEnabled && kv) {
    await kv.put('password_enabled', 'true');
    passwordEnabled = true;
  }
  
  return {
    uniqueIPs: uniqueIPCount,
    threshold: threshold,
    passwordEnabled: passwordEnabled,
    needPassword: passwordEnabled, // 一旦启用，永久需要密码
  };
}
