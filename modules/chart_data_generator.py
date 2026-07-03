"""
圖表資料產生模組 - 為互動 K 線圖產生每支股票的 JSON（含四色指標）

四色定義（N=20）：
  close >= ma20 且 volume >  vma20 → red    帶量翻紅
  close <  ma20 且 volume >  vma20 → green  帶量翻黑
  close >= ma20 且 volume <= vma20 → yellow 偏強、量未確認
  close <  ma20 且 volume <= vma20 → blue   偏弱、量未確認
  MA 暖身期                         → gray   無訊號
"""
import numpy as np
import pandas as pd

from .logger import get_logger

logger = get_logger(__name__)

MA_PERIOD = 20


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
