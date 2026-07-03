"""
圖表資料產生模組 - 為互動 K 線圖產生每支股票的 JSON（含四色指標）

四色定義（N=20）：
  close >= ma20 且 volume >  vma20 → red    帶量翻紅
  close <  ma20 且 volume >  vma20 → green  帶量翻黑
  close >= ma20 且 volume <= vma20 → yellow 偏強、量未確認
  close <  ma20 且 volume <= vma20 → blue   偏弱、量未確認
  MA 暖身期                         → gray   無訊號
"""
import json
import os
import shutil
import sqlite3

import numpy as np
import pandas as pd

from .config import DB_PATH
from .logger import get_logger
from .stock_codes import get_stock_name

logger = get_logger(__name__)

MA_PERIOD = 20
DAYS_TO_EXPORT = 140  # 20 天 MA 暖身 + 約 120 根顯示


def compute_four_color(df: pd.DataFrame, n: int = MA_PERIOD) -> pd.DataFrame:
    """計算 N 日均價/均量與四色指標

    Args:
        df: 需含 close、volume 欄位，依日期由舊到新排序
        n: 均價/均量週期

    Returns:
        pd.DataFrame: 原欄位 + ma20 / vma20 / color 的複本
    """
    out = df.copy()
    out["ma20"] = out["close"].rolling(n, min_periods=n).mean()
    out["vma20"] = out["volume"].rolling(n, min_periods=n).mean()

    strong = out["close"] >= out["ma20"]
    heavy = out["volume"] > out["vma20"]
    warmup = out["ma20"].isna() | out["vma20"].isna()

    out["color"] = np.select(
        [warmup, strong & heavy, ~strong & heavy, strong],
        ["gray", "red", "green", "yellow"],
        default="blue",
    )
    return out


def generate_chart_data(output_dir: str = "docs", db_path: str = None) -> int:
    """為資料庫中全部股票產生互動圖 JSON，並複製 chart.html 到 output_dir

    單股失敗時跳過並繼續（永不中斷 pipeline）。

    Returns:
        int: 成功產生的股票數
    """
    db_path = db_path or DB_PATH
    chart_dir = os.path.join(output_dir, "chart_data")
    os.makedirs(chart_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        prices = pd.read_sql_query(
            "SELECT code, date, open, high, low, close, volume "
            "FROM prices ORDER BY code, date",
            conn,
        )

    ok, fail = 0, 0
    for code, g in prices.groupby("code"):
        try:
            g = g.tail(DAYS_TO_EXPORT).reset_index(drop=True)
            g["volume"] = (g["volume"] // 1000).astype(int)  # 股 → 張
            g = compute_four_color(g)
            days = [
                [
                    r.date, r.open, r.high, r.low, r.close, int(r.volume),
                    None if pd.isna(r.ma20) else round(float(r.ma20), 2),
                    None if pd.isna(r.vma20) else int(round(float(r.vma20))),
                    r.color,
                ]
                for r in g.itertuples()
            ]
            payload = {
                "code": code,
                "name": get_stock_name(code),
                "updated": g["date"].iloc[-1],
                "days": days,
            }
            with open(os.path.join(chart_dir, f"{code}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            ok += 1
        except Exception as e:
            logger.debug(f"{code} 圖表資料產生失敗: {e}")
            fail += 1

    src = os.path.join(os.path.dirname(__file__), "..", "static", "chart.html")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(output_dir, "chart.html"))
    else:
        logger.warning("⚠️ static/chart.html 不存在，略過複製")

    logger.info(f"✅ 圖表資料完成: {ok} 支成功, {fail} 支失敗")
    return ok
