"""
延續觀察模組

載入前幾個交易日的推薦股，重新評估是否仍符合策略條件。
"""

import os
import re
from datetime import date

import numpy as np
import pandas as pd

from .logger import get_logger
from .strategies import ensemble_score

logger = get_logger(__name__)


def get_previous_trading_days(data_dir: str, today_date, n: int = 2) -> list[str]:
    """
    掃描 data/ 目錄，回傳最近 n 個交易日的日期字串（不含今天）。

    以實際有產出資料的日期為準，自動跳過週末與假日。
    """
    today_str = str(today_date)
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    try:
        entries = os.listdir(data_dir)
    except FileNotFoundError:
        logger.warning("data 目錄不存在: %s", data_dir)
        return []

    date_dirs = sorted(
        [d for d in entries if date_pattern.match(d) and d != today_str],
        reverse=True,
    )
    return date_dirs[:n]


def parse_picks_from_txt(date_str: str, data_dir: str = "data") -> list[str]:
    """
    從指定日期的 txt 檔案中解析推薦股代碼。

    讀取「有機會噴-前100大交易量能」和「有機會噴-其餘」兩個檔案。
    """
    folder = os.path.join(data_dir, date_str)
    if not os.path.isdir(folder):
        logger.debug("資料夾不存在，跳過: %s", folder)
        return []

    filenames = [
        f"有機會噴-前100大交易量能_{date_str}.txt",
        f"有機會噴-其餘_{date_str}.txt",
    ]

    codes = []
    code_pattern = re.compile(r"^(\d{4})\s")

    for fname in filenames:
        fpath = os.path.join(folder, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    m = code_pattern.match(line.strip())
                    if m:
                        codes.append(m.group(1))
        except Exception as e:
            logger.warning("讀取 %s 失敗: %s", fpath, e)

    # 去重但保持順序
    seen = set()
    unique = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return unique


def evaluate_continuation(
    codes: list[str],
    hist: pd.DataFrame,
    today_codes_to_exclude: set[str],
) -> pd.DataFrame:
    """
    對前幾日推薦的股票重新評估，判斷是否仍符合策略條件。

    判斷邏輯：
    - MA20 位置：近5日開收均價是否仍在 MA20 之上（與 pick_stocks 相同邏輯）
    - Ensemble 評分：RSI / MACD / 布林 / 量能 4 策略投票

    Returns
    -------
    pd.DataFrame
        columns: code, ma20_ok, ensemble_bullish, ensemble_total, ensemble_label, status
    """
    if not codes or hist.empty:
        return pd.DataFrame()

    # 排除今日已選中的股票
    codes_to_eval = [c for c in codes if c not in today_codes_to_exclude]
    if not codes_to_eval:
        return pd.DataFrame()

    results = []

    for code in codes_to_eval:
        stock_hist = hist[hist["code"] == code].sort_values("date")

        if len(stock_hist) < 20:
            logger.debug("延續觀察: %s 資料不足 (%d 筆)，跳過", code, len(stock_hist))
            continue

        # 計算 MA20
        close = stock_hist["close"].values
        ma20 = pd.Series(close).rolling(20, min_periods=20).mean().values

        last_5_idx = slice(-5, None)
        last_5_open = stock_hist["open"].values[last_5_idx]
        last_5_close = stock_hist["close"].values[last_5_idx]
        last_5_ma20 = ma20[last_5_idx]

        # 檢查 MA20 是否有效
        if np.isnan(last_5_ma20).any():
            logger.debug("延續觀察: %s MA20 含 NaN，跳過", code)
            continue

        # 近5日開收均價是否都在 MA20 之上（與 pick_stocks 相同邏輯）
        avg_price_5d = (last_5_open + last_5_close) / 2
        ma20_ok = bool((avg_price_5d > last_5_ma20).all())

        # Ensemble 評分
        score = ensemble_score(stock_hist)
        bullish = score["bullish_count"]
        total = score["total"]
        label = f"{bullish}/{total}"

        status = "仍符合" if ma20_ok else "已轉弱"

        results.append({
            "code": code,
            "ma20_ok": ma20_ok,
            "ensemble_bullish": bullish,
            "ensemble_total": total,
            "ensemble_label": label,
            "status": status,
        })

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results)
