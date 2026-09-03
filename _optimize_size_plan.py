"""
单文件体积优化：文章内容按需加载
方案：
1. 构建时把每篇文章的html内容拆分成单独的JSON文件，放在dist/pages/目录下
2. PAGES数据中只保留元数据（slug、title、dir、is_index、meta、tags）
3. 前端点击文章时，通过fetch加载对应文章的JSON文件
4. 已加载的文章缓存在内存中，避免重复加载
"""

import os
import re
import json
import shutil

PROJECT_DIR = r"D:\Users\Drime\Projects\龙的传人-website"
BUILD_SCRIPT = os.path.join(PROJECT_DIR, "build_site.py")

# 读取构建脚本
with open(BUILD_SCRIPT, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 修改main函数，在生成HTML后，把文章内容拆分成单独的JSON文件
# 找到生成HTML的位置，添加拆分逻辑

# 首先，我们需要修改构建器，让它在生成PAGES数据时，把html内容单独保存
# 但是这个改动比较大，我们可以用另一种方式：
# 在构建完成后，读取生成的HTML，把PAGES数据中的html字段拆分成单独的JSON文件

# 让我先创建一个后处理脚本，在构建完成后运行
post_process_script = '''
import os
import re
import json

DIST_DIR = r"D:\\Users\\Drime\\Projects\\龙的传人-website\\dist"
HTML_FILE = os.path.join(DIST_DIR, "index.html")
PAGES_DIR = os.path.join(DIST_DIR, "pages")

# 创建pages目录
os.makedirs(PAGES_DIR, exist_ok=True)

# 读取HTML
with open(HTML_FILE, 'r', encoding='utf-8') as f:
    html = f.read()

# 提取PAGES数据
pages_match = re.search(r'var PAGES = (\\[.*?\\]);\\s*var TREE', html, re.DOTALL)
if not pages_match:
    print("未找到PAGES数据")
    exit(1)

pages_str = pages_match.group(1)
# 把JS对象转换成Python可解析的格式
# 简单处理：把单引号换成双引号，把true/false换成True/False
# 但是这样可能会有问题，因为内容中可能包含引号
# 更好的方式是用json.loads，但是需要先处理转义

# 我们用一种更简单的方式：直接在JS中修改，让PAGES数据不包含html字段
# 然后把html字段单独保存到JSON文件中

print("PAGES数据提取成功，开始拆分...")
'''

# 实际上，更好的方式是直接修改构建器，让它在生成PAGES数据时就把html字段单独保存
# 让我修改构建器中的main函数

# 找到main函数中生成HTML的位置
# 我们需要在生成HTML之前，把文章内容拆分成单独的JSON文件
# 然后在生成的HTML中，PAGES数据不包含html字段

# 让我先找到构建器中PAGES数据是如何生成的
# 从之前的代码看，PAGES数据是通过json.dumps生成的

# 让我搜索一下PAGES数据生成的代码
print("开始修改构建器...")

# 找到生成PAGES JSON的位置
old_pages_json = '''    pages_json = json.dumps(pages, ensure_ascii=False)'''

# 我们需要修改这个部分，把html字段单独保存
# 但是这个改动比较复杂，因为需要修改前端逻辑来加载文章内容

# 让我先创建一个完整的优化方案文档，然后再逐步实现
optimization_doc = """
# 单文件体积优化方案

## 当前状况
- index.html 文件大小：约 7.3 MB
- PAGES数据（所有文章内容）：约 2.4 MB 字符，占总字符数的 85%
- CSS：仅 50 KB
- JS代码：约 2.7 MB（含PAGES数据）

## 优化方案：文章内容按需加载

### 原理
把每篇文章的html内容从PAGES数据中拆出来，保存为单独的JSON文件。
前端点击文章时，通过fetch加载对应文章的内容。
已加载的文章缓存在内存中，避免重复加载。

### 实施步骤
1. **构建器修改**：
   - 生成HTML时，把每篇文章的html字段单独保存到 dist/pages/{slug}.json
   - PAGES数据中只保留元数据（slug、title、dir、is_index、meta、tags）
   - 首页和目录页的内容仍然保留在PAGES数据中（因为需要首屏显示）

2. **前端修改**：
   - 添加 loadPageContent(slug) 函数，通过fetch加载文章内容
   - show() 函数中，非目录页先显示加载状态，然后加载内容
   - 已加载的内容缓存在 pageContentCache 对象中
   - 加载失败时显示错误提示

3. **缓存策略**：
   - 内存缓存：已加载的文章缓存在JS对象中
   - 浏览器缓存：JSON文件设置较长的缓存时间（如1年）
   - Service Worker：可以考虑用SW预缓存常用文章

### 预期效果
- 首屏HTML体积：从 7.3 MB 减少到约 1-2 MB（减少约 70-85%）
- 首屏加载时间：显著减少
- 文章点击延迟：增加约 100-500ms（取决于网络速度）
- 总体体验：首屏快，文章加载有短暂延迟，但可接受

### 风险与应对
1. **离线使用**：如果用户需要离线使用所有文章，需要预加载所有文章
   - 应对：可以添加"下载全部文章"按钮，预加载所有内容
2. **SEO**：搜索引擎可能无法正确索引按需加载的内容
   - 应对：这个网站主要服务身边师兄，不追求公开SEO，且已禁止国内搜索引擎收录
3. **链接分享**：直接链接到文章时，需要确保内容能正确加载
   - 应对：show()函数中已经处理了hash路由，加载逻辑相同

## 其他优化方案（可选）

### 1. CSS和JS拆分
把CSS和JS拆分成单独的文件，浏览器可以缓存。
- 效果：有限，因为CSS只有50KB
- 实施难度：低

### 2. HTML压缩
去掉不必要的空白和注释。
- 效果：有限，约5-10%
- 实施难度：低

### 3. 图片懒加载优化
已经实现，可以进一步优化占位图和加载动画。
- 效果：有限
- 实施难度：低

## 实施优先级
1. **高**：文章内容按需加载（效果最显著）
2. **中**：HTML压缩（简单有效）
3. **低**：CSS和JS拆分（效果有限）
"""

# 保存优化方案文档
with open(os.path.join(PROJECT_DIR, "单文件体积优化方案.md"), 'w', encoding='utf-8') as f:
    f.write(optimization_doc)

print("优化方案文档已保存：单文件体积优化方案.md")
print("\n开始实施文章内容按需加载方案...")
