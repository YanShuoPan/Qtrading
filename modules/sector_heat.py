"""
族群熱度模組 (Sector Heat)
計算每個 fine 細分類的族群熱度：同族群中帶量上漲的股票比例

定義：
  - 上漲 = 最新收盤 > MA5（5日移動平均）
  - 帶量 = 最新成交量 > 前5日平均成交量
  - 熱度 = (帶量上漲股數) / (群組中有價格資料的股數)
"""
import json
from pathlib import Path

import pandas as pd

from .logger import get_logger

logger = get_logger(__name__)

INDUSTRY_JSON = Path("backtest/stock_industry.json")
MIN_GROUP_SIZE = 3  # 至少 N 支有資料才計算熱度
MA_WINDOW = 5


def load_industry_data(path: Path = INDUSTRY_JSON) -> dict:
    """
    載入 stock_industry.json

    Returns:
        dict: {code: {"coarse": str, "fine": str, ...}}，失敗回傳 {}
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"⚠️ 找不到產業分類檔: {path}")
        return {}
    except Exception as e:
        logger.warning(f"⚠️ 載入產業分類失敗: {e}")
        return {}


def compute_sector_heat(hist: pd.DataFrame, industry_data: dict) -> dict:
    """
    計算每個 fine 群組的族群熱度

    Args:
        hist: 股價歷史 DataFrame（需有 code, date, close, volume 欄位）
        industry_data: load_industry_data() 的回傳值

    Returns:
        dict: {fine_label: {"heat": float, "active": int, "total": int}}
              只含 total >= MIN_GROUP_SIZE 的群組
    """
    if hist.empty or not industry_data:
        return {}

    try:
        hist = hist.sort_values(["code", "date"]).copy()

        # 向量化計算 MA5 和 5日平均量
        hist["_ma5"] = hist.groupby("code")["close"].transform(
            lambda x: x.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
        )
        hist["_avg_vol5"] = hist.groupby("code")["volume"].transform(
            lambda x: x.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
        )

        # 取每支股票最後一筆（最新交易日）
        latest = hist.groupby("code").last().reset_index()
        latest = latest.dropna(subset=["_ma5", "_avg_vol5"])

        # 判斷帶量上漲
        latest["_active"] = (latest["close"] > latest["_ma5"]) & (latest["volume"] > latest["_avg_vol5"])

        active_map: dict[str, bool] = latest.set_index("code")["_active"].to_dict()

        # 按 fine 群組統計
        fine_data: dict[str, dict] = {}
        for code, info in industry_data.items():
            fine = info.get("fine", "")
            if not fine or code not in active_map:
                continue
            bucket = fine_data.setdefault(fine, {"active": 0, "total": 0})
            bucket["total"] += 1
            if active_map[code]:
                bucket["active"] += 1

        return {
            fine: {
                "heat": d["active"] / d["total"],
                "active": d["active"],
                "total": d["total"],
            }
            for fine, d in fine_data.items()
            if d["total"] >= MIN_GROUP_SIZE
        }

    except Exception as e:
        logger.warning(f"⚠️ 計算族群熱度失敗: {e}")
        return {}


def get_top_sectors(heat_scores: dict, n: int = 3, industry_data: dict = None) -> list:
    """
    取熱度最高的前 N 個 fine 族群

    Args:
        heat_scores: compute_sector_heat() 的回傳值
        n: 取前 N 個
        industry_data: 選填，提供後會附上每個族群的股票代碼清單

    Returns:
        list of dict: [
            {"fine": str, "heat": float, "active": int, "total": int, "codes": list[str]},
            ...
        ]  已按 heat 由高到低排序
    """
    if not heat_scores:
        return []

    fine_to_codes: dict = {}
    if industry_data:
        for code, info in industry_data.items():
            fine = info.get("fine", "")
            if fine:
                fine_to_codes.setdefault(fine, []).append(code)

    ranked = sorted(heat_scores.items(), key=lambda x: x[1]["heat"], reverse=True)[:n]
    return [
        {
            "fine": fine,
            "heat": data["heat"],
            "active": data["active"],
            "total": data["total"],
            "codes": fine_to_codes.get(fine, []),
        }
        for fine, data in ranked
    ]


def annotate_picks(picks_df: pd.DataFrame, heat_scores: dict, industry_data: dict) -> pd.DataFrame:
    """
    在選股 DataFrame 加上族群相關欄位

    新增欄位：
        fine_group   (str)  fine 細分類標籤
        coarse_group (str)  coarse 粗分類標籤
        sector_heat  (float|None) 族群熱度 0.0~1.0，群組太小則 None
        sector_active (int|None)  帶量上漲股數
        sector_total  (int|None)  群組有資料股數

    Args:
        picks_df: pick_stocks() 回傳的 DataFrame
        heat_scores: compute_sector_heat() 的結果
        industry_data: load_industry_data() 的結果

    Returns:
        DataFrame: 加上族群欄位後的副本
    """
    if picks_df.empty:
        return picks_df

    df = picks_df.copy()

    def _info(code: str, field: str) -> str:
        return industry_data.get(str(code), {}).get(field, "")

    def _heat(fine: str, field: str):
        if not fine or fine not in heat_scores:
            return None
        return heat_scores[fine].get(field)

    df["fine_group"] = df["code"].apply(lambda c: _info(c, "fine"))
    df["coarse_group"] = df["code"].apply(lambda c: _info(c, "coarse"))
    df["sector_heat"] = df["fine_group"].apply(lambda f: _heat(f, "heat"))
    df["sector_active"] = df["fine_group"].apply(lambda f: _heat(f, "active"))
    df["sector_total"] = df["fine_group"].apply(lambda f: _heat(f, "total"))

    return df
