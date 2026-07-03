"""四色指標圖表資料測試"""
import pandas as pd

from modules.chart_data_generator import compute_four_color


def make_df(closes, volumes):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(closes)).strftime("%Y-%m-%d"),
        "close": [float(c) for c in closes],
        "volume": volumes,
    })


def test_warmup_period_is_gray():
    """MA20 暖身期（前 19 天）無訊號，之後必有顏色"""
    df = make_df([100] * 25, [1000] * 25)
    out = compute_four_color(df)
    assert (out["color"].iloc[:19] == "gray").all()
    assert (out["color"].iloc[19:] != "gray").all()


def test_red_above_ma_with_heavy_volume():
    """收盤 > 均價 且 量 > 均量 → 紅（帶量翻紅）"""
    df = make_df([100] * 20 + [110], [1000] * 20 + [2000])
    out = compute_four_color(df)
    assert out["color"].iloc[-1] == "red"


def test_green_below_ma_with_heavy_volume():
    """收盤 < 均價 且 量 > 均量 → 綠（帶量翻黑）"""
    df = make_df([100] * 20 + [90], [1000] * 20 + [2000])
    out = compute_four_color(df)
    assert out["color"].iloc[-1] == "green"


def test_yellow_above_ma_without_volume():
    """收盤 > 均價 但量未過均量 → 黃"""
    df = make_df([100] * 20 + [110], [1000] * 20 + [500])
    out = compute_four_color(df)
    assert out["color"].iloc[-1] == "yellow"


def test_blue_below_ma_without_volume():
    """收盤 < 均價 但量未過均量 → 藍"""
    df = make_df([100] * 20 + [90], [1000] * 20 + [500])
    out = compute_four_color(df)
    assert out["color"].iloc[-1] == "blue"


def test_close_equal_ma_counts_as_strong():
    """收盤恰等於均價 → 併入偏強（黃），量恰等於均量 → 不算帶量"""
    df = make_df([100] * 25, [1000] * 25)  # 全平盤：close==ma20, volume==vma20
    out = compute_four_color(df)
    assert out["color"].iloc[-1] == "yellow"


def test_ma_columns_present():
    """輸出需含 ma20 / vma20 欄位，暖身期為 NaN"""
    df = make_df([100] * 25, [1000] * 25)
    out = compute_four_color(df)
    assert out["ma20"].iloc[:19].isna().all()
    assert out["ma20"].iloc[19] == 100.0
    assert out["vma20"].iloc[19] == 1000.0
