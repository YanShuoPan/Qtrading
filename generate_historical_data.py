"""
生成歷史測試資料 - 用於測試 GitHub Pages 的 5 天保留機制
"""
import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from modules.html_generator import generate_daily_html, generate_index_html
from modules.logger import setup_logger, get_logger
from modules.stock_codes import get_stock_codes
from modules.database import ensure_db, load_recent_prices
from modules.stock_data import pick_stocks
from modules.visualization import plot_stock_charts
import shutil

# 初始化日誌
setup_logger()
logger = get_logger(__name__)

def generate_historical_data(days_back=7):
    """
    生成過去 N 天的歷史測試資料

    Args:
        days_back: 往回生成幾天的資料（預設 7 天）
    """
    logger.info(f"開始生成過去 {days_back} 天的歷史資料...")

    # 確保資料庫存在
    ensure_db()

    # 載入歷史股價資料
    logger.info("載入歷史股價資料...")
    hist = load_recent_prices(days=120)

    # 如果資料庫是空的，先下載資料
    if hist.empty:
        logger.info("📥 資料庫為空，開始下載股價資料...")
        from modules.stock_data import fetch_prices_yf
        from modules.database import upsert_prices

        codes = get_stock_codes()
        logger.info(f"下載 {len(codes)} 支股票的資料...")

        df_new = fetch_prices_yf(codes, lookback_days=120)
        if not df_new.empty:
            upsert_prices(df_new)
            logger.info("✅ 股價資料下載完成")

            # 重新載入資料
            hist = load_recent_prices(days=120)
        else:
            logger.error("❌ 無法下載股價資料")
            return

    if hist.empty:
        logger.error("❌ 仍然無法載入歷史資料")
        return

    # 取得今日日期
    today = datetime.now(timezone(timedelta(hours=8))).date()

    # 為每一天生成資料
    for i in range(days_back, 0, -1):
        target_date = today - timedelta(days=i)

        # 跳過週末
        if target_date.weekday() >= 5:  # 週六或週日
            logger.info(f"跳過週末: {target_date}")
            continue

        logger.info(f"\n{'='*50}")
        logger.info(f"生成 {target_date} 的資料...")
        logger.info(f"{'='*50}")

        # 執行選股（使用當天的資料）
        picks = pick_stocks(hist, top_k=300)

        # 分組
        if picks.empty:
            group1 = picks
            group2 = picks
        else:
            group1 = picks[(picks["ma20_slope"] >= 0.5) & (picks["ma20_slope"] < 1)]
            group2 = picks[picks["ma20_slope"] < 0.5]

        logger.info(f"好像蠻強的: {len(group1)} 支")
        logger.info(f"有機會噴 觀察一下: {len(group2)} 支")

        # 創建目錄
        date_str = str(target_date)
        images_output_dir = os.path.join("docs", "images", date_str)
        os.makedirs(images_output_dir, exist_ok=True)

        # 生成 K 線圖
        if not group1.empty:
            generate_charts_for_group(group1, "好像蠻強的", target_date, hist, images_output_dir)

        if not group2.empty:
            generate_charts_for_group(group2, "有機會噴 觀察一下", target_date, hist, images_output_dir)

        # 生成 HTML
        try:
            generate_daily_html(date_str, group1, group2, output_dir="docs")
            logger.info(f"✅ {target_date} 的 HTML 已生成")
        except Exception as e:
            logger.error(f"❌ 生成 {target_date} 的 HTML 失敗: {e}")

    # 更新首頁
    logger.info("\n生成首頁...")
    try:
        generate_index_html(output_dir="docs")
        logger.info("✅ 首頁已更新")
    except Exception as e:
        logger.error(f"❌ 生成首頁失敗: {e}")

    logger.info("\n" + "="*50)
    logger.info("🎉 歷史資料生成完成！")
    logger.info("="*50)
    logger.info("\n請執行以下命令提交變更：")
    logger.info("  git add docs/")
    logger.info('  git commit -m "Add historical test data for GitHub Pages"')
    logger.info("  git push")


def generate_charts_for_group(group_df, group_name, target_date, hist, output_dir):
    """
    為股票分組生成 K 線圖
    """
    logger.info(f"生成「{group_name}」組 K 線圖...")

    group_codes = group_df["code"].tolist()
    for batch_num in range(0, len(group_codes), 6):
        batch_codes = group_codes[batch_num:batch_num + 6]
        batch_display = ", ".join(batch_codes)
        logger.info(f"  正在處理第 {batch_num//6 + 1} 批: {batch_display}")

        chart_path = plot_stock_charts(batch_codes, hist)
        if chart_path:
            # 保存圖表
            timestamp = datetime.now().strftime("%H%M%S")
            chart_filename = f"{group_name}_batch_{batch_num//6 + 1}_{target_date}_{timestamp}.png"
            saved_chart_path = os.path.join(output_dir, chart_filename)
            shutil.copy(chart_path, saved_chart_path)
            logger.info(f"  ✅ K 線圖已保存: {saved_chart_path}")

            # 刪除臨時檔案
            os.unlink(chart_path)
        else:
            logger.warning(f"  ❌ K 線圖生成失敗")


if __name__ == "__main__":
    import sys

    # 可以從命令行參數指定天數
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 7

    generate_historical_data(days_back=days_back)
