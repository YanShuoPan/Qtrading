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
        top_k = get_picks_top_k()
        picks = pick_stocks(hist, top_k=top_k)
        logger.debug(f"載入 {len(hist)} 筆歷史資料")
        logger.debug(f"篩選出 {len(picks)} 支符合條件的股票")

        # ===== 步驟 6: 股票分組 =====
        logger.info("\n📌 步驟 6: 將股票分組")

        if picks.empty:
            group1 = picks
            group2 = picks
        else:
            group1 = picks[(picks["ma20_slope"] >= 0.5) & (picks["ma20_slope"] < 1)]
            group2 = picks[picks["ma20_slope"] < 0.5]

        logger.info(f"📈 好像蠻強的（斜率 0.5-1）：{len(group1)} 支")
        logger.info(f"📊 有機會噴 觀察一下（斜率 < 0.5）：{len(group2)} 支")

        # ===== 步驟 6.5: 生成 K 線圖並複製到 docs 資料夾 =====
        logger.info("\n📌 步驟 6.5: 生成 K 線圖並準備 GitHub Pages 資料")
        date_str = str(today_tpe)
        images_output_dir = os.path.join("docs", "images", date_str)
        os.makedirs(images_output_dir, exist_ok=True)

        # 生成並保存 Group1 圖片
        if not group1.empty:
            generate_and_save_charts(group1, "好像蠻強的", today_tpe, hist, images_output_dir)

        # 生成並保存 Group2 圖片
        if not group2.empty:
            generate_and_save_charts(group2, "有機會噴 觀察一下", today_tpe, hist, images_output_dir)

        # ===== 步驟 6.6: 生成 GitHub Pages HTML =====
        logger.info("\n📌 步驟 6.6: 生成 GitHub Pages HTML")
        try:
            generate_daily_html(date_str, group1, group2, output_dir="docs")
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

            if group1.empty and group2.empty:
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
        if not group1.empty:
            save_stock_list(group1, "好像蠻強的", "💪", today_tpe)
        if not group2.empty:
            save_stock_list(group2, "有機會噴 觀察一下", "👀", today_tpe)

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