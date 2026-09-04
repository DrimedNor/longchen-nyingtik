"""
龙钦宁提资料库 - 数据一键导出脚本
功能：导出Cloudflare KV中的所有统计数据到本地JSON文件
使用方法：python export_data.py
"""

import json
import urllib.request
import os
from datetime import datetime

# 统计API地址
API_BASE = 'https://stats.longchen-nyingtik.wiki'

# 导出目录
EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')

def fetch_data(url):
    """获取API数据"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"  获取失败: {e}")
        return None

def main():
    # 创建导出目录
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # 生成时间戳
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_file = os.path.join(EXPORT_DIR, f'website_backup_{timestamp}.json')
    
    print("=" * 60)
    print("龙钦宁提资料库 - 数据导出")
    print("=" * 60)
    
    all_data = {
        'export_time': datetime.now().isoformat(),
        'version': '1.0',
        'data': {}
    }
    
    # 1. 获取访问统计
    print("\n[1/5] 获取访问统计...")
    stats = fetch_data(f'{API_BASE}/api/stats')
    if stats:
        all_data['data']['access_stats'] = stats
        print(f"  成功: {len(stats.get('devices', []))} 个设备, {len(stats.get('ips', []))} 个IP")
    
    # 2. 获取文章浏览统计
    print("\n[2/5] 获取文章浏览统计...")
    page_stats = fetch_data(f'{API_BASE}/api/admin/stats')
    if page_stats:
        all_data['data']['page_stats'] = page_stats.get('pageStats', [])
        all_data['data']['audio_stats'] = page_stats.get('audioStats', [])
        print(f"  成功: {len(page_stats.get('pageStats', []))} 篇文章, {len(page_stats.get('audioStats', []))} 个音频")
    
    # 3. 获取AI问答统计
    print("\n[3/5] 获取AI问答统计...")
    ai_stats = fetch_data(f'{API_BASE}/api/stats/ai-ask')
    if ai_stats:
        all_data['data']['ai_ask_stats'] = ai_stats
        print(f"  成功: 总调用 {ai_stats.get('summary', {}).get('totalCalls', 0)} 次")
    
    # 4. 获取待审核注册（如果有）
    print("\n[4/5] 获取待审核注册...")
    pending = fetch_data(f'{API_BASE}/api/admin/pending')
    if pending:
        all_data['data']['pending_registrations'] = pending
        print(f"  成功: {len(pending.get('pending', []))} 个待审核")
    
    # 5. 保存到文件
    print("\n[5/5] 保存到文件...")
    with open(export_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    file_size = os.path.getsize(export_file)
    print(f"  保存成功: {export_file}")
    print(f"  文件大小: {file_size / 1024:.2f} KB")
    
    print("\n" + "=" * 60)
    print("导出完成！")
    print(f"备份文件: {export_file}")
    print("=" * 60)
    
    # 显示最近的备份文件
    print("\n最近的备份文件:")
    backups = sorted([f for f in os.listdir(EXPORT_DIR) if f.endswith('.json')], reverse=True)[:5]
    for i, backup in enumerate(backups, 1):
        size = os.path.getsize(os.path.join(EXPORT_DIR, backup))
        print(f"  {i}. {backup} ({size / 1024:.2f} KB)")

if __name__ == '__main__':
    main()
