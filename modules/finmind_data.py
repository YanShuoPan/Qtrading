"""
FinMind 數據模組 - 法人買賣超與融資融券數據
"""
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from .config import FINMIND_API_TOKEN
from .logger import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://api.finmindtrade.com/api/v4/data"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch(dataset: str, params: dict) -> list:
    """
    FinMind API 通用 GET 請求輔助函式

    Args:
        dataset: FinMind dataset 名稱
        params: 其餘查詢參數（例如 data_id, start_date）

    Returns:
        list: API 回傳的 data 陣列；失敗時回傳空 list
    """
    query = {"dataset": dataset, **params}
    if FINMIND_API_TOKEN:
        query["token"] = FINMIND_API_TOKEN

    try:
        resp = requests.get(_BASE_URL, params=query, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") == 200:
            return payload.get("data", [])
        logger.warning(f"FinMind API 狀態碼非 200：{payload.get('status')} ({dataset}, {params})")
        return []
    except requests.exceptions.Timeout:
        logger.error(f"FinMind 請求逾時 ({dataset}, {params})")
        return []
    except requests.exceptions.RequestException as exc:
        logger.error(f"FinMind 請求失敗 ({dataset}, {params}): {exc}")
        return []
    except Exception as exc:
        logger.error(f"FinMind 未預期錯誤 ({dataset}, {params}): {exc}")
        return []


def _aggregate_institutional(group) -> pd.Series:
    """
    對單一日期的法人資料群組進行彙總（向量化）

    Args:
        group: 同一日期的 DataFrame 群組

    Returns:
        pd.Series: foreign_net, trust_net, dealer_net, total_net
    """
    name_col = group["name"].astype(str)
    buy = pd.to_numeric(group.get("buy", 0), errors="coerce").fillna(0)
    sell = pd.to_numeric(group.get("sell", 0), errors="coerce").fillna(0)
    net = buy - sell

    foreign_net = net[name_col.str.contains("Foreign_Investor", na=False)].sum()
    trust_net = net[name_col.str.contains("Investment_Trust", na=False)].sum()
    dealer_net = net[name_col.str.contains("Dealer", na=False)].sum()
    total_net = foreign_net + trust_net + dealer_net

    return pd.Series({
        "foreign_net": foreign_net,
        "trust_net": trust_net,
        "dealer_net": dealer_net,
        "total_net": total_net,
    })


def _fetch_one_institutional(code: str, dataset: str, start_date: str, days: int) -> dict | None:
    """單支股票的法人資料抓取與彙總（供 ThreadPoolExecutor 使用）"""
    raw = _fetch(dataset, {"data_id": str(code), "start_date": start_date})
    if not raw:
        return None

    df = pd.DataFrame(raw)
    if df.empty or "date" not in df.columns:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    unique_dates = df["date"].unique()
    if len(unique_dates) > days:
        cutoff = sorted(unique_dates)[-days]
        df = df[df["date"] >= cutoff]

    daily = df.groupby("date").apply(_aggregate_institutional).reset_index()

    daily = daily.sort_values("date", ascending=False)
    is_buy = (daily["total_net"] > 0).values
    consecutive_buy_days = 0
    for v in is_buy:
        if v:
            consecutive_buy_days += 1
        else:
            break

    agg = daily[["foreign_net", "trust_net", "dealer_net", "total_net"]].sum()

    return {
        "code": code,
        "foreign_net": agg["foreign_net"],
        "trust_net": agg["trust_net"],
        "dealer_net": agg["dealer_net"],
        "total_net": agg["total_net"],
        "consecutive_buy_days": consecutive_buy_days,
    }


def fetch_institutional(codes: list, days: int = 10) -> pd.DataFrame:
    """
    從 FinMind 取得法人買賣超資料，並彙總成每支股票的摘要指標

    Args:
        codes: 股票代碼列表
        days: 回溯天數（預設 10）

    Returns:
        DataFrame: columns=[code, foreign_net, trust_net, dealer_net,
                            total_net, consecutive_buy_days]
                   每支股票一列，彙總 days 天內的累計買賣超
    """
    _cols = ["code", "foreign_net", "trust_net", "dealer_net",
             "total_net", "consecutive_buy_days"]
    if not codes:
        return pd.DataFrame(columns=_cols)

    start_date = (datetime.today() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
    dataset = "TaiwanStockInstitutionalInvestorsBuySell"

    records = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_one_institutional, code, dataset, start_date, days): code
            for code in codes
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                records.append(result)

    result = pd.DataFrame(records, columns=_cols) if records else pd.DataFrame(columns=_cols)
    logger.info(f"fetch_institutional: 取得 {len(result)} 支股票的法人資料")
    return result


def _fetch_one_margin(code: str, dataset: str, start_date: str) -> dict | None:
    """單支股票的融資融券資料抓取與計算（供 ThreadPoolExecutor 使用）"""
    raw = _fetch(dataset, {"data_id": str(code), "start_date": start_date})
    if not raw:
        return None

    df = pd.DataFrame(raw)
    if df.empty or "date" not in df.columns:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for col in [
        "MarginPurchaseTodayBalance",
        "MarginPurchaseLimit",
        "ShortSaleTodayBalance",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

    if len(df) < 2:
        latest = df.iloc[-1]
        margin_balance = float(latest.get("MarginPurchaseTodayBalance", 0))
        short_balance = float(latest.get("ShortSaleTodayBalance", 0))
        limit = float(latest.get("MarginPurchaseLimit", 0))
        margin_utilization = (margin_balance / limit * 100) if limit > 0 else 0.0
        return {
            "code": code,
            "margin_balance": margin_balance,
            "margin_change": 0,
            "margin_change_pct": 0.0,
            "short_balance": short_balance,
            "short_change": 0,
            "margin_utilization": margin_utilization,
            "margin_decreasing_days": 0,
        }

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    margin_balance = float(latest["MarginPurchaseTodayBalance"])
    prev_margin = float(prev["MarginPurchaseTodayBalance"])
    margin_change = margin_balance - prev_margin
    margin_change_pct = (
        (margin_change / prev_margin * 100) if prev_margin != 0 else 0.0
    )

    short_balance = float(latest["ShortSaleTodayBalance"])
    prev_short = float(prev["ShortSaleTodayBalance"])
    short_change = short_balance - prev_short

    limit = float(latest["MarginPurchaseLimit"])
    margin_utilization = (margin_balance / limit * 100) if limit > 0 else 0.0

    margin_decreasing_days = 0
    balances = df["MarginPurchaseTodayBalance"].tolist()
    for i in range(len(balances) - 1, 0, -1):
        if balances[i] < balances[i - 1]:
            margin_decreasing_days += 1
        else:
            break

    return {
        "code": code,
        "margin_balance": margin_balance,
        "margin_change": margin_change,
        "margin_change_pct": round(margin_change_pct, 4),
        "short_balance": short_balance,
        "short_change": short_change,
        "margin_utilization": round(margin_utilization, 4),
        "margin_decreasing_days": margin_decreasing_days,
    }


def fetch_margin(codes: list, days: int = 10) -> pd.DataFrame:
    """
    從 FinMind 取得融資融券資料，並計算各項指標

    Args:
        codes: 股票代碼列表
        days: 回溯天數（預設 10）

    Returns:
        DataFrame: columns=[code, margin_balance, margin_change,
                            margin_change_pct, short_balance, short_change,
                            margin_utilization, margin_decreasing_days]
    """
    _cols = ["code", "margin_balance", "margin_change", "margin_change_pct",
             "short_balance", "short_change", "margin_utilization", "margin_decreasing_days"]
    if not codes:
        return pd.DataFrame(columns=_cols)

    start_date = (datetime.today() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
    dataset = "TaiwanStockMarginPurchaseShortSale"

    records = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_one_margin, code, dataset, start_date): code
            for code in codes
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                records.append(result)

    result = pd.DataFrame(records, columns=_cols) if records else pd.DataFrame(columns=_cols)
    logger.info(f"fetch_margin: 取得 {len(result)} 支股票的融資融券資料")
    return result
