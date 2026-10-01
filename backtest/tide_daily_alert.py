"""
潮汐策略每日推播：收盤後產生一則訊息（只看台灣加權指數）

內容：今日收盤、今天收盤依規則該做的動作、目前部位、明日收盤情境表
（明天 13:25 左右看加權指數落在哪一格照表操作，下單台指期近月）。
同一份狀態資料（build_status）同時產生推播文字與 GitHub Pages 的 tide/ 頁面（--site-dir）。

傳送：有 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID 就發 Telegram；否則有
LINE_CHANNEL_ACCESS_TOKEN + LINE_USER_ID 就推給該 LINE 使用者（不發給選股訂閱者）；
都沒有就只印出訊息。任何傳送失敗只記 warning，不中斷。
用法：python tide_daily_alert.py [--dry-run] [--require-today] [--site-dir DIR]
"""

import argparse
import os
import sys

import pandas as pd
import requests

import tide_backtest as bt
from tide_next_close import RANGE_PCT, Scenario, build_table, classify, describe_state

sys.stdout.reconfigure(encoding="utf-8")

NOTES = ["13:25 看加權指數落在哪一格照表操作，下單台指期近月",
         f"情境只算到 ±{RANGE_PCT:.0f}%，超出範圍沿用最外側動作"]


def today_action(sc: Scenario) -> str:
    """今天收盤依規則該做什麼：比較「昨天收盤後」與「今天收盤後」的狀態。"""
    _, prev_state = bt.simulate_combined(sc.hist.iloc[:-1].reset_index(drop=True), return_state=True)
    return classify(prev_state, sc.state, sc.last["Date"])


def exit_line(st: dict) -> float:
    """多單/鎖利等待：最高收盤回落 EXIT_PCT；空單/幻影：最低收盤反彈 EXIT_PCT。"""
    return st["extreme_close"] * (1 - bt.EXIT_PCT / 100 if st["state"] == "long" else 1 + bt.EXIT_PCT / 100)


def position_line(sc: Scenario) -> str:
    st, close = sc.state, float(sc.last["Close"])
    desc = describe_state(st)
    if st["state"] is None:
        if st["pause_until_date"] is not None and sc.next_date < st["pause_until_date"]:
            return f"空手（連續虧損暫停到 {st['pause_until_date']:%m/%d}）"
        return "空手"
    # 鎖利後等待、幻影佔位：手上其實沒有部位，只顯示解除條件，不顯示未實現損益
    if st["state"] == "long" and st["long_locked_leg"]:
        return (f"空手・{desc}\n（{st['entry_date']:%m/%d} 進場那筆已鎖利出場；收盤跌破 {exit_line(st):,.0f}"
                f"〔最高收盤 {st['extreme_close']:,.0f} 回落2%〕後，隔天起恢復找訊號）")
    if st["state"] == "short" and st["is_phantom"]:
        return (f"空手・{desc}\n（{st['entry_date']:%m/%d} 的空方訊號被布林寬度濾網擋下；收盤漲過 {exit_line(st):,.0f}"
                f"〔最低收盤 {st['extreme_close']:,.0f} 反彈2%〕後，隔天起恢復找訊號）")
    sign = 1 if st["state"] == "long" else -1
    pnl = (close / st["entry_price"] - 1) * 100 * sign
    line = f"{desc}（{st['entry_date']:%m/%d} @ {st['entry_price']:,.0f}，未實現 {pnl:+.2f}%）"
    if st["state"] == "long":
        line += f"\n持倉最高收盤 {st['extreme_close']:,.0f} → 回落出場線 {exit_line(st):,.0f}"
    else:
        line += f"\n持倉最低收盤 {st['extreme_close']:,.0f} → 反彈回補線 {exit_line(st):,.0f}"
    return line


def scenario_rows(sc: Scenario) -> list[dict]:
    """情境表轉成顯示用文字；每列代表 下界 ≤ 收盤 < 上界。"""
    rows, close = build_table(sc), float(sc.last["Close"])
    out = []
    for lo, hi, act in rows:
        if len(rows) == 1:
            rng = f"±{RANGE_PCT:.0f}% 內收在哪裡都一樣"
        elif lo == rows[0][0]:
            rng = f"< {hi:,.1f}（{(hi / close - 1) * 100:+.2f}%）"
        elif hi == rows[-1][1]:
            rng = f"≥ {lo:,.1f}（{(lo / close - 1) * 100:+.2f}%）"
        else:
            rng = f"{lo:,.1f} ~ {hi:,.1f} 之間"
        out.append({"range": rng, "action": act})
    return out


def build_status(sc: Scenario) -> dict:
    close, prev = float(sc.last["Close"]), float(sc.raw.iloc[-2]["Close"])
    return {
        "date": f"{sc.last['Date']:%Y-%m-%d}",
        "close": round(close, 2),
        "change_pct": round((close / prev - 1) * 100, 2),
        "today_action": today_action(sc),
        "position": position_line(sc),
        "next_date": f"{sc.next_date:%Y-%m-%d}",
        "scenarios": scenario_rows(sc),
        "notes": NOTES,
        "generated_at": pd.Timestamp.now(tz="Asia/Taipei").isoformat(timespec="minutes"),
    }


def render_text(status: dict) -> str:
    d, nd = pd.Timestamp(status["date"]), pd.Timestamp(status["next_date"])
    lines = [
        f"🌊 潮汐策略｜{d:%Y/%m/%d} 收盤",
        f"加權指數 {status['close']:,.2f}（{status['change_pct']:+.2f}%）",
        f"今日收盤動作：{status['today_action']}",
        f"部位：{status['position']}",
        "",
        f"📋 下一個交易日（{nd:%m/%d}，遇假日順延）收盤情境：",
        *[f"・{r['range']}：{r['action']}" for r in status["scenarios"]],
        "",
        *[f"※ {n}" for n in status["notes"]],
    ]
    return "\n".join(lines)


def build_message(raw: pd.DataFrame | None = None) -> str:
    """raw 可給截到某一天的歷史價格，用來重現過去某天的推播內容。"""
    return render_text(build_status(Scenario(raw=raw)))


def send_telegram(msg: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": msg}, timeout=30)
    r.raise_for_status()
    return True


def send_line(msg: str) -> bool:
    """直接呼叫 LINE push API 推給單一使用者（不經 modules/，免得拖進選股機器人的設定與資料庫）。"""
    token, user = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"), os.environ.get("LINE_USER_ID", "").strip()
    if not (token and user):
        return False
    r = requests.post("https://api.line.me/v2/bot/message/push",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"to": user, "messages": [{"type": "text", "text": msg}]}, timeout=30)
    r.raise_for_status()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只印出訊息，不傳送")
    parser.add_argument("--require-today", action="store_true", help="最新收盤不是今天（休市）就整個跳過")
    parser.add_argument("--site-dir", help="同時輸出 GitHub Pages 的 tide/ 頁面到這個資料夾")
    args = parser.parse_args()

    sc = Scenario()
    today = pd.Timestamp.now(tz="Asia/Taipei").date()
    if args.require_today and sc.last["Date"].date() != today:
        print(f"📌 最新資料是 {sc.last['Date']:%Y-%m-%d}，不是今天 {today}（休市或資料未更新），不推播也不更新頁面")
        return

    status = build_status(sc)
    msg = render_text(status)
    print(msg)
    if args.site_dir:
        from tide_pages import write_site
        write_site(sc, status, args.site_dir)
    if args.dry_run:
        return
    for name, sender in [("Telegram", send_telegram), ("LINE", send_line)]:
        try:
            if sender(msg):
                print(f"\n✅ 已透過 {name} 傳送")
                return
        except Exception as e:
            print(f"\n⚠️ {name} 傳送失敗: {e}")
    print("\n⚠️ 沒有可用的推播設定（TELEGRAM_* 或 LINE_*），只印出訊息")


if __name__ == "__main__":
    main()
