"""
HTML 網頁生成模組 - 為 GitHub Pages 生成每日股票推薦網頁
"""
import os
from datetime import datetime
from .logger import get_logger
from .stock_codes import get_stock_name

logger = get_logger(__name__)

# 設定保留天數（與 workflow 和 generate_index_standalone.py 使用相同參數）
KEEP_DAYS = 7


def generate_daily_html(date_str: str, group2a_df, group2b_df, output_dir: str = "docs", images_dir: str = None, breakout_df=None):
    """
    生成每日股票推薦 HTML 頁面

    Args:
        date_str: 日期字串 (YYYY-MM-DD)
        group2a_df: 有機會噴 - 前100大交易量能組 DataFrame
        group2b_df: 有機會噴 - 其餘組 DataFrame
        output_dir: 輸出目錄（預設 'docs' 給 GitHub Pages）
        images_dir: 圖片資料夾路徑（相對於 output_dir）
        breakout_df: 破底翻股票 DataFrame（可選）

    Returns:
        生成的 HTML 檔案路徑
    """
    os.makedirs(output_dir, exist_ok=True)

    # 如果沒有指定圖片目錄，使用預設值
    if images_dir is None:
        images_dir = f"images/{date_str}"

    # 生成個別日期頁面
    html_file = os.path.join(output_dir, f"{date_str}.html")

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{date_str} 台股推薦</title>
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
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }}

        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }}

        .header .date {{
            font-size: 1.2em;
            opacity: 0.95;
        }}

        .content {{
            padding: 40px 30px;
        }}

        .section {{
            margin-bottom: 50px;
        }}

        .section-title {{
            font-size: 1.8em;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .section-title.strong {{
            color: #667eea;
        }}

        .section-title.potential {{
            color: #764ba2;
        }}

        .stock-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}

        .stock-card {{
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            cursor: pointer;
        }}

        .stock-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 15px rgba(0,0,0,0.2);
        }}

        .stock-code {{
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 8px;
        }}

        .stock-name {{
            font-size: 1.1em;
            color: #333;
        }}

        .stock-info {{
            margin-top: 10px;
            font-size: 0.9em;
            color: #666;
        }}

        .empty-message {{
            text-align: center;
            padding: 40px;
            color: #999;
            font-size: 1.2em;
        }}

        .chart-container {{
            margin-top: 30px;
            display: grid;
            gap: 20px;
        }}

        .chart-image {{
            width: 100%;
            border-radius: 12px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.2);
            transition: transform 0.2s;
        }}

        .chart-image:hover {{
            transform: scale(1.02);
            cursor: pointer;
        }}

        .footer {{
            text-align: center;
            padding: 30px;
            background: #f5f7fa;
            color: #666;
            border-top: 1px solid #e0e0e0;
        }}

        .nav-buttons {{
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-top: 30px;
            flex-wrap: wrap;
        }}

        .btn {{
            padding: 12px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            border-radius: 25px;
            font-weight: bold;
            transition: transform 0.2s, box-shadow 0.2s;
            display: inline-block;
        }}

        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }}

        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 1.8em;
            }}

            .stock-grid {{
                grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
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
            <h1>📊 台股推薦</h1>
            <div class="date">{date_str}</div>
        </div>

        <div class="content">
"""

    # 添加 Group 2A: 有機會噴 - 前100大交易量能
    html_content += """
            <div class="section">
                <div class="section-title strong">
                    <span>👀</span>
                    <span>有機會噴 - 前100大交易量能</span>
                </div>
"""

    if group2a_df.empty:
        html_content += """
                <div class="empty-message">今日無符合條件的股票</div>
"""
    else:
        html_content += """
                <div class="stock-grid">
"""
        for idx, row in group2a_df.iterrows():
            code = row['code']
            name = get_stock_name(code)
            slope = row.get('ma20_slope', 0)

            html_content += f"""
                    <div class="stock-card" onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')">
                        <div class="stock-code">{code}</div>
                        <div class="stock-name">{name}</div>
                        <div class="stock-info">斜率: {slope:.3f}</div>
                    </div>
"""
        html_content += """
                </div>
"""

        # 添加 K 線圖（如果有圖片）
        images_path = os.path.join(output_dir, images_dir)
        if os.path.exists(images_path):
            # 查找該組的圖片
            group2a_images = [f for f in os.listdir(images_path) if '有機會噴-前100大交易量能' in f and f.endswith('.png')]
            if group2a_images:
                html_content += """
                <div class="chart-container">
"""
                for img_file in sorted(group2a_images):
                    img_path = f"{images_dir}/{img_file}"
                    html_content += f"""
                    <img src="{img_path}" alt="K線圖" class="chart-image" onclick="window.open('{img_path}', '_blank')">
"""
                html_content += """
                </div>
"""

    html_content += """
            </div>
"""

    # 添加 Group 2B: 有機會噴 - 其餘
    html_content += """
            <div class="section">
                <div class="section-title potential">
                    <span>👀</span>
                    <span>有機會噴 - 其餘</span>
                </div>
"""

    if group2b_df.empty:
        html_content += """
                <div class="empty-message">今日無符合條件的股票</div>
"""
    else:
        html_content += """
                <div class="stock-grid">
"""
        for idx, row in group2b_df.iterrows():
            code = row['code']
            name = get_stock_name(code)
            slope = row.get('ma20_slope', 0)

            html_content += f"""
                    <div class="stock-card" onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')">
                        <div class="stock-code">{code}</div>
                        <div class="stock-name">{name}</div>
                        <div class="stock-info">斜率: {slope:.3f}</div>
                    </div>
"""
        html_content += """
                </div>
"""

        # 添加 K 線圖（如果有圖片）
        images_path = os.path.join(output_dir, images_dir)
        if os.path.exists(images_path):
            # 查找該組的圖片
            group2b_images = [f for f in os.listdir(images_path) if '有機會噴-其餘' in f and f.endswith('.png')]
            if group2b_images:
                html_content += """
                <div class="chart-container">
"""
                for img_file in sorted(group2b_images):
                    img_path = f"{images_dir}/{img_file}"
                    html_content += f"""
                    <img src="{img_path}" alt="K線圖" class="chart-image" onclick="window.open('{img_path}', '_blank')">
"""
                html_content += """
                </div>
"""

    html_content += """
            </div>
"""

    # 添加破底翻組別（如果有）- 放在最下面
    if breakout_df is not None and not breakout_df.empty:
        html_content += """
            <div class="section">
                <div class="section-title" style="color: #e74c3c; border-bottom-color: #e74c3c;">
                    <span>🔥</span>
                    <span>破底翻型態 (五日內) - 至少等三天站穩十日線</span>
                </div>
"""
        html_content += """
                <div class="stock-grid">
"""
        for idx, row in breakout_df.iterrows():
            code = row['code']
            name = get_stock_name(code)
            reclaim_pct = row.get('reclaim_pct', 0)
            reclaim_date = row.get('reclaim_date')

            # 格式化收回日期
            if hasattr(reclaim_date, 'strftime'):
                reclaim_date_str = reclaim_date.strftime('%m/%d')
            else:
                reclaim_date_str = str(reclaim_date)[:10] if reclaim_date else ''

            html_content += f"""
                    <div class="stock-card" onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')" style="background: linear-gradient(135deg, #fff5f5 0%, #ffe5e5 100%);">
                        <div class="stock-code" style="color: #e74c3c;">{code}</div>
                        <div class="stock-name">{name}</div>
                        <div class="stock-info">收回: {reclaim_date_str} ({reclaim_pct:.2f}%)</div>
                    </div>
"""
        html_content += """
                </div>
"""

        # 添加 K 線圖（如果有圖片）
        images_path = os.path.join(output_dir, images_dir)
        if os.path.exists(images_path):
            # 查找該組的圖片
            breakout_images = [f for f in os.listdir(images_path) if '破底翻' in f and f.endswith('.png')]
            if breakout_images:
                html_content += """
                <div class="chart-container">
"""
                for img_file in sorted(breakout_images):
                    img_path = f"{images_dir}/{img_file}"
                    html_content += f"""
                    <img src="{img_path}" alt="破底翻K線圖" class="chart-image" onclick="window.open('{img_path}', '_blank')">
"""
                html_content += """
                </div>
"""

        html_content += """
            </div>
"""

    html_content += """
            <div class="nav-buttons">
                <a href="index.html" class="btn">📅 回到首頁</a>
            </div>
        </div>

        <div class="footer">
            <p>⚠️ 本資訊僅供學習研究使用，不構成任何投資建議</p>
            <p>投資有風險，請謹慎評估</p>
        </div>
    </div>
</body>
</html>
"""

    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"✅ 已生成 HTML: {html_file}")
    return html_file


def generate_index_html(output_dir: str = "docs"):
    """
    生成首頁 index.html，顯示最近的推薦日期列表

    Args:
        output_dir: 輸出目錄
    """
    os.makedirs(output_dir, exist_ok=True)

    # 掃描所有已生成的日期頁面
    html_files = [f for f in os.listdir(output_dir) if f.endswith('.html') and f != 'index.html']
    dates = sorted([f.replace('.html', '') for f in html_files], reverse=True)

    html_content = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>台股推薦機器人</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 60px 30px;
            text-align: center;
        }

        .header h1 {
            font-size: 3em;
            margin-bottom: 15px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }

        .header p {
            font-size: 1.2em;
            opacity: 0.95;
        }

        .content {
            padding: 40px 30px;
        }

        .intro {
            text-align: center;
            margin-bottom: 40px;
            color: #666;
        }

        .intro h2 {
            color: #667eea;
            margin-bottom: 15px;
        }

        .date-list {
            display: grid;
            gap: 15px;
        }

        .date-item {
            display: block;
            padding: 25px 30px;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 12px;
            text-decoration: none;
            color: #333;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        .date-item:hover {
            transform: translateX(10px);
            box-shadow: 0 8px 15px rgba(0,0,0,0.2);
        }

        .date-item-date {
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }

        .date-item-arrow {
            float: right;
            font-size: 1.5em;
            color: #667eea;
        }

        .empty-message {
            text-align: center;
            padding: 60px 20px;
            color: #999;
            font-size: 1.2em;
        }

        .footer {
            text-align: center;
            padding: 30px;
            background: #f5f7fa;
            color: #666;
            border-top: 1px solid #e0e0e0;
        }

        @media (max-width: 768px) {
            .header h1 {
                font-size: 2em;
            }

            .content {
                padding: 20px 15px;
            }
        }
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
"""

    if not dates:
        html_content += """
                <div class="empty-message">
                    目前尚無推薦資料<br>
                    請等待每日自動更新
                </div>
"""
    else:
        # 只顯示最近 KEEP_DAYS 天（與 workflow 歸檔邏輯一致）
        for date in dates[:KEEP_DAYS]:
            weekday = datetime.strptime(date, '%Y-%m-%d').strftime('%A')
            weekday_zh = {
                'Monday': '週一', 'Tuesday': '週二', 'Wednesday': '週三',
                'Thursday': '週四', 'Friday': '週五', 'Saturday': '週六', 'Sunday': '週日'
            }[weekday]

            html_content += f"""
                <a href="{date}.html" class="date-item">
                    <div class="date-item-date">📅 {date} ({weekday_zh})</div>
                    <div class="date-item-arrow">→</div>
                </a>
"""

    html_content += """
            </div>
        </div>

        <div class="footer">
            <p>⚠️ 本資訊僅供學習研究使用，不構成任何投資建議</p>
            <p>投資有風險，請謹慎評估</p>
            <p style="margin-top: 15px; font-size: 0.9em;">
                <a href="archive/" style="color: #667eea; text-decoration: none; border: 1px solid #667eea; padding: 8px 16px; border-radius: 5px; display: inline-block; margin-bottom: 10px;">
                    📁 查看歷史歸檔資料
                </a>
            </p>
            <p style="margin-top: 10px; font-size: 0.9em;">
                Powered by <a href="https://github.com/YanShuoPan/Qtrading" style="color: #667eea;">GitHub Actions</a>
            </p>
        </div>
    </div>
</body>
</html>
"""

    index_file = os.path.join(output_dir, 'index.html')
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"✅ 已生成首頁: {index_file}")
    return index_file
