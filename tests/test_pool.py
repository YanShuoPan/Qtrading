"""Tests for modules/pool.py"""
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from modules.config import TPE_TZ


def _today() -> str:
    """回傳台北時區的今天日期字串（與 pool.py 邏輯一致）"""
    return datetime.now(TPE_TZ).date().isoformat()


@pytest.fixture()
def pool_env(tmp_path, monkeypatch):
    """Temp SQLite DB with pool table; returns (db_path, pool_module)."""
    db_path = str(tmp_path / "test.sqlite")
    import modules.pool as pool_mod
    monkeypatch.setattr(pool_mod, "DB_PATH", db_path)
    pool_mod.ensure_pool_table()
    return db_path, pool_mod


def test_ensure_pool_table_creates_table(pool_env):
    db_path, _ = pool_env
    with sqlite3.connect(db_path) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "pool" in tables


def test_expire_pool_removes_old_entries(pool_env):
    db_path, pool_mod = pool_env
    tpe_today = datetime.now(TPE_TZ).date()
    old_date = (tpe_today - timedelta(days=15)).isoformat()
    recent_date = tpe_today.isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pool (code, name, entry_date) VALUES (?, ?, ?)",
            ("0001", "Old", old_date)
        )
        conn.execute(
            "INSERT INTO pool (code, name, entry_date) VALUES (?, ?, ?)",
            ("0002", "Recent", recent_date)
        )
        conn.commit()
    removed = pool_mod.expire_pool()
    assert removed == 1
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT code FROM pool").fetchall()
    assert [r[0] for r in rows] == ["0002"]


def test_add_to_pool_inserts_new_entry(pool_env, monkeypatch):
    db_path, pool_mod = pool_env
    monkeypatch.setattr("modules.pool.get_stock_name", lambda c: f"Stock{c}")
    picks = pd.DataFrame({"code": ["2330"]})
    hist = pd.DataFrame({
        "code": ["2330", "2330"],
        "date": ["2026-06-07", "2026-06-08"],
        "close": [900.0, 910.0],
    })
    industry_data = {"2330": {"fine": "半導體", "coarse": "電子"}}
    heat_scores = {"半導體": {"heat": 0.75, "active": 15, "total": 20}}
    added = pool_mod.add_to_pool(picks, hist, industry_data, heat_scores)
    assert added == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT code, entry_price, fine_group, heat_at_entry FROM pool"
        ).fetchone()
    assert row[0] == "2330"
    assert row[1] == 910.0
    assert row[2] == "半導體"
    assert abs(row[3] - 0.75) < 1e-6


def test_add_to_pool_no_duplicate_same_day(pool_env, monkeypatch):
    _, pool_mod = pool_env
    monkeypatch.setattr("modules.pool.get_stock_name", lambda c: "T")
    picks = pd.DataFrame({"code": ["2330"]})
    hist = pd.DataFrame({"code": ["2330"], "date": ["2026-06-08"], "close": [900.0]})
    pool_mod.add_to_pool(picks, hist, {}, {})
    added_second = pool_mod.add_to_pool(picks, hist, {}, {})
    assert added_second == 0  # INSERT OR IGNORE prevents duplicate


def test_get_active_pool_filters_by_date(pool_env):
    db_path, pool_mod = pool_env
    tpe_today = datetime.now(TPE_TZ).date()
    old_date = (tpe_today - timedelta(days=15)).isoformat()
    today_str = tpe_today.isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pool (code, name, entry_date) VALUES ('0001','A',?)", (old_date,)
        )
        conn.execute(
            "INSERT INTO pool (code, name, entry_date) VALUES ('0002','B',?)", (today_str,)
        )
        conn.commit()
    df = pool_mod.get_active_pool()
    assert len(df) == 1
    assert df.iloc[0]["code"] == "0002"


def test_annotate_pool_heat_adds_columns(pool_env):
    _, pool_mod = pool_env
    pool_df = pd.DataFrame({
        "code": ["2330"],
        "name": ["台積電"],
        "entry_date": [_today()],
        "entry_price": [900.0],
        "fine_group": ["半導體"],
        "heat_at_entry": [0.60],
    })
    heat_scores = {"半導體": {"heat": 0.80, "active": 16, "total": 20}}
    result = pool_mod.annotate_pool_heat(pool_df, heat_scores)
    assert "current_heat" in result.columns
    assert "heat_delta" in result.columns
    assert "heat_status" in result.columns
    assert "days_held" in result.columns
    assert abs(result.iloc[0]["current_heat"] - 0.80) < 1e-6
    assert abs(result.iloc[0]["heat_delta"] - 0.20) < 1e-6
    assert result.iloc[0]["heat_status"] == "hot"
    assert result.iloc[0]["days_held"] == 0


def test_annotate_pool_heat_status_cold(pool_env):
    _, pool_mod = pool_env
    pool_df = pd.DataFrame({
        "code": ["2330"],
        "name": ["台積電"],
        "entry_date": [_today()],
        "entry_price": [900.0],
        "fine_group": ["半導體"],
        "heat_at_entry": [0.80],
    })
    heat_scores = {"半導體": {"heat": 0.60, "active": 12, "total": 20}}
    result = pool_mod.annotate_pool_heat(pool_df, heat_scores)
    assert result.iloc[0]["heat_status"] == "cold"
