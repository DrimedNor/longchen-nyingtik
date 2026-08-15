# -*- coding: utf-8 -*-
"""
process_content.py — 批处理 content/ 下全部文章，统一完成三件事：
  1. 补充作者字段：路径含「上师开示」的文章 → 作者「龙洋仁波切」；其余 → 「Drimed」。
  2. 提取内容关键词作为标签（tags），便于后期推荐阅读。
     - 优先用 jieba 分词做词频统计；不可用时退化为 CJK n-gram 词频。
     - 标题/小标题中的词额外加权，使标签更贴近主题。
  3. 在每篇文章结尾插入「相关主题文章推荐」板块，按标签重合度匹配并列出相关文章
     （wikilink 形式 [[slug|title]]，由 build_site.py 渲染为站内链接）。
约定：
  - 跳过特殊文件：本次更新内容.md、更新日志.md、所有 index.md（目录落地页）。
  - 仅处理文件名标注 🔊 符号的文章（已定稿、已放置配套音频）；
    未放置音频（文件名无 🔊）的文件暂不处理，待补录音频后再统一处理。
  - 跳过 Obsidian 进行中的重命名文件：以「X.md」结尾者（如「xxxX.md」），
    约定不改动用户尚未定稿的文章，待其去掉 X 后再统一处理。
  - 幂等：已有 author/tags 不覆盖；已含「相关主题文章推荐」则不重复插入。
  - 仅改动 frontmatter 与文末追加，正文结构保持不变。
用法：
  python process_content.py            # 真正写入
  python process_content.py --dry-run  # 仅预览将要做的改动，不落盘
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(HERE, "content")
SKIP_FILES = {"本次更新内容.md", "更新日志.md"}
RELATED_HEADING = "相关主题文章推荐"

# 常见中文停用词（功能词 / 过泛词语），分词与 n-gram 阶段均过滤
STOPWORDS = set("""
的 了 和 是 在 我 你 他 她 它 我们 你们 他们 自己 这 那 之 其 此 该 各 某 每 个 些 等
为 以 于 对 从 把 被 让 使 给 向 往 由 据 按 经 通过 由于 关于 对于 除了 以及 或者 还是
而 与 及 或 但 却 可 也 都 还 就 才 又 再 很 太 更 最 极 稍 比较 非常 十分 尤其
因为 所以 如果 虽然 但是 然而 于是 然后 接着 比如 例如 其实 确实 显然 当然 无疑
一个 一种 一样 一些 一切 一定 一直 一样 这样 那样 这么 那么 这些 那些 这里 那里
什么 怎么 怎样 如何 为什么 多少 几 哪 谁 哪 何时 是否 能否 可否
就 要 会 能 可以 应该 必须 需要 想 要 希望 喜欢 觉得 认为 知道 明白 理解 认识 发现
看到 听到 感到 告诉 说明 解释 表示 意味 成为 作为 进行 发生 出现 存在 保持 获得 失去
开始 结束 继续 改变 提高 发展 建设 创造 实现 完成 达到 超过 低于 高于 增加 减少
时间 时候 现在 今天 明天 昨天 去年 今年 明年 过去 未来 先后 同时 然后 一直 永远
地方 程度 状态 情况 过程 系统 部分 整体 基础 条件 机会 选择 决定 行动 行为 态度
观念 理念 思想 精神 文化 历史 社会 国家 人民 人类 个人 大家 别人 朋友 家人 老师
学生 孩子 父母 工作 学习 研究 实践 经验 知识 信息 内容 形式 方式 水平 质量 标准
目标 方向 意义 价值 方面 问题 答案 方法 世界 生活 生命 东西 事情 原因 结果 关系
重要 正确 错误 真实 简单 困难 容易 复杂 清楚 明白 安静 平静 快乐 幸福 痛苦 烦恼
自由 平等 公正 善良 美丽 健康 安全 危险 可能 应该 需要 几乎 尤其 甚至 究竟 到底
""".split())

CJK = lambda s: any('\u4e00' <= c <= '\u9fff' for c in s)


def load_jieba():
    try:
        import jieba
        return jieba
    except Exception:
        return None


def extract_plain(body):
    """去除 markdown 标记，得到近似纯文本（用于词频统计）。"""
    txt = body
    txt = re.sub(r"```.*?```", " ", txt, flags=re.S)        # 代码块
    txt = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", txt)          # 图片
    txt = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", txt)  # wikilink → 标题
    txt = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", txt)        # 普通链接 → 文字
    txt = re.sub(r"[#>*_`~\-]+", " ", txt)                    # 标记符号
    return txt


# 佛法 / 修行主题词表（无 jieba 时的高质量标签来源；与 n-gram 互补）
TERMS = set("""
修行 上师 众生 无常 轮回 菩提 三宝 因果 慈悲 智慧 佛法 解脱 菩提心 出离心 空性
中观 密法 密宗 灌顶 皈依 业力 业障 六道 净土 念佛 禅修 禅宗 加行 资粮 方便 般若
如来 菩萨 佛陀 佛性 金刚 坛城 本尊 护法 闻思 修持 见地 道次第 慈悲心 布施 持戒
忍辱 精进 禅定 六度 四谛 八正道 十二因缘 缘起 性空 如来藏 法身 报身 化身 三身
极乐 往生 转经 供灯 烟供 火供 会供 破瓦 闭关 实修 观想 持咒 咒语 真言 佛号 心咒
百字明 金刚萨埵 莲师 莲花生 龙钦 宁提 大圆满 窍诀 开示 教言 法语 传承 上师瑜伽
气脉 明点 虹身 虹化 证悟 觉悟 开悟 明心 见性 本性 心性 觉性 光明 任运 自在 安乐
欢喜 清净 圆满 究竟 了义 世俗 胜义 二谛 中道 离戏 无我 无住 无相 无为 无分别
慈悲喜舍 四无量心 利他 自利 度化 度众 弘扬 护持 护生 放生 吃素 素食 戒律 五戒
菩萨戒 别解脱戒 三皈 三乘 大乘 小乘 显宗 密乘 金刚乘 闻法 思惟 修习 串习 觉知
正念 正知 正见 邪见 迷惑 无明 烦恼 贪嗔痴 三毒 执著 执取 放下 随缘 安心 安住
保任 觉照 观照 照见 如如 本来 面目 家乡 归处 归宿 依靠 依怙 怙主 皈处 福田 功德
福报 供养 赞叹 顶礼 绕塔 绕佛 诵经 弘法 利生 悲愿 宏愿 大愿 普贤 文殊 观音 地藏
弥勒 释迦 牟尼 三身 五智 五方佛 五毒 贪 嗔 痴 慢 疑 五蕴 色受想行识 十八界 涅槃
成佛 成道 证果 果位 初地 十地 罗汉 缘觉 声闻 戒定慧 三学 止观 寂止 胜观 奢摩他
毗婆舍那 定慧 等持 三昧 正定 神通 六神通 五眼 开悟 见性 即身成佛 悉地 成就 证量
境界 次第 修心 七义 修心八颂 佛子行 入行论 菩萨行 自他交换 明空 乐空 双运 智悲双运
悲智双运 二资双运 福慧双修 显密双融
""".split())


def extract_tags(body, jieba):
    """返回 (tags_list, weighted_scores)。"""
    plain = extract_plain(body)
    headings = [ln.lstrip("#").strip() for ln in body.splitlines() if re.match(r"^#{1,6}\s", ln)]
    scores = {}

    def add(tok, w):
        tok = tok.strip()
        if len(tok) < 2 or not CJK(tok):
            return
        if tok in STOPWORDS:
            return
        scores[tok] = scores.get(tok, 0) + w

    if jieba:
        for tok in jieba.cut(plain):
            add(tok, 1)
        for h in headings:                      # 标题词加权
            for tok in jieba.cut(h):
                add(tok, 3)
    else:
        # 1) 主题词表扫描（高质量、领域相关）
        for t in TERMS:
            c = plain.count(t)
            if c:
                scores[t] = scores.get(t, 0) + c
        for h in headings:
            for t in TERMS:
                if t in h:
                    scores[t] = scores.get(t, 0) + 3
        # 2) 词表命中过少时，用 CJK n-gram 词频补充
        if len(scores) < 5:
            for run in re.findall(r"[\u4e00-\u9fff]+", plain):
                for n in (2, 3):
                    for i in range(len(run) - n + 1):
                        add(run[i:i + n], 1)
            for h in headings:
                for run in re.findall(r"[\u4e00-\u9fff]+", h):
                    for n in (2, 3):
                        for i in range(len(run) - n + 1):
                            add(run[i:i + n], 3)

    # 取词频最高的若干个作为标签
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    tags = [t for t, _ in ranked[:8]]
    return tags, scores


# ---------------------------------------------------------------- frontmatter
def split_frontmatter(text):
    if text.startswith("---"):
        m = re.match(r"^---\n(.*?\n)---(?:\n|$)", text, re.S)
        if m:
            return m.group(1), text[m.end():]
    return None, text


def update_frontmatter(fm, author, tags):
    """在 fm（不含首尾 --- 的内部块）中补充/更新 author 与 tags，返回新块文本。
    正确处理 YAML 块列表（key:\\n  - a\\n  - b），并吞掉脚本首轮可能遗留的
    悬空列表项，避免产生非法 frontmatter（Obsidian 无法解析）。tags 统一序列化为
    块列表格式，便于 Obsidian 识别为列表属性。"""
    lines = fm.split("\n")
    out = []
    handled_author = False
    handled_tags = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        key = m.group(1).lower() if m else ""
        val = m.group(2).strip() if m else ""
        if key == "author":
            out.append("author: " + author)
            handled_author = True
            i += 1
            continue
        if key == "tags":
            out.append("tags:")
            for t in tags:
                out.append("  - " + t)
            handled_tags = True
            # 消费紧随其后的块列表项（原 tags 列表，或首轮遗留的悬空项）
            j = i + 1
            while j < n and re.match(r"^\s*-\s+", lines[j]):
                j += 1
            i = j
            continue
        # 其它键：若值为空且其后为块列表，保留整段原始文本（不破坏其它列表属性）
        if m and val == "":
            j = i + 1
            while j < n and re.match(r"^\s*-\s+", lines[j]):
                j += 1
            out.extend(lines[i:j])
            i = j
            continue
        out.append(line)
        i += 1
    if not handled_author:
        out.append("author: " + author)
    if not handled_tags:
        out.append("tags:")
        for t in tags:
            out.append("  - " + t)
    # 去掉尾部可能的空行
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)


def make_frontmatter(author, tags):
    """无 frontmatter 的文件：生成 author + 块列表 tags。"""
    lines = ["author: " + author, "tags:"]
    for t in tags:
        lines.append("  - " + t)
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程
def collect_articles():
    arts = []
    for dirpath, dirs, files in os.walk(CONTENT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            if f in SKIP_FILES or f == "index.md":
                continue
            # 仅处理文件名标注 🔊 符号的文章（已定稿、已放置配套音频）；
            # 未放置音频（文件名无 🔊）的文件暂不处理。
            if "🔊" not in f:
                continue
            # 跳过 Obsidian 进行中的重命名文件（约定：不触碰 X 后缀，
            # 例如「xxxX.md」），避免改动用户尚未定稿的文章。
            if f[:-3] and f[:-3][-1] == "X":
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, CONTENT_DIR).replace("\\", "/")
            txt = open(full, encoding="utf-8").read()
            fm, body = split_frontmatter(txt)
            # 已有 tags 解析（支持内联与 YAML 块列表两种格式）
            existing_tags = []
            if fm is not None:
                flines = fm.split("\n")
                for idx, ln in enumerate(flines):
                    if ln.lower().startswith("tags:"):
                        v = ln.split(":", 1)[1].strip()
                        if v:
                            existing_tags = [t.strip() for t in re.sub(r"[\[\]]", "", v).split(",") if t.strip()]
                        else:
                            # 块列表：key: 后逐行读取「  - xxx」
                            j = idx + 1
                            while j < len(flines) and re.match(r"^\s*-\s+", flines[j]):
                                item = re.sub(r"^\s*-\s+", "", flines[j]).strip()
                                if item:
                                    existing_tags.append(item)
                                j += 1
                        break
            title = None
            if fm is not None:
                for ln in fm.split("\n"):
                    if ln.lower().startswith("title:"):
                        title = ln.split(":", 1)[1].strip().strip('"').strip()
                        break
            if not title:
                title = re.sub(r"🔊\s*", "", f[:-3]).strip().rstrip("Xx").strip().strip('"').strip()
            slug = rel[:-3]
            slug = re.sub(r"🔊\s*", "", slug)
            slug = "/".join(seg.strip() for seg in slug.split("/"))
            arts.append({
                "rel": rel, "full": full, "txt": txt, "fm": fm, "body": body,
                "title": title, "slug": slug,
                "top": slug.split("/")[0] if "/" in slug else "",
                "existing_tags": existing_tags,
            })
    return arts


def main():
    dry = "--dry-run" in sys.argv[1:]
    jieba = load_jieba()
    print("[info] jieba: %s" % ("已加载" if jieba else "不可用，使用 n-gram 退化方案"))
    arts = collect_articles()
    print("[info] 待处理文章数：%d" % len(arts))

    # 第一遍：为每篇计算标签（已有则与原标签合并去重，补充提取关键词），
    # 汇总全局用于相关推荐
    for a in arts:
        computed, _ = extract_tags(a["body"], jieba)
        if a["existing_tags"]:
            # 合并：保留用户原有标签，补充提取关键词（去重、保持先后顺序）
            seen = set()
            merged = []
            for t in a["existing_tags"] + computed:
                if t not in seen:
                    seen.add(t)
                    merged.append(t)
            a["tags"] = merged[:12]
        else:
            a["tags"] = computed
    tagmap = {a["slug"]: set(a["tags"]) for a in arts}

    changed = 0
    for a in arts:
        # ---- author ----
        author = "龙洋仁波切" if "上师开示" in a["slug"] else "Drimed"
        # ---- 相关推荐 ----
        recs = []
        scored = []
        for b in arts:
            if b["slug"] == a["slug"]:
                continue
            shared = len(tagmap[a["slug"]] & tagmap[b["slug"]])
            same_top = (b["top"] == a["top"]) and bool(a["top"])
            scored.append((shared, same_top, b))
        scored.sort(key=lambda x: (-x[0], 0 if x[1] else 1, x[2]["title"]))
        for shared, same_top, b in scored:
            if len(recs) >= 5:
                break
            if shared >= 1 or (same_top and len(recs) < 5):
                recs.append(b)
        # 仍不足 5 时，放宽到任意其他文章（保证每篇都有推荐）
        if len(recs) < 5:
            for shared, same_top, b in scored:
                if b not in recs:
                    recs.append(b)
                if len(recs) >= 5:
                    break

        # ---- 组装新文件 ----
        new_fm = make_frontmatter(author, a["tags"]) if a["fm"] is None else \
            update_frontmatter(a["fm"], author, a["tags"])
        body = a["body"]
        has_rel = RELATED_HEADING in body
        related_block = ""
        if not has_rel and recs:
            lines = ["", "", "## " + RELATED_HEADING, ""]
            for b in recs:
                lines.append("- [[" + b["slug"] + "|" + b["title"] + "]]")
            related_block = "\n".join(lines) + "\n"
        new_body = body.rstrip("\n") + related_block
        if a["fm"] is None:
            new_txt = "---\n" + new_fm + "\n---\n" + new_body
        else:
            new_txt = "---\n" + new_fm + "\n---\n" + new_body

        # 判断是否有改动
        if new_txt == a["txt"]:
            continue
        changed += 1
        if dry:
            print("\n[dry-run] 将修改：%s" % a["rel"])
            print("  author -> %s" % author)
            print("  tags   -> %s" % ", ".join(a["tags"]))
            print("  相关推荐(%d)：%s" % (len(recs), "、".join(b["title"] for b in recs)))
        else:
            with open(a["full"], "w", encoding="utf-8") as fh:
                fh.write(new_txt)
            print("已处理：%s  (author=%s, tags=%d, 相关=%d)" %
                  (a["rel"], author, len(a["tags"]), len(recs)))

    print("\n[完成] 实际改动文件数：%d / %d%s" % (changed, len(arts), "（dry-run，未落盘）" if dry else ""))


if __name__ == "__main__":
    main()
