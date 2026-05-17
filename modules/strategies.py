"""
Multi-Strategy + Ensemble Module

Provides RSI, MACD, Bollinger Band signal computation and an Ensemble voting system
for stock analysis.
"""

import pandas as pd
import numpy as np
from .logger import get_logger

logger = get_logger(__name__)


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Compute the Relative Strength Index (RSI) for a price series.

    Uses rolling mean of gains and losses (Wilder's method approximation via
    simple rolling mean for the initial calculation).

    Parameters
    ----------
    close : pd.Series
        Closing price series.
    period : int, optional
        Look-back period (default 14).

    Returns
    -------
    pd.Series
        RSI values in the range 0-100. Values for the first `period` rows
        will be NaN due to insufficient data.
    """
    if close.empty or len(close) < period + 1:
        logger.debug("compute_rsi: insufficient data (len=%d, period=%d)", len(close), period)
        return pd.Series(np.nan, index=close.index)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Where avg_loss == 0 (all gains), RSI should be 100
    rsi = rsi.where(avg_loss != 0, other=100.0)

    logger.debug("compute_rsi: computed for %d rows", len(rsi.dropna()))
    return rsi


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict:
    """
    Compute MACD, Signal line, and Histogram using EMA.

    Parameters
    ----------
    close : pd.Series
        Closing price series.
    fast : int, optional
        Fast EMA period (default 12).
    slow : int, optional
        Slow EMA period (default 26).
    signal_period : int, optional
        Signal line EMA period (default 9).

    Returns
    -------
    dict
        Keys: "macd" (Series), "signal" (Series), "histogram" (Series).
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    logger.debug("compute_macd: computed for series length %d", len(close))
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def compute_bollinger(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> dict:
    """
    Compute Bollinger Bands (upper, middle, lower).

    Parameters
    ----------
    close : pd.Series
        Closing price series.
    period : int, optional
        Rolling window period (default 20).
    std_dev : float, optional
        Number of standard deviations for the bands (default 2.0).

    Returns
    -------
    dict
        Keys: "upper" (Series), "middle" (Series), "lower" (Series).
    """
    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()

    upper = middle + std_dev * std
    lower = middle - std_dev * std

    logger.debug("compute_bollinger: computed for series length %d", len(close))
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
    }


def ensemble_score(df: pd.DataFrame) -> dict:
    """
    Compute an ensemble (voting) score for a single stock OHLCV DataFrame.

    Requires at least 30 rows of data. Four signals are evaluated:
      - RSI: last RSI value in 40-70 range = bullish (healthy uptrend zone)
      - MACD: last histogram value > 0 = bullish (positive momentum)
      - Bollinger: last close > middle band = bullish (price above mean)
      - Volume: 5-day avg volume > 20-day avg volume = bullish (increasing volume)

    Parameters
    ----------
    df : pd.DataFrame
        Single-stock OHLCV DataFrame with columns: open, high, low, close, volume.
        Must have at least 30 rows.

    Returns
    -------
    dict
        {
            "bullish_count": int,
            "total": 4,
            "signals": {
                signal_name: {"value": float, "bullish": bool}
            }
        }
        If df has fewer than 30 rows, returns {"bullish_count": 0, "total": 4, "signals": {}}.
    """
    if df is None or len(df) < 30:
        logger.debug("ensemble_score: insufficient data (rows=%d), returning empty", len(df) if df is not None else 0)
        return {"bullish_count": 0, "total": 4, "signals": {}}

    close = df["close"].reset_index(drop=True)
    volume = df["volume"].reset_index(drop=True)

    signals = {}

    # --- RSI signal ---
    rsi_series = compute_rsi(close, period=14)
    rsi_val = rsi_series.dropna().iloc[-1] if not rsi_series.dropna().empty else np.nan
    rsi_bullish = bool(not np.isnan(rsi_val) and 40.0 <= rsi_val <= 70.0)
    signals["rsi"] = {"value": float(rsi_val) if not np.isnan(rsi_val) else float("nan"), "bullish": rsi_bullish}

    # --- MACD signal ---
    macd_result = compute_macd(close)
    hist_series = macd_result["histogram"].dropna()
    hist_val = hist_series.iloc[-1] if not hist_series.empty else np.nan
    macd_bullish = bool(not np.isnan(hist_val) and hist_val > 0)
    signals["macd"] = {"value": float(hist_val) if not np.isnan(hist_val) else float("nan"), "bullish": macd_bullish}

    # --- Bollinger signal ---
    boll_result = compute_bollinger(close, period=20)
    middle_series = boll_result["middle"].dropna()
    last_close = float(close.iloc[-1])
    if not middle_series.empty:
        middle_val = float(middle_series.iloc[-1])
        boll_bullish = last_close > middle_val
    else:
        middle_val = np.nan
        boll_bullish = False
    signals["bollinger"] = {"value": last_close, "bullish": bool(boll_bullish)}

    # --- Volume signal ---
    vol_5 = volume.rolling(window=5, min_periods=5).mean()
    vol_20 = volume.rolling(window=20, min_periods=20).mean()
    vol_5_val = vol_5.dropna().iloc[-1] if not vol_5.dropna().empty else np.nan
    vol_20_val = vol_20.dropna().iloc[-1] if not vol_20.dropna().empty else np.nan
    if not np.isnan(vol_5_val) and not np.isnan(vol_20_val):
        vol_bullish = bool(vol_5_val > vol_20_val)
        vol_value = float(vol_5_val)
    else:
        vol_bullish = False
        vol_value = float("nan")
    signals["volume"] = {"value": vol_value, "bullish": vol_bullish}

    bullish_count = sum(1 for s in signals.values() if s["bullish"])
    logger.debug(
        "ensemble_score: bullish_count=%d/4 (rsi=%s, macd=%s, boll=%s, vol=%s)",
        bullish_count,
        rsi_bullish, macd_bullish, boll_bullish, vol_bullish,
    )

    return {
        "bullish_count": bullish_count,
        "total": 4,
        "signals": signals,
    }


def compute_ensemble_for_picks(picks_df: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich a picks DataFrame with ensemble scoring for each stock.

    For each stock in picks_df (identified by the "code" column), retrieve its
    historical data from hist and compute the ensemble_score(). Three new columns
    are added to picks_df:
      - ensemble_bullish : int  -- number of bullish signals (0-4)
      - ensemble_total   : int  -- total signals evaluated (always 4)
      - ensemble_label   : str  -- human-readable fraction string, e.g. "3/4"

    Parameters
    ----------
    picks_df : pd.DataFrame
        DataFrame with at least a "code" column identifying stock tickers.
    hist : pd.DataFrame
        Historical OHLCV data with columns: code, date, open, high, low, close, volume.

    Returns
    -------
    pd.DataFrame
        A copy of picks_df with the three new ensemble columns added.
    """
    result = picks_df.copy()
    bullish_counts = []
    totals = []
    labels = []

    for _, row in result.iterrows():
        code = row["code"]
        stock_hist = hist[hist["code"] == code].copy()

        score = ensemble_score(stock_hist)
        bc = score["bullish_count"]
        tot = score["total"]

        bullish_counts.append(bc)
        totals.append(tot)
        labels.append(f"{bc}/{tot}")

        logger.debug("compute_ensemble_for_picks: code=%s -> %d/%d bullish", code, bc, tot)

    result["ensemble_bullish"] = bullish_counts
    result["ensemble_total"] = totals
    result["ensemble_label"] = labels

    return result
