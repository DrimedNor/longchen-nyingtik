# AI 搜索（AI 问答）配置指南 · 腾讯云 TokenHub 版

> **本文档已于 2026-09-21 按线上真实实现重写。**
> 旧版写的是「腾讯混元 hunyuan-lite + 环境变量 `HUNYUAN_API_KEY` + `SecretId:SecretKey`」——**与线上不符，已作废**。
> 照旧版操作会配出一个用不上的 Key（甚至开通错模型产生费用）。当前真实链路见下。

---

## 一、这条链路到底连了什么

```
访问者点击 🔍
   ↓
① 前端（本站 index.html）
   先在本地检索：knowledge.json（16127 段全文索引）+ 同义词打分
   → 得出「本站最相关的文章」
   ↓  POST {question, context, hasContext, related}
② Cloudflare Worker：steep-rain-0d77longchen-ai-ask
   代码 ai-ask-worker.js，配置 wrangler.toml
   域名 https://ai.longchen-nyingtik.wiki
   作用：① 藏住 Key ② 组装 system prompt ③ 记 AI 用量统计
   ↓  POST https://tokenhub.tencentmaas.com/v1/chat/completions
      Authorization: Bearer <API_KEY>
      model: deepseek-v4-flash-0731
③ 腾讯云 TokenHub（大模型服务平台）—— 唯一的外部云依赖
   只负责「生成回答」，不参与检索
   ↓
回答回流前端，附引用来源可点击跳转
```

**关键认知**：AI 搜索里的"搜索"是本站自己做的（本地语料检索，不联网、不花钱）；腾讯云**只做最后那步"组织语言回答"**。
所以腾讯云侧要配的东西只有一样：**一个能调 DeepSeek-V4-Flash 的 API Key**。

### 全站唯一的腾讯云依赖

| 项目 | 值 | 代码/配置位置 |
|---|---|---|
| 接入域名 | `https://tokenhub.tencentmaas.com/v1/chat/completions` | `ai-ask-worker.js:96` |
| 模型标识 | `deepseek-v4-flash-0731` | `ai-ask-worker.js:103` |
| 鉴权方式 | `Authorization: Bearer <API_KEY>` | `ai-ask-worker.js:100` |
| Key 存放 | Cloudflare Secret `API_KEY` | `wrangler.toml`（Key 本身不落文件） |
| Worker 名 | `steep-rain-0d77longchen-ai-ask` | `wrangler.toml:1` |
| 前端入口 | `var AI_API_ENDPOINT = 'https://ai.longchen-nyingtik.wiki'` | `build_site.py:3752` |

> 站内其余对外调用只有 `stats.longchen-nyingtik.wiki`（自建统计/鉴权 Worker，与腾讯云无关）；
> 藏历/农历/节假日是**本地内嵌离线库**，不出网。**全站再无其他云服务。**

---

## 二、腾讯云侧：要配的设置与路径

### 2.1 进入 TokenHub 控制台

- 直链（API Key 管理）：**https://console.cloud.tencent.com/tokenhub/apikey**
- 或：腾讯云控制台 → 顶部搜索「**TokenHub**」→ 进入「大模型服务平台 TokenHub」→ 左侧「**API Key 管理**」

### 2.2 领取新用户免费额度（建议先做）

1. 控制台 → TokenHub → 「**模型广场**」
2. 领取新用户免费体验包
3. 每个主账号**一次性**赠送多款模型额度（Hy3 / DeepSeek-V4-Pro / **V4-Flash** / GLM-5 / MiniMax 等），
   每款约 **50–100 万 Tokens**，**有效期 90 天**
4. ⚠️ 额度领了还要**在控制台把该模型开通**，否则调用报 `402xxx`（模型服务未开通/额度不足）

### 2.3 创建 API Key（这就是本站"链接的腾讯云设置"）

1. 「API Key 管理」页 → 选**地域**（本站调用走 `tokenhub.tencentmaas.com`，属境内/广州站点）
2. 点「**创建 API Key**」→ 填名称（建议：`longchen-ai-ask`）
3. 设置**访问范围**（全选 / 限定特定模型 / 限定特定服务）→ 建议限定到 DeepSeek-V4-Flash，降低泄露损失
4. 确定 → **复制并妥善保管（只在创建时显示一次，此后无法再看）**

### 2.4 计费与用量

- **用量**：TokenHub 控制台 → 用量/统计页（本站自建后台「AI问答统计」也记 token 消耗，可交叉核对）
- **费用**：腾讯云 → 费用中心。免费额度用完后按量计费；若不想自动扣费，注意账户余额策略
- **本站后台**：`https://longchen-nyingtik.wiki/admin/` → AI问答统计（次数 / token / 失败原因 / 平均响应）

---

## 三、Cloudflare 侧：Key 的实际存放处

Key **不写在代码里、不写进 git**，只存在于 Cloudflare Secret：

```bash
# 写入/替换腾讯云 TokenHub 的 API Key
npx wrangler secret put API_KEY --config wrangler.toml

# 部署 AI 问答 Worker（改了 ai-ask-worker.js 之后执行）
npx wrangler deploy --config wrangler.toml
```

- 域名 `ai.longchen-nyingtik.wiki` 在 **Cloudflare DNS/Workers 自定义域名**里绑定到该 Worker
- `wrangler.toml` 里只有非敏感项（Worker 名、account_id、KV 绑定、ADMIN_DEVICE_IDS），**没有 Key**

> 为什么不直接用 `xxx.workers.dev`：`workers.dev` 在国内被 DNS 污染，直连不通，故必须套自定义域名。

---

## 四、故障排查对照表

| 现象 | 大概率原因 | 去哪里处理 |
|---|---|---|
| 前端 15 秒后回落到本地搜索结果 | 前端 `AbortController` 超时（**不代表腾讯云故障**） | 重试；持续发生再看 Worker 日志 |
| Worker 报 `401002` | API Key 无效，或 Key 与接入站点不匹配（**Key 不可跨站点/跨地域通用**） | TokenHub → API Key 管理，改用与 `tokenhub.tencentmaas.com` 同站点的 Key |
| Worker 报 `402xxx` | 模型未开通 或 免费额度用尽 | TokenHub → 模型广场开通模型 / 充值 |
| Worker 报 `429xxx` | 触发限流 | 降低频率、错峰；响应里可能带 `Retry-After` |
| 全线突然连不上（含 `404`） | 接入域名可能变更（官方文档现用 `tokenhub.tencentcloudmaas.com`，本站代码是 `tokenhub.tencentmaas.com`） | 核对官方「API 使用说明」的 Base URL 后改 `ai-ask-worker.js:96` |
| 前端完全不出现 AI 按钮/面板 | `build_site.py` 里 `AI_API_ENDPOINT` 被清空（会走降级模式） | 检查 `build_site.py:3752` |

**自检命令**（验证 Key 与模型可用，需自备 Key）：

```bash
curl https://tokenhub.tencentmaas.com/v1/models \
  -H "Authorization: Bearer $API_KEY"
```

---

## 五、凭据登记现状与建议

- ⚠️ **该 API Key 目前只存在于 Cloudflare Secret，本机没有任何副本**——
  `D:\Users\Drime\Documents\机密-不入云\龙的传人-当前凭据-2026-09-21.md` 记了后台口令、访问密码、临时账号，**但没有腾讯云 API Key 的任何痕迹**。
- 后果：Key 需要轮换或丢失时，只能去腾讯云控制台重新创建（旧的直接删）。
- **建议**（不存明文也够用）：在上述凭据文件里补一段**元信息**——Key 名称、创建日期、地域/站点、访问范围、绑定 Worker。
  将来任何 AI 接手，都知道"去哪儿找、怎么重建"，而不必翻遍控制台。

---

## 六、本文档的修正记录（2026-09-21）

| 旧版写法 | 真实情况 |
|---|---|
| 大模型 = 腾讯混元 `hunyuan-lite` | **腾讯云 TokenHub，模型 `deepseek-v4-flash-0731`** |
| 环境变量名 `HUNYUAN_API_KEY` | **`API_KEY`** |
| Key 格式 `SecretId:SecretKey` | **Bearer Token（API Key 单值）** |
| 控制台 `cloud.tencent.com/product/hunyuan` | **`console.cloud.tencent.com/tokenhub/apikey`** |
| "隐藏 API Key，转发请求到腾讯混元" | 代理作用不变，但**上游是 TokenHub** |
