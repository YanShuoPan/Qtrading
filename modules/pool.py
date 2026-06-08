"""
Pool 監控模組
管理「觀察池」：記錄每日入選股，追蹤最近 14 日的族群熱度變化
"""
import sqlite3
from datetime import date, timedelta

import pandas as pd

from .config import DB_PATH
from .logger import get_logger
from .stock_codes import get_stock_name

logger = get_logger(__name__)

POOL_DAYS = 14  # 保留天數（日曆天）


def ensure_pool_table() -> None:
    """建立 pool 資料表（若不存在）"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pool (
                code TEXT NOT NULL,
                name TEXT,
                entry_date TEXT NOT NULL,
                entry_price REAL,
                fine_group TEXT,
                heat_at_entry REAL,
                PRIMARY KEY (code, entry_date)
            )
        """)
        conn.commit()


def expire_pool() -> int:
    """移除 pool 中超過 POOL_DAYS 日曆天的紀錄，回傳移除筆數"""
    cutoff = (date.today() - timedelta(days=POOL_DAYS)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM pool WHERE entry_date < ?", (cutoff,))
        conn.commit()
    removed = cur.rowcount
    if removed:
        logger.info(f"✅ Pool 過期清除: 移除 {removed} 筆（entry_date < {cutoff}）")
    return removed


def add_to_pool(picks_df: pd.DataFrame, hist: pd.DataFrame,
                industry_data: dict, heat_scores: dict) -> int:
    """
    將選股加入 Pool（INSERT OR IGNORE，不重複插入同一 (code, entry_date)）

    Args:
        picks_df: 選股 DataFrame（需有 code 欄位）
        hist: 歷史股價 DataFrame（取最新收盤作為 entry_price）
        industry_data: load_industry_data() 的回傳值
        heat_scores: compute_sector_heat() 的回傳值

    Returns:
        實際新增筆數
    """
    if picks_df.empty:
        return 0

    today_str = date.today().isoformat()
    latest_close = hist.sort_values("date").groupby("code").last()["close"].to_dict()

    added = 0
    with sqlite3.connect(DB_PATH) as conn:
        for _, row in picks_df.iterrows():
            code = str(row["code"])
            fine = industry_data.get(code, {}).get("fine", "")
            heat = heat_scores.get(fine, {}).get("heat") if fine else None
            price = latest_close.get(code)
            name = get_stock_name(code)
            try:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO pool "
                    "(code, name, entry_date, entry_price, fine_group, heat_at_entry) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (code, name, today_str, price, fine or None, heat)
                )
                if cur.rowcount > 0:
                    added += 1
            except Exception as e:
                logger.warning(f"⚠️  {code} 加入 Pool 失敗: {e}")
        conn.commit()

    logger.info(f"✅ Pool 新增 {added} 筆（{today_str}）")
    return added


def get_active_pool() -> pd.DataFrame:
    """
    取得 Pool 中仍有效的紀錄（14 日曆天內），依 entry_date 降序排列

    Returns:
        DataFrame columns: code, name, entry_date, entry_price, fine_group, heat_at_entry
    """
    cutoff = (date.today() - timedelta(days=POOL_DAYS)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT code, name, entry_date, entry_price, fine_group, heat_at_entry "
            "FROM pool WHERE entry_date >= ? ORDER BY entry_date DESC",
            conn, params=(cutoff,)
        )
    return df


def annotate_pool_heat(pool_df: pd.DataFrame, heat_scores: dict) -> pd.DataFrame:
    """
    在 Pool DataFrame 加上目前熱度、Δheat 和狀態標籤

    新增欄位:
        current_heat (float|None): 目前族群熱度
        heat_delta (float|None): current_heat - heat_at_entry
        heat_status (str): "hot" | "cold" | "stable" | "unknown"
        days_held (int): 從 entry_date 到今天的日曆天數

    Args:
        pool_df: get_active_pool() 的回傳值
        heat_scores: compute_sector_heat() 的回傳值

    Returns:
        DataFrame: 加上新欄位後的副本
    """
    if pool_df.empty:
        return pool_df

    df = pool_df.copy()
    today = date.today()

    df["current_heat"] = df["fine_group"].apply(
        lambda f: heat_scores.get(f, {}).get("heat") if f else None
    )
    df["heat_delta"] = df.apply(
        lambda r: (r["current_heat"] - r["heat_at_entry"])
        if pd.notna(r.get("current_heat")) and pd.notna(r.get("heat_at_entry"))
        else None,
        axis=1
    )
    df["heat_status"] = df["heat_delta"].apply(
        lambda d: "hot" if pd.notna(d) and d > 0.15
        else ("cold" if pd.notna(d) and d < -0.10
              else ("stable" if pd.notna(d) else "unknown"))
    )
    df["days_held"] = df["entry_date"].apply(
        lambda s: (today - date.fromisoformat(str(s))).days
    )
    return df
