"""
批量读取上师开示目录下的所有文章，提炼标签
"""
import os
import re

BASE_DIR = r"D:\Users\Drimed\Projects\龙的传人-website\content\上师开示"

def extract_tags(content, title):
    """基于文章内容和标题提炼标签"""
    tags = set()
    
    # 合并标题和内容用于关键词匹配
    text = title + " " + content
    
    # 定义关键词与标签的映射
    keyword_mappings = {
        # 修行基础
        "无常": "诸行无常",
        "死亡": "诸行无常",
        "轮回": "轮回过患",
        "地狱": "轮回过患",
        "饿鬼": "轮回过患",
        "中阴": "轮回过患",
        "羡慕嫉妒恨": "轮回过患",
        "享乐": "轮回过患",
        "钱": "轮回过患",
        
        # 依师之道
        "上师": "依师之道",
        "师父": "依师之道",
        "依止": "依师之道",
        "依师": "依师之道",
        "心子": "依师之道",
        "弟子": "依师之道",
        "老师": "依师之道",
        "救命稻草": "依师之道",
        "听上师的话": "依师之道",
        "亲近": "依师之道",
        "礼仪": "依师之道",
        
        # 发心与心态
        "发心": "发心与心态",
        "心态": "发心与心态",
        "心": "发心与心态",
        "无私": "发心与心态",
        "利他": "发心与心态",
        "无我": "发心与心态",
        "信心": "发心与心态",
        "信仰": "发心与心态",
        "决心": "发心与心态",
        "态度": "发心与心态",
        
        # 戒律与行为
        "戒律": "戒律与行为",
        "学处": "戒律与行为",
        "行为": "戒律与行为",
        "规则": "戒律与行为",
        "人品": "戒律与行为",
        "靠谱": "戒律与行为",
        "团结": "戒律与行为",
        "自省": "戒律与行为",
        "反观": "戒律与行为",
        "缺点": "戒律与行为",
        "毛病": "戒律与行为",
        
        # 福报与供养
        "福报": "福报与供养",
        "供养": "福报与供养",
        "回报率": "福报与供养",
        
        # 修行方法
        "修行": "修行方法",
        "功课": "修行方法",
        "程序": "修行方法",
        "DIY": "修行方法",
        "规划": "修行方法",
        "方式": "修行方法",
        "龙钦宁提": "修行方法",
        "密行": "修行方法",
        "皈依": "修行方法",
        
        # 修行障碍
        "障碍": "修行障碍",
        "勇士": "修行障碍",
        "歧途": "修行障碍",
        "挣扎": "修行障碍",
        
        # 传承与寺院
        "多智钦": "传承与寺院",
        "母寺": "传承与寺院",
        "莲师": "传承与寺院",
        "传承": "传承与寺院",
        "历世": "传承与寺院",
        
        # 人生与生活
        "人生": "人生与生活",
        "机会": "人生与生活",
        "选择": "人生与生活",
        "计划": "人生与生活",
        "新年": "人生与生活",
        "第一": "人生与生活",
        "最重要": "人生与生活",
    }
    
    # 匹配关键词
    for keyword, tag in keyword_mappings.items():
        if keyword in text:
            tags.add(tag)
    
    return sorted(list(tags))

def main():
    articles = []
    
    for root, dirs, files in os.walk(BASE_DIR):
        for file in files:
            if file.endswith(".md") and file != "index.md":
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, BASE_DIR)
                
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # 提取标题（去掉🔊等标记）
                    title = file.replace(".md", "").replace("🔊", "").strip()
                    
                    # 提炼标签
                    tags = extract_tags(content, title)
                    
                    # 提取内容摘要（前200字）
                    # 去掉markdown标记
                    clean_content = re.sub(r'[#*`>\-\[\]()]', '', content)
                    clean_content = re.sub(r'\s+', ' ', clean_content).strip()
                    summary = clean_content[:150] + "..." if len(clean_content) > 150 else clean_content
                    
                    articles.append({
                        "path": rel_path,
                        "title": title,
                        "tags": tags,
                        "summary": summary
                    })
                except Exception as e:
                    print(f"读取失败: {rel_path}, 错误: {e}")
    
    # 输出结果
    print(f"共读取 {len(articles)} 篇文章\n")
    print("="*80)
    
    # 按当前目录结构分组输出
    current_dir = ""
    for article in sorted(articles, key=lambda x: x["path"]):
        dir_path = os.path.dirname(article["path"])
        if dir_path != current_dir:
            current_dir = dir_path
            print(f"\n【{dir_path}】")
        
        print(f"\n  标题: {article['title']}")
        print(f"  标签: {', '.join(article['tags']) if article['tags'] else '（未匹配到标签）'}")
        print(f"  摘要: {article['summary'][:80]}...")
    
    # 统计所有标签
    print("\n" + "="*80)
    print("\n【标签统计】")
    all_tags = {}
    for article in articles:
        for tag in article["tags"]:
            all_tags[tag] = all_tags.get(tag, 0) + 1
    
    for tag, count in sorted(all_tags.items(), key=lambda x: -x[1]):
        print(f"  {tag}: {count} 篇")
    
    # 保存完整结果到文件
    output_file = os.path.join(BASE_DIR, "..", "..", "文章标签分析结果.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"共读取 {len(articles)} 篇文章\n\n")
        f.write("="*80 + "\n\n")
        
        current_dir = ""
        for article in sorted(articles, key=lambda x: x["path"]):
            dir_path = os.path.dirname(article["path"])
            if dir_path != current_dir:
                current_dir = dir_path
                f.write(f"\n【{dir_path}】\n")
            
            f.write(f"\n  标题: {article['title']}\n")
            f.write(f"  标签: {', '.join(article['tags']) if article['tags'] else '（未匹配到标签）'}\n")
            f.write(f"  摘要: {article['summary']}\n")
        
        f.write("\n" + "="*80 + "\n\n")
        f.write("【标签统计】\n")
        for tag, count in sorted(all_tags.items(), key=lambda x: -x[1]):
            f.write(f"  {tag}: {count} 篇\n")
    
    print(f"\n完整结果已保存到: {output_file}")

if __name__ == "__main__":
    main()
