"""
台股推薦機器人 - 主程式
使用動能策略篩選台股，並透過 LINE 推送推薦清單與 K 線圖
"""
import os
from datetime import datetime, timedelta, timezone

# 導入模組
from modules.logger import setup_logger, get_logger
from modules.config import IN_GITHUB_ACTIONS, LINE_USER_ID
from modules.database import (
    ensure_db,
    ensure_users_table,
    seed_subscribers_from_env,
    list_active_subscribers,
    upsert_prices,
    load_recent_prices
)
from modules.google_drive import (
    get_drive_service,
    sync_database_from_drive,
    sync_line_ids_from_drive,
    sync_database_to_drive
)
from modules.line_messaging import broadcast_text, broadcast_image
from modules.stock_codes import get_stock_codes, get_stock_name, get_picks_top_k
from modules.stock_data import fetch_prices_yf, pick_stocks
from modules.visualization import plot_stock_charts
from modules.image_upload import upload_image

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
        seed_subscribers_from_env()
        subscribers = list_active_subscribers()

        if not subscribers:
            if LINE_USER_ID:
                subscribers = [LINE_USER_ID]
                logger.warning("⚠️ subscribers 為空，使用 LINE_USER_ID 作為單一對象推送。")
            else:
                logger.warning("⚠️ 無任何可推送對象（subscribers 表與 LINE_USER_ID 皆為空）。")
        logger.info(f"📱 活躍訂閱者數量: {len(subscribers)}")

        # ===== 步驟 4: 下載股價數據 =====
        logger.info("\n📌 步驟 4: 檢查並下載需要的數據")
        codes = get_stock_codes()
        df_new = fetch_prices_yf(codes, lookback_days=120)
        data_updated = False
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
        today_tpe = datetime.now(timezone(timedelta(hours=8))).date()
        today_weekday = today_tpe.weekday()  # 0=週一, 6=週日

        if picks.empty:
            group1 = picks
            group2 = picks
        else:
            group1 = picks[(picks["ma20_slope"] >= 0.5) & (picks["ma20_slope"] < 1)]
            group2 = picks[picks["ma20_slope"] < 0.5]

        logger.info(f"📈 好像蠻強的（斜率 0.5-1）：{len(group1)} 支")
        logger.info(f"📊 有機會噴 觀察一下（斜率 < 0.5）：{len(group2)} 支")

        # ===== 步驟 7: 發送 LINE 訊息 =====
        logger.info("\n📌 步驟 7: 發送 LINE 訊息")

        # 測試模式：所有日期都發送訊息
        if False:  # 停用週末檢查，測試用
            weekday_names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
            logger.info(f"🗓️  今日為{weekday_names[today_weekday]} ({today_tpe})，股市休市，跳過發送訊息")
            logger.info("📴 週末不發送股票推薦訊息")
        else:
            # 平日發送訊息
            if group1.empty and group2.empty:
                msg = f"📉 {today_tpe}\n今日無符合條件之台股推薦。"
                logger.info(f"將發送的訊息:\n{msg}")
                try:
                    broadcast_text(msg, subscribers)
                    logger.info("✅ LINE 訊息發送成功！")
                except Exception as e:
                    logger.error(f"❌ LINE 訊息發送失敗: {e}")
            else:
                # 發送 Group1: 好像蠻強的
                if not group1.empty:
                    send_group_messages(group1, "好像蠻強的", "💪", today_tpe, subscribers, hist)

                # 發送 Group2: 有機會噴 觀察一下
                if not group2.empty:
                    send_group_messages(group2, "有機會噴 觀察一下", "👀", today_tpe, subscribers, hist)

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