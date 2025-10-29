#!/usr/bin/env python3
"""
獨立的 index.html 生成腳本
用於在 gh-pages 分支上重新生成 index.html
"""
import os
from datetime import datetime

def generate_index_html(output_dir='.'):
    """生成 index.html"""
    os.makedirs(output_dir, exist_ok=True)

    # 掃描所有 HTML 檔案
    html_files = [f for f in os.listdir(output_dir)
                  if f.endswith('.html') and f != 'index.html']
    dates = sorted([f.replace('.html', '') for f in html_files], reverse=True)

    print(f"找到 {len(dates)} 個日期: {dates}")

    # 生成日期項目
    date_items_html = '\n'.join([
        f'''
                <a href="{date}.html" class="date-item">
                    <div class="date-item-date">📅 {date}</div>
                    <div class="date-item-arrow">→</div>
                </a>
        '''
        for date in dates
    ])

    html_content = f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>台股推薦機器人</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 60px 30px;
            text-align: center;
        }}

        .header h1 {{
            font-size: 3em;
            margin-bottom: 15px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }}

        .header p {{
            font-size: 1.2em;
            opacity: 0.95;
        }}

        .content {{
            padding: 40px 30px;
        }}

        .intro {{
            text-align: center;
            margin-bottom: 40px;
            color: #666;
        }}

        .intro h2 {{
            color: #667eea;
            margin-bottom: 15px;
        }}

        .date-list {{
            display: grid;
            gap: 15px;
        }}

        .date-item {{
            display: block;
            padding: 25px 30px;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 12px;
            text-decoration: none;
            color: #333;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        .date-item:hover {{
            transform: translateX(10px);
            box-shadow: 0 8px 15px rgba(0,0,0,0.2);
        }}

        .date-item-date {{
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }}

        .date-item-arrow {{
            float: right;
            font-size: 1.5em;
            color: #667eea;
        }}

        .footer {{
            text-align: center;
            padding: 30px;
            background: #f5f7fa;
            color: #666;
            border-top: 1px solid #e0e0e0;
        }}

        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 2em;
            }}

            .content {{
                padding: 20px 15px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 台股推薦機器人</h1>
            <p>每日自動篩選台股推薦</p>
        </div>

        <div class="content">
            <div class="intro">
                <h2>選股策略</h2>
                <p>基於 MA20 斜率與動能分析，每日篩選台股市場中的強勢股與潛力股</p>
            </div>

            <div class="date-list">
{date_items_html}
            </div>
        </div>

        <div class="footer">
            <p>⚠️ 本資訊僅供學習研究使用，不構成任何投資建議</p>
            <p>投資有風險，請謹慎評估</p>
            <p style="margin-top: 15px; font-size: 0.9em;">
                Powered by <a href="https://github.com/YanShuoPan/Qtrading" style="color: #667eea;">GitHub Actions</a>
            </p>
        </div>
    </div>
</body>
</html>
'''

    index_file = os.path.join(output_dir, 'index.html')
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✅ index.html 已生成，包含 {len(dates)} 個日期")

if __name__ == '__main__':
    generate_index_html()
