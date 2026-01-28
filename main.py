"""
台股推薦機器人 - 主程式
使用動能策略篩選台股，並透過 LINE 推送推薦清單與 K 線圖
"""
import os
from datetime import datetime, timedelta, timezone

# 導入模組
from modules.logger import setup_logger, get_logger
from modules.config import IN_GITHUB_ACTIONS, LINE_USER_ID, GITHUB_PAGES_URL, LINE_NOTIFY_ENABLED
from modules.database import (
    ensure_db,
    ensure_users_table,
    seed_subscribers_from_env,
    upsert_prices,
    load_recent_prices
)
from modules.google_drive import (
    get_drive_service,
    sync_database_from_drive,
    sync_line_ids_from_drive,
    sync_database_to_drive
)
from modules.line_messaging import broadcast_text, broadcast_image, broadcast_button_message, get_active_subscribers
from modules.stock_codes import get_stock_codes, get_stock_name, get_picks_top_k
from modules.stock_data import fetch_prices_yf, pick_stocks
from modules.visualization import plot_stock_charts
from modules.image_upload import upload_image
from modules.html_generator import generate_daily_html, generate_index_html
from modules.breakout_detector import detect_c_pattern, summarize_c_pattern_events

# 初始化日誌
setup_logger()
logger = get_logger(__name__)


def main():
    """主程式流程"""
    logger.info("=" * 50)
    logger.info("🚀 台股推薦機器人自動執行")
    logger.info("=" * 50)
    start_time = datetime.now()

    try:
        # ===== 步驟 1-2: Google Drive 設定與同步 =====
        if IN_GITHUB_ACTIONS:
            logger.info("\n📌 步驟 1: GitHub Actions 環境，跳過 Google Drive OAuth 設定")
            logger.info("   (rclone 已處理資料同步)")
            drive_service = None
        else:
            logger.info("\n📌 步驟 1: 設定 Google Drive 連線")
            drive_service = get_drive_service()

            logger.info("\n📌 步驟 2: 從 Google Drive 同步資料")
            sync_database_from_drive(drive_service)
            sync_line_ids_from_drive(drive_service)

        # ===== 步驟 3: 初始化資料庫和訂閱者 =====
        logger.info("\n📌 步驟 3: 建立資料庫")
        ensure_db()
        ensure_users_table()
        # 取得訂閱者（優先從 line_id.txt，再從資料庫，最後用環境變數）
        subscribers = get_active_subscribers()

        if not subscribers:
            logger.warning("⚠️ 無任何可推送對象（line_id.txt、資料庫、環境變數皆為空）。")
        else:
            logger.info(f"📱 活躍訂閱者數量: {len(subscribers)}")
            for sub in subscribers:
                if isinstance(sub, dict):
                    logger.info(f"  - {sub.get('display_name', 'Unknown')}: {sub['user_id']}")
                else:
                    logger.info(f"  - {sub}")

        # ===== 步驟 4: 下載股價數據 =====
        logger.info("\n📌 步驟 4: 檢查並下載需要的數據")

        # 取得今日日期和星期
        today_tpe = datetime.now(timezone(timedelta(hours=8))).date()
        today_weekday = today_tpe.weekday()  # 0=週一, 6=週日

        # 週末不更新股價數據（股市休市）
        data_updated = False
        if today_weekday >= 5:  # 週六=5, 週日=6
            weekday_names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
            logger.info(f"🗓️  今日為{weekday_names[today_weekday]} ({today_tpe})，股市休市，跳過更新股價數據")
            logger.info("ℹ️  使用資料庫中的現有數據")
        else:
            codes = get_stock_codes()
            df_new = fetch_prices_yf(codes, lookback_days=120)
            if not df_new.empty:
                upsert_prices(df_new)
                data_updated = True
                logger.info("✅ 資料庫已更新")
            else:
                logger.info("ℹ️  無需更新資料庫")

        # ===== 步驟 5: 選股 =====
        logger.info("\n📌 步驟 5: 載入數據並篩選股票")
        hist = load_recent_prices(days=120)

        # 檢查資料是否正常載入
        if hist.empty:
            logger.warning("⚠️  資料庫中沒有可用的股價數據")
            logger.warning("   可能原因：")
            logger.warning("   1. 首次執行，資料庫為空")
            logger.warning("   2. yfinance 下載失敗")
            logger.warning("   3. 網路連線問題")
        else:
            logger.info(f"✅ 載入 {len(hist)} 筆歷史資料")
            logger.info(f"   涵蓋 {hist['code'].nunique()} 支股票")
            logger.info(f"   日期範圍: {hist['date'].min()} ~ {hist['date'].max()}")

        top_k = get_picks_top_k()
        picks = pick_stocks(hist, top_k=top_k)
        logger.info(f"📊 篩選出 {len(picks)} 支符合條件的股票")

        # ===== 步驟 6: 股票分組（依交易量能分組）=====
        logger.info("\n📌 步驟 6: 將股票分組（依交易量能）")

        if picks.empty:
            group2a = picks  # 前100大交易量能
            group2b = picks  # 其餘
        else:
            # 只保留斜率 < 0.7 的股票（刪除原本的 group1）
            candidates = picks[picks["ma20_slope"] < 0.7].copy()

            if candidates.empty:
                group2a = candidates
                group2b = candidates
            else:
                # 計算交易量能（交易量 × 收盤價）
                # 從歷史資料取得最近一日的收盤價和交易量
                latest_data = hist.sort_values('date').groupby('code').tail(1)
                latest_data['trading_value'] = latest_data['close'] * latest_data['volume']

                # 找出前100大交易量能的股票代碼
                top100_codes = latest_data.nlargest(100, 'trading_value')['code'].tolist()

                # 分成兩組
                group2a = candidates[candidates["code"].isin(top100_codes)]  # 前100大交易量能
                group2b = candidates[~candidates["code"].isin(top100_codes)]  # 其餘

                # 限制每組最多 6 支股票
                MAX_STOCKS_PER_GROUP = 6
                if len(group2a) > MAX_STOCKS_PER_GROUP:
                    logger.info(f"   前100大交易量能組有 {len(group2a)} 支，限制為 {MAX_STOCKS_PER_GROUP} 支")
                    group2a = group2a.head(MAX_STOCKS_PER_GROUP)
                if len(group2b) > MAX_STOCKS_PER_GROUP:
                    logger.info(f"   其餘組有 {len(group2b)} 支，限制為 {MAX_STOCKS_PER_GROUP} 支")
                    group2b = group2b.head(MAX_STOCKS_PER_GROUP)

        logger.info(f"📈 有機會噴 - 前100大交易量能（斜率 < 0.7）：{len(group2a)} 支")
        logger.info(f"📊 有機會噴 - 其餘（斜率 < 0.7）：{len(group2b)} 支")

        # ===== 步驟 6.3: 破底翻偵測 =====
        logger.info("\n📌 步驟 6.3: 偵測破底翻型態（C型）")
        breakout_stocks = []

        # 對所有股票進行破底翻偵測
        stock_codes = hist['code'].unique()
        logger.info(f"掃描 {len(stock_codes)} 支股票尋找破底翻型態...")

        for code in stock_codes:
            stock_df = hist[hist['code'] == code].copy()

            # 確保資料量足夠
            if len(stock_df) < 40:
                continue

            try:
                # 執行破底翻偵測
                result_df = detect_c_pattern(stock_df)
                events = summarize_c_pattern_events(result_df)

                # 只保留五日內收回的事件
                if not events.empty:
                    # 計算五日前的日期
                    five_days_ago = today_tpe - timedelta(days=5)
                    recent_events = events[events['reclaim_date'].dt.date >= five_days_ago]
                    if not recent_events.empty:
                        breakout_stocks.append(recent_events)
                        for _, evt in recent_events.iterrows():
                            logger.info(f"  ✅ {code} 發現破底翻事件（收回日期: {evt['reclaim_date'].date()}）")
            except Exception as e:
                logger.debug(f"  ⚠️  {code} 偵測失敗: {e}")

        # 彙整破底翻股票
        if breakout_stocks:
            import pandas as pd
            breakout_df = pd.concat(breakout_stocks, ignore_index=True)

            # 額外篩選：今日股價需在十日線之上
            logger.info("🔍 篩選條件：今日股價需在十日線之上")
            filtered_breakout = []
            for idx, row in breakout_df.iterrows():
                code = row['code']
                stock_df = hist[hist['code'] == code].copy()

                # 計算十日均線
                stock_df = stock_df.sort_values('date')
                stock_df['MA10'] = stock_df['close'].rolling(window=10).mean()

                # 取得今日資料（最新一筆）
                today_data = stock_df.iloc[-1]
                close_price = today_data['close']
                ma10 = today_data['MA10']

                # 判斷今日收盤是否在十日線之上
                if pd.notna(ma10) and close_price > ma10:
                    filtered_breakout.append(row)
                    logger.info(f"  ✅ {code} 通過篩選（收盤: {close_price:.2f}, MA10: {ma10:.2f}）")
                else:
                    ma10_str = f"{ma10:.2f}" if pd.notna(ma10) else "N/A"
                    logger.info(f"  ❌ {code} 未通過篩選（收盤: {close_price:.2f}, MA10: {ma10_str}）")

            if filtered_breakout:
                breakout_df = pd.DataFrame(filtered_breakout)
                # 按收回日期排序（最新的在前）
                breakout_df = breakout_df.sort_values('reclaim_date', ascending=False)
                logger.info(f"🔥 五日內破底翻股票（篩選後）：{len(breakout_df)} 支")
            else:
                breakout_df = None
                logger.info("ℹ️  五日內無符合條件的破底翻事件（今日股價需在十日線之上）")
        else:
            breakout_df = None
            logger.info("ℹ️  五日內無破底翻事件")

        # ===== 步驟 6.5: 生成 K 線圖並複製到 docs 資料夾 =====
        logger.info("\n📌 步驟 6.5: 生成 K 線圖並準備 GitHub Pages 資料")
        date_str = str(today_tpe)
        images_output_dir = os.path.join("docs", "images", date_str)
        os.makedirs(images_output_dir, exist_ok=True)

        # 生成並保存 Group2A 圖片（前100大交易量能）
        if not group2a.empty:
            generate_and_save_charts(group2a, "有機會噴-前100大交易量能", today_tpe, hist, images_output_dir)

        # 生成並保存 Group2B 圖片（其餘）
        if not group2b.empty:
            generate_and_save_charts(group2b, "有機會噴-其餘", today_tpe, hist, images_output_dir)

        # 生成並保存破底翻股票圖片
        if breakout_df is not None and not breakout_df.empty:
            logger.info(f"生成破底翻股票 K 線圖...")
            breakout_codes = breakout_df['code'].unique().tolist()
            generate_and_save_charts_from_codes(breakout_codes, "破底翻", today_tpe, hist, images_output_dir)

        # ===== 步驟 6.6: 生成 GitHub Pages HTML =====
        logger.info("\n📌 步驟 6.6: 生成 GitHub Pages HTML")
        try:
            generate_daily_html(date_str, group2a, group2b, output_dir="docs", breakout_df=breakout_df)
            # 注意：index.html 將由 workflow 統一生成（合併歷史資料後）
            logger.info("✅ GitHub Pages 每日 HTML 已生成")
        except Exception as e:
            logger.error(f"❌ 生成 HTML 失敗: {e}")

        # ===== 步驟 7: 發送 LINE 訊息 =====
        logger.info("\n📌 步驟 7: 發送 LINE 訊息")

        # 檢查 LINE 通知是否啟用
        if not LINE_NOTIFY_ENABLED:
            logger.info("📴 LINE 通知功能已關閉（可透過設定 LINE_NOTIFY_ENABLED=true 啟用）")
        # 檢查是否為週末（週六=5, 週日=6）
        elif today_weekday >= 5:
            weekday_names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
            logger.info(f"🗓️  今日為{weekday_names[today_weekday]} ({today_tpe})，股市休市，跳過發送訊息")
            logger.info("📴 週末不發送股票推薦訊息")
        else:
            # 平日發送訊息 - 改用按鈕訊息
            date_str = str(today_tpe)

            if group2a.empty and group2b.empty:
                # 無推薦時仍然發送按鈕訊息，讓用戶可以查看歷史記錄
                msg = f"📉 {today_tpe}\n今日無符合條件之台股推薦。"
                logger.info(f"將發送的訊息:\n{msg}")
                try:
                    broadcast_text(msg, subscribers)
                    logger.info("✅ LINE 訊息發送成功！")
                except Exception as e:
                    logger.error(f"❌ LINE 訊息發送失敗: {e}")
            else:
                # 有推薦時發送按鈕訊息（含網站連結和 Postback 互動）
                logger.info(f"發送按鈕訊息，連結到 GitHub Pages: {GITHUB_PAGES_URL}")
                try:
                    broadcast_button_message(date_str, GITHUB_PAGES_URL, subscribers)
                    logger.info("✅ LINE 按鈕訊息發送成功！")
                except Exception as e:
                    logger.error(f"❌ LINE 按鈕訊息發送失敗: {e}")

        # 無論是否發送 LINE，都保存股票清單到檔案（供未來使用）
        if not group2a.empty:
            save_stock_list(group2a, "有機會噴-前100大交易量能", "👀", today_tpe)
        if not group2b.empty:
            save_stock_list(group2b, "有機會噴-其餘", "👀", today_tpe)

        # ===== 步驟 8: 同步資料庫到 Google Drive =====
        if IN_GITHUB_ACTIONS:
            logger.info("\n📌 步驟 8: GitHub Actions 環境，資料同步由 rclone 處理")
        elif data_updated and drive_service:
            logger.info("\n📌 步驟 8: 同步資料庫到 Google Drive")
            sync_database_to_drive(drive_service)
        elif drive_service:
            logger.info("\n步驟 8: 資料無更新，跳過 Google Drive 同步")
        else:
            logger.info("\n步驟 8: Google Drive 服務不可用，跳過同步")

        # 任務完成
        end_time = datetime.now()
        execution_time = end_time - start_time
        logger.info("\n" + "=" * 50)
        logger.info(f"🎉 任務完成！執行時間: {execution_time}")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ 程式執行發生錯誤: {e}")
        from modules.config import DEBUG_MODE
        if DEBUG_MODE:
            logger.debug(f"詳細錯誤: {str(e)}", exc_info=True)
        raise
    finally:
        from modules.config import DEBUG_MODE
        if DEBUG_MODE:
            logger.debug("程式執行結束")


def generate_and_save_charts(group_df, group_name, today_tpe, hist, output_dir):
    """
    生成 K 線圖並保存到指定目錄

    Args:
        group_df: 股票群組 DataFrame
        group_name: 群組名稱
        today_tpe: 今日日期
        hist: 歷史股價數據
        output_dir: 輸出目錄
    """
    import shutil
    logger.info(f"生成「{group_name}」組 K 線圖...")

    group_codes = group_df["code"].tolist()
    for batch_num in range(0, len(group_codes), 6):
        batch_codes = group_codes[batch_num:batch_num + 6]
        batch_display = ", ".join(batch_codes)
        logger.info(f"  正在處理第 {batch_num//6 + 1} 批: {batch_display}")

        chart_path = plot_stock_charts(batch_codes, hist)
        if chart_path:
            # 保存圖表到 docs/images/{date}/ 資料夾
            # 加入時間戳記避免瀏覽器快取問題
            from datetime import datetime
            timestamp = datetime.now().strftime("%H%M%S")
            chart_filename = f"{group_name}_batch_{batch_num//6 + 1}_{today_tpe}_{timestamp}.png"
            saved_chart_path = os.path.join(output_dir, chart_filename)
            shutil.copy(chart_path, saved_chart_path)
            logger.info(f"  ✅ K 線圖已保存: {saved_chart_path}")

            # 刪除臨時檔案
            os.unlink(chart_path)
        else:
            logger.warning(f"  ❌ K 線圖生成失敗")


def generate_and_save_charts_from_codes(codes_list, group_name, today_tpe, hist, output_dir):
    """
    從股票代碼列表生成 K 線圖並保存到指定目錄

    Args:
        codes_list: 股票代碼列表
        group_name: 群組名稱
        today_tpe: 今日日期
        hist: 歷史股價數據
        output_dir: 輸出目錄
    """
    import shutil
    logger.info(f"生成「{group_name}」組 K 線圖...")

    for batch_num in range(0, len(codes_list), 6):
        batch_codes = codes_list[batch_num:batch_num + 6]
        batch_display = ", ".join(batch_codes)
        logger.info(f"  正在處理第 {batch_num//6 + 1} 批: {batch_display}")

        chart_path = plot_stock_charts(batch_codes, hist)
        if chart_path:
            # 保存圖表到 docs/images/{date}/ 資料夾
            # 加入時間戳記避免瀏覽器快取問題
            from datetime import datetime
            timestamp = datetime.now().strftime("%H%M%S")
            chart_filename = f"{group_name}_batch_{batch_num//6 + 1}_{today_tpe}_{timestamp}.png"
            saved_chart_path = os.path.join(output_dir, chart_filename)
            shutil.copy(chart_path, saved_chart_path)
            logger.info(f"  ✅ K 線圖已保存: {saved_chart_path}")

            # 刪除臨時檔案
            os.unlink(chart_path)
        else:
            logger.warning(f"  ❌ K 線圖生成失敗")


def save_stock_list(group_df, group_name, emoji, today_tpe):
    """
    保存股票清單到文字檔（供 Postback 互動使用）

    Args:
        group_df: 股票群組 DataFrame
        group_name: 群組名稱
        emoji: 群組表情符號
        today_tpe: 今日日期
    """
    logger.info(f"保存「{group_name}」組股票清單...")
    lines = [f"{emoji} {group_name} ({today_tpe})"]
    lines.append("以下股票可以參考：\n")
    for i, r in group_df.iterrows():
        stock_name = get_stock_name(r.code)
        lines.append(f"{r.code} {stock_name}")
    msg = "\n".join(lines)

    # 創建日期資料夾
    date_folder = os.path.join("data", str(today_tpe))
    os.makedirs(date_folder, exist_ok=True)

    # 保存股票清單到文字檔
    list_filename = f"{group_name}_{today_tpe}.txt"
    list_path = os.path.join(date_folder, list_filename)
    with open(list_path, "w", encoding="utf-8") as f:
        f.write(msg)
    logger.info(f"📝 股票清單已保存: {list_path}")


def send_group_messages(group_df, group_name, emoji, today_tpe, subscribers, hist):
    """
    發送分組訊息和圖表

    Args:
        group_df: 股票群組 DataFrame
        group_name: 群組名稱
        emoji: 群組表情符號
        today_tpe: 今日日期
        subscribers: 訂閱者列表
        hist: 歷史股價數據
    """
    logger.info(f"\n處理「{group_name}」組...")
    lines = [f"{emoji} {group_name} ({today_tpe})"]
    lines.append("以下股票可以參考：\n")
    for i, r in group_df.iterrows():
        stock_name = get_stock_name(r.code)
        lines.append(f"{r.code} {stock_name}")
    msg = "\n".join(lines)
    logger.info(f"訊息:\n{msg}")

    # 創建日期資料夾
    date_folder = os.path.join("data", str(today_tpe))
    os.makedirs(date_folder, exist_ok=True)

    # 保存股票清單到文字檔
    list_filename = f"{group_name}_{today_tpe}.txt"
    list_path = os.path.join(date_folder, list_filename)
    with open(list_path, "w", encoding="utf-8") as f:
        f.write(msg)
    logger.info(f"📝 股票清單已保存: {list_path}")

    try:
        broadcast_text(msg, subscribers)
        logger.info(f"✅ {group_name}組訊息發送成功")
    except Exception as e:
        logger.error(f"❌ {group_name}組訊息發送失敗: {e}")

    logger.info(f"\n生成並發送「{group_name}」組圖片")
    group_codes = group_df["code"].tolist()
    for batch_num in range(0, len(group_codes), 6):
        batch_codes = group_codes[batch_num:batch_num + 6]
        batch_display = ", ".join(batch_codes)
        logger.info(f"正在處理{group_name}第 {batch_num//6 + 1} 組: {batch_display}")

        chart_path = plot_stock_charts(batch_codes, hist)
        if chart_path:
            # 保存圖表到日期資料夾
            import shutil
            chart_filename = f"{group_name}_batch_{batch_num//6 + 1}_{today_tpe}.png"
            saved_chart_path = os.path.join(date_folder, chart_filename)
            shutil.copy(chart_path, saved_chart_path)
            logger.info(f"💾 圖表已保存: {saved_chart_path}")

            img_url = upload_image(chart_path)
            if img_url:
                try:
                    broadcast_image(img_url, subscribers)
                    logger.info(f"✅ 圖表已發送到 LINE")
                except Exception as e:
                    logger.error(f"❌ LINE 發送失敗: {e}")
            else:
                logger.warning(f"❌ 圖床上傳失敗")

            # 刪除臨時檔案
            os.unlink(chart_path)
        else:
            logger.warning(f"❌ 圖表生成失敗")


if __name__ == "__main__":
    main()