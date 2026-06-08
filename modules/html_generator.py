"""
HTML 網頁生成模組 - 為 GitHub Pages 生成每日股票推薦網頁
"""
import os
import pandas as pd
from datetime import datetime
from .logger import get_logger
from .stock_codes import get_stock_name

logger = get_logger(__name__)

# 設定保留天數（與 workflow 和 generate_index_standalone.py 使用相同參數）
KEEP_DAYS = 7


def _build_enriched_badges(code, row, fundamentals_df, institutional_df, margin_df):
    """生成包含多維數據的股票 badge HTML"""
    badges = ""

    # 基本面 badges (P/E, 殖利率, P/B)
    if fundamentals_df is not None and not fundamentals_df.empty:
        fund_row = fundamentals_df[fundamentals_df["code"] == code]
        if not fund_row.empty:
            fr = fund_row.iloc[0]
            pe = f"{fr['pe_ratio']:.1f}" if pd.notna(fr.get('pe_ratio')) else "-"
            dy = f"{fr['dividend_yield']:.2f}%" if pd.notna(fr.get('dividend_yield')) else "-"
            pb = f"{fr['pb_ratio']:.2f}" if pd.notna(fr.get('pb_ratio')) else "-"
            badges += f'''
                        <div style="display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap;">
                            <span style="background: #eef2ff; color: #4338ca; padding: 2px 7px; border-radius: 4px; font-size: 0.75em;">P/E {pe}</span>
                            <span style="background: #fef3c7; color: #92400e; padding: 2px 7px; border-radius: 4px; font-size: 0.75em;">殖利率 {dy}</span>
                            <span style="background: #ecfdf5; color: #065f46; padding: 2px 7px; border-radius: 4px; font-size: 0.75em;">P/B {pb}</span>
                        </div>'''

    # 法人 badges
    if institutional_df is not None and not institutional_df.empty:
        inst_row = institutional_df[institutional_df["code"] == code]
        if not inst_row.empty:
            ir = inst_row.iloc[0]
            cons = ir.get("consecutive_buy_days", 0)
            foreign = int(ir.get("foreign_net", 0))
            trust = int(ir.get("trust_net", 0))
            f_bg = "#dcfce7" if foreign > 0 else ("#f3f4f6" if foreign == 0 else "#fee2e2")
            f_color = "#166534" if foreign > 0 else ("#6b7280" if foreign == 0 else "#991b1b")
            t_bg = "#dcfce7" if trust > 0 else ("#f3f4f6" if trust == 0 else "#fee2e2")
            t_color = "#166534" if trust > 0 else ("#6b7280" if trust == 0 else "#991b1b")
            badges += f'''
                        <div style="display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap;">
                            <span style="background: {f_bg}; color: {f_color}; padding: 2px 7px; border-radius: 4px; font-size: 0.75em;">外資 {foreign:+,}</span>
                            <span style="background: {t_bg}; color: {t_color}; padding: 2px 7px; border-radius: 4px; font-size: 0.75em;">投信 {trust:+,}</span>'''
            if cons >= 3:
                badges += f'''
                            <span style="background: #dcfce7; color: #166534; padding: 2px 7px; border-radius: 4px; font-size: 0.75em; font-weight: bold;">連買{cons}日</span>'''
            badges += '''
                        </div>'''

    # 融資洗盤信號
    if margin_df is not None and not margin_df.empty:
        margin_row = margin_df[margin_df["code"] == code]
        if not margin_row.empty:
            mr = margin_row.iloc[0]
            dec_days = mr.get("margin_decreasing_days", 0)
            if dec_days >= 3:
                badges += f'''
                        <div style="margin-top: 4px;">
                            <span style="background: #fef3c7; color: #92400e; padding: 2px 7px; border-radius: 4px; font-size: 0.75em;">融資連減{dec_days}日</span>
                        </div>'''

    # Ensemble 分數
    if "ensemble_label" in row.index:
        label = row.get("ensemble_label", "")
        bc = row.get("ensemble_bullish", 0)
        if bc >= 3:
            e_color, e_bg = "#059669", "#dcfce7"
        elif bc >= 2:
            e_color, e_bg = "#2563eb", "#dbeafe"
        else:
            e_color, e_bg = "#6b7280", "#f3f4f6"
        badges += f'''
                        <div style="margin-top: 4px;">
                            <span style="background: {e_bg}; color: {e_color}; padding: 2px 7px; border-radius: 4px; font-size: 0.75em; font-weight: bold;">{label} 策略看好</span>
                        </div>'''

    return badges


def _build_continuation_section(section_title, icon, title_css_class, continuation_df,
                                prev_date_str, fundamentals_df, institutional_df,
                                margin_df, stock_tags):
    """生成延續觀察 section HTML"""
    if continuation_df is None or continuation_df.empty:
        return ""

    html = f"""
            <div class="section">
                <div class="section-title {title_css_class}">
                    <span>{icon}</span>
                    <span>{section_title}（{prev_date_str} 推薦）</span>
                </div>

                <div class="stock-grid">
"""
    for _, row in continuation_df.iterrows():
        code = row["code"]
        name = get_stock_name(code)
        ma20_ok = row.get("ma20_ok", False)
        status = row.get("status", "已轉弱")

        card_class = "stock-card still-valid" if ma20_ok else "stock-card no-longer-valid"
        if ma20_ok:
            badge_html = f'<span style="display:inline-block;background:#134e4a;color:white;font-size:0.8em;font-weight:bold;padding:3px 10px;border-radius:12px;margin-bottom:6px;">{status}</span>'
        else:
            badge_html = f'<span style="display:inline-block;background:#92400e;color:white;font-size:0.8em;font-weight:bold;padding:3px 10px;border-radius:12px;margin-bottom:6px;">{status}</span>'

        tags = (stock_tags or {}).get(code, [])
        tags_html = "".join(f'<span class="stock-tag">{t}</span>' for t in tags)

        # 建立 ensemble badge 用的 row
        badge_row = pd.Series({
            "ensemble_label": row.get("ensemble_label", ""),
            "ensemble_bullish": row.get("ensemble_bullish", 0),
        })
        enriched = _build_enriched_badges(code, badge_row, fundamentals_df, institutional_df, margin_df)

        html += f"""
                    <div class="{card_class}" onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')">
                        {badge_html}
                        <div class="stock-code">{code}</div>
                        <div class="stock-name">{name}</div>
                        {f'<div class="stock-tags">{tags_html}</div>' if tags_html else ''}{enriched}
                    </div>
"""
    html += """
                </div>
            </div>
"""
    return html


def generate_daily_html(date_str: str, group2a_df, group2b_df, output_dir: str = "docs", images_dir: str = None, breakout_df=None, hot_stocks_df=None, stock_tags: dict = None, fundamentals_df=None, institutional_df=None, margin_df=None, theme_sentiments: dict = None, yesterday_continuation_df=None, yesterday_date_str: str = "", day_before_continuation_df=None, day_before_date_str: str = ""):
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

        .section-title.continuation-yesterday {{
            color: #0f766e;
            border-bottom-color: #0f766e;
        }}

        .section-title.continuation-daybefore {{
            color: #b45309;
            border-bottom-color: #b45309;
        }}

        .stock-card.still-valid {{
            background: linear-gradient(135deg, #f0fdfa 0%, #ccfbf1 100%);
        }}

        .stock-card.no-longer-valid {{
            background: linear-gradient(135deg, #fff7ed 0%, #fed7aa 100%);
            opacity: 0.75;
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

        .stock-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 6px;
        }}

        .stock-tag {{
            background: rgba(102, 126, 234, 0.12);
            color: #5a6fd6;
            font-size: 0.72em;
            padding: 2px 7px;
            border-radius: 10px;
            border: 1px solid rgba(102, 126, 234, 0.25);
            white-space: nowrap;
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

    # 熱門股按鈕（放在選股策略上方）
    if hot_stocks_df is not None and not hot_stocks_df.empty:
        html_content += f"""
            <div style="text-align: center; margin-bottom: 35px;">
                <a href="{date_str}_hot.html" class="btn" style="background: linear-gradient(135deg, #e67e22 0%, #d35400 100%); font-size: 1.1em; padding: 14px 36px;">
                    🔥 每日熱門股 ({date_str})
                </a>
            </div>
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
            tags = (stock_tags or {}).get(code, [])
            tags_html = "".join(f'<span class="stock-tag">{t}</span>' for t in tags)
            enriched = _build_enriched_badges(code, row, fundamentals_df, institutional_df, margin_df)

            html_content += f"""
                    <div class="stock-card" onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')">
                        <div class="stock-code">{code}</div>
                        <div class="stock-name">{name}</div>
                        {f'<div class="stock-tags">{tags_html}</div>' if tags_html else ''}
                        <div class="stock-info">斜率: {slope:.3f}</div>{enriched}
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
            tags = (stock_tags or {}).get(code, [])
            tags_html = "".join(f'<span class="stock-tag">{t}</span>' for t in tags)
            enriched = _build_enriched_badges(code, row, fundamentals_df, institutional_df, margin_df)

            html_content += f"""
                    <div class="stock-card" onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')">
                        <div class="stock-code">{code}</div>
                        <div class="stock-name">{name}</div>
                        {f'<div class="stock-tags">{tags_html}</div>' if tags_html else ''}
                        <div class="stock-info">斜率: {slope:.3f}</div>{enriched}
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

    # 添加延續觀察 sections
    html_content += _build_continuation_section(
        "昨日延續觀察", "🔄", "continuation-yesterday",
        yesterday_continuation_df, yesterday_date_str,
        fundamentals_df, institutional_df, margin_df, stock_tags,
    )
    html_content += _build_continuation_section(
        "前日延續觀察", "📋", "continuation-daybefore",
        day_before_continuation_df, day_before_date_str,
        fundamentals_df, institutional_df, margin_df, stock_tags,
    )

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


def _make_sparkline(prices: list, width: int = 150, height: int = 52) -> str:
    """生成 inline SVG 折線圖（sparkline）"""
    if not prices or len(prices) < 2:
        return (f'<svg width="{width}" height="{height}">'
                f'<text x="5" y="{height // 2 + 4}" fill="#9ca3af" font-size="10">無資料</text></svg>')
    mn, mx = min(prices), max(prices)
    rng = mx - mn or mn * 0.01 or 1
    pad = 4
    pw, ph = width - pad * 2, height - pad * 2
    n = len(prices)
    pts = " ".join(
        f"{pad + i * pw / (n - 1):.1f},{pad + ph - (p - mn) / rng * ph:.1f}"
        for i, p in enumerate(prices)
    )
    color = "#16a34a" if prices[-1] >= prices[0] else "#dc2626"
    return (f'<svg width="{width}" height="{height}" style="display:block;overflow:visible">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
            f'</svg>')


def _build_pool_cards_html(pool_df, industry_data, hist_df, date_str: str = "") -> str:
    """
    將 Pool DataFrame 依粗粒度（coarse）分組，生成可展開的卡片 HTML。

    Summary 顯示：股數、今日新增（+N）、降溫數（❄️N）、各狀態 emoji 聚合。
    展開後顯示個股 sparkline、細分類 badge、選入日/價。
    """
    import pandas as pd

    if pool_df is None or (hasattr(pool_df, "empty") and pool_df.empty):
        return '<p style="color:#9ca3af;text-align:center;padding:20px 0;">觀察池目前為空（明日起入選股票自動記錄）</p>'

    today_str = date_str[:10] if date_str else ""

    def _get_coarse(code):
        if industry_data:
            return industry_data.get(str(code), {}).get("coarse", "其他")
        return "其他"

    df = pool_df.copy()
    df["coarse"] = df["code"].apply(_get_coarse)

    # 同一 code 可能跨日重複入選，只保留最早那筆（以首次選入為準）
    df = df.sort_values("entry_date").drop_duplicates("code", keep="first")

    # 依 coarse 分組，每組按最新 entry_date 排序
    coarse_order = df.groupby("coarse")["entry_date"].max().sort_values(ascending=False).index.tolist()

    cards_html = []
    for coarse in coarse_order:
        group = df[df["coarse"] == coarse].sort_values("entry_date", ascending=False)
        n = len(group)

        # ── 統計新增 / 各狀態數量 ────────────────────────────────────────────
        new_today = int((group["entry_date"].astype(str).str[:10] == today_str).sum()) if today_str else 0
        status_counts = group.get("heat_status", pd.Series(dtype=str)).value_counts().to_dict() if "heat_status" in group.columns else {}
        hot_n  = status_counts.get("hot", 0)
        cold_n = status_counts.get("cold", 0)

        # Summary 徽章列
        badges = []
        if new_today:
            badges.append(f'<span style="background:#dcfce7;color:#16a34a;font-size:0.78em;'
                          f'padding:2px 8px;border-radius:10px;font-weight:bold;">+{new_today} 今日</span>')
        if cold_n:
            badges.append(f'<span style="background:#fef2f2;color:#dc2626;font-size:0.78em;'
                          f'padding:2px 8px;border-radius:10px;">❄️ {cold_n}</span>')
        if hot_n:
            badges.append(f'<span style="background:#f0fdf4;color:#16a34a;font-size:0.78em;'
                          f'padding:2px 8px;border-radius:10px;">🔥 {hot_n}</span>')
        badges_html = "".join(badges)

        # ── 個股卡片（不重複顯示狀態 icon，已在 summary 聚合）────────────────
        stock_items = []
        for _, r in group.iterrows():
            code = str(r["code"])
            name = r.get("name") or get_stock_name(code)
            fine = r.get("fine_group") or "—"
            entry_date = str(r.get("entry_date", ""))[:10]
            days_held = r.get("days_held", "—")
            entry_price = r.get("entry_price")
            status = r.get("heat_status", "unknown")
            ep_str = f"{entry_price:.1f}" if pd.notna(entry_price) else "—"
            days_str = f"({days_held}天)" if days_held != "—" else ""

            # 新增 badge（個股卡片左上角）
            is_new = (entry_date == today_str and bool(today_str))
            new_dot = ('<span style="background:#16a34a;color:white;font-size:0.68em;'
                       'padding:1px 5px;border-radius:6px;margin-left:4px;">NEW</span>'
                       if is_new else "")

            # 狀態色框
            border_color = {"hot": "#86efac", "cold": "#fca5a5"}.get(status, "#e2e8f0")
            bg_color = {"hot": "#f0fdf4", "cold": "#fef2f2"}.get(status, "#f8fafc")

            # Sparkline
            prices = []
            if hist_df is not None and not (hasattr(hist_df, "empty") and hist_df.empty):
                code_hist = hist_df[hist_df["code"] == code].sort_values("date").tail(20)
                prices = code_hist["close"].dropna().tolist()

            fine_badge = (f'<span style="background:#eff6ff;color:#2563eb;'
                          f'font-size:0.75em;padding:2px 7px;border-radius:10px;'
                          f'white-space:nowrap;">{fine}</span>')

            stock_items.append(f"""
                    <div style="background:{bg_color};border-radius:8px;padding:10px 12px;
                                border:1px solid {border_color};min-width:150px;flex:1;max-width:210px;">
                        <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;">
                            <a href="https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis"
                               target="_blank"
                               style="font-weight:bold;color:#2563eb;text-decoration:none;">{code}</a>{new_dot}
                            <span style="color:#374151;font-size:0.88em;">{name}</span>
                        </div>
                        <div style="margin-top:4px;">{fine_badge}</div>
                        <div style="margin-top:6px;">{_make_sparkline(prices, width=160, height=48)}</div>
                        <div style="margin-top:5px;font-size:0.8em;color:#6b7280;">
                            {entry_date} {days_str} ｜ 選入價 {ep_str}
                        </div>
                    </div>""")

        cards_html.append(f"""
            <details style="background:white;border-radius:12px;
                            box-shadow:0 2px 8px rgba(0,0,0,0.08);margin-bottom:14px;overflow:hidden;">
                <summary style="padding:16px 20px;cursor:pointer;
                                display:flex;align-items:center;gap:8px;flex-wrap:wrap;user-select:none;">
                    <span style="font-size:1.05em;font-weight:bold;color:#1e293b;">{coarse}</span>
                    <span style="background:#e0f2fe;color:#0369a1;font-size:0.8em;
                                 padding:2px 10px;border-radius:12px;">{n} 支</span>
                    {badges_html}
                    <span class="expand-arrow" style="margin-left:auto;color:#94a3b8;
                                                      font-size:0.85em;transition:transform 0.2s;">▼</span>
                </summary>
                <div style="padding:4px 16px 16px 16px;border-top:1px solid #f1f5f9;">
                    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;">
                        {"".join(stock_items)}
                    </div>
                </div>
            </details>""")

    return "\n".join(cards_html)


def _build_sector_stocks_html(sec: dict, hist_df) -> str:
    """為族群卡片生成展開後的個股清單（含 sparkline，最多量最大前六名）"""
    codes = sec.get("codes", [])
    if not codes or hist_df is None or (hasattr(hist_df, "empty") and hist_df.empty):
        return '<p style="color:#9ca3af;font-size:0.9em;padding:8px 0;">無法取得個股明細</p>'

    sec_hist = hist_df[hist_df["code"].isin(codes)].copy()
    if sec_hist.empty:
        return '<p style="color:#9ca3af;font-size:0.9em;padding:8px 0;">無法取得個股明細</p>'

    sec_hist = sec_hist.sort_values("date")
    latest = sec_hist.groupby("code").last().reset_index()
    vol_col = "volume" if "volume" in latest.columns else None
    top6_codes = (latest.nlargest(6, vol_col)["code"].tolist() if vol_col
                  else latest["code"].head(6).tolist())

    cards = []
    for code in top6_codes:
        code_hist = sec_hist[sec_hist["code"] == code].tail(20)
        prices = code_hist["close"].tolist()
        name = get_stock_name(code)
        latest_close = prices[-1] if prices else None
        pct_chg = ((prices[-1] - prices[-2]) / prices[-2]) if len(prices) >= 2 else None

        close_str = f"{latest_close:.1f}" if latest_close is not None else "—"
        chg_str = f"{pct_chg:+.1%}" if pct_chg is not None else ""
        chg_color = ("#16a34a" if pct_chg and pct_chg > 0
                     else ("#dc2626" if pct_chg and pct_chg < 0 else "#6b7280"))

        cards.append(f"""
                <div style="background:#f8fafc;border-radius:8px;padding:10px 12px;
                            border:1px solid #e2e8f0;min-width:150px;flex:1;max-width:195px;">
                    <div style="font-weight:bold;font-size:0.88em;">
                        <a href="https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis"
                           target="_blank" style="color:#2563eb;text-decoration:none;">{code}</a>
                        <span style="color:#6b7280;font-size:0.85em;margin-left:4px;">{name}</span>
                    </div>
                    <div style="margin-top:2px;font-size:0.9em;">
                        {close_str}
                        <span style="color:{chg_color};margin-left:6px;font-size:0.85em;">{chg_str}</span>
                    </div>
                    <div style="margin-top:6px;">{_make_sparkline(prices)}</div>
                </div>""")

    return f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;">{"".join(cards)}</div>'


def generate_hot_stocks_html(
    date_str: str,
    pool_df,
    top_sectors: list,
    output_dir: str = "docs",
    theme_sentiments: dict = None,
    hist=None,
    industry_data: dict = None,
):
    """
    生成每日 Pool 監控 + 熱門族群頁面（{date_str}_hot.html）

    Args:
        date_str: 日期字串 (YYYY-MM-DD)
        pool_df: annotate_pool_heat() 回傳的 DataFrame（可為空或 None）
        top_sectors: get_top_sectors() 回傳的 list（最多 3 個族群 dict）
        output_dir: 輸出目錄（預設 'docs'）
        theme_sentiments: 未使用，保留參數相容性

    Returns:
        生成的 HTML 檔案路徑
    """
    os.makedirs(output_dir, exist_ok=True)
    html_file = os.path.join(output_dir, f"{date_str}_hot.html")

    # ── Pool cards (grouped by coarse category) ─────────────────────────────
    pool_cards_html = _build_pool_cards_html(pool_df, industry_data, hist, date_str=date_str)

    # ── Top sectors cards (expandable) ───────────────────────────────────────
    sector_cards_html = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, sec in enumerate(top_sectors or []):
        fine = sec.get("fine", "")
        heat = sec.get("heat", 0)
        active = sec.get("active", 0)
        total = sec.get("total", 0)
        medal = medals[i] if i < len(medals) else f"#{i+1}"
        heat_color = "#16a34a" if heat >= 0.7 else ("#d97706" if heat >= 0.5 else "#6b7280")
        stocks_html = _build_sector_stocks_html(sec, hist)
        sector_cards_html += f"""
                <details style="background:white;border-radius:12px;
                                box-shadow:0 2px 8px rgba(0,0,0,0.08);margin-bottom:16px;overflow:hidden;">
                    <summary style="padding:18px 22px;cursor:pointer;
                                    display:flex;align-items:center;gap:12px;user-select:none;">
                        <span style="font-size:1.5em;">{medal}</span>
                        <span style="font-size:1.1em;font-weight:bold;color:#1e293b;">{fine}</span>
                        <span style="margin-left:auto;background:#f0fdf4;color:{heat_color};
                               font-weight:bold;padding:4px 14px;border-radius:20px;">{heat:.0%}</span>
                        <span class="expand-arrow" style="color:#94a3b8;font-size:0.85em;transition:transform 0.2s;">▼</span>
                    </summary>
                    <div style="padding:0 20px 16px 20px;border-top:1px solid #f1f5f9;">
                        <div style="color:#6b7280;font-size:0.88em;padding-top:10px;">
                            {active} / {total} 支帶量上漲　｜　點選個股可查 K 線圖
                        </div>
                        {stocks_html}
                    </div>
                </details>"""

    if not sector_cards_html:
        sector_cards_html = '<p style="color:#9ca3af;text-align:center;padding:20px 0;">今日無足夠資料</p>'

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{date_str} 觀察池 &amp; 熱門族群</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", Arial, sans-serif;
            background: linear-gradient(135deg, #1e3a5f 0%, #2d6a4f 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 960px;
            margin: 0 auto;
            background: #f8fafc;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
            color: white;
            padding: 32px 30px;
            text-align: center;
        }}
        .header h1 {{ font-size: 2em; margin-bottom: 8px; }}
        .header .date {{ font-size: 1.1em; opacity: 0.9; }}
        .content {{ padding: 32px 24px; }}
        .section-title {{
            font-size: 1.4em;
            font-weight: bold;
            color: #1e293b;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid #e2e8f0;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .nav-buttons {{
            display: flex; justify-content: center; gap: 12px;
            margin-top: 28px; flex-wrap: wrap;
        }}
        .btn {{
            padding: 10px 24px;
            background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
            color: white;
            text-decoration: none;
            border-radius: 20px;
            font-weight: bold;
            transition: transform 0.2s;
            display: inline-block;
            font-size: 0.95em;
        }}
        .btn:hover {{ transform: translateY(-2px); }}
        details > summary {{ list-style: none; }}
        details > summary::-webkit-details-marker {{ display: none; }}
        details[open] .expand-arrow {{ transform: rotate(180deg); }}
        .footer {{
            text-align:center; padding:24px; background:#f1f5f9;
            color:#94a3b8; font-size:0.85em; border-top:1px solid #e2e8f0;
        }}
        @media (max-width:768px) {{
            .header h1 {{ font-size: 1.5em; }}
            .content {{ padding: 20px 12px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📋 觀察池 &amp; 熱門族群</h1>
            <div class="date">{date_str}</div>
        </div>
        <div class="content">

            <!-- ① Pool 觀察池 -->
            <div style="margin-bottom: 48px;">
                <div class="section-title">📋 觀察池（最近 14 天入選股）</div>
                {pool_cards_html}
                <p style="font-size:0.78em;color:#94a3b8;margin-top:10px;text-align:right;">
                    🔥 族群持續跟進　❄️ 族群降溫　➡️ 持穩
                </p>
            </div>

            <!-- ② 今日熱門族群前三名 -->
            <div>
                <div class="section-title">🏆 今日熱門族群前三名</div>
                {sector_cards_html}
            </div>

            <div class="nav-buttons">
                <a href="{date_str}.html" class="btn">📊 今日選股</a>
                <a href="index.html" class="btn">🏠 首頁</a>
            </div>
        </div>
        <div class="footer">
            <p>⚠️ 本資訊僅供學習研究使用，不構成任何投資建議</p>
            <p style="margin-top:4px;">Qtrading 台股推薦機器人 · {date_str}</p>
        </div>
    </div>
</body>
</html>"""

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"✅ 已生成 Pool 監控 HTML: {html_file}")
    return html_file


def generate_index_html(output_dir: str = "docs"):
    """
    生成首頁 index.html，顯示最近的推薦日期列表

    Args:
        output_dir: 輸出目錄
    """
    os.makedirs(output_dir, exist_ok=True)

    # 掃描所有已生成的日期頁面（只取 YYYY-MM-DD.html，排除 _hot.html 等）
    dates = []
    for f in os.listdir(output_dir):
        if not f.endswith('.html') or f == 'index.html':
            continue
        date_str = f.replace('.html', '')
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            dates.append(date_str)
        except ValueError:
            pass
    dates = sorted(dates, reverse=True)

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
