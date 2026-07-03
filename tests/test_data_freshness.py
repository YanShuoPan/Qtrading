"""Tests for modules/stock_data.py — filter_fresh_stocks() 與 fetch_prices_yf() 失敗重試"""
import numpy as np
import pandas as pd
import pytest

from modules.stock_data import filter_fresh_stocks


def _make_prices_with_end(code: str, end_date: str, n: int = 30) -> pd.DataFrame:
    """生成單一股票、以 end_date 為最後交易日的模擬股價"""
    dates = pd.bdate_range(end=end_date, periods=n)
    close = 100.0 + np.arange(n) * 0.1
    return pd.DataFrame({
        "code": code,
        "date": dates,
        "open": close - 0.1,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 5_000_000,
    })


class TestFilterFreshStocks:
    """filter_fresh_stocks() 資料時效過濾測試"""

    def test_stale_code_excluded(self):
        """最新日期落後於全體最新交易日的股票應被排除"""
        fresh = _make_prices_with_end("2330", "2026-07-02")
        stale = _make_prices_with_end("8088", "2026-06-17")
        prices = pd.concat([fresh, stale], ignore_index=True)

        result, stale_codes = filter_fresh_stocks(prices)

        assert set(result["code"].unique()) == {"2330"}
        assert stale_codes == ["8088"]

    def test_all_fresh_unchanged(self):
        """全部股票都是最新資料時，不應排除任何股票"""
        a = _make_prices_with_end("2330", "2026-07-02")
        b = _make_prices_with_end("2317", "2026-07-02")
        prices = pd.concat([a, b], ignore_index=True)

        result, stale_codes = filter_fresh_stocks(prices)

        assert len(result) == len(prices)
        assert stale_codes == []

    def test_empty_input(self):
        """空 DataFrame 應回傳空結果且不出錯"""
        result, stale_codes = filter_fresh_stocks(pd.DataFrame())

        assert result.empty
        assert stale_codes == []

    def test_max_lag_days_tolerance(self):
        """max_lag_days 容忍範圍內的股票應保留"""
        fresh = _make_prices_with_end("2330", "2026-07-02")
        lag1 = _make_prices_with_end("2317", "2026-07-01")   # 落後 1 天
        stale = _make_prices_with_end("8088", "2026-06-17")  # 落後 15 天
        prices = pd.concat([fresh, lag1, stale], ignore_index=True)

        result, stale_codes = filter_fresh_stocks(prices, max_lag_days=1)

        assert set(result["code"].unique()) == {"2330", "2317"}
        assert stale_codes == ["8088"]

    def test_stale_codes_sorted(self):
        """回傳的過舊代碼清單應排序，方便 log 閱讀"""
        fresh = _make_prices_with_end("2330", "2026-07-02")
        s1 = _make_prices_with_end("9962", "2026-06-17")
        s2 = _make_prices_with_end("8088", "2026-06-17")
        prices = pd.concat([fresh, s1, s2], ignore_index=True)

        _, stale_codes = filter_fresh_stocks(prices)

        assert stale_codes == ["8088", "9962"]


# ===== fetch_prices_yf 失敗重試 =====

def _fake_yf_frame(codes: list[str], suffix: str, end_date: str = "2026-07-02",
                   n: int = 10) -> pd.DataFrame:
    """模擬 yf.download(group_by='ticker') 的多層欄位回傳格式"""
    dates = pd.bdate_range(end=end_date, periods=n)
    tickers = [f"{c}{suffix}" for c in codes]
    cols = pd.MultiIndex.from_product(
        [tickers, ["Open", "High", "Low", "Close", "Volume"]]
    )
    df = pd.DataFrame(index=dates, columns=cols, dtype=float)
    for t in tickers:
        close = 100.0 + np.arange(n) * 0.1
        df[(t, "Open")] = close - 0.1
        df[(t, "High")] = close + 1.0
        df[(t, "Low")] = close - 1.0
        df[(t, "Close")] = close
        df[(t, "Volume")] = 1_000_000
    return df


class TestFetchRetry:
    """fetch_prices_yf() 對下載失敗股票的小批次重試"""

    @pytest.fixture(autouse=True)
    def _no_sleep_no_db(self, monkeypatch):
        monkeypatch.setattr("modules.stock_data.time.sleep", lambda s: None)
        monkeypatch.setattr("modules.stock_data.get_existing_data_range", lambda: {})

    def test_failed_codes_retried_and_recovered(self, monkeypatch):
        """主批次失敗的股票應被重試並補回結果"""
        from modules.stock_data import fetch_prices_yf

        calls = {"n": 0}

        def fake_download(tickers, **kwargs):
            calls["n"] += 1
            ticker_list = tickers.split()
            codes = [t.split(".")[0] for t in ticker_list]
            suffix = "." + ticker_list[0].split(".")[1]
            if calls["n"] <= 2:
                # 主批次 .TW 與 .TWO 兩個 pass 都失敗（模擬限流）
                return pd.DataFrame()
            # 重試時成功
            return _fake_yf_frame(codes, suffix)

        monkeypatch.setattr("modules.stock_data.yf.download", fake_download)

        result = fetch_prices_yf(["2330", "2317"])

        assert not result.empty
        assert set(result["code"].unique()) == {"2330", "2317"}
        assert calls["n"] > 2, "應該有重試的下載呼叫"

    def test_no_retry_when_all_succeed(self, monkeypatch):
        """主批次全部成功時，不應觸發重試"""
        from modules.stock_data import fetch_prices_yf

        calls = {"n": 0}

        def fake_download(tickers, **kwargs):
            calls["n"] += 1
            ticker_list = tickers.split()
            codes = [t.split(".")[0] for t in ticker_list]
            suffix = "." + ticker_list[0].split(".")[1]
            return _fake_yf_frame(codes, suffix)

        monkeypatch.setattr("modules.stock_data.yf.download", fake_download)

        result = fetch_prices_yf(["2330", "2317"])

        assert set(result["code"].unique()) == {"2330", "2317"}
        assert calls["n"] == 1, "全部成功時只該有主批次一次 .TW 下載"

    def test_still_failing_after_retry_returns_partial(self, monkeypatch):
        """重試後仍失敗的股票應被略過，回傳其餘成功的資料"""
        from modules.stock_data import fetch_prices_yf

        def fake_download(tickers, **kwargs):
            ticker_list = tickers.split()
            codes = [t.split(".")[0] for t in ticker_list]
            suffix = "." + ticker_list[0].split(".")[1]
            # 8088 永遠失敗
            ok_codes = [c for c in codes if c != "8088"]
            if not ok_codes:
                return pd.DataFrame()
            return _fake_yf_frame(ok_codes, suffix)

        monkeypatch.setattr("modules.stock_data.yf.download", fake_download)

        result = fetch_prices_yf(["2330", "8088"])

        assert set(result["code"].unique()) == {"2330"}
