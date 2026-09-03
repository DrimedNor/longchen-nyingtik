/**
 * 访问统计与密码验证 Worker
 * 功能：
 * 1. 记录每日独立 IP 数（存储在 KV 中）
 * 2. 提供 /api/stats 接口返回当日独立 IP 数
 * 3. 提供 /api/verify-password 接口验证访问密码
 * 
 * 环境变量：
 * - ACCESS_PASSWORD：访问密码（当独立 IP > 阈值时需要）
 * - IP_THRESHOLD：独立 IP 阈值，默认 10
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
    
    // 获取今天的日期字符串
    const today = new Date().toISOString().split('T')[0];
    
    try {
      // 路由：获取统计数据
      if (path === '/api/stats' || path === '/stats') {
        const ipCount = await getUniqueIPCount(env.STATS_KV, today);
        const threshold = parseInt(env.IP_THRESHOLD || '10');
        const needPassword = ipCount >= threshold;
        
        return new Response(JSON.stringify({
          date: today,
          uniqueIPs: ipCount,
          threshold: threshold,
          needPassword: needPassword,
        }), {
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
          return new Response(JSON.stringify({ success: false, message: '密码错误' }), {
            status: 401,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
      }
      
      // 路由：记录访问（每个页面加载时调用）
      if (path === '/api/track' || path === '/track') {
        await recordIP(env.STATS_KV, today, clientIP);
        return new Response(JSON.stringify({ success: true }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        });
      }
      
      // 默认：404
      return new Response(JSON.stringify({ error: 'Not found', paths: ['/api/stats', '/api/verify-password', '/api/track'] }), {
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
 * 记录 IP 到 KV（使用 Set 去重）
 */
async function recordIP(kv, date, ip) {
  if (!kv) return;
  
  const key = `ips:${date}`;
  const existing = await kv.get(key, 'json');
  const ipSet = new Set(existing || []);
  
  if (!ipSet.has(ip)) {
    ipSet.add(ip);
    // 设置过期时间为 7 天，自动清理旧数据
    await kv.put(key, JSON.stringify([...ipSet]), { expirationTtl: 7 * 24 * 60 * 60 });
  }
}

/**
 * 获取当日独立 IP 数
 */
async function getUniqueIPCount(kv, date) {
  if (!kv) return 0;
  
  const key = `ips:${date}`;
  const existing = await kv.get(key, 'json');
  return existing ? existing.length : 0;
}
