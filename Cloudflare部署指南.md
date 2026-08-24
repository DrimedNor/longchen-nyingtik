# Cloudflare Pages 部署指南（暂不绑定独立域名）

本指南用于把「龙的传人」网站从 GitHub Pages 迁到 Cloudflare Pages，**暂不绑定独立域名**，使用 Cloudflare 默认子域 `*.pages.dev`。

## 一、接入步骤（在 Cloudflare Dashboard 操作）

1. 登录 https://dash.cloudflare.com → 左侧 **Workers & Pages** → **Create** → 选 **Pages** → **Connect to Git**。
2. 授权并选择仓库 **`DrimedNor/longchen-nyingtik`**，分支选 **`v5`**。
3. 构建设置（Framework preset 选 **None / 无**）：
   - **Build command（构建命令）**：`python3 build_site.py`
   - **Build output directory（输出目录）**：`dist`
4. 点击 **Save and Deploy**，Cloudflare 会自动拉取 `v5`、运行构建、发布到 `https://<项目名>.pages.dev`。

> 项目名可自定义（建议 `longchen-nyingtik`，对应默认域 `longchen-nyingtik.pages.dev`）。之后每次 `git push origin v5`，Cloudflare 自动重新构建部署。

## 二、已就位的缓存与安全策略（无需再配置）

仓库根 `cloudflare/_headers` 已由 `build_site.py` 在构建时复制到 `dist/_headers`，Cloudflare 自动生效：

- `/index.html` → `Cache-Control: no-cache`：每次发布访客**立即看到最新版**，根治"看到旧版"的缓存痛点。
- `/audio/*` → `Cache-Control: public, max-age=86400, immutable`：音频文件名即内容指纹，更新即改名，可安全长缓存、提升反复收听体验。
- `/*` → `X-Content-Type-Options: nosniff` + `Referrer-Policy: no-referrer`：基础安全头。
- `https://:project.pages.dev/*` → `X-Robots-Tag: noindex`：本站仅自己与朋友使用、不对外，阻止默认子域被搜索引擎收录。

## 三、环境变量

**无需设置。** 本站为零后端纯静态站点（单文件 SPA + 本地音频），所有数据内联于 `dist/index.html`，不含任何密钥或运行时配置，Cloudflare Pages 的 Variables / Functions 均用不到。

## 四、与 GitHub Pages 的关系

- **保留** GitHub Pages 及 `.github/workflows/deploy.yml` 作为备份：Cloudflare 出问题时不丢失访问入口。
- 迁移完成后两个地址会同时可用；待 Cloudflare 跑稳、确认无问题后，再视情况决定是否停用 GitHub Pages。

## 五、将来若想绑定独立域名（暂缓）

1. 购买域名（如 `longchennyingtik.com`，约 ¥70–80/年）。
2. Cloudflare 项目内 **Custom domains** → 添加域名 → 按提示把域名 DNS 的 CNAME 指向 `*.pages.dev`。
3. Cloudflare 自动签发 HTTPS 证书，无需额外配置。
4. 如需对外 SEO，去掉 `_headers` 中 `X-Robots-Tag: noindex` 这一条即可。
