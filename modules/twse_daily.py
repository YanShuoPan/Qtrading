"""
TWSE/TPEx 官方 API 當日行情備援模組

當 yfinance 批次下載（含重試）後仍有股票缺當日資料時，
用官方 OpenAPI 以少量 request 補回全市場當日 OHLCV：
- 上市：TWSE MI_INDEX（帶日期參數，自帶交易日驗證）
- 上櫃：TPEx mainboard daily close quotes（以回應中的民國日期驗證）
"""
from datetime import date

import pandas as pd
import requests

from .logger import get_logger

logger = get_logger(__name__)

TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_QUOTES_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
REQUEST_TIMEOUT = 30  # 秒
# TPEx 不帶 User-Agent 會提前斷線（Response ended prematurely）
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_COLUMNS = ["code", "date", "open", "high", "low", "close", "volume"]
_EMPTY = pd.DataFrame(columns=_COLUMNS)


def _parse_number(value) -> float:
    """解析官方 API 的數字字串（千分位逗號、'--'/空字串視為無值）"""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s or s in ("--", "-", "---"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _roc_to_iso(value) -> str:
    """民國日期字串轉 ISO（支援 '1150702' 與 '115/07/02'；已是西元則原樣正規化）"""
    if value is None:
        return ""
    s = str(value).strip().replace("/", "").replace("-", "")
    if not s.isdigit():
        return ""
    if len(s) == 7:  # 民國 yyymmdd
        year = int(s[:3]) + 1911
        return f"{year:04d}-{s[3:5]}-{s[5:7]}"
    if len(s) == 8:  # 西元 yyyymmdd
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return ""


def _parse_twse_mi_index(payload: dict, trade_date: date) -> pd.DataFrame:
    """
    解析 TWSE MI_INDEX 回應，取出全部上市股票的當日 OHLCV

    Args:
        payload: MI_INDEX JSON（rwd 版 tables 格式，兼容舊版 fields9/data9）
        trade_date: 預期交易日（請求參數即此日期）

    Returns:
        DataFrame: code/date/open/high/low/close/volume；非交易日回傳空
    """
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return _EMPTY.copy()

    # rwd 版：tables 裡找出含「證券代號」欄位的那張表；舊版：fields9/data9
    candidates = [(t.get("fields"), t.get("data")) for t in payload.get("tables", [])]
    candidates.append((payload.get("fields9"), payload.get("data9")))

    for fields, data in candidates:
        if not fields or not data or "證券代號" not in fields:
            continue
        idx = {name: fields.index(name)
               for name in ("證券代號", "成交股數", "開盤價", "最高價", "最低價", "收盤價")
               if name in fields}
        if len(idx) < 6:
            continue

        rows = []
        max_idx = max(idx.values())
        short_rows = 0
        for r in data:
            if len(r) <= max_idx:  # 欄位數不足的異常列（如小計列），跳過以免整表解析中斷
                short_rows += 1
                continue
            ohlc = [_parse_number(r[idx[k]]) for k in ("開盤價", "最高價", "最低價", "收盤價")]
            if any(v is None for v in ohlc):
                continue  # 無成交
            volume = _parse_number(r[idx["成交股數"]])
            rows.append({
                "code": str(r[idx["證券代號"]]).strip(),
                "date": trade_date.isoformat(),
                "open": ohlc[0], "high": ohlc[1], "low": ohlc[2], "close": ohlc[3],
                "volume": int(volume) if volume is not None else 0,
            })
        if short_rows:
            logger.debug(f"TWSE 解析跳過 {short_rows} 筆欄位數不足的列")
        if rows:
            return pd.DataFrame(rows, columns=_COLUMNS)

    return _EMPTY.copy()


def _parse_tpex_quotes(payload: list, trade_date: date) -> pd.DataFrame:
    """
    解析 TPEx 上櫃當日行情回應

    回應中的 Date（民國格式）必須等於預期交易日，
    否則視為假日拿到舊資料，回傳空以避免寫入錯誤日期。
    """
    if not isinstance(payload, list) or not payload:
        return _EMPTY.copy()

    expected_iso = trade_date.isoformat()
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if _roc_to_iso(item.get("Date")) != expected_iso:
            continue
        ohlc = [_parse_number(item.get(k)) for k in ("Open", "High", "Low", "Close")]
        if any(v is None for v in ohlc):
            continue  # 無成交
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not code:
            continue
        volume = _parse_number(item.get("TradingShares"))
        rows.append({
            "code": code,
            "date": expected_iso,
            "open": ohlc[0], "high": ohlc[1], "low": ohlc[2], "close": ohlc[3],
            "volume": int(volume) if volume is not None else 0,
        })

    if not rows:
        return _EMPTY.copy()
    return pd.DataFrame(rows, columns=_COLUMNS)


def fetch_official_daily(trade_date: date, codes: list = None) -> pd.DataFrame:
    """
    從 TWSE + TPEx 官方 API 取得指定交易日的全市場 OHLCV

    Args:
        trade_date: 交易日（非交易日會回傳空）
        codes: 若提供，只保留這些股票代碼

    Returns:
        DataFrame: code/date/open/high/low/close/volume；任一來源失敗則略過該來源
    """
    frames = []

    try:
        resp = requests.get(
            TWSE_MI_INDEX_URL,
            params={"response": "json", "date": trade_date.strftime("%Y%m%d"), "type": "ALLBUT0999"},
            timeout=REQUEST_TIMEOUT,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        twse_df = _parse_twse_mi_index(resp.json(), trade_date)
        if not twse_df.empty:
            frames.append(twse_df)
        logger.debug(f"TWSE MI_INDEX: {len(twse_df)} 支上市股票")
    except Exception as e:
        logger.warning(f"⚠️  TWSE 官方 API 取得失敗: {e}")

    try:
        resp = requests.get(TPEX_QUOTES_URL, timeout=REQUEST_TIMEOUT, headers=_HEADERS)
        resp.raise_for_status()
        tpex_df = _parse_tpex_quotes(resp.json(), trade_date)
        if not tpex_df.empty:
            frames.append(tpex_df)
        logger.debug(f"TPEx 上櫃行情: {len(tpex_df)} 支上櫃股票")
    except Exception as e:
        logger.warning(f"⚠️  TPEx 官方 API 取得失敗: {e}")

    if not frames:
        return _EMPTY.copy()

    result = pd.concat(frames, ignore_index=True)
    if codes is not None:
        result = result[result["code"].isin(set(codes))].reset_index(drop=True)
    return result
