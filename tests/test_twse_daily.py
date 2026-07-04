"""Tests for modules/twse_daily.py — TWSE/TPEx 官方 API 當日行情備援"""
from datetime import date

import pandas as pd
import pytest

from modules.twse_daily import (
    _parse_twse_mi_index,
    _parse_tpex_quotes,
    fetch_official_daily,
)

TRADE_DATE = date(2026, 7, 2)


def _twse_payload() -> dict:
    """模擬 TWSE MI_INDEX (rwd JSON) 回應"""
    return {
        "stat": "OK",
        "date": "20260702",
        "tables": [
            {
                "title": "價格指數(臺灣證券交易所)",
                "fields": ["指數", "收盤指數", "漲跌(+/-)"],
                "data": [["發行量加權股價指數", "23,000.00", "+"]],
            },
            {
                "title": "每日收盤行情(全部(不含權證、牛熊證))",
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
                           "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差",
                           "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"],
                "data": [
                    ["2330", "台積電", "33,241,633", "55,558", "36,079,251,626",
                     "1,085.00", "1,090.00", "1,080.00", "1,085.00", "+", "5.00",
                     "1,085.00", "1,262", "1,090.00", "2,657", "28.32"],
                    ["8110", "華東", "5,123,000", "3,210", "300,000,000",
                     "58.10", "59.00", "57.80", "58.90", "+", "0.80",
                     "58.80", "10", "58.90", "20", "15.00"],
                    # 無成交的股票：價格欄位為 "--"，應被略過
                    ["9999", "測試", "0", "0", "0",
                     "--", "--", "--", "--", " ", "0.00",
                     "10.00", "1", "10.50", "1", "0.00"],
                ],
            },
        ],
    }


def _tpex_payload() -> list:
    """模擬 TPEx mainboard_daily_close_quotes 回應（ROC 日期）"""
    return [
        {
            "Date": "1150702",  # 民國 115 年 = 2026
            "SecuritiesCompanyCode": "8088",
            "CompanyName": "品安",
            "Close": "69.50",
            "Change": "1.20",
            "Open": "68.00",
            "High": "69.90",
            "Low": "67.80",
            "Average": "68.90",
            "TradingShares": "1,234,567",
            "TransactionAmount": "85,000,000",
            "TransactionNumber": "800",
        },
        {
            # 無成交：價格為空字串，應被略過
            "Date": "1150702",
            "SecuritiesCompanyCode": "9998",
            "CompanyName": "測試",
            "Close": "",
            "Change": "",
            "Open": "--",
            "High": "--",
            "Low": "--",
            "Average": "",
            "TradingShares": "0",
            "TransactionAmount": "0",
            "TransactionNumber": "0",
        },
    ]


class TestParseTwse:
    """TWSE MI_INDEX 解析"""

    def test_parses_normal_rows(self):
        df = _parse_twse_mi_index(_twse_payload(), TRADE_DATE)

        assert set(df["code"]) == {"2330", "8110"}
        row = df[df["code"] == "2330"].iloc[0]
        assert row["open"] == 1085.0
        assert row["high"] == 1090.0
        assert row["low"] == 1080.0
        assert row["close"] == 1085.0
        assert row["volume"] == 33_241_633
        assert row["date"] == "2026-07-02"

    def test_skips_no_trade_rows(self):
        """價格為 '--' 的無成交股票應被略過"""
        df = _parse_twse_mi_index(_twse_payload(), TRADE_DATE)
        assert "9999" not in set(df["code"])

    def test_not_ok_returns_empty(self):
        """非交易日（stat != OK）應回傳空 DataFrame"""
        df = _parse_twse_mi_index({"stat": "很抱歉，沒有符合條件的資料!"}, TRADE_DATE)
        assert df.empty

    def test_short_row_does_not_abort_parse(self):
        """欄位數不足的異常列（如小計列）應被跳過，不得讓整表解析中斷"""
        payload = _twse_payload()
        # 在正常列之間插入一筆只有 3 欄的短列
        payload["tables"][1]["data"].insert(1, ["小計", "合計", "38,364,633"])
        df = _parse_twse_mi_index(payload, TRADE_DATE)
        assert set(df["code"]) == {"2330", "8110"}  # 正常列全數保留


class TestParseTpex:
    """TPEx 上櫃行情解析"""

    def test_parses_normal_rows(self):
        df = _parse_tpex_quotes(_tpex_payload(), TRADE_DATE)

        assert set(df["code"]) == {"8088"}
        row = df.iloc[0]
        assert row["open"] == 68.0
        assert row["close"] == 69.5
        assert row["volume"] == 1_234_567
        assert row["date"] == "2026-07-02"

    def test_date_mismatch_returns_empty(self):
        """回應日期與預期交易日不符（假日拿到舊資料）應回傳空，避免寫入錯誤日期"""
        df = _parse_tpex_quotes(_tpex_payload(), date(2026, 7, 3))
        assert df.empty

    def test_empty_payload_returns_empty(self):
        df = _parse_tpex_quotes([], TRADE_DATE)
        assert df.empty


class TestFetchOfficialDaily:
    """fetch_official_daily() 整合行為（mock HTTP）"""

    @pytest.fixture()
    def _mock_http(self, monkeypatch):
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                pass

        def fake_get(url, **kwargs):
            if "twse.com.tw" in url:
                return FakeResponse(_twse_payload())
            return FakeResponse(_tpex_payload())

        monkeypatch.setattr("modules.twse_daily.requests.get", fake_get)

    def test_combines_twse_and_tpex(self, _mock_http):
        df = fetch_official_daily(TRADE_DATE)
        assert set(df["code"]) == {"2330", "8110", "8088"}
        assert set(df.columns) == {"code", "date", "open", "high", "low", "close", "volume"}

    def test_filters_by_codes(self, _mock_http):
        df = fetch_official_daily(TRADE_DATE, codes=["8088", "8110"])
        assert set(df["code"]) == {"8088", "8110"}

    def test_http_failure_returns_empty(self, monkeypatch):
        """API 失敗時應回傳空 DataFrame，不可中斷 pipeline"""
        def boom(url, **kwargs):
            raise ConnectionError("network down")

        monkeypatch.setattr("modules.twse_daily.requests.get", boom)

        df = fetch_official_daily(TRADE_DATE)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
