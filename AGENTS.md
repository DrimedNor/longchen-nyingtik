# AGENTS.md · 龙的传人网站（ZCode 工作区指令）

> 全局原则见 `C:\Users\Drime\.zcode\AGENTS.md`（总持 × 四肢）。本文件是项目级细化。

## 项目快照

- 自研零依赖 Python 构建器 `build_site.py`（约 5600 行），**无 package.json/node_modules**
- 产物：`dist/index.html`（预渲染）+ `dist/pages/*.json`（按需）+ `knowledge.json`（AI 搜索语料）
- 后端：Cloudflare Workers（`stats-auth-worker.js` 统计/密码/注册遮罩；`ai-ask-worker.js` AI 问答代理）+ KV
- 托管：Cloudflare Pages，正式域名 longchen-nyingtik.wiki；**发布＝本地构建 + `npx wrangler pages deploy dist --branch=main`，git push 不触发部署**。⚠️ **生产分支是 main 而非 v5**：不带 `--branch=main` 会部署成 Preview（生产域名不更新）；git 仓库里并没有 main 分支，`--branch=main` 只是部署元数据（2026-09-09 实测踩坑，WorkBuddy）
- git：工作分支 v5；每次发布必推 GitHub（`git@github.com:DrimedNor/longchen-nyingtik.git`）
- 统计：GoatCounter + 自建设备统计（10 台密码 610 / 100 台注册审核）

## 必读规范（总持，开工前先读）

位置：`D:\Users\Drime\Documents\Obsidian\龙的传人（网站建设）\规范与盘点\`

1. **项目设计原则与规范.md**——重点：第二章法律合规（不传教不募捐、密码 610、10/100 台阶梯）、第十一章**已确认的固定修改清单（不可随意改动）**
2. **配色方案_藏红主题.md / 藏传佛教主题.md**——颜色只用现有 CSS 变量（--bg/--surface/--ink/--accent 等 12 token）
3. 历史外包任务书通用约束（AI协作\任务书归档\外包任务书-给其他AI.md）：只改 `build_site.py`、动效只用 transform/opacity、交付写「位置+新旧对比+自测清单」

## 硬约束

1. **content/ 是发布源**：`is_excluded_dir()`（build_site.py）只排除目录名含「不推送」、`.` 开头、`_backup`、assets——**新文件进 content/ 前必须确认允许上线；私人日志只进 `日志-不推送\`**
2. 不动 `.workbuddy\`；密钥/密码不入库不入 git（密码 610 除外，它是合规设计的站内密码）
3. 操作前备份（规范第七章维护规则）；`工作进度看板.md` 不入 git
4. **音频分类必须镜像「读开示」**：`content/1. 听法音/1. 上师开示（AI朗读）/` 的文件夹结构与 `content/2. 读开示/` 严格一致，音频跟着文章走（规范 6.2）。**每次发布前先跑 `python check_audio_taxonomy.py`，不通过不许发布**（规范 6.4）
5. **一级目录命名（2026-09-15 板块重组）**：`1. 听法音 / 2. 读开示 / 3. 知传承 / 4. 阅典籍 / 5. 瞻法照 / 9. 关于本站`。首页与导航显示顺序由 `build_site.py` 的 `TOP_ORDER` / `ORDER` 决定（知传承 → 听法音 → 读开示 → 阅典籍 → 瞻法照 → 关于本站）。**改名必须全库收口**：`TOP_ORDER` `TOP_LABELS` `META` `ORDER` `DIR_INTROS` `OTHER_INTROS` `DIR_ALIASES`、`audio_folder_rel()`、`_article_dir`、`check_audio_taxonomy.py` 的 `KS/AUD`，改完必须 `grep -rn "旧名"` 复核（历史三次「改一层漏一层」踩坑）
6. **图片入库（2026-09-15）**：`content/**` 与 `content/assets/**` 下的图片都可被 Obsidian 嵌入 `![[文件名.jpg]]` 引用（`find_image_src()` 两段查找）；相册网格用块语法
   ```
   :::gallery
   ![[图片名.jpg|说明文字]]
   :::
   ```
   渲染为响应式网格、点击放大（复用 `showPosterBig`）。注意 `![[图|数字]]` 里的数字仍是宽度；相册块内第二段才当说明文字。
7. **构建会累积旧文件**：`build_site.py` 不清理 `dist/`，改名后旧分片会残留（2026-09-15 实测 235 个旧名分片）。**每次改名后先 `mv dist dist_old_<日期>` 或删空再构建**（dist/ 已 gitignore，可安全重建）
8. **海报「原图 + 压缩图」必须两路都进 dist（2026-09-15）**：法音详情页引用 `poster_map` 生成的 `xxx.webp`（需 Pillow），而「瞻法照」等页面按**原文件名** `![[xxx.jpg]]` 嵌入原图。`build_site.py` 海报循环须 `shutil.copy2` 原图 **且** 生成 webp，缺任一即断图（实测「圣像与法物」19 张断 18 张）。**构建一律用 `D:\Program Files\Python\python.exe`**——托管 Python 无 Pillow 会静默降级，且 dist 未清理时旧 webp 残留会造成假通过
9. **发布前必须真实渲染复验（2026-09-15）**：构建退出码 0 与门禁绿灯**都不保证图片能加载**。发布前用 Playwright 实渲染逐页统计断图数（脚本模板见技能 `longchen-publish` → `references/verify_pages.js`），**累计断图必须为 0**；同时核对导航标签顺序
10. **推送与部署须留可复核实证**：`git push` 可能静默失败（无输出无报错）→ 必须 `git ls-remote origin v5` 对比远端 commit；部署后必须 `npx wrangler pages deployment list` 确认 `Environment=Production` 且 `Source=<本地 HEAD>`。**不以命令回显判断成败**

11. **板块首页不能只有文字**：首页快捷卡片、导航点击后落到的都是板块首页（`content/<板块>/index.md`）。若板块首页只有文字与链接、一张图都没有，用户会直接反馈「这个板块看不到图片」——即使子页相册完全正常。**建有子级图文的板块，首页必须用 `:::entry` 出封面入口卡**（语法见技能 `longchen-publish` → `references/content-blocks.md`）。同理：收到「某板块没图/没内容」的报障，**先看板块首页，再查子页**。
12. **新增内容块必须复验「渲染出来了」**：真实渲染复验只保证「已渲染的图没断」，不保证「新块被解析」。新增 `:::` 围栏块后，必须数一次产出标记（如 `entry-grid`/`en-card`）的出现次数。⚠️ 索引页 HTML 嵌在 JSON 字符串中、属性带转义反斜杠（`class=\"en-card\"`），**用 grep 会误报 0**，须用脚本 `html.count('en-card')` 计数。

## 工作流

1. **接任务**：读总持 `AI协作\任务包\` 中状态为「待开工」的任务包 → 按 PRD 实施
2. **实施**：改代码 → 按任务包《检查清单.md》自测（构建通过、移动端、暗色模式、音频播放）
3. **收尾**：调用技能 `brain-deposit`（日志→`content\日志-不推送\`，交接簿→AI协作日志.md，状态.md 结案）
4. **发布**：调用技能 `longchen-publish`（含发布前计划外文件检查）

## 协作路径速查

| 内容 | 路径 |
| --- | --- |
| 任务包 | `…\Obsidian\龙的传人（网站建设）\AI协作\任务包\` |
| 交接簿 | `…\AI协作\AI协作日志.md`（先读后写/只追加/最新在上） |
| 日报 | `…\日报\`（WorkBuddy 自动产出） |
| 素材池 | `…\整理输出\`（上师开示上游，网站 content 的候选内容） |
| 工作进度看板 | 本仓库根 `工作进度看板.md` |
