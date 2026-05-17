"""
基本面模組 - 從 TWSE OpenAPI 抓取本益比、殖利率、股價淨值比

API 端點: https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL
- 免費，無需 API key，一次回傳所有上市股票
- 欄位: Code, PEratio, DividendYield, PBratio
"""

import requests
import pandas as pd

from .logger import get_logger

logger = get_logger(__name__)

TWSE_FUNDAMENTALS_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _to_float(val) -> float | None:
    """
    安全地將值轉換為 float。

    - None、""、"-" 回傳 None
    - 移除逗號後嘗試轉換
    - 發生任何錯誤回傳 None
    """
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-"):
        return None
    # 移除千分位逗號
    s = s.replace(",", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def fetch_fundamentals() -> pd.DataFrame:
    """
    從 TWSE OpenAPI 抓取所有上市股票的基本面數據。

    Returns:
        DataFrame，欄位為 [code, pe_ratio, dividend_yield, pb_ratio]。
        若抓取失敗則回傳空 DataFrame（含正確欄位）。
    """
    empty = pd.DataFrame(columns=["code", "pe_ratio", "dividend_yield", "pb_ratio"])

    try:
        resp = requests.get(TWSE_FUNDAMENTALS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning(f"TWSE 基本面 API 請求失敗: {e}")
        return empty
    except ValueError as e:
        logger.warning(f"TWSE 基本面 API 回應非合法 JSON: {e}")
        return empty

    if not isinstance(data, list) or len(data) == 0:
        logger.warning("TWSE 基本面 API 回傳空資料或非預期格式")
        return empty

    rows = []
    for item in data:
        code = str(item.get("Code", "")).strip()
        if not code:
            continue
        rows.append({
            "code": code,
            "pe_ratio": _to_float(item.get("PEratio")),
            "dividend_yield": _to_float(item.get("DividendYield")),
            "pb_ratio": _to_float(item.get("PBratio")),
        })

    if not rows:
        logger.warning("TWSE 基本面 API 回應無可用資料列")
        return empty

    df = pd.DataFrame(rows)
    logger.info(f"TWSE 基本面：成功取得 {len(df)} 支股票資料")
    return df


def filter_by_fundamentals(
    picks_df: pd.DataFrame,
    fundamentals_df: pd.DataFrame,
    max_pe: float = 50.0,
    min_pe: float = 0.0,
) -> pd.DataFrame:
    """
    根據基本面過濾選股結果，移除本益比不符合條件的股票。

    過濾條件（同時滿足才移除）：
    - P/E <= min_pe：虧損或本益比為零（預設 0.0）
    - P/E > max_pe：本益比過高（預設 50.0）

    無 P/E 資料的股票視為通過過濾（不予懲罰）。

    Args:
        picks_df: 選股結果，需含 "code" 欄位
        fundamentals_df: fetch_fundamentals() 的回傳值
        max_pe: P/E 上限，超過此值視為估值過高
        min_pe: P/E 下限，低於或等於此值視為虧損/無效

    Returns:
        過濾後的 DataFrame，保留原有欄位並新增 pe_ratio、dividend_yield、pb_ratio。
    """
    if picks_df.empty:
        logger.info("選股結果為空，跳過基本面過濾")
        # 回傳含基本面欄位的空 DataFrame
        result = picks_df.copy()
        for col in ["pe_ratio", "dividend_yield", "pb_ratio"]:
            if col not in result.columns:
                result[col] = None
        return result

    # 合併基本面資料
    if fundamentals_df.empty:
        logger.warning("基本面資料為空，跳過過濾，所有股票保留")
        result = picks_df.copy()
        for col in ["pe_ratio", "dividend_yield", "pb_ratio"]:
            result[col] = None
        return result

    merged = picks_df.merge(
        fundamentals_df[["code", "pe_ratio", "dividend_yield", "pb_ratio"]],
        on="code",
        how="left",
    )

    # 判斷需要移除的股票（有 P/E 且不在合理範圍內）
    has_pe = merged["pe_ratio"].notna()
    too_low = merged["pe_ratio"] <= min_pe
    too_high = merged["pe_ratio"] > max_pe
    to_remove = has_pe & (too_low | too_high)

    removed = merged[to_remove]
    if not removed.empty:
        for _, row in removed.iterrows():
            reason = (
                f"P/E={row['pe_ratio']:.2f} <= {min_pe}（虧損）"
                if row["pe_ratio"] <= min_pe
                else f"P/E={row['pe_ratio']:.2f} > {max_pe}（估值過高）"
            )
            logger.info(f"移除 {row['code']}：{reason}")

    filtered = merged[~to_remove].reset_index(drop=True)
    logger.info(
        f"基本面過濾：{len(picks_df)} 支 → {len(filtered)} 支"
        f"（移除 {to_remove.sum()} 支）"
    )
    return filtered
