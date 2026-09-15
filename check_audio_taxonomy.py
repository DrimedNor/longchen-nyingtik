# -*- coding: utf-8 -*-
"""
音频分类一致性检查（发布前必跑）
================================
规则：「1. 听法音/1. 上师开示（AI朗读）」的文件夹结构，必须严格镜像「2. 读开示」的文件夹结构；
      每个音频必须待在与它对应文章相同的分类下。

判定依据（优先级从高到低）：
  1. 文章正文里的 [[xxx.mp3]] 引用 —— 权威依据
  2. MANUAL 表 —— 文章未写引用时的人工确认（每项都需注明理由）

用法：
  python check_audio_taxonomy.py           # 只检查，有问题退出码 1
  python check_audio_taxonomy.py --fix     # 自动把音频移动到正确分类

发布流程：build_site.py 之前先跑本脚本；不通过就不要发布。
"""
import os
import re
import sys
import shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content")
KS = os.path.join(ROOT, "2. 读开示")                          # 分类真相源
AUD = os.path.join(ROOT, "1. 听法音", "1. 上师开示（AI朗读）")   # 被校验方

LINK = re.compile(r"\[\[([^\]\|]+?\.(?:mp3|m4a|wav))\]\]", re.I)

# 文章未写 wikilink 引用时的人工确认映射：音频文件名 -> 分类相对路径
# 新增前必须确认：该分类下确有一篇文章与音频内容对应
MANUAL = {
    "什么样的老师适合你.mp3": "3. 寻找上师",  # 对应《找一位什么样的上师最好🔊》
}


def scan_ks():
    """返回 (分类列表, {音频名: 分类})"""
    cats, ref = [], {}
    for dp, dn, fn in os.walk(KS):
        dn[:] = [d for d in dn if not d.startswith(".")]
        rel = os.path.relpath(dp, KS).replace("\\", "/")
        if rel == ".":
            continue
        cats.append(rel)
        for f in fn:
            if not f.endswith(".md") or f == "index.md":
                continue
            txt = open(os.path.join(dp, f), encoding="utf-8").read()
            for name in LINK.findall(txt):
                ref[name.strip()] = rel
    ref.update(MANUAL)
    return cats, ref


def scan_audio():
    """返回 {分类: [音频名]}，根目录未归类的键为空字符串"""
    out = {}
    if not os.path.isdir(AUD):
        return out
    for dp, dn, fn in os.walk(AUD):
        dn[:] = [d for d in dn if not d.startswith(".")]
        rel = os.path.relpath(dp, AUD).replace("\\", "/")
        if rel == ".":
            continue
        files = [f for f in fn if f.lower().endswith((".mp3", ".m4a", ".wav"))]
        if files:
            out[rel] = files
    root_files = [f for f in os.listdir(AUD)
                  if f.lower().endswith((".mp3", ".m4a", ".wav"))
                  and os.path.isfile(os.path.join(AUD, f))]
    if root_files:
        out[""] = root_files
    return out


def main():
    cats, ref = scan_ks()
    actual = scan_audio()
    errors, warns = [], []

    # 1) 分类目录是否齐全（空分类允许，但要存在，保证结构镜像）
    for c in cats:
        if not os.path.isdir(os.path.join(AUD, c)):
            errors.append("缺少分类目录：1. 听法音/1. 上师开示（AI朗读）/%s" % c)

    # 2) 音频是否出现多余分类（上师开示里没有的分类）
    for c in actual:
        if c and c not in cats:
            errors.append("多余分类目录（读开示中没有）：%s" % c)

    # 3) 每个音频是否待在正确分类
    for c, files in actual.items():
        for f in files:
            want = ref.get(f)
            if want is None:
                warns.append("音频无对应文章（请确认是否该归档，或补一篇对应文章）：%s%s"
                             % (("「%s」/" % c) if c else "", f))
                continue
            if c != want:
                errors.append("音频位置错误：%s%s  → 应在「%s」"
                              % (("「%s」/" % c) if c else "（根目录）", f, want))

    # 4) 文章引用了但音频不存在
    all_audio = set()
    for files in actual.values():
        all_audio.update(files)
    for name, c in sorted(ref.items()):
        if name not in all_audio:
            warns.append("文章引用了不存在的音频：「%s」%s" % (c, name))

    # ---- 输出 ----
    print("=" * 60)
    print("音频分类一致性检查")
    print("  分类真相源：content/2. 读开示            （%d 个分类）" % len(cats))
    print("  被 校 验 方：content/1. 听法音/1. 上师开示（AI朗读）（%d 个音频）"
          % len(all_audio))
    print("=" * 60)

    if warns:
        print("\n[警告] %d 条" % len(warns))
        for w in warns:
            print("  ! " + w)
    if errors:
        print("\n[错误] %d 条" % len(errors))
        for e in errors:
            print("  x " + e)

    if not errors and not warns:
        print("\n✓ 完全一致：音频分类与「读开示」文章目录严格对应。")
        return 0

    if "--fix" in sys.argv and errors:
        print("\n-- 自动修正 --")
        fixed = 0
        for c in cats:
            os.makedirs(os.path.join(AUD, c), exist_ok=True)
        for c, files in list(actual.items()):
            for f in files:
                want = ref.get(f)
                if want is None or c == want:
                    continue
                src = os.path.join(AUD, c, f) if c else os.path.join(AUD, f)
                dst = os.path.join(AUD, want, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                print("  移动 %s → %s/" % (f, want))
                fixed += 1
        print("已修正 %d 个音频，请重新运行检查确认。" % fixed)
        return 0

    if errors:
        print("\n✗ 检查未通过。修正方法：手动移动，或运行 `python check_audio_taxonomy.py --fix`")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
