# AGENTS.md · 龙的传人网站（ZCode 工作区指令）

> 全局原则见 `C:\Users\Drime\.zcode\AGENTS.md`（总持 × 四肢）。本文件是项目级细化。

## 项目快照

- 自研零依赖 Python 构建器 `build_site.py`（**单文件；行数随功能增长，不写死**），**无 package.json/node_modules**
- 产物：`dist/index.html`（预渲染）+ `dist/pages/*.json`（按需）+ `knowledge.json`（AI 搜索语料）
- 后端：Cloudflare Workers（`stats-auth-worker.js` 统计/密码/注册遮罩；`ai-ask-worker.js` AI 问答代理）+ KV
- 托管：Cloudflare Pages，正式域名 longchen-nyingtik.wiki；**发布＝本地构建 + `npx wrangler pages deploy dist --branch=main`，git push 不触发部署**。⚠️ **生产分支是 main 而非 v5**：不带 `--branch=main` 会部署成 Preview（生产域名不更新）；git 仓库里并没有 main 分支，`--branch=main` 只是部署元数据（2026-09-09 实测踩坑，WorkBuddy）
- git：工作分支 v5；每次发布必推 GitHub（`git@github.com:DrimedNor/longchen-nyingtik.git`）
- 统计：自建设备统计（10 台起需访问密码 / 100 台起注册审核）；第三方 GoatCounter 已于 2026-09-18 移除

## 必读规范（总持，开工前先读）

位置：`D:\Users\Drime\Documents\Obsidian\龙的传人（网站建设）\规范与盘点\`

1. **项目设计原则与规范.md**——重点：第二章法律合规（不传教不募捐、访问密码门禁、10/100 台阶梯）、第十一章**已确认的固定修改清单（不可随意改动）**
2. **配色方案_藏红主题.md / 藏传佛教主题.md**——颜色只用现有 CSS 变量（--bg/--surface/--ink/--accent 等 12 token）
3. 历史外包任务书通用约束（AI协作\任务书归档\外包任务书-给其他AI.md）：只改 `build_site.py`、动效只用 transform/opacity、交付写「位置+新旧对比+自测清单」
4. **网站功能设计规则总纲.md / 网站定期自查机制.md**（2026-09-22 新增）——前者是「判定口径」（编号化规则＋门禁挂接＋影响面清单＋在册违规），后者是「三套自查机制」（全量体检／铁律→门禁台账／改动影响面清单）。**与本文档的分工：本文档回答「为什么这样设计」，总纲回答「什么算违规、怎么查」**；冲突时意图以本文档为准、判定以总纲为准。
5. **改动复盘规范.md**（2026-09-22 新增）——**改完怎么沉淀**：复盘四段式（改动／依据／验证／觉察与待办）、内容分流到何处（总纲在册违规 / 待核观察 / 门禁台账 / 交接簿 / 登记簿 / 记忆）、以及**是否封装技能的判据**。见硬约束 17。

## 硬约束

1. **content/ 是发布源**：`is_excluded_dir()`（build_site.py）只排除目录名含「不推送」、`.` 开头、`_backup`、assets——**新文件进 content/ 前必须确认允许上线；私人日志只进 `日志-不推送\`**
2. 不动 `.workbuddy\`；密钥/口令一律不入库不入 git（口令只存 Cloudflare Secret 或本机 `机密-不入云` 目录，2026-09-18 起无任何例外）
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
13. **法照零裁切红线（2026-09-17 小谦立，大忌级）**：**所有上师/祖师法照在任何展示场合（轮播、相册、入口卡封面、海报变体等）一律禁止裁切面部与身体**——宁可画面某一维度留白（用底色补），也绝不 `cover`/crop 残缺法相。「构建裁切变体 ＋ object-fit:cover」的做法已全面作废：轮播/卡片类一律用**完整原图压缩变体＋`object-fit:contain`（容器补 `var(--surface)` 底色）**；加工管线里的纯色边裁切（detect_border）不在此限（不涉及法相主体）。今后任何人做图库类功能前先读本条。
14. **已上线资产换图必须破缓存（2026-09-17 实证新增）**：本站 SW 对图片作 `cache-first` 永久缓存且**键＝完整 URL**——同名 URL 替换文件内容对老用户**永远无效**（会一直回放旧图）。凡更换已发布过的图片/资产：①引用 URL 加新版本参数（如 `?v=日期版次`，SW 键控含 query，会自动失效旧键）或改名文件；②本地验证一律用「带旧缓存的回头客」视角（不可用全新无痕实例自我证明）；③发布前用 Playwright 二刷复验（首次载入新 SW、二次刷新确认生效）。

15. **改动前先读《网站功能设计规则总纲》（2026-09-22 立）**：位置 `…\规范与盘点\网站功能设计规则总纲.md`。所有功能改动动手前先在该文档对号入座；**若需求本身违反总纲，必须当场指出并给出替代方案，不得擅自照做**。配套定期体检脚本（仓库根）`python audit_site_rules.py`（只读；加 `--full` 含 dist/ 项）：**发布前必跑，错误不为 0 不许发布**。总纲中标 `[脆弱]` 的条款即「同一份信息写在两处」的位置，改动必须逐处同步（清单见总纲 §16）。

16. **CSP `connect-src` 铁律（2026-09-22 实证立）**：生效的响应头文件是 `cloudflare/_headers`（**仓库根 `_headers` 是失效遗留，改它等于没改**）。本站是单文件内联 SPA，故 `script-src/style-src` 必须含 `'unsafe-inline'`。**新增任何浏览器侧跨源调用（`fetch`/`sendBeacon`/`WebSocket`）必须在 `connect-src` 加域**，否则被**静默拦截**——服务端无日志、`curl` 不执行 CSP、功能静默降级且不报错（09-18 曾致后台登不上＋全站埋点丢数 3 天；09-21 修 stats 域时漏掉 `https://ai.longchen-nyingtik.wiki`，主站 AI 问答因此长期走降级分支，详见《网站定期自查机制》机制一·1.3）。新增后**必须用真实浏览器验证**（监听 `securitypolicyviolation` 事件），静态检查与体检脚本只能对表、不能替代实测。

17. **改完默认复盘（2026-09-22 小谦立，适用于一切工作）**：任何改动完成**立即**按《改动复盘规范》四段式沉淀，**不需要小谦提醒**；复杂操作须按该规范 §4 判据判断是否封装技能（优先更新已有技能）。与之配套的三条发布纪律：
    - **改播放器/音频功能必跑端到端**：`python verify_player_e2e.py`（仓库根）——「▶ 播放全部 → 起播 → seek 到结尾 → 是否自动跳下一集」，并收集 `pageerror`。09-19 的 `autoNext` 与 09-22 的 `needsKeepAlive`、`getElementById('audioPlayer')` **三次事故都是语法/构建/门禁/部署全绿、只有真播才暴露**。
    - **引用完整性已门禁化**：`audit_site_rules.py` 的 **JS-2**（`!NAME` 未定义 ⇒ 错误级）与 **JS-1**（`getElementById` 引用的 id 不存在 ⇒ 暂列警告，存量见总纲 V-06）。写 JS 时不要引用了不存在的名字/元素。
    - **核对远端必须用 `git ls-remote origin v5`**：本地 `origin/v5` 追踪 ref 在 push 后**可能不刷新**，只看它会误判推送状态。

## 工作流

1. **接任务**：读总持 `AI协作\任务包\` 中状态为「待开工」的任务包 → 按 PRD 实施
2. **实施**：改代码 → 按任务包《检查清单.md》自测（构建通过、移动端、暗色模式、音频播放）
3. **收尾**：调用技能 `brain-deposit`（日志→`content\日志-不推送\`，交接簿→AI协作日志.md，状态.md 结案）
4. **发布**：调用技能 `longchen-publish`（含发布前计划外文件检查）。发布前必跑三道：`python audit_site_rules.py`（错误非 0 不许发布）→ `python verify_mobile_layout.py --width 375` → **动过播放器/音频则加** `python verify_player_e2e.py`。
5. **复盘**：按《改动复盘规范》四段式沉淀（→ 总纲在册违规/待核观察、门禁台账、交接簿、登记簿、记忆），并判断是否需封装/更新技能（硬约束 17）。

## 协作路径速查

| 内容 | 路径 |
| --- | --- |
| 任务包 | `…\Obsidian\龙的传人（网站建设）\AI协作\任务包\` |
| 交接簿 | `…\AI协作\AI协作日志.md`（先读后写/只追加/最新在上） |
| 日报 | `…\日报\`（WorkBuddy 自动产出） |
| 素材池 | `…\整理输出\`（上师开示上游，网站 content 的候选内容） |
| 工作进度看板 | 本仓库根 `工作进度看板.md` |
