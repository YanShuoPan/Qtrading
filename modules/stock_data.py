"""
股票數據處理模組 - 下載股價數據和選股邏輯
"""
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from .database import get_existing_data_range
from .logger import get_logger

logger = get_logger(__name__)


def fetch_prices_yf(codes, lookback_days=120) -> pd.DataFrame:
    """
    從 Yahoo Finance 下載股價數據

    Args:
        codes: 股票代碼列表
        lookback_days: 回溯天數

    Returns:
        DataFrame: 包含股價數據的 DataFrame
    """
    existing = get_existing_data_range()
    target_start = (datetime.utcnow() - timedelta(days=lookback_days * 2)).date().isoformat()

    codes_to_fetch = []
    for c in codes:
        c = c.strip()
        if not c:
            continue
        if c not in existing:
            codes_to_fetch.append(c)
            logger.info(f"{c}: 無歷史資料，需下載")
        else:
            max_date = existing[c]["max"]
            if max_date < datetime.utcnow().date().isoformat():
                codes_to_fetch.append(c)
                logger.info(f"{c}: 資料過舊 (最新: {max_date})，需更新")
            else:
                logger.debug(f"{c}: 資料已是最新 (最新: {max_date})")

    if not codes_to_fetch:
        logger.info("所有股票資料都已是最新，無需下載")
        return pd.DataFrame()

    tickers = [f"{c}.TW" for c in codes_to_fetch]
    logger.info(f"\n開始下載 {len(codes_to_fetch)} 支股票")
    logger.info(f"期間: {target_start} ~ 今日")

    df = yf.download(
        tickers=" ".join(tickers),
        start=target_start,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
    )
    out = []
    for c in codes_to_fetch:
        t = f"{c}.TW"
        if isinstance(df, pd.DataFrame) and t in df:
            tmp = df[t].reset_index().rename(columns=str.lower)
            if "date" in tmp.columns:
                tmp["date"] = pd.to_datetime(tmp["date"]).dt.tz_localize(None)
            tmp["code"] = c
            out.append(tmp[["code", "date", "open", "high", "low", "close", "volume"]])
    result = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    logger.info(f"成功下載 {len(result)} 筆數據")
    return result


def pick_stocks(prices: pd.DataFrame, top_k=30) -> pd.DataFrame:
    """
    動能選股策略 - 選出符合條件的股票

    策略說明:
    1. 排除近10日平均成交量小於1000張的股票
    2. 計算 MA20 (20日移動平均線)
    3. 檢查最近5天開盤價與收盤價的平均都在MA20之上
    4. MA20 斜率在合理範圍內 (< 1)
    5. 波動率控制在 5% 以內
    6. 近十日的最高點減最低點的平均要大於1塊
    7. 價格與 MA20 距離在允許範圍內
    8. 依照 MA20 斜率分組，選出最接近 MA20 的股票

    Args:
        prices: 股價數據 DataFrame
        top_k: 最多返回幾支股票 (未使用，保留參數向後相容)

    Returns:
        DataFrame: 選股結果
    """
    if prices.empty:
        return pd.DataFrame()
    prices = prices.sort_values(["code", "date"])

    def add_feat(g):
        g = g.copy()
        g["ma20"] = g["close"].rolling(20, min_periods=20).mean()
        return g

    feat = prices.groupby("code", group_keys=False).apply(add_feat)

    results = []
    for code, group in feat.groupby("code"):
        group = group.sort_values("date")
        if len(group) < 10:
            continue

        # 檢查近10日平均成交量是否大於1000張（1張=1000股）
        last_10 = group.tail(10)
        avg_volume = last_10["volume"].mean()
        avg_volume_lots = avg_volume / 1000  # 轉換為張數

        if avg_volume_lots < 1000:
            continue

        last_5 = group.tail(5)
        if last_5["ma20"].isna().any():
            continue

        # 檢查最近5天開盤價與收盤價的平均都在MA20之上
        avg_price_5d = (last_5["open"] + last_5["close"]) / 2
        price_above_ma20 = (avg_price_5d > last_5["ma20"]).all()

        if not price_above_ma20:
            continue

        # 近十日的最高點減最低點的平均要大於1塊
        high_low_diff = last_10["high"] - last_10["low"]
        avg_high_low_diff = high_low_diff.mean()

        if avg_high_low_diff <= 1.0:
            continue

        # 計算 MA20 斜率
        ma20_values = last_5["ma20"].values
        ma20_slope = (ma20_values[-1] - ma20_values[0]) / 4

        # 過濾掉斜率過大的股票
        if ma20_slope >= 1:
            continue

        # 計算波動率
        price_std = last_5["close"].std()
        price_mean = last_5["close"].mean()
        volatility_pct = (price_std / price_mean * 100) if price_mean > 0 else 999
        if volatility_pct > 5.0:
            continue

        # 動態調整距離限制
        max_distance_allowed = max(2.0, volatility_pct * 1.5)

        # 計算價格與 MA20 的距離
        min_price = last_5[["open", "close"]].min(axis=1)
        distance_pct = ((min_price - last_5["ma20"]) / last_5["ma20"] * 100)
        avg_distance = distance_pct.mean()

        if avg_distance > max_distance_allowed:
            continue

        # 計算平均距離 MA20
        avg_price = (last_5["open"] + last_5["close"]) / 2
        avg_ma20_distance = abs(avg_price - last_5["ma20"]).mean()

        # 判斷最後一天是否為最低收盤價
        latest = last_5.iloc[-1]
        is_lowest_close = latest["close"] == last_5["close"].min()

        results.append({
            "code": code,
            "close": latest["close"],
            "ma20": latest["ma20"],
            "distance": avg_distance,
            "volatility": volatility_pct,
            "ma20_slope": ma20_slope,
            "max_distance": max_distance_allowed,
            "volume": latest["volume"],
            "avg_volume_10d": avg_volume,
            "avg_volume_10d_lots": avg_volume_lots,
            "avg_ma20_distance": avg_ma20_distance,
            "is_lowest_close": is_lowest_close
        })

    if not results:
        return pd.DataFrame()

    result_df = pd.DataFrame(results)

    # 依照 MA20 斜率分組
    group1 = result_df[(result_df["ma20_slope"] >= 0.5) & (result_df["ma20_slope"] < 1)]
    group2 = result_df[result_df["ma20_slope"] < 0.5]

    # Group1: MA20 斜率 >= 0.5，最多選 6 支
    if len(group1) > 6:
        group1_filtered = group1[group1["is_lowest_close"] == False]
        if len(group1_filtered) > 6:
            group1 = group1_filtered.nsmallest(6, "avg_ma20_distance")
        elif len(group1_filtered) > 0:
            group1 = group1_filtered
        else:
            group1 = group1.nsmallest(6, "avg_ma20_distance")

    # Group2: MA20 斜率 < 0.5，最多選 6 支
    if len(group2) > 6:
        group2_filtered = group2[group2["is_lowest_close"] == False]
        if len(group2_filtered) > 6:
            group2 = group2_filtered.nsmallest(6, "avg_ma20_distance")
        elif len(group2_filtered) > 0:
            group2 = group2_filtered
        else:
            group2 = group2.nsmallest(6, "avg_ma20_distance")

    final_result = pd.concat([group1, group2], ignore_index=True)
    return final_result