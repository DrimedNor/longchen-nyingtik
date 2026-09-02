# AI 问答功能部署指南

## 概述

本网站的 AI 问答功能采用以下架构：
- 前端：网站内置问答界面，搜索本站 41 篇文章作为参考资料
- 代理：Cloudflare Workers（免费），隐藏 API Key，转发请求到腾讯混元
- 大模型：腾讯混元（hunyuan-lite 免费模型）

## 第一步：开通腾讯混元 API

1. 访问 https://cloud.tencent.com/product/hunyuan
2. 登录腾讯云账号（没有就注册）
3. 完成实名认证（需要身份证）
4. 搜索"腾讯混元 API"，点击"立即开通"
5. 开通后，进入"访问管理" → "API 密钥管理"
6. 创建新的密钥，获取 **SecretId** 和 **SecretKey**
   - 注意：SecretKey 只显示一次，请妥善保存
7. 新用户赠送 100 万 Token 资源包（有效期 1 年），hunyuan-lite 模型可长期免费使用

## 第二步：部署 Cloudflare Workers

1. 访问 https://workers.cloudflare.com/，注册 Cloudflare 账号（免费）
2. 登录后，点击"Create a Worker"
3. 给 Worker 起个名字（如 `longchen-ai-ask`）
4. 把默认代码全部删除，粘贴 `ai-ask-worker.js` 的内容
5. 点击"Deploy"部署

## 第三步：配置环境变量

1. 在 Worker 详情页，点击"Settings" → "Variables and Secrets"
2. 点击"Add variable"
3. 变量名填：`HUNYUAN_API_KEY`
4. 变量值填：`SecretId:SecretKey`（把第一步获取的 SecretId 和 SecretKey 用冒号连接）
   - 例如：`AKIDxxxxxxxxxxxxxxxx:yyyyyyyyyyyyyyyyyyyy`
5. 勾选"Encrypt"（加密存储）
6. 点击"Save"保存
7. 重新部署 Worker（点击"Deployments" → "Redeploy"）

## 第四步：测试 Worker

1. 在 Worker 详情页，复制访问地址（如 `https://longchen-ai-ask.xxx.workers.dev`）
2. 用 curl 或 Postman 测试：
```bash
curl -X POST https://longchen-ai-ask.xxx.workers.dev \
  -H "Content-Type: application/json" \
  -d '{
    "question": "什么是菩提心？",
    "context": "菩提心是指觉悟之心，是修行的根本...",
    "related": [{"title": "发菩提心", "slug": "上师开示/发菩提心"}]
  }'
```
3. 如果返回 `{"answer": "..."}`，说明配置成功

## 第五步：配置网站前端

1. 把 Worker 访问地址发给我
2. 我会修改网站前端代码，把 AI 问答功能接入
3. 重新构建并推送网站

## 费用说明

- **Cloudflare Workers**：免费版每天 10 万次请求，足够个人使用
- **腾讯混元 hunyuan-lite**：完全免费
- **腾讯混元 hunyuan-turbo**：输入 4.5元/百万token，输出 5元/百万token（新用户有 100 万免费额度）
- 建议先用免费的 hunyuan-lite，效果不够再升级

## 常见问题

**Q: API Key 格式是什么？**
A: 格式是 `SecretId:SecretKey`，注意中间是英文冒号，不是中文冒号。

**Q: 回答不准确怎么办？**
A: 可以把模型从 `hunyuan-lite` 改成 `hunyuan-turbo`，能力更强但需要付费。或者增加参考资料的数量。

**Q: 可以限制只有我的网站能调用吗？**
A: 可以在 Worker 代码中添加 Origin 检查，只允许你的网站域名调用。需要的话告诉我，我帮你加。

**Q: 回答中出现了参考资料以外的内容怎么办？**
A: system prompt 已经明确要求只使用参考资料，但模型偶尔会"幻觉"。如果频繁出现，可以把 temperature 降到 0.1，或者在 system prompt 中更加强调规则。
