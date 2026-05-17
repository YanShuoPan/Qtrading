"""
Tests for modules/strategies.py

Covers RSI, MACD, Bollinger Band calculations and the Ensemble scoring system.
"""

import sys
import os

# Ensure the project root is on the path so `modules` can be imported directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import pytest

from modules.strategies import (
    compute_rsi,
    compute_macd,
    compute_bollinger,
    ensemble_score,
    compute_ensemble_for_picks,
)


# ---------------------------------------------------------------------------
# Helper data generators
# ---------------------------------------------------------------------------

def _make_uptrend_data(n: int = 60) -> pd.DataFrame:
    """Generate uptrend fake OHLCV data."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    close = 100 + np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.random.randint(5000, 20000, n),
        }
    )


def _make_downtrend_data(n: int = 60) -> pd.DataFrame:
    """Generate downtrend fake OHLCV data."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    close = 200 - np.arange(n) * 0.8 + np.random.randn(n) * 0.3
    return pd.DataFrame(
        {
            "date": dates,
            "open": close + 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.random.randint(5000, 20000, n),
        }
    )


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------

class TestComputeRsi:
    """Tests for compute_rsi()."""

    def test_compute_rsi_returns_series(self):
        """RSI should return a pd.Series with the same index as input."""
        df = _make_uptrend_data()
        result = compute_rsi(df["close"])
        assert isinstance(result, pd.Series), "Expected pd.Series"
        assert len(result) == len(df), "Output length should match input length"

    def test_compute_rsi_values_0_to_100(self):
        """All non-NaN RSI values must be in [0, 100]."""
        df = _make_uptrend_data()
        rsi = compute_rsi(df["close"])
        valid = rsi.dropna()
        assert (valid >= 0).all(), "RSI values must be >= 0"
        assert (valid <= 100).all(), "RSI values must be <= 100"

    def test_compute_rsi_uptrend_above_50(self):
        """For a strong uptrend, the last RSI value should be above 50."""
        np.random.seed(42)
        df = _make_uptrend_data()
        rsi = compute_rsi(df["close"])
        last_rsi = rsi.dropna().iloc[-1]
        assert last_rsi > 50, f"Expected RSI > 50 for uptrend, got {last_rsi:.2f}"

    def test_compute_rsi_nan_for_insufficient_data(self):
        """RSI should return all NaN when fewer data points than period+1."""
        close = pd.Series([100.0, 101.0, 102.0])
        rsi = compute_rsi(close, period=14)
        assert rsi.isna().all(), "Expected all NaN for insufficient data"

    def test_compute_rsi_first_period_rows_nan(self):
        """The first `period` rows of RSI output should be NaN."""
        df = _make_uptrend_data()
        period = 14
        rsi = compute_rsi(df["close"], period=period)
        # The first `period` rows (indices 0..period-1) should be NaN
        assert rsi.iloc[:period].isna().all(), (
            f"First {period} RSI rows should be NaN"
        )


# ---------------------------------------------------------------------------
# MACD tests
# ---------------------------------------------------------------------------

class TestComputeMacd:
    """Tests for compute_macd()."""

    def test_compute_macd_returns_dict(self):
        """MACD should return a dict with macd, signal, histogram keys."""
        df = _make_uptrend_data()
        result = compute_macd(df["close"])
        assert isinstance(result, dict), "Expected dict"
        assert "macd" in result, "Missing 'macd' key"
        assert "signal" in result, "Missing 'signal' key"
        assert "histogram" in result, "Missing 'histogram' key"

    def test_compute_macd_series_types(self):
        """Each value in the MACD dict should be a pd.Series."""
        df = _make_uptrend_data()
        result = compute_macd(df["close"])
        for key in ("macd", "signal", "histogram"):
            assert isinstance(result[key], pd.Series), f"Expected pd.Series for '{key}'"

    def test_compute_macd_lengths_match_input(self):
        """All MACD output series should have the same length as the input."""
        df = _make_uptrend_data()
        result = compute_macd(df["close"])
        n = len(df)
        for key in ("macd", "signal", "histogram"):
            assert len(result[key]) == n, f"Length mismatch for '{key}'"

    def test_compute_macd_histogram_equals_macd_minus_signal(self):
        """Histogram must equal macd - signal (with floating point tolerance)."""
        df = _make_uptrend_data()
        result = compute_macd(df["close"])
        diff = (result["macd"] - result["signal"] - result["histogram"]).abs()
        assert (diff < 1e-10).all(), "Histogram != MACD - Signal"


# ---------------------------------------------------------------------------
# Bollinger Band tests
# ---------------------------------------------------------------------------

class TestComputeBollinger:
    """Tests for compute_bollinger()."""

    def test_compute_bollinger_returns_dict(self):
        """Bollinger should return a dict with upper, middle, lower keys."""
        df = _make_uptrend_data()
        result = compute_bollinger(df["close"])
        assert isinstance(result, dict), "Expected dict"
        assert "upper" in result, "Missing 'upper' key"
        assert "middle" in result, "Missing 'middle' key"
        assert "lower" in result, "Missing 'lower' key"

    def test_compute_bollinger_series_types(self):
        """Each value in the Bollinger dict should be a pd.Series."""
        df = _make_uptrend_data()
        result = compute_bollinger(df["close"])
        for key in ("upper", "middle", "lower"):
            assert isinstance(result[key], pd.Series), f"Expected pd.Series for '{key}'"

    def test_compute_bollinger_band_ordering(self):
        """upper >= middle >= lower for all non-NaN rows."""
        df = _make_uptrend_data()
        result = compute_bollinger(df["close"])
        valid_mask = result["upper"].notna() & result["middle"].notna() & result["lower"].notna()
        upper = result["upper"][valid_mask]
        middle = result["middle"][valid_mask]
        lower = result["lower"][valid_mask]
        assert (upper >= middle).all(), "upper should be >= middle"
        assert (middle >= lower).all(), "middle should be >= lower"

    def test_compute_bollinger_middle_is_rolling_mean(self):
        """Middle band should match the rolling mean of the close."""
        df = _make_uptrend_data()
        period = 20
        result = compute_bollinger(df["close"], period=period)
        expected_middle = df["close"].rolling(window=period, min_periods=period).mean()
        pd.testing.assert_series_equal(
            result["middle"].reset_index(drop=True),
            expected_middle.reset_index(drop=True),
            check_names=False,
        )


# ---------------------------------------------------------------------------
# Ensemble score tests
# ---------------------------------------------------------------------------

class TestEnsembleScore:
    """Tests for ensemble_score()."""

    def test_ensemble_score_range(self):
        """ensemble_score should return a dict with valid structure and counts."""
        df = _make_uptrend_data()
        result = ensemble_score(df)

        assert isinstance(result, dict), "Expected dict"
        assert "bullish_count" in result, "Missing 'bullish_count'"
        assert "total" in result, "Missing 'total'"
        assert "signals" in result, "Missing 'signals'"
        assert result["total"] == 4, "total should always be 4"
        assert 0 <= result["bullish_count"] <= 4, "bullish_count should be 0-4"
        assert isinstance(result["signals"], dict), "'signals' should be a dict"

    def test_ensemble_score_signal_structure(self):
        """Each signal entry must have 'value' (float) and 'bullish' (bool) keys."""
        df = _make_uptrend_data()
        result = ensemble_score(df)
        for name, sig in result["signals"].items():
            assert "value" in sig, f"Signal '{name}' missing 'value' key"
            assert "bullish" in sig, f"Signal '{name}' missing 'bullish' key"
            assert isinstance(sig["bullish"], bool), f"Signal '{name}' 'bullish' should be bool"

    def test_ensemble_score_insufficient_data(self):
        """With fewer than 30 rows, ensemble_score must return the empty sentinel."""
        df = _make_uptrend_data(n=20)
        result = ensemble_score(df)
        assert result["bullish_count"] == 0
        assert result["total"] == 4
        assert result["signals"] == {}

    def test_ensemble_uptrend_mostly_bullish(self):
        """Uptrend data should yield at least 2 bullish signals out of 4."""
        np.random.seed(42)
        df = _make_uptrend_data(n=60)
        result = ensemble_score(df)
        assert result["bullish_count"] >= 2, (
            f"Expected >= 2 bullish signals for uptrend, got {result['bullish_count']}"
        )

    def test_ensemble_downtrend_mostly_bearish(self):
        """Downtrend data should yield at most 2 bullish signals out of 4."""
        np.random.seed(42)
        df = _make_downtrend_data(n=60)
        result = ensemble_score(df)
        assert result["bullish_count"] <= 2, (
            f"Expected <= 2 bullish signals for downtrend, got {result['bullish_count']}"
        )

    def test_ensemble_score_known_signal_names(self):
        """Signals dict should contain exactly: rsi, macd, bollinger, volume."""
        df = _make_uptrend_data()
        result = ensemble_score(df)
        expected_keys = {"rsi", "macd", "bollinger", "volume"}
        assert set(result["signals"].keys()) == expected_keys, (
            f"Expected signal keys {expected_keys}, got {set(result['signals'].keys())}"
        )


# ---------------------------------------------------------------------------
# compute_ensemble_for_picks tests
# ---------------------------------------------------------------------------

class TestComputeEnsembleForPicks:
    """Tests for compute_ensemble_for_picks()."""

    def _make_hist(self, codes=("AAPL", "TSLA"), n=60):
        """Build a combined hist DataFrame for multiple stocks."""
        np.random.seed(42)
        frames = []
        for i, code in enumerate(codes):
            df = _make_uptrend_data(n=n)
            df["code"] = code
            # Offset prices per stock so they differ
            df["close"] = df["close"] + i * 10
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    def test_returns_dataframe(self):
        """compute_ensemble_for_picks should return a DataFrame."""
        hist = self._make_hist()
        picks = pd.DataFrame({"code": ["AAPL", "TSLA"], "score": [1.0, 2.0]})
        result = compute_ensemble_for_picks(picks, hist)
        assert isinstance(result, pd.DataFrame)

    def test_output_has_ensemble_columns(self):
        """Result must contain ensemble_bullish, ensemble_total, ensemble_label."""
        hist = self._make_hist()
        picks = pd.DataFrame({"code": ["AAPL", "TSLA"], "score": [1.0, 2.0]})
        result = compute_ensemble_for_picks(picks, hist)
        assert "ensemble_bullish" in result.columns
        assert "ensemble_total" in result.columns
        assert "ensemble_label" in result.columns

    def test_ensemble_label_format(self):
        """ensemble_label should be formatted as 'X/4'."""
        hist = self._make_hist()
        picks = pd.DataFrame({"code": ["AAPL", "TSLA"]})
        result = compute_ensemble_for_picks(picks, hist)
        for label in result["ensemble_label"]:
            assert "/" in label, f"Label '{label}' missing '/'"
            parts = label.split("/")
            assert len(parts) == 2
            assert parts[1] == "4", f"Denominator should be 4, got '{parts[1]}'"
            assert parts[0].isdigit(), f"Numerator '{parts[0]}' should be a digit"

    def test_does_not_mutate_picks_df(self):
        """Original picks_df must not be modified in place."""
        hist = self._make_hist()
        picks = pd.DataFrame({"code": ["AAPL"]})
        original_cols = list(picks.columns)
        _ = compute_ensemble_for_picks(picks, hist)
        assert list(picks.columns) == original_cols, "picks_df was mutated"

    def test_ensemble_total_always_four(self):
        """ensemble_total column should always be 4."""
        hist = self._make_hist()
        picks = pd.DataFrame({"code": ["AAPL", "TSLA"]})
        result = compute_ensemble_for_picks(picks, hist)
        assert (result["ensemble_total"] == 4).all()
