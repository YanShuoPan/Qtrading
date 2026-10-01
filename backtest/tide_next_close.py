"""
潮汐策略：明日收盤情境表

規則全部只看收盤價，所以把「下一個交易日收盤價」當未知數，從 -RANGE% 掃到 +RANGE%，
每個價位都在歷史資料後面接一根假設K棒、重算指標、完整重跑一次策略，比較跑完後的部位
狀態跟今天的差異，得到「收盤落在哪個區間 → 要做什麼」。區間邊界再用二分法逼到 0.05 點；每列代表 下界 ≤ 收盤 < 上界。

假設K棒的開高低都設成收盤價：策略的進出場判斷只用收盤，高低點只影響 MAE（槓桿分析用）。
本模組只提供函式給 tide_daily_alert.py 用；要看情境表請跑 python tide_daily_alert.py --dry-run。
"""

import numpy as np
import pandas as pd

import tide_backtest as bt

RANGE_PCT = 6.0
GRID_STEP_PCT = 0.1
BOUNDARY_PRECISION = 0.05  # 區間邊界二分法精度（點），顯示到小數一位
TAIL_ROWS = 600   # 指標最長需要 252+20 天(布林寬度百分位)+70 天(MA60斜率)，取 600 天足夠讓最後一根完全一致


def describe_state(st: dict) -> str:
    if st["state"] is None:
        return "空手"
    if st["state"] == "short":
        return "幻影空單佔位中(不實際持有)" if st["is_phantom"] else "持有空單"
    return "鎖利後等待(已出場，等2%回落條件解除)" if st["long_locked_leg"] else "持有多單"


def classify(before: dict, after: dict, next_date: pd.Timestamp) -> str:
    """比較今天收盤後的狀態與明天收盤後的狀態，翻成要做的動作。"""
    entered_today = after["entry_date"] == next_date.date()
    if before["state"] is None:
        paused = before["pause_until_date"] is not None and next_date < before["pause_until_date"]
        if after["state"] is None:
            return "不動作（連續虧損暫停中）" if paused else "不動作（無訊號）"
        if after["state"] == "long":
            return f"進場做多（{'V轉路徑' if after['entry_type'] == 'v_reversal' else '拉回收復路徑'}）"
        return "空方訊號被布林寬度濾網擋下 → 不下單，進入幻影佔位" if after["is_phantom"] else "進場做空"
    if before["state"] == "long" and not before["long_locked_leg"]:
        if after["state"] == "long" and not after["long_locked_leg"] and not entered_today:
            return "續抱多單" + ("（創持倉新高）" if after["extreme_close"] > before["extreme_close"] else "")
        if after["state"] == "long" and after["long_locked_leg"]:
            return "布林上緣鎖利：多單出場，之後等2%回落條件才重新找訊號"
        return "多單出場（從持倉最高收盤回落達2%）"
    if before["state"] == "long":  # 鎖利後等待
        return "繼續等待（不進場）" if after["state"] == "long" else "等待結束（隔天起恢復找訊號）"
    if before["is_phantom"]:
        return "幻影佔位持續（不進場）" if after["state"] == "short" else "幻影佔位結束（隔天起恢復找訊號）"
    if after["state"] == "short" and not entered_today:
        return "續抱空單" + ("（創持倉新低）" if after["extreme_close"] < before["extreme_close"] else "")
    return "空單回補（從持倉最低收盤反彈達2%）"


def next_trading_day(d: pd.Timestamp) -> pd.Timestamp:
    """只跳過週末；國定假日無法預知，訊息裡標示「下一個交易日」。"""
    return d + pd.offsets.BDay(1)


class Scenario:
    def __init__(self, raw: pd.DataFrame | None = None):
        """raw 可直接給 Date/Open/High/Low/Close（測試、重現歷史某天用）；沒給就下載加權指數。"""
        self.raw = raw.reset_index(drop=True) if raw is not None else bt.load_raw_prices("twii")
        self.hist = bt.add_indicators(self.raw)
        _, self.state = bt.simulate_combined(self.hist, return_state=True)
        self.last = self.raw.iloc[-1]
        self.next_date = next_trading_day(self.last["Date"])

    def run(self, close: float) -> dict:
        bar = pd.DataFrame([{"Date": self.next_date, "Open": close, "High": close, "Low": close, "Close": close}])
        tail = bt.add_indicators(pd.concat([self.raw.tail(TAIL_ROWS), bar], ignore_index=True)).iloc[[-1]]
        df = pd.concat([self.hist, tail], ignore_index=True)
        _, st = bt.simulate_combined(df, return_state=True)
        return st

    def action(self, close: float) -> str:
        return classify(self.state, self.run(close), self.next_date)


def build_table(sc: Scenario) -> list[tuple[float, float, str]]:
    base = float(sc.last["Close"])
    grid = base * (1 + np.arange(-RANGE_PCT, RANGE_PCT + 1e-9, GRID_STEP_PCT) / 100)
    acts = [sc.action(c) for c in grid]
    # 動作改變處用二分法找邊界
    bounds = []
    for i in range(1, len(grid)):
        if acts[i] != acts[i - 1]:
            lo, hi = grid[i - 1], grid[i]
            while hi - lo > BOUNDARY_PRECISION:
                mid = (lo + hi) / 2
                if sc.action(mid) == acts[i - 1]:
                    lo = mid
                else:
                    hi = mid
            bounds.append((hi, acts[i - 1], acts[i]))
    rows, start, cur = [], grid[0], acts[0]
    for b, prev_act, nxt in bounds:
        rows.append((start, b, prev_act))
        start, cur = b, nxt
    rows.append((start, grid[-1], cur))
    return rows
