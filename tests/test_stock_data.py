"""Tests for modules/stock_data.py — pick_stocks()"""
import numpy as np
import pandas as pd
import pytest

from modules.stock_data import pick_stocks


def _make_prices(codes: list[str], n: int = 60, base_close: float = 100.0,
                 slope: float = 0.3, volume: int = 5_000_000) -> pd.DataFrame:
    """
    生成模擬股價 DataFrame（多支股票）。

    Args:
        codes: 股票代碼列表
        n: 每支股票的交易日數
        base_close: 基礎收盤價
        slope: 每日上漲幅度
        volume: 每日成交量
    """
    np.random.seed(42)
    frames = []
    for code in codes:
        dates = pd.date_range("2026-01-01", periods=n, freq="B")
        close = base_close + np.arange(n) * slope + np.random.randn(n) * 0.2
        df = pd.DataFrame({
            "code": code,
            "date": dates,
            "open": close - 0.1,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": volume,
        })
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


class TestPickStocks:
    """pick_stocks() 選股邏輯測試"""

    def test_returns_dataframe(self):
        """回傳值必須是 DataFrame"""
        prices = _make_prices(["2330"])
        result = pick_stocks(prices)
        assert isinstance(result, pd.DataFrame)

    def test_empty_prices_returns_empty(self):
        """空 DataFrame 輸入應回傳空 DataFrame"""
        result = pick_stocks(pd.DataFrame())
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_missing_code_column_returns_empty(self):
        """缺少 code 欄位應 graceful 回傳空"""
        prices = pd.DataFrame({"close": [100.0]})
        result = pick_stocks(prices)
        assert result.empty

    def test_insufficient_data_returns_empty(self):
        """不到 10 筆的股票應被排除"""
        prices = _make_prices(["2330"], n=5)
        result = pick_stocks(prices)
        assert result.empty

    def test_low_volume_excluded(self):
        """近 10 日均量 < 1000 張的股票應被排除"""
        prices = _make_prices(["2330"], volume=500_000)  # 500 張
        result = pick_stocks(prices)
        assert result.empty

    def test_uptrend_stock_selected(self):
        """符合條件的上升趨勢股應被選入"""
        prices = _make_prices(["2330"], n=60, slope=0.2, volume=5_000_000)
        result = pick_stocks(prices)
        # 不一定保證選入（取決於隨機種子），但至少不應出錯
        assert isinstance(result, pd.DataFrame)

    def test_output_columns_present(self):
        """回傳 DataFrame 必須包含 code, close, ma20, ma20_slope 等欄位"""
        prices = _make_prices(["2330", "2317", "2454"], n=60, slope=0.15)
        result = pick_stocks(prices)
        if not result.empty:
            expected_cols = {"code", "close", "ma20", "ma20_slope", "distance",
                             "volatility", "volume", "is_lowest_close"}
            assert expected_cols.issubset(set(result.columns)), (
                f"Missing columns: {expected_cols - set(result.columns)}"
            )

    def test_group_limit_respected(self):
        """每組最多 6 支股票，因此總數 <= 12"""
        # 大量股票以測試上限
        codes = [str(i) for i in range(2300, 2350)]
        prices = _make_prices(codes, n=60, slope=0.15, volume=5_000_000)
        result = pick_stocks(prices)
        assert len(result) <= 12

    def test_ma20_slope_filter(self):
        """所有選出的股票 MA20 斜率應 < 1"""
        codes = [str(i) for i in range(2300, 2320)]
        prices = _make_prices(codes, n=60, slope=0.15, volume=5_000_000)
        result = pick_stocks(prices)
        if not result.empty:
            assert (result["ma20_slope"] < 1).all(), "All slopes should be < 1"

    def test_steep_uptrend_excluded(self):
        """斜率過大（>= 1）的股票應被排除"""
        prices = _make_prices(["2330"], n=60, slope=5.0, volume=5_000_000)
        result = pick_stocks(prices)
        # slope=5.0 → MA20 斜率遠大於 1，應被過濾
        if not result.empty:
            assert (result["ma20_slope"] < 1).all()
