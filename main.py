import os
import requests
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf


# === Environment ===
import os, json

sa_file = os.environ.get("GDRIVE_SERVICE_ACCOUNT_FILE")
if sa_file and os.path.exists(sa_file):
    with open(sa_file) as f:
        sa_json = json.load(f)
else:
    # 從 GitHub Actions 環境變數讀整個 JSON（線上）
    sa_json = json.loads(os.environ["GDRIVE_SERVICE_ACCOUNT"])
from dotenv import load_dotenv
load_dotenv()
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

# Google Drive sync is handled by GitHub Actions (rclone). We just read/write under ./data
DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "taiex.sqlite")

# Seed codes (you can replace with a dynamic list later)
CODES = os.environ.get("TWSE_CODES", "2330,2317,2303,2454,2603,2615,2881,2882,2886,1101").split(",")
PICKS_TOP_K = int(os.environ.get("TOP_K", "10"))


def line_push_text(msg: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    body = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()


def ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices(
                code TEXT,
                date TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER,
                PRIMARY KEY(code, date)
            )
            """
        )
        conn.commit()


def fetch_prices_yf(codes, lookback_days=240) -> pd.DataFrame:
    tickers = [f"{c.strip()}.TW" for c in codes if c.strip()]
    if not tickers:
        return pd.DataFrame()

    start = (datetime.utcnow() - timedelta(days=lookback_days * 2)).date().isoformat()
    df = yf.download(
        tickers=" ".join(tickers),
        start=start,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
    )
    out = []
    for c in codes:
        c = c.strip()
        if not c:
            continue
        t = f"{c}.TW"
        if isinstance(df, pd.DataFrame) and t in df:
            tmp = df[t].reset_index().rename(columns=str.lower)
            # yfinance sometimes returns timezone-aware pandas Timestamps for 'Date'
            if "date" in tmp.columns:
                tmp["date"] = pd.to_datetime(tmp["date"]).dt.tz_localize(None)
            tmp["code"] = c
            out.append(tmp[["code", "date", "open", "high", "low", "close", "volume"]])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def upsert_prices(df: pd.DataFrame):
    if df.empty:
        return
    # Normalize date to ISO string (YYYY-MM-DD)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    with sqlite3.connect(DB_PATH) as conn:
        # create temp table then merge to handle upsert
        df.to_sql("_prices_in", conn, if_exists="replace", index=False)
        conn.execute("DELETE FROM prices WHERE (code, date) IN (SELECT code, date FROM _prices_in)")
        conn.execute(
            """
            INSERT INTO prices(code, date, open, high, low, close, volume)
            SELECT code, date, open, high, low, close, volume FROM _prices_in
            """
        )
        conn.execute("DROP TABLE _prices_in")
        conn.commit()


def load_recent_prices(days=240) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT code, date, open, high, low, close, volume FROM prices",
            conn,
            parse_dates=["date"],
        )
    cutoff = datetime.utcnow() - timedelta(days=days)
    return df[df["date"] >= cutoff]


def pick_stocks(prices: pd.DataFrame, top_k=10) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    prices = prices.sort_values(["code", "date"])

    def add_feat(g):
        g = g.copy()
        g["ma50"] = g["close"].rolling(50, min_periods=50).mean()
        g["ret20"] = g["close"] / g["close"].shift(20) - 1.0
        g["vol5"] = g["volume"].rolling(5, min_periods=5).mean()
        return g

    feat = prices.groupby("code", group_keys=False).apply(add_feat)
    latest = feat.groupby("code").tail(1).dropna(subset=["ma50", "ret20", "vol5"])

    filt = latest[
        (latest["close"] > latest["ma50"])
        & (latest["ret20"] > 0)
        & (latest["vol5"] > 5_000_000)
    ]
    return (
        filt.sort_values("ret20", ascending=False)
        .head(top_k)[["code", "close", "ret20", "vol5"]]
        .reset_index(drop=True)
    )


def main():
    ensure_db()

    # 1) Update prices
    df_new = fetch_prices_yf(CODES, lookback_days=240)
    upsert_prices(df_new)

    # 2) Load and pick
    hist = load_recent_prices(days=240)
    picks = pick_stocks(hist, top_k=PICKS_TOP_K)

    # 3) Compose message
    today_tpe = datetime.now(timezone(timedelta(hours=8))).date()
    if picks.empty:
        msg = f"📉 {today_tpe} 今日無符合條件之台股推薦。"
    else:
        lines = [f"📈 今日台股推薦 {today_tpe}"]
        for i, r in picks.iterrows():
            lines.append(f"{i+1}. {r.code} 收盤 {r.close:.2f}  動能20日 {r.ret20:.1%}")
        msg = "\n".join(lines)

    # 4) Send via LINE Messaging API push
    line_push_text(msg)


if __name__ == "__main__":
    main()
