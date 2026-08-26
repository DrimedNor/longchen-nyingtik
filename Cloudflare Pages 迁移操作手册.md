# Cloudflare Pages 迁移操作手册

> 龙的传人网站 · GitHub Pages → Cloudflare Pages
> 编制日期：2026-08-21　依据：Cloudflare 官方文档（developers.cloudflare.com）逐条核实
> 本手册为**本地操作文档**，不纳入网站 git 仓库。

## 一、结论速览（你的两个问题）

**Q1：迁移后还能建立独立域名吗？**
能。Cloudflare Pages 免费计划每个项目支持最多 **100 个自定义域名**。域名可在 Cloudflare Registrar 注册（成本价），自动托管 Cloudflare DNS，绑定 Pages 一步到位，自动 HTTPS。

**Q2：付费的话多少钱？**
| 项目 | 费用 |
|---|---|
| Cloudflare Pages（免费计划） | **¥0**：每月 500 次构建、无带宽费、单文件 ≤25MiB、≤20,000 个文件、1 个并发构建 |
| 独立域名（可选） | **.com ≈ $10.44/年 ≈ ¥76/年**（注册价 = 续费价，零加价；含免费 WHOIS 隐私保护；支持支付宝/信用卡付款） |

> 不注册域名的话，迁移总成本 = 0 元，免费拿一个 `xxx.pages.dev` 网址。

**已核实的技术兼容性（无风险）**
- 构建镜像 v3：Ubuntu 22.04.2，默认 **Python 3.13.3**（你本地是 3.13.12，零依赖，完全兼容）。
- `build_site.py` 已检查：路径处理全部跨平台（`os.path` + 反斜杠统一替换），Linux 构建环境可直接运行。
- 你的 mp3：14 个、最大 8.6MiB、总 48.2MiB —— **0 个超过 25MiB 单文件上限**。
- 站点文件数远低于 20,000 上限。

## 二、迁移步骤

### 第 1 步（你操作）：注册 Cloudflare 账号
1. 打开 https://dash.cloudflare.com/sign-up
2. 用邮箱 + 密码注册（免费）
3. 打开邮箱点击验证链接（**必须验证**，注册域名前尤其重要）

### 第 2 步（你操作）：连接 GitHub 仓库
1. 登录后进入 **Workers & Pages**
2. **Create application → Pages → Connect to Git**
3. 选择 GitHub，弹出 GitHub 登录授权，同意
4. 选择仓库：`DrimedNor/longchen-nyingtik` → **Begin setup**

### 第 3 步（你操作）：填构建配置（关键三项）
| 配置项 | 填写值 |
|---|---|
| Production branch | `v5`（不是 main！） |
| Build command | `python3 build_site.py` |
| Build output directory | `dist` |

- Framework preset：不选（留空）
- Environment variables：留空（构建镜像默认 Python 3.13.3 已匹配）
- 点 **Save and Deploy**

### 第 4 步：验证新站
1. 构建完成后得到网址：`https://longchen-nyingtik.pages.dev`（或你起的项目名）
2. 检查：首页「最近更新」区块、导航、音频播放按钮、文章页
3. 此时**新旧两站并行运行**，旧站 drimednor.github.io 不受影响

### 第 5 步（可选，付费）：绑定独立域名
1. 左侧 **Register domains** → 搜索想要的域名（如 `longchen-nyingtik.com`）→ 查看实时价格
2. 付款（支付宝/信用卡），域名自动托管 Cloudflare DNS
3. Pages 项目 → **Custom domains → Set up a domain** → 输入域名 → 自动创建 CNAME + 签发 HTTPS 证书（几分钟生效）
4. 旧地址处理（可选）：保留 GitHub Pages 作备份，或在首页加跳转提示

## 三、需要你做的事（清单）

- [ ] 注册 Cloudflare 账号并**验证邮箱**
- [ ] 授权 GitHub、选仓库 `DrimedNor/longchen-nyingtik`
- [ ] 填三项构建配置（分支 `v5` / 命令 `python3 build_site.py` / 目录 `dist`）并部署
- [ ] （可选）挑选并注册域名，把域名名告诉我（我可帮你查可用性与价格）
- [ ] 部署完成后告诉我一声 —— 我来做线上验证、加缓存优化配置（`_headers`）、旧站跳转等收尾

## 四、风险与注意

- **国内访问速度**：Cloudflare 免费 CDN 在中国大陆无直连节点，速度与 github.io 相当或略好；服务器在海外，**无需 ICP 备案**。
- **不停机切换**：新旧两站并行，验证无误后再决定是否关闭 GitHub Pages。
- **GitHub Actions 保留**：`deploy.yml` 不动，继续部署 GitHub Pages 作备份，与 Cloudflare 互不干扰。
- **缓存改善（核心收益）**：Cloudflare Pages 对 HTML 不强制缓存、mp3 等静态资源长缓存 —— 正好解决你反复遇到的「手机端显示旧版」问题。
- 构建超时 20 分钟（你的构建秒级完成）；新账号前 48 小时有新建项目数量限制（只建 1 个，无影响）。

## 五、参考资料（官方文档）

- Git 集成：https://developers.cloudflare.com/pages/get-started/git-integration/
- 构建配置：https://developers.cloudflare.com/pages/configuration/build-configuration/
- 自定义域名：https://developers.cloudflare.com/pages/configuration/custom-domains/
- 免费计划限制：https://developers.cloudflare.com/pages/platform/limits/
- 域名注册：https://developers.cloudflare.com/registrar/get-started/register-domain/
