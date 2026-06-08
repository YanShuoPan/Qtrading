"""
股票數據處理模組 - 下載股價數據和選股邏輯
"""
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import time
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

    # 為了避免 Yahoo Finance API 限流，採用分批下載策略
    # 每批最多 200 支股票，批次之間延遲 3 秒
    BATCH_SIZE = 200
    BATCH_DELAY = 3  # 秒

    logger.info(f"\n開始下載 {len(codes_to_fetch)} 支股票")
    logger.info(f"期間: {target_start} ~ 今日")

    # 如果股票數量超過 BATCH_SIZE，採用分批下載
    if len(codes_to_fetch) > BATCH_SIZE:
        num_batches = (len(codes_to_fetch) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"⚠️  股票數量較多，將分成 {num_batches} 批下載（每批 {BATCH_SIZE} 支）")
        logger.info(f"   批次之間延遲 {BATCH_DELAY} 秒，以避免 API 限流")

    all_results = []
    for batch_idx in range(0, len(codes_to_fetch), BATCH_SIZE):
        batch_codes = codes_to_fetch[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1
        total_batches = (len(codes_to_fetch) + BATCH_SIZE - 1) // BATCH_SIZE

        if total_batches > 1:
            logger.info(f"\n📦 批次 {batch_num}/{total_batches}: 下載 {len(batch_codes)} 支股票")

        batch_results = []
        got_data = set()

        # ── Pass 1: .TW（上市 + 部分上櫃）────────────────────────────────────
        tickers = [f"{c}.TW" for c in batch_codes]
        try:
            df = yf.download(
                tickers=" ".join(tickers),
                start=target_start,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
            )
            logger.info(f"   ✅ 批次 {batch_num} (.TW) 下載完成，形狀: {df.shape if hasattr(df, 'shape') else 'N/A'}")

            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                # 診斷：顯示 DataFrame 結構
                if hasattr(df.columns, 'nlevels'):
                    logger.info(f"   DataFrame columns nlevels={df.columns.nlevels}")
                    if df.columns.nlevels > 1:
                        level0 = list(df.columns.get_level_values(0).unique())[:5]
                        level1 = list(df.columns.get_level_values(1).unique())[:5]
                        logger.info(f"   Level 0 (前5): {level0}")
                        logger.info(f"   Level 1 (前5): {level1}")
                if hasattr(df.index, 'max'):
                    logger.info(f"   DataFrame 日期範圍: {df.index.min()} ~ {df.index.max()}")

                for c in batch_codes:
                    t = f"{c}.TW"
                    if isinstance(df, pd.DataFrame) and t in df:
                        tmp = df[t].reset_index().rename(columns=str.lower)
                        if "date" not in tmp.columns:
                            for col in tmp.columns:
                                if pd.api.types.is_datetime64_any_dtype(tmp[col]):
                                    tmp = tmp.rename(columns={col: "date"})
                                    break
                        if "date" not in tmp.columns:
                            continue
                        tmp["date"] = pd.to_datetime(tmp["date"]).dt.tz_localize(None)
                        tmp["code"] = c
                        tmp = tmp.dropna(subset=["close"])
                        if not tmp.empty:
                            if "volume" not in tmp.columns:
                                tmp["volume"] = 0
                            batch_results.append(tmp[["code", "date", "open", "high", "low", "close", "volume"]])
                            got_data.add(c)
            else:
                logger.warning(f"   ⚠️  批次 {batch_num} (.TW) 返回空資料")

        except Exception as e:
            logger.error(f"   ❌ 批次 {batch_num} (.TW) 下載失敗: {e}")

        # ── Pass 2: .TWO（對 .TW 無資料的上櫃股票重試）────────────────────────
        missing_codes = [c for c in batch_codes if c not in got_data]
        if missing_codes:
            logger.info(f"   🔄 {len(missing_codes)} 支改用 .TWO 重試（上櫃）")
            tickers_two = [f"{c}.TWO" for c in missing_codes]
            try:
                df2 = yf.download(
                    tickers=" ".join(tickers_two),
                    start=target_start,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    progress=False,
                )
                if df2 is not None and isinstance(df2, pd.DataFrame) and not df2.empty:
                    recovered = 0
                    for c in missing_codes:
                        t2 = f"{c}.TWO"
                        if t2 in df2:
                            tmp2 = df2[t2].reset_index().rename(columns=str.lower)
                            if "date" not in tmp2.columns:
                                for col in tmp2.columns:
                                    if pd.api.types.is_datetime64_any_dtype(tmp2[col]):
                                        tmp2 = tmp2.rename(columns={col: "date"})
                                        break
                            if "date" not in tmp2.columns:
                                continue
                            tmp2["date"] = pd.to_datetime(tmp2["date"]).dt.tz_localize(None)
                            tmp2["code"] = c
                            tmp2 = tmp2.dropna(subset=["close"])
                            if not tmp2.empty:
                                if "volume" not in tmp2.columns:
                                    tmp2["volume"] = 0
                                batch_results.append(tmp2[["code", "date", "open", "high", "low", "close", "volume"]])
                                got_data.add(c)
                                recovered += 1
                    if recovered:
                        logger.info(f"   ✅ .TWO 補回 {recovered} 支上櫃股票")
            except Exception as e:
                logger.error(f"   ❌ 批次 {batch_num} (.TWO) 下載失敗: {e}")

        still_missing = len(batch_codes) - len(got_data)
        if still_missing > 0:
            logger.warning(f"   ⚠️  批次 {batch_num}: {still_missing}/{len(batch_codes)} 支股票仍無資料（可能已下市）")

        if batch_results:
            all_results.extend(batch_results)
            logger.info(f"   ✅ 批次 {batch_num} 成功處理 {len(batch_results)} 支股票")

        # 如果還有下一批，延遲一段時間避免限流
        if batch_idx + BATCH_SIZE < len(codes_to_fetch):
            logger.debug(f"   ⏸️  延遲 {BATCH_DELAY} 秒後繼續下一批...")
            time.sleep(BATCH_DELAY)

    # 合併所有批次的結果
    if not all_results:
        logger.error("❌ 所有批次都未能成功下載資料")
        logger.error("   可能原因：")
        logger.error("   1. Yahoo Finance API 暫時無法訪問")
        logger.error("   2. 網路連線問題")
        logger.error("   3. API 限流（Too Many Requests）")
        logger.error("   建議：稍後重試或檢查 GitHub Actions 日誌")
        return pd.DataFrame()

    # 合併所有批次的結果
    result = pd.concat(all_results, ignore_index=True) if all_results else pd.DataFrame()
    logger.info(f"成功下載 {len(result)} 筆數據")
    if not result.empty and 'date' in result.columns:
        logger.info(f"合併後總日期範圍: {result['date'].min()} ~ {result['date'].max()}")
        logger.info(f"合併後唯一日期數: {result['date'].nunique()}")
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
    if prices.empty or 'code' not in prices.columns:
        logger.warning("股價資料為空或缺少必要欄位，無法進行選股")
        return pd.DataFrame()
    prices = prices.sort_values(["code", "date"])

    # 使用 transform 代替 apply 以確保保留所有欄位（包括 code）
    # 這避免了某些 pandas 版本中 group_keys=False 導致 code 欄位消失的問題
    prices = prices.copy()
    prices["ma20"] = prices.groupby("code")["close"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    feat = prices

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