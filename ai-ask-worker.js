/**
 * 龙的传人网站 - AI 问答 Cloudflare Workers 代理
 * 
 * 功能：
 * 1. 接收前端发送的问题和相关文章内容
 * 2. 调用腾讯云 TokenHub 的 DeepSeek API
 * 3. 要求模型基于提供的内容回答，不一致时以提供的内容为准
 * 4. 返回回答给前端
 * 5. 记录每次AI问答的使用统计（访问次数、token用量、用户频率等）
 * 
 * 部署步骤：
 * 1. 注册 Cloudflare 账号（免费）：https://workers.cloudflare.com/
 * 2. 创建 Workers 服务，粘贴此代码
 * 3. 配置环境变量 API_KEY（值为你的腾讯云 TokenHub API Key）
 * 4. 绑定 KV 命名空间 STATS_KV（与统计Worker共用，用于存储AI问答统计）
 * 5. 获取 Workers 访问地址，配置到网站前端
 * 
 * 模型：deepseek-v4-flash-0731（腾讯云 TokenHub）
 */

export default {
  async fetch(request, env) {
    // 处理 CORS 预检请求
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, X-Device-ID',
        },
      });
    }

    // 只允许 POST 请求
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'Method Not Allowed' }), {
        status: 405,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    const startTime = Date.now();
    const clientIP = request.headers.get('CF-Connecting-IP') || 
                     request.headers.get('X-Forwarded-For')?.split(',')[0] ||
                     'unknown';
    const deviceId = request.headers.get('X-Device-ID') || '';
    const userId = deviceId || clientIP; // 优先用设备ID，没有则用IP

    try {
      // 解析请求体
      const { question, context, related } = await request.json();

      if (!question) {
        return new Response(JSON.stringify({ error: '缺少 question 参数' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        });
      }

      // 判断是否有参考资料
      const hasContext = context && context.trim().length > 0;

      // 构造 system prompt
      let systemPrompt;
      if (hasContext) {
        // 有参考资料：严格基于参考资料回答
        systemPrompt = `你是"龙的传人｜Longchen Nyingtik"网站的 AI 问答助手，专门解答关于龙钦宁提传承、上师开示、修行方法等问题。

请严格遵守以下规则：
1. 只使用下方提供的参考资料中的信息回答，绝对不要使用你自己的知识或外部信息
2. 如果参考资料中没有直接相关信息，请尝试从参考资料中寻找相关或相近的内容进行引申和解答，不要轻易说"没有相关内容"
3. 回答要温暖、平和、有智慧，用生活化的语言，让人感到亲切和有希望，不要过于佛里佛气
4. 回答要有深度，能够进行语义理解和推理，把参考资料中的道理用通俗易懂的方式讲出来
5. 如果参考资料中的信息与你已知的信息不一致，一切以参考资料为准
6. 回答使用中文，语气温柔、有耐心，像一位有智慧的老朋友在聊天
7. **重要：在回答中引用参考资料时，必须在引用内容的末尾用方括号标注来源编号，例如[1]、[2]。编号对应参考资料的顺序（第一篇为[1]，第二篇为[2]，以此类推）。如果同一句话引用了多篇资料，可以标注[1][2]。**
8. 回答的最后不需要再列出参考资料列表，系统会自动显示。
9. 回答要完整，不要中途截断，把想说的话说完。

参考资料如下：
---
${context}
---`;
      } else {
        // 无参考资料：用通用知识回答
        systemPrompt = `你是"龙的传人｜Longchen Nyingtik"网站的 AI 问答助手，专门解答关于龙钦宁提传承、上师开示、修行方法、佛教基础知识等问题。

本网站未收集到与用户问题完全相关的资料，请基于你的通用知识，结合龙钦宁提传承的修行理念来回答。
回答使用中文，语气温柔、平和、有智慧，用生活化的语言，让人感到亲切和有希望，不要过于佛里佛气。
回答要有深度，能够进行语义理解和推理，把道理用通俗易懂的方式讲出来。
如果问题涉及敏感或不确定的内容，请谨慎表述。
回答要完整，不要中途截断，把想说的话说完。`;
      }

      // 调用腾讯云 TokenHub 的 DeepSeek API
      const apiResponse = await fetch('https://tokenhub.tencentmaas.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${env.API_KEY}`,
        },
        body: JSON.stringify({
          model: 'deepseek-v4-flash-0731',
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: question },
          ],
          temperature: 0.3,  // 低温度，回答更稳定准确
          max_tokens: 4000,  // 最大回答长度（增加以避免回复被截断）
          stream: false,
        }),
      });

      const endTime = Date.now();
      const responseTime = endTime - startTime;

      if (!apiResponse.ok) {
        const errorText = await apiResponse.text();
        console.error('API 错误:', apiResponse.status, errorText);
        
        // 记录失败的调用
        await recordAiAsk(env.STATS_KV, {
          timestamp: startTime,
          userId: userId,
          deviceId: deviceId,
          ip: clientIP,
          question: question.slice(0, 200), // 只记录前200字符
          hasContext: hasContext,
          success: false,
          error: `API ${apiResponse.status}: ${errorText.slice(0, 100)}`,
          responseTime: responseTime,
          promptTokens: 0,
          completionTokens: 0,
          totalTokens: 0,
          model: 'deepseek-v4-flash-0731',
        });

        return new Response(JSON.stringify({ 
          error: `API 调用失败: ${apiResponse.status}`,
          detail: errorText.slice(0, 200)
        }), {
          status: 500,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        });
      }

      const data = await apiResponse.json();

      // 提取回答
      let answer = data.choices?.[0]?.message?.content || '抱歉，AI 暂时无法回答，请稍后再试。';

      // 清理回答中的多余空白
      answer = answer.trim();

      // 无参考资料时，在回答开头加上提示
      if (!hasContext) {
        answer = '⚠️ 本网站未收集到相关资料，以下内容基于网络和大模型自身知识，非本站内容，仅供参考。\n\n' + answer;
      }

      // 提取token用量
      const usage = data.usage || {};
      const promptTokens = usage.prompt_tokens || 0;
      const completionTokens = usage.completion_tokens || 0;
      const totalTokens = usage.total_tokens || (promptTokens + completionTokens);

      // 记录成功的调用
      await recordAiAsk(env.STATS_KV, {
        timestamp: startTime,
        userId: userId,
        deviceId: deviceId,
        ip: clientIP,
        question: question.slice(0, 200), // 只记录前200字符
        answerLength: answer.length,
        hasContext: hasContext,
        success: true,
        responseTime: responseTime,
        promptTokens: promptTokens,
        completionTokens: completionTokens,
        totalTokens: totalTokens,
        model: 'deepseek-v4-flash-0731',
      });

      // 相关文章链接由前端处理，显示为可点击链接

      return new Response(JSON.stringify({ answer }), {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (error) {
      console.error('代理服务器错误:', error);
      
      // 记录异常
      await recordAiAsk(env.STATS_KV, {
        timestamp: startTime,
        userId: userId,
        deviceId: deviceId,
        ip: clientIP,
        question: '',
        hasContext: false,
        success: false,
        error: `Worker error: ${error.message}`.slice(0, 100),
        responseTime: Date.now() - startTime,
        promptTokens: 0,
        completionTokens: 0,
        totalTokens: 0,
        model: 'deepseek-v4-flash-0731',
      }).catch(() => {});

      return new Response(JSON.stringify({ error: '服务器内部错误: ' + error.message }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }
  },
};

/**
 * 记录AI问答使用统计
 * 存储结构：
 * - ai_ask_summary: 汇总统计（总次数、总token、最后访问时间等）
 * - ai_ask_daily_{YYYY-MM-DD}: 每日统计
 * - ai_ask_user_{userId}: 用户统计
 * - ai_ask_log_{timestamp}_{random}: 单次记录（最近100条）
 */
async function recordAiAsk(kv, record) {
  if (!kv) return;

  const date = new Date(record.timestamp);
  const dateStr = date.toISOString().split('T')[0];
  const hourStr = date.getHours();

  try {
    // 1. 更新汇总统计
    const summaryKey = 'ai_ask_summary';
    let summary = await kv.get(summaryKey, 'json').catch(() => null);
    if (!summary) {
      summary = {
        totalCalls: 0,
        successCalls: 0,
        failedCalls: 0,
        totalTokens: 0,
        totalPromptTokens: 0,
        totalCompletionTokens: 0,
        totalResponseTime: 0,
        withContextCalls: 0,
        withoutContextCalls: 0,
        uniqueUsers: 0,
        firstCallTime: record.timestamp,
        lastCallTime: record.timestamp,
      };
    }
    
    summary.totalCalls++;
    if (record.success) {
      summary.successCalls++;
    } else {
      summary.failedCalls++;
    }
    summary.totalTokens += record.totalTokens || 0;
    summary.totalPromptTokens += record.promptTokens || 0;
    summary.totalCompletionTokens += record.completionTokens || 0;
    summary.totalResponseTime += record.responseTime || 0;
    if (record.hasContext) {
      summary.withContextCalls++;
    } else {
      summary.withoutContextCalls++;
    }
    summary.lastCallTime = record.timestamp;
    
    await kv.put(summaryKey, JSON.stringify(summary));

    // 2. 更新每日统计
    const dailyKey = `ai_ask_daily_${dateStr}`;
    let daily = await kv.get(dailyKey, 'json').catch(() => null);
    if (!daily) {
      daily = {
        date: dateStr,
        totalCalls: 0,
        successCalls: 0,
        failedCalls: 0,
        totalTokens: 0,
        uniqueUsers: 0,
        users: {},
        hourlyCalls: new Array(24).fill(0),
      };
    }
    
    daily.totalCalls++;
    if (record.success) daily.successCalls++;
    else daily.failedCalls++;
    daily.totalTokens += record.totalTokens || 0;
    daily.hourlyCalls[hourStr] = (daily.hourlyCalls[hourStr] || 0) + 1;
    
    // 记录用户
    if (!daily.users[record.userId]) {
      daily.users[record.userId] = 0;
      daily.uniqueUsers++;
    }
    daily.users[record.userId]++;
    
    await kv.put(dailyKey, JSON.stringify(daily));

    // 3. 更新用户统计
    const userKey = `ai_ask_user_${record.userId}`;
    let userStats = await kv.get(userKey, 'json').catch(() => null);
    if (!userStats) {
      userStats = {
        userId: record.userId,
        deviceId: record.deviceId,
        ip: record.ip,
        totalCalls: 0,
        successCalls: 0,
        failedCalls: 0,
        totalTokens: 0,
        firstCallTime: record.timestamp,
        lastCallTime: record.timestamp,
        recentQuestions: [],
      };
    }
    
    userStats.totalCalls++;
    if (record.success) userStats.successCalls++;
    else userStats.failedCalls++;
    userStats.totalTokens += record.totalTokens || 0;
    userStats.lastCallTime = record.timestamp;
    
    // 记录最近的问题（最多10条）
    if (record.question) {
      userStats.recentQuestions.unshift({
        question: record.question,
        timestamp: record.timestamp,
        success: record.success,
        tokens: record.totalTokens || 0,
      });
      if (userStats.recentQuestions.length > 10) {
        userStats.recentQuestions = userStats.recentQuestions.slice(0, 10);
      }
    }
    
    await kv.put(userKey, JSON.stringify(userStats));

    // 4. 记录单次日志（只保留最近100条，用列表方式）
    const logKey = 'ai_ask_recent_logs';
    let logs = await kv.get(logKey, 'json').catch(() => []);
    if (!Array.isArray(logs)) logs = [];
    
    logs.unshift({
      timestamp: record.timestamp,
      userId: record.userId,
      question: record.question,
      success: record.success,
      tokens: record.totalTokens || 0,
      responseTime: record.responseTime || 0,
      hasContext: record.hasContext,
      error: record.error || '',
    });
    
    // 只保留最近100条
    if (logs.length > 100) {
      logs = logs.slice(0, 100);
    }
    
    await kv.put(logKey, JSON.stringify(logs));

  } catch (e) {
    console.error('记录AI问答统计失败:', e);
  }
}
