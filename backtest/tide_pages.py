"""
潮汐策略的 GitHub Pages 輸出（部署到 gh-pages 的 tide/ 資料夾）

  status.json  今日狀態＋明日情境表（首頁的 panel.js 讀它畫在最上方）
  panel.js     首頁潮汐區塊（index.html 只需放 <div id="tide-panel"> 並載入這支）
  index.html   進出場圖表（tide_chart.html 模板）
  data.json    圖表資料：2025 起的K線與進出場，持有中照「持倉中」虛線畫

資料不做增量合併：每天都用全歷史重算（MA60、布林寬度一年百分位、部位狀態都需要更早的
資料，重算不到一秒），再截取 CHART_START 之後輸出，所以不會有新舊資料接不起來的問題。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import tide_backtest as bt
from tide_next_close import Scenario

CHART_START = "2025-01-01"
HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "tide_site"


def _num(v, nd=2):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), nd)


def build_candles(hist: pd.DataFrame) -> list[dict]:
    c = hist["Close"]
    mid = c.rolling(bt.BB_PERIOD).mean()
    bbl = 2 * mid - hist["BBU"]
    df = pd.DataFrame({
        "t": hist["Date"].dt.strftime("%Y-%m-%d"),
        "o": hist["Open"], "h": hist["High"], "l": hist["Low"], "c": c,
        "ma10": hist["MA_short"], "ma60": hist["MA_long"], "bbu": hist["BBU"], "bbl": bbl,
        "bbw": (hist["BBU"] - bbl) / mid * 100,
    })
    df = df[hist["Date"] >= CHART_START]
    return [{k: (v if k == "t" else _num(v)) for k, v in r.items()} for r in df.to_dict("records")]


def build_trades(hist: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """全歷史跑引擎，編號沿用全歷史流水號（跟回測報表一致），只輸出跟 CHART_START 之後有交集的交易。"""
    trades = bt.simulate_combined(hist)
    longs, shorts = [], []
    for r in trades.to_dict("records"):
        side_list = longs if r["side"] == "long" else shorts
        exit_date = r["exit_date"]
        item = {
            "id": len(side_list) + 1,
            "entry_date": str(r["entry_date"]), "exit_date": None if exit_date is None else str(exit_date),
            "entry_price": _num(r["entry_price"], 1), "exit_price": _num(r["exit_price"], 1),
            "net_pct": _num(r["net_pct"]),
            # 未平倉那筆在 DataFrame 裡是 NaN 不是 None，要用 isna 判斷（JSON 不能有 NaN）
            "net_points": None if pd.isna(r["net_pct"]) else round(r["net_pct"] * r["entry_price"] / 100, 1),
            "days_held": None if exit_date is None else r["days_held"],
        }
        item.update({"peak": None, "entry_type": r["entry_type"]} if r["side"] == "long" else {"trough": None})
        side_list.append(item)

    def shown(t):
        return t["exit_date"] is None or t["exit_date"] >= CHART_START
    return [t for t in longs if shown(t)], [t for t in shorts if shown(t)]


def write_site(sc: Scenario, status: dict, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    longs, shorts = build_trades(sc.hist)
    data = {
        "meta": {
            "title": f"潮汐策略：加權指數進出場（{CHART_START[:4]} 起）",
            "sub": (f"多方：站上MA60＋拉回收復MA10（或深跌V轉）；空方：跌破MA60＋反彈失敗跌破MA10；"
                    f"出場：從持倉極值回落/反彈2%，另有布林上緣鎖利。資料：台灣加權指數，"
                    f"{CHART_START[:7]} ~ {status['date']}，每個交易日收盤後自動更新"),
            "footer": ("進出場為潮汐策略規則的機械化模擬，以加權指數收盤價判斷，實際下單台指期近月會有基差與滑價；"
                       "虛線＋「持倉中」代表目前仍持有的部位。編號沿用 1997 年起的全歷史流水號。"),
            "home": "../",
        },
        "candles": build_candles(sc.hist),
        "trades": longs,
        "short_trades": shorts,
    }
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    # tide_chart.html 是 artifact 用的頁面片段，獨立網頁要補上 doctype、字元集與 viewport
    head = ('<!doctype html>\n<html lang="zh-TW"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>\n')
    page = head + (HERE / "tide_chart.html").read_text(encoding="utf-8") + "\n</body></html>\n"
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "panel.js").write_text((TEMPLATE_DIR / "panel.js").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"✅ GitHub Pages 檔案已輸出到 {out}（K線 {len(data['candles'])} 根，多 {len(longs)} / 空 {len(shorts)} 筆）")
