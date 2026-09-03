with open('build_site.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加复制admin.html到dist/admin/index.html的逻辑
old_copy = '''    # 复制 Cloudflare Pages 的 _headers（缓存/安全策略）到 dist/ 根；仓库无此文件时跳过
    _headers_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflare", "_headers")
    if os.path.exists(_headers_src):
        shutil.copy2(_headers_src, os.path.join(DIST_DIR, "_headers"))

    print("已生成: %s" % out_path)'''

new_copy = '''    # 复制 Cloudflare Pages 的 _headers（缓存/安全策略）到 dist/ 根；仓库无此文件时跳过
    _headers_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflare", "_headers")
    if os.path.exists(_headers_src):
        shutil.copy2(_headers_src, os.path.join(DIST_DIR, "_headers"))

    # 复制管理后台 admin.html 到 dist/admin/index.html
    admin_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")
    if os.path.exists(admin_src):
        admin_dir = os.path.join(DIST_DIR, "admin")
        os.makedirs(admin_dir, exist_ok=True)
        shutil.copy2(admin_src, os.path.join(admin_dir, "index.html"))
        print("管理后台已复制: dist/admin/index.html")

    print("已生成: %s" % out_path)'''

if old_copy in content:
    content = content.replace(old_copy, new_copy)
    print("1. 添加复制admin.html逻辑 - 完成")
else:
    print("1. 添加复制admin.html逻辑 - 未找到")

# 2. 修改最近更新生成逻辑，去掉每一项前面的日期
old_update = '''    if recent_items:
        html_parts = ['<ul>']
        display_items = recent_items[:3]  # 最多显示3项
        for item in display_items:
            date_str = datetime.datetime.fromtimestamp(item['mtime']).strftime('%m-%d')
            icon = '📄' if item['type'] == 'article' else '🎧'
            if item['slug']:
                html_parts.append(f'<li>{date_str} {icon} <a href="#/{item["slug"]}" style="color:var(--accent);">{item["title"]}</a></li>')
            else:
                html_parts.append(f'<li>{date_str} {icon} {item["title"]}</li>')
        if len(recent_items) > 3:
            html_parts.append(f'<li style="color:var(--ink-faint);font-size:.9em;">等 {len(recent_items)} 项内容更新</li>')
        html_parts.append('</ul>')'''

new_update = '''    if recent_items:
        html_parts = ['<ul>']
        display_items = recent_items[:3]  # 最多显示3项
        for item in display_items:
            icon = '📄' if item['type'] == 'article' else '🎧'
            if item['slug']:
                html_parts.append(f'<li>{icon} <a href="#/{item["slug"]}" style="color:var(--accent);">{item["title"]}</a></li>')
            else:
                html_parts.append(f'<li>{icon} {item["title"]}</li>')
        if len(recent_items) > 3:
            html_parts.append(f'<li style="color:var(--ink-faint);font-size:.9em;">等 {len(recent_items)} 项内容更新</li>')
        html_parts.append('</ul>'''

if old_update in content:
    content = content.replace(old_update, new_update)
    print("2. 最近更新去掉日期 - 完成")
else:
    print("2. 最近更新去掉日期 - 未找到")

with open('build_site.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n所有修改完成")
