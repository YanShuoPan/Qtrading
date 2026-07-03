"""四色指標圖表資料測試"""
import json
import os
import sqlite3

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


def _make_test_db(tmp_path, code="2330", days=140):
    """建立含單一股票的測試資料庫"""
    db = str(tmp_path / "test.sqlite")
    dates = pd.date_range("2025-10-01", periods=days).strftime("%Y-%m-%d")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE prices (code TEXT, date TEXT, open REAL, high REAL, "
            "low REAL, close REAL, volume INTEGER)"
        )
        rows = [
            (code, d, 100.0, 105.0, 99.0, 102.0, 5_000_000)
            for d in dates
        ]
        conn.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    return db


def test_generate_chart_data_writes_json(tmp_path):
    from modules.chart_data_generator import generate_chart_data

    db = _make_test_db(tmp_path)
    out_dir = str(tmp_path / "docs")
    count = generate_chart_data(output_dir=out_dir, db_path=db)

    assert count == 1
    json_path = os.path.join(out_dir, "chart_data", "2330.json")
    assert os.path.exists(json_path)

    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["code"] == "2330"
    assert payload["updated"] == payload["days"][-1][0]
    # 欄位順序: [date, open, high, low, close, volume(張), ma20, vma20, color]
    last = payload["days"][-1]
    assert len(last) == 9
    assert last[1] == 100.0 and last[4] == 102.0
    assert last[5] == 5000          # 股 → 張
    assert last[8] in ("red", "green", "yellow", "blue")
    # 暖身期 ma 為 null
    assert payload["days"][0][6] is None
    assert payload["days"][0][8] == "gray"


def test_generate_chart_data_copies_chart_html(tmp_path):
    from modules.chart_data_generator import generate_chart_data

    db = _make_test_db(tmp_path)
    out_dir = str(tmp_path / "docs")
    generate_chart_data(output_dir=out_dir, db_path=db)
    # static/chart.html 存在於 repo，應被複製為 docs/chart.html
    assert os.path.exists(os.path.join(out_dir, "chart.html"))
