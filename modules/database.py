"""
資料庫操作模組 - 處理股價數據和訂閱者管理
"""
import os
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from .config import DB_PATH, DEBUG_MODE, TPE_TZ
from .logger import get_logger

logger = get_logger(__name__)


# ===== 資料庫初始化 =====

def ensure_db():
    """建立股價資料表"""
    # 如果資料庫路徑包含目錄，確保目錄存在
    if os.path.dirname(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices(
                code TEXT,
                date TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER,
                PRIMARY KEY(code, date)
            )
            """
        )
        conn.commit()


def ensure_users_table():
    """建立訂閱者資料表"""
    # 如果資料庫路徑包含目錄，確保目錄存在
    if os.path.dirname(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
              user_id TEXT PRIMARY KEY,
              display_name TEXT,
              followed_at TEXT,
              active INTEGER DEFAULT 1
            )
        """)
        conn.commit()


# ===== 訂閱者管理 =====

def seed_subscribers_from_env():
    """
    從環境變數匯入訂閱者
    - LINE_USER_ID（你自己）
    - EXTRA_USER_IDS=Uxxx1,Uxxx2,...（其他人）
    """
    ids = []

    # 檢查 LINE_USER_ID
    line_user_id = os.environ.get("LINE_USER_ID", "").strip()
    if line_user_id:
        ids.append(line_user_id)
        logger.debug(f"💡 從 LINE_USER_ID 讀取: {line_user_id}")
    else:
        logger.warning("⚠️ LINE_USER_ID 環境變數為空")

    # 檢查 EXTRA_USER_IDS
    extra = os.environ.get("EXTRA_USER_IDS", "").strip()
    if extra:
        extra_ids = [x.strip() for x in extra.split(",") if x.strip()]
        ids.extend(extra_ids)
        logger.debug(f"💡 從 EXTRA_USER_IDS 讀取 {len(extra_ids)} 個用戶: {extra_ids}")
    else:
        logger.debug("💡 EXTRA_USER_IDS 環境變數為空或未設定")

    if not ids:
        logger.warning("⚠️ 無任何用戶 ID 可從環境變數載入")
        return

    logger.info(f"📥 準備從環境變數載入 {len(ids)} 個訂閱者")

    with sqlite3.connect(DB_PATH) as conn:
        inserted_count = 0
        for uid in set(ids):
            cursor = conn.execute("""
                INSERT OR IGNORE INTO subscribers(user_id, display_name, followed_at, active)
                VALUES(?, NULL, datetime('now'), 1)
            """, (uid,))
            if cursor.rowcount > 0:
                inserted_count += 1
                logger.debug(f"✅ 新增訂閱者: {uid}")
            else:
                logger.debug(f"ℹ️  訂閱者已存在: {uid}")
        conn.commit()

    logger.info(f"📊 環境變數訂閱者載入完成：新增 {inserted_count} 個，共處理 {len(set(ids))} 個")


def list_active_subscribers():
    """取得所有活躍訂閱者的 user_id 列表"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT user_id FROM subscribers WHERE active = 1").fetchall()
        total_rows = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
        inactive_rows = conn.execute("SELECT COUNT(*) FROM subscribers WHERE active = 0").fetchone()[0]

    active_users = [r[0] for r in rows]

    if DEBUG_MODE:
        logger.debug(f"📊 訂閱者統計 - 總數: {total_rows}, 活躍: {len(active_users)}, 非活躍: {inactive_rows}")
        if active_users:
            logger.debug(f"📋 活躍訂閱者清單: {active_users}")
        else:
            logger.debug("⚠️ 無活躍訂閱者")

    return active_users


# ===== 股價數據管理 =====

def get_existing_data_range() -> dict:
    """取得資料庫中每支股票的資料日期範圍"""
    if not os.path.exists(DB_PATH):
        return {}
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT code, MIN(date) as min_date, MAX(date) as max_date FROM prices GROUP BY code"
        )
        result = {}
        for row in cursor:
            result[row[0]] = {"min": row[1], "max": row[2]}
    return result


def upsert_prices(df: pd.DataFrame):
    """
    更新或插入股價數據到資料庫

    Args:
        df: 包含 code, date, open, high, low, close, volume 欄位的 DataFrame
    """
    if df.empty:
        return
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("_prices_in", conn, if_exists="replace", index=False)
        conn.execute("DELETE FROM prices WHERE (code, date) IN (SELECT code, date FROM _prices_in)")
        conn.execute(
            """
            INSERT INTO prices(code, date, open, high, low, close, volume)
            SELECT code, date, open, high, low, close, volume FROM _prices_in
            """
        )
        conn.execute("DROP TABLE _prices_in")
        conn.commit()
    logger.info(f"數據已存入資料庫: {DB_PATH}")


def load_recent_prices(days=120) -> pd.DataFrame:
    """
    從資料庫讀取最近 N 天的股價數據

    Args:
        days: 天數

    Returns:
        DataFrame: 股價數據（包含 code, date, open, high, low, close, volume 欄位）
    """
    _empty = pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "volume"])

    cutoff_str = (datetime.now(TPE_TZ).replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")

    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT code, date, open, high, low, close, volume FROM prices WHERE date >= ?",
            conn,
            params=(cutoff_str,),
            parse_dates=["date"],
        )

    if df.empty:
        return _empty

    return df