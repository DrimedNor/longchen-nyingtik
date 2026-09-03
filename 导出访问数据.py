"""
网站访问数据导出脚本
从 Cloudflare KV 导出访问数据，保存为 JSON 和 CSV 文件
使用 Python 标准库，无需安装额外依赖
"""

import json
import csv
import os
import urllib.request
from datetime import datetime

# 配置
API_BASE = "https://stats.longchen-nyingtik.wiki"
ADMIN_PASSWORD = "admin610"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "访问数据导出")

def export_data():
    """导出所有访问数据"""
    print("正在从 Cloudflare KV 导出访问数据...")
    
    # 1. 获取统计概览和详细数据
    req = urllib.request.Request(
        f"{API_BASE}/api/admin/stats",
        headers={
            "X-Admin-Password": ADMIN_PASSWORD,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"导出失败: {e}")
        return
    
    if not data.get("success"):
        print(f"导出失败: {data.get('message', '未知错误')}")
        return
    
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 2. 保存完整 JSON 数据
    json_file = os.path.join(OUTPUT_DIR, f"访问数据_{timestamp}.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON 数据已保存: {json_file}")
    
    # 3. 导出设备列表为 CSV
    devices_file = os.path.join(OUTPUT_DIR, f"设备列表_{timestamp}.csv")
    with open(devices_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["设备 ID", "首次 IP", "国家/地区", "省份", "城市", "时区", "首次访问时间"])
        for d in reversed(data.get("recentDevices", [])):
            writer.writerow([
                d.get("deviceId", ""),
                d.get("firstIp", ""),
                d.get("country", ""),
                d.get("region", ""),
                d.get("city", ""),
                d.get("timezone", ""),
                d.get("firstSeen", ""),
            ])
    print(f"✓ 设备列表 CSV 已保存: {devices_file}")
    
    # 4. 导出 IP 列表为 CSV
    ips_file = os.path.join(OUTPUT_DIR, f"IP列表_{timestamp}.csv")
    with open(ips_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["IP 地址", "国家/地区", "省份", "城市", "邮编", "纬度", "经度", "时区", "关联设备", "首次访问时间"])
        for ip in reversed(data.get("recentIps", [])):
            writer.writerow([
                ip.get("ip", ""),
                ip.get("country", ""),
                ip.get("region", ""),
                ip.get("city", ""),
                ip.get("postalCode", ""),
                ip.get("latitude", ""),
                ip.get("longitude", ""),
                ip.get("timezone", ""),
                ip.get("deviceId", ""),
                ip.get("firstSeen", ""),
            ])
    print(f"✓ IP 列表 CSV 已保存: {ips_file}")
    
    # 5. 打印统计概览
    print("\n" + "="*50)
    print("📊 统计概览")
    print("="*50)
    print(f"累计设备数: {data.get('deviceCount', 0)}")
    print(f"累计 IP 数: {data.get('ipCount', 0)}")
    print(f"设备阈值: {data.get('deviceThreshold', 10)}")
    print(f"注册阈值: {data.get('registerThreshold', 100)}")
    print(f"密码保护: {'已启用' if data.get('passwordEnabled') else '未启用'}")
    print(f"注册审核: {'已启用' if data.get('registerEnabled') else '未启用'}")
    print(f"待审核注册: {data.get('pendingCount', 0)}")
    print("="*50)
    print(f"\n所有文件已保存到: {OUTPUT_DIR}")

if __name__ == "__main__":
    export_data()
