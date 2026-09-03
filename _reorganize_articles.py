"""
调整上师开示目录结构
按照新的分类建议重新组织文章
"""
import os
import shutil

BASE_DIR = r"D:\Users\Drimed\Projects\龙的传人-website\content\上师开示"

def safe_mkdir(path):
    """安全创建目录"""
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"创建目录: {path}")

def copy_file(src, dst):
    """复制文件，如果目标已存在则跳过"""
    if os.path.exists(dst):
        print(f"  已存在，跳过: {os.path.basename(dst)}")
        return False
    shutil.copy2(src, dst)
    print(f"  复制: {os.path.basename(dst)}")
    return True

def find_file(filename, search_dirs):
    """在多个目录中查找文件"""
    for d in search_dirs:
        filepath = os.path.join(d, filename)
        if os.path.exists(filepath):
            return filepath
    return None

def main():
    print("="*60)
    print("开始调整上师开示目录结构")
    print("="*60)
    
    # 定义新的目录结构和文件映射
    # 格式: (新目录, 文件名, 可能的旧目录列表)
    
    old_dirs = [
        os.path.join(BASE_DIR, "1. 为何修行？", "1.1 诸行无常"),
        os.path.join(BASE_DIR, "1. 为何修行？", "1.2 轮回过患"),
        os.path.join(BASE_DIR, "2. 找到智慧的指引"),
        os.path.join(BASE_DIR, "3. 心态决定命运"),
        os.path.join(BASE_DIR, "4.如何修行", "4.1 正确的依师之道"),
        os.path.join(BASE_DIR, "4.如何修行", "4.2 做一个靠谱的人"),
        os.path.join(BASE_DIR, "4.如何修行", "4.3 戒律，决定你的成败"),
        os.path.join(BASE_DIR, "4.如何修行", "4.4 处处离不开福报"),
        os.path.join(BASE_DIR, "4.如何修行", "4.5 修行也要有规划"),
        os.path.join(BASE_DIR, "4.如何修行", "修行的态度和决心"),
        os.path.join(BASE_DIR, "4.如何修行", "未分类"),
        os.path.join(BASE_DIR, "4.如何修行", "正确的修行方式"),
        os.path.join(BASE_DIR, "4.如何修行", "跨越修行的障碍"),
        os.path.join(BASE_DIR, "传承与母寺"),
    ]
    
    # 新的目录结构
    new_structure = {
        "1. 信心之源（根基篇）": [
            "历世多智钦与多智钦寺.md",
            "莲师赐予的珍贵礼物.md",
        ],
        "2. 为什么要修行（觉醒篇）\\2.1 诸行无常——生命就在呼吸间": [
            "万事无常，唯有佛法是依靠🔊.md",
            "死亡是最公平的🔊.md",
            "计划赶不上无常 🔊.md",
        ],
        "2. 为什么要修行（觉醒篇）\\2.2 轮回过患——不要错过解脱的机会": [
            "“羡慕嫉妒恨”的结果🔊.md",
            "不可错过的机会🔊.md",
            "不同状态的生命形态🔊.md",
            "不能太爱钱，它会要你命🔊.md",
            "享乐的尽头，是堕落🔊.md",
            "人生中最重要的事情🔊.md",
            "千万不要滞留在中阴间🔊.md",
            "地狱里大概的情形🔊.md",
            "饿鬼道🔊.md",
        ],
        "3. 寻找你的上师（入门篇）": [
            "什么样的老师适合你🔊.md",
            "认真对待自己的选择🔊.md",
            "选好你的“救命稻草”🔊.md",
        ],
        "4. 如何依止上师（核心篇）": [
            "为什么要把修行放在第一？.md",
            "亲近师父的礼仪.md",
            "依止弟子与心子.md",
            "修行程序拒绝 DIY🔊.md",
            "修行，上师只接受你的认真.md",
            "做一个合格的密行者.md",
            "听上师的话就是修行.md",
            "成就的必由之路🔊.md",
            "求学的关键问题🔊.md",
            "皈依，庄严的承诺.md",
            "至少让师父记住你.md",
        ],
        "5. 调伏自己的心（修心篇）\\5.1 心态与发心": [
            "一切从心开始.md",
            "发一颗无私的心.md",
            "新年第一天的发心.md",
            "信仰，要修到骨头和血液里去.md",
            "相信，来世银行最好的密码.md",
            "坚固的信心从哪里来.md",
        ],
        "5. 调伏自己的心（修心篇）\\5.2 无我利他——修行的真正境界": [
            "无我利他，修行的真正境界.md",
        ],
        "6. 做一个靠谱的修行人（品行篇）\\6.1 做人与品行": [
            "人品到底有多重要.md",
            "修行人的行为规则.md",
            "做 一个真正的修行人.md",
        ],
        "6. 做一个靠谱的修行人（品行篇）\\6.2 戒律与自省": [
            "为什么要团结.md",
            "入门的学处你做到了吗.md",
            "如何看待      他人的 “缺点 ”.md",
            "戒律，修行人最大的要害.md",
            "如何反观与自省🔊.md",
            "改掉内心的毛病.md",
        ],
        "7. 积累福报与资粮（福报篇）": [
            "供养  需要注意这些.md",
            "如何提高供养回报率.md",
        ],
        "8. 踏上实修之路（实修篇）\\8.1 修行程序与方法": [
            "龙钦宁提的修行程序.md",
            "选择适合自己的修行方式.md",
            "如何做好自己的功课.md",
        ],
        "8. 踏上实修之路（实修篇）\\8.2 修行的态度与决心": [
            "要选对“挣扎”的方向.md",
            "踏实修行，切莫误入歧途.md",
        ],
        "9. 跨越修行的障碍（精进篇）": [
            "做一名修行的勇士.md",
            "如何对待修行中的障碍.md",
        ],
    }
    
    # 创建新目录并复制文件
    copied_count = 0
    missing_files = []
    
    for new_dir, files in new_structure.items():
        full_new_dir = os.path.join(BASE_DIR, new_dir)
        safe_mkdir(full_new_dir)
        
        print(f"\n处理目录: {new_dir}")
        for filename in files:
            src = find_file(filename, old_dirs)
            if src:
                dst = os.path.join(full_new_dir, filename)
                if copy_file(src, dst):
                    copied_count += 1
            else:
                print(f"  ⚠️ 未找到: {filename}")
                missing_files.append(filename)
    
    print("\n" + "="*60)
    print(f"复制完成: 共复制 {copied_count} 个文件")
    if missing_files:
        print(f"未找到的文件: {len(missing_files)} 个")
        for f in missing_files:
            print(f"  - {f}")
    print("="*60)
    print("\n⚠️ 注意：旧目录尚未删除，请先验证新目录结构无误后再删除旧目录。")
    print("旧目录包括：")
    print("  - 1. 为何修行？")
    print("  - 2. 找到智慧的指引")
    print("  - 3. 心态决定命运")
    print("  - 4.如何修行")
    print("  - 传承与母寺")

if __name__ == "__main__":
    main()
