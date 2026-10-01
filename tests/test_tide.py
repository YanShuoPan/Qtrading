"""潮汐策略（backtest/tide_*.py）測試：用合成價格，不連網。"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest"))

import tide_backtest as bt  # noqa: E402
from tide_next_close import TAIL_ROWS, Scenario, build_table, classify  # noqa: E402


def make_prices(closes: np.ndarray) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=len(closes))
    return pd.DataFrame({"Date": dates, "Open": closes, "High": closes, "Low": closes, "Close": closes})


@pytest.fixture
def reclaim_prices() -> pd.DataFrame:
    """穩定上漲 200 天 → 最後幾天拉回跌破 MA10 → 最後一天收回，觸發拉回收復進場。"""
    c = np.linspace(100, 160, 200)
    c[-6:-1] = c[-7] * np.array([0.985, 0.975, 0.97, 0.968, 0.972])
    c[-1] = c[-7]
    return make_prices(c)


def test_open_position_recorded_and_excluded_from_stats(reclaim_prices):
    trades, state = bt.simulate_combined(bt.add_indicators(reclaim_prices), return_state=True)
    open_rows = trades[trades["exit_date"].isna()]
    assert len(open_rows) == 1
    assert open_rows.iloc[0]["side"] == "long"
    assert state["state"] == "long" and state["entry_date"] == reclaim_prices["Date"].iloc[-1].date()
    # 只有未平倉一筆時，績效統計應視為沒有已平倉交易
    assert bt.compound_stats(trades) is None


def test_tail_window_indicators_match_full(reclaim_prices):
    long = make_prices(np.linspace(100, 300, TAIL_ROWS + 200))
    full = bt.add_indicators(long).iloc[-1]
    tail = bt.add_indicators(long.tail(TAIL_ROWS).reset_index(drop=True)).iloc[-1]
    for col in ["MA_short", "MA_long", "MA60_slope10_pct", "MA10_slope5_pct", "BBU", "BBW_percentile_1y", "pctB_close"]:
        assert full[col] == pytest.approx(tail[col], rel=1e-9, abs=1e-9)


def test_exit_boundary_equals_trailing_stop(reclaim_prices):
    # 進場後再漲兩天，持倉最高收盤 = 最後一天
    c = np.append(reclaim_prices["Close"].to_numpy(), reclaim_prices["Close"].iloc[-1] * np.array([1.01, 1.02]))
    sc = Scenario(raw=make_prices(c))
    assert sc.state["state"] == "long"
    peak = sc.state["extreme_close"]
    rows = build_table(sc)
    exit_rows = [r for r in rows if r[2].startswith("多單出場")]
    assert exit_rows, rows
    boundary = exit_rows[-1][1]
    assert boundary == pytest.approx(peak * (1 - bt.EXIT_PCT / 100), abs=0.1)


def test_pages_output_includes_open_trade_without_nan(reclaim_prices, monkeypatch, tmp_path):
    import json

    import tide_pages
    from tide_daily_alert import build_status

    start = reclaim_prices["Date"].iloc[150].strftime("%Y-%m-%d")
    monkeypatch.setattr(tide_pages, "CHART_START", start)
    sc = Scenario(raw=reclaim_prices)
    tide_pages.write_site(sc, build_status(sc), str(tmp_path))

    raw_json = (tmp_path / "data.json").read_text(encoding="utf-8")
    assert "NaN" not in raw_json
    data = json.loads(raw_json)
    assert data["candles"][0]["t"] >= start and len(data["candles"]) == 50
    open_trades = [t for t in data["trades"] if t["exit_date"] is None]
    assert len(open_trades) == 1 and open_trades[0]["net_points"] is None
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["scenarios"] and "持有多單" in status["position"]
    assert (tmp_path / "index.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert (tmp_path / "panel.js").exists()


def _state(state=None, **kw):
    base = {"state": state, "is_phantom": False, "long_locked_leg": False, "entry_date": None,
            "entry_price": None, "entry_type": None, "extreme_close": None, "pause_until_date": None}
    base.update(kw)
    return base


def test_classify_transitions():
    d = pd.Timestamp("2026-10-02")
    holding = _state("long", entry_date=pd.Timestamp("2026-09-18").date(), extreme_close=100.0)
    assert classify(holding, _state("long", entry_date=holding["entry_date"], extreme_close=101.0), d).startswith("續抱多單（創持倉新高")
    assert classify(holding, _state(None), d).startswith("多單出場")
    assert classify(holding, _state("long", long_locked_leg=True, entry_date=holding["entry_date"]), d).startswith("布林上緣鎖利")
    assert classify(_state(None), _state("long", entry_date=d.date(), entry_type="normal"), d) == "進場做多（拉回收復路徑）"
    assert classify(_state(None), _state("short", entry_date=d.date(), is_phantom=True), d).startswith("空方訊號被布林寬度濾網擋下")
    paused = _state(None, pause_until_date=pd.Timestamp("2026-10-30"))
    assert classify(paused, _state(None), d) == "不動作（連續虧損暫停中）"
