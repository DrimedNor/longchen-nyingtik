#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成PWA标准图标：藏红底金"龙"字"""

from PIL import Image, ImageDraw, ImageFont
import os

# 颜色定义
BG_COLOR = (138, 31, 28)  # #8a1f1c 藏红
GOLD_COLOR = (217, 184, 106)  # #d9b86a 金色
MASKABLE_BG = (138, 31, 28)  # maskable图标背景

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content", "assets")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def find_chinese_font():
    """查找支持中文的字体"""
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
        "C:/Windows/Fonts/simhei.ttf",    # 黑体
        "C:/Windows/Fonts/simsun.ttc",    # 宋体
        "C:/Windows/Fonts/simkai.ttf",    # 楷体
        "/System/Library/Fonts/PingFang.ttc",  # macOS
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            return path
    return None

def create_icon(size, maskable=False, output_path=None):
    """创建图标"""
    # 使用RGB模式（去掉透明通道，避免Android设备安装问题）
    img = Image.new('RGB', (size, size), BG_COLOR if not maskable else MASKABLE_BG)
    draw = ImageDraw.Draw(img)
    
    # 查找字体
    font_path = find_chinese_font()
    if font_path:
        # 字体大小为图标的60%
        font_size = int(size * 0.6)
        font = ImageFont.truetype(font_path, font_size)
    else:
        font = ImageFont.load_default()
    
    # 绘制"龙"字，居中
    text = "龙"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # maskable图标：图案缩小到中心66%安全区
    if maskable:
        scale = 0.66
        x = (size - text_width * scale) / 2 - bbox[0] * scale
        y = (size - text_height * scale) / 2 - bbox[1] * scale
        # 重新创建合适大小的字体
        if font_path:
            font = ImageFont.truetype(font_path, int(font_size * scale))
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (size - text_width) / 2 - bbox[0]
            y = (size - text_height) / 2 - bbox[1]
    else:
        x = (size - text_width) / 2 - bbox[0]
        y = (size - text_height) / 2 - bbox[1] - size * 0.02  # 稍微上移一点视觉居中
    
    draw.text((x, y), text, fill=GOLD_COLOR, font=font)
    
    if output_path:
        img.save(output_path, 'PNG')
        print(f"已生成: {output_path} ({size}x{size})")
    
    return img

# 生成6个图标
print("=== 生成PWA图标 ===")

# 1. icon-512.png (manifest标准)
create_icon(512, output_path=os.path.join(OUTPUT_DIR, "icon-512.png"))

# 2. icon-192.png (manifest标准)
create_icon(192, output_path=os.path.join(OUTPUT_DIR, "icon-192.png"))

# 3. icon-maskable-512.png (Android自适应图标)
create_icon(512, maskable=True, output_path=os.path.join(OUTPUT_DIR, "icon-maskable-512.png"))

# 4. apple-touch-icon-180.png (iOS主屏幕图标)
create_icon(180, output_path=os.path.join(OUTPUT_DIR, "apple-touch-icon-180.png"))

# 5. favicon-64.png
create_icon(64, output_path=os.path.join(OUTPUT_DIR, "favicon-64.png"))

# 6. favicon-32.png
create_icon(32, output_path=os.path.join(OUTPUT_DIR, "favicon-32.png"))

print("\n=== 图标生成完成 ===")
print(f"输出目录: {OUTPUT_DIR}")
