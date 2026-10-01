"""
加權指數(^TWII)日K：yfinance 抓完整歷史，最近幾個月再用證交所官方資料補缺漏、覆蓋。

Yahoo 偶爾會漏掉整天（例如 2026-09-22），證交所 MI_5MINS_HIST 是官方來源；
2025/01~2026/09 抽查 420 個交易日，除了漏掉的那天，收盤價兩邊完全一致，
所以只需要補最近幾個月，不必整段歷史都改抓證交所。
"""

import time
from datetime import date

import pandas as pd
import requests
import yfinance as yf

TWSE_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
TWSE_PATCH_MONTHS = 2   # 本月＋上月（月初時最新幾天可能落在上個月）


def _twse_month(month_start: pd.Timestamp) -> pd.DataFrame:
    resp = requests.get(TWSE_URL, params={"date": month_start.strftime("%Y%m%d"), "response": "json"}, timeout=30)
    resp.raise_for_status()
    rows = []
    for d, o, h, l, c in resp.json().get("data", []):
        y, m, dd = d.split("/")
        rows.append({"Date": pd.Timestamp(int(y) + 1911, int(m), int(dd)),
                     **{k: float(v.replace(",", "")) for k, v in zip(["Open", "High", "Low", "Close"], [o, h, l, c])}})
    return pd.DataFrame(rows)


def load_twii(start: str, end: str) -> pd.DataFrame:
    """回傳欄位 Date/Open/High/Low/Close，依日期排序。"""
    df = yf.download("^TWII", start=start, end=end, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.reset_index()[["Date", "Open", "High", "Low", "Close"]]
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)

    months = pd.date_range(end=pd.Timestamp(date.today()).replace(day=1), periods=TWSE_PATCH_MONTHS, freq="MS")
    patches = []
    for i, m in enumerate(months):
        try:
            patches.append(_twse_month(m))
        except Exception as e:  # 證交所失敗就退回純 Yahoo 資料，不中斷回測
            print(f"⚠️ 證交所 {m:%Y-%m} 資料抓取失敗，沿用 Yahoo: {e}")
        if i < len(months) - 1:
            time.sleep(3)
    if patches:
        tw = pd.concat(patches)
        tw = tw[(tw["Date"] >= start) & (tw["Date"] < end)]
        added = sorted(set(tw["Date"]) - set(df["Date"]))
        df = pd.concat([df[~df["Date"].isin(tw["Date"])], tw])
        if added:
            print(f"📌 Yahoo 缺漏、已用證交所補上: {[d.strftime('%Y-%m-%d') for d in added]}")
    return df.sort_values("Date").reset_index(drop=True)
