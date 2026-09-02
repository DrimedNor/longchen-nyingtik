/**
 * 龙的传人网站 - AI 问答 Cloudflare Workers 代理
 * 
 * 功能：
 * 1. 接收前端发送的问题和相关文章内容
 * 2. 调用腾讯混元 API（OpenAI 兼容接口）
 * 3. 要求模型基于提供的内容回答，不一致时以提供的内容为准
 * 4. 返回回答给前端
 * 
 * 部署步骤：
 * 1. 注册 Cloudflare 账号（免费）
 * 2. 创建 Workers 服务，粘贴此代码
 * 3. 配置环境变量 HUNYUAN_API_KEY（格式：SecretId:SecretKey）
 * 4. 获取 Workers 访问地址，配置到网站前端
 * 
 * 腾讯混元 API 开通：https://cloud.tencent.com/product/hunyuan
 */

export default {
  async fetch(request, env) {
    // 处理 CORS 预检请求
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
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

    try {
      // 解析请求体
      const { question, context, related } = await request.json();

      if (!question || !context) {
        return new Response(JSON.stringify({ error: '缺少 question 或 context 参数' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        });
      }

      // 构造 system prompt，要求基于提供的内容回答
      const systemPrompt = `你是"龙的传人｜Longchen Nyingtik"网站的 AI 问答助手，专门解答关于龙钦宁提传承、上师开示、修行方法等问题。

请严格遵守以下规则：
1. 只使用下方提供的参考资料中的信息回答，绝对不要使用你自己的知识或外部信息
2. 如果参考资料中没有相关信息，请明确说"本网站暂无相关内容，建议浏览「上师开示」栏目或换个关键词提问"
3. 回答要简洁、准确，尽量引用资料中的原文
4. 如果参考资料中的信息与你已知的信息不一致，一切以参考资料为准
5. 回答使用中文，语气恭敬、温和，符合佛教网站的氛围

参考资料如下：
---
${context}
---`;

      // 调用腾讯混元 API（OpenAI 兼容接口）
      const apiResponse = await fetch('https://api.hunyuan.cloud.tencent.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${env.HUNYUAN_API_KEY}`,
        },
        body: JSON.stringify({
          model: 'hunyuan-lite',  // 免费模型，可改为 hunyuan-turbo（付费但能力更强）
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: question },
          ],
          temperature: 0.3,  // 低温度，回答更稳定准确
          max_tokens: 1500,  // 最大回答长度
        }),
      });

      if (!apiResponse.ok) {
        const errorText = await apiResponse.text();
        console.error('腾讯混元 API 错误:', apiResponse.status, errorText);
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

      // 添加相关文章链接
      if (related && related.length > 0) {
        answer += '\n\n📖 相关文章：\n';
        related.forEach((item, idx) => {
          answer += `${idx + 1}. 《${item.title}》\n`;
        });
      }

      return new Response(JSON.stringify({ answer }), {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (error) {
      console.error('代理服务器错误:', error);
      return new Response(JSON.stringify({ error: '服务器内部错误: ' + error.message }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }
  },
};
