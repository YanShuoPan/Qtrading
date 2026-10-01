"""
潮汐策略（Tide）回測引擎：最終定案版（多方 + 空方，單一部位互斥引擎）

多方（做多，2026-09-21補上輕量濾網）：
  進場：站上60日均線（大格局多頭）+ 前一日收盤跌破10日均線、當日收盤收回站上（拉回反彈）
        + 10日均線近5日變化率 >= LONG_SLOPE_TH（排除跌破當下短均線崩得太誇張的情況）
  出場：從進場後最高收盤價回落 EXIT_PCT 就出場

空方（做空，2026-09-25新增布林通道寬度濾網）：
  進場：跌破60日均線（大格局空頭）+ 前一日收盤站上10日均線、當日收盤跌破（反彈失敗轉弱）
        + MA60過去10日變化率 < SHORT_SLOPE_TH（確認空頭格局有一定斜率，排除還在強多頭的情況）
        + 布林通道寬度(20,2) 相對近一年的百分位 <= BBW_PERCENTILE_TH（排除通道已經寬到極致
        才追空的情況，這類訊號常是「已經跌深、隨時可能反彈」而非「剛要開始跌」）
  出場：從進場後最低收盤價反彈 EXIT_PCT 就回補

布林通道寬度濾網(BBW_PERCENTILE_TH)的選定過程：
  分析270筆交易在進場當下的11種布林通道相關特徵（%B位置、MA10/收盤到上下軌距離、
  通道寬度%、寬度近一年百分位排名、寬度斜率、MA乖離/通道寬度比）與淨報酬的相關性。
  多方沒有找到明顯線性相關（|r|<0.1皆是），但空方在「通道寬度近一年百分位」上有中度
  負相關（pearson=-0.226），四分位分箱顯示最寬20%這一格是唯一勝率<50%且平均虧損的
  區間（18筆、勝率22%、均報酬-0.77%）。剔除這18筆後空方複利總報酬 +113.2%→+148.5%，
  勝率46.8%→54.2%，且這18筆分布橫跨2000/2001/2002/2003/2008×4/2011×2/2014/2016/
  2020/2022×3/2025共11個不同年份，非單一事件造成的偽相關，故採用 80 為門檻。
  取捨：這批訊號裡也包含2008金融海嘯兩筆最佳空單（+10.76%、+9.11%），代表此濾網會
  犧牲「趨勢已經噴出、通道極寬時順勢追空崩盤加速段」的機會，換取濾掉多數小額雜訊單。

部位互斥：同一時間只能持有一個方向的部位（同一帳戶邏輯），手上有多單時空方訊號跳過，反之亦然。

多方布林上緣鎖利（2026-09-25新增）：
  持倉期間內只要收盤價曾經貼近過布林通道上緣(pctB_close >= BBU_NEAR_TH，不必是當下這
  天)，之後只要布林通道上緣連續 BBU_FLAT_DAYS 天沒有創新高(動能停滯)、且目前浮動獲利
  為正，就把這筆獲利入帳鎖住——但部位「不真的空出來」，繼續用原本2%回落規則追蹤到
  自然出場才釋放部位(這段期間不接受新訊號進場，跟空方幻影單同一個精神)。
  選定過程：最早測試「BBU本身沒創新高就停利」，發現任何寬鬆度都讓勝率大增但Calmar
  腰斬(全樣本230.31→66~122)，因為部位提早空出來，換來更多次數在磨損期重新進場、
  砍到大波段的尾巴。改成「觸發時鎖利入帳但幻影佔位到自然出場」修正了「提早空手」的
  副作用，但要求「收盤價貼近上緣」跟「BBU轉平」發生在同一天時，全歷史只觸發7次，
  樣本太小。最後放寬成「持倉期間內只要曾經貼近過上緣一次」+「之後任何一天BBU轉平」，
  在BBU_NEAR_TH=0.95、BBU_FLAT_DAYS=2時觸發35次，全樣本Calmar 230.31→291.64，
  2010起47.24→80.73、2015起47.14→72.25、2020起66.96→96.74、2022起59.34→66.46，
  是目前唯一一個「全年代無一變差」且同時改善報酬與MDD的出場優化，故採用。

  BBU_FLAT_TOLERANCE_PCT 的選定過程：原版「轉平」判定嚴格要求BBU[i] <= BBU[i-1]，
  哪怕只創新高0.001%都不算轉平。測試加入容忍度(BBU日對日漲幅在此%以內仍算沒創新高)，
  掃描0.03%~1.0%：BBU日對日變化的中位數約0.2%、正值中位數約0.3%，門檻設太寬(>=0.1%)
  會讓機制觸發過於頻繁(次數暴增、MDD回升)，重演「提早出場」的副作用；門檻在0.03%~0.05%
  區間全年代無一變差，0.05%表現最好且最乾淨：全樣本Calmar 291.64→317.62、
  2010起80.73→83.92、2015起72.25→74.54、2020起96.74→98.34、2022起66.46打平，
  故採用0.05%。

連續虧損暫停（2026-09-25新增，多空皆適用）：
  交易序列（不分方向）連續 LOSS_STREAK_TH 筆虧損後，接下來 PAUSE_DAYS 天內任何多方或
  空方訊號都跳過不進場，過了暫停期才恢復正常。判定連續虧損不限制兩筆虧損之間的時間
  間隔（測試過限制「間隔須<=20天才算連續」的嚴謹版，全樣本Calmar 213.32，效果較弱但
  更乾淨；也測過只暫停多方訊號的版本，全樣本211.80，同樣較弱。原版全年代無一變差且
  效果最強，全樣本Calmar 201.17→230.31，故採用不限間隔、多空皆暫停的原版）。
  移除的14筆交易裡有9筆虧錢/5筆賺錢，賺錢單合計(+21.6%)其實比虧錢單合計(-16.2%)還多，
  包含忍痛放棄2007/05/04那筆+13.59%的大單——採用這版是因為虧損單發生的時間點多在
  「已經連續虧損後」的脆弱期，砍掉它們對壓低MDD的幫助大於錯過那幾筆賺錢單，屬於用
  「風險調整後報酬」而非「總損益」衡量下的主觀取捨。

SHORT_SLOPE_TH 的選定過程：
  - 掃描 0% ~ -3% 多組門檻，全樣本(1997起)在 -0.5% 有最高Calmar，但用「近代加權分數」
    (2010起x1 + 2015起x2 + 2020起x3) 重新評分後，-0.6% 勝出，且在2020起、2022起
    這兩個最近期的子樣本都是三者(-0.5%/-0.6%/-0.75%)裡表現最好的，故採用 -0.6%。
  - 完整掃描過程與走勢驗證(train/test split)見對話紀錄與 STRATEGY_MEMO.md。

LONG_SLOPE_TH 的選定過程：
  - 掃描多方進場當下「10日均線近5日變化率」門檻，嚴格門檻(0%、-0.5%，要求動能已止穩)
    全面大幅拖累各年代表現(Calmar腰斬甚至更差)，判定拉回反彈訊號本來就需要帶一點短線
    下彎慣性，不宜要求動能已轉正。唯獨很寬鬆的 -1.5% 門檻（只排除最誇張的破底）在
    全樣本/2005/2010/2020起都小幅改善，2015/2022起幾乎打平，沒有任何一段明顯變差，
    故採用 -1.5% 當多方的輕量濾網。

多方第二條進場路徑「V轉」（2026-09-21新增）：
  進場：10日均線明顯低於60日均線(乖離 <= V_DEV_TH，代表深跌格局) + 前一日10日均線
        斜率還是負的、當日轉正(動能反轉確認) + 當日收盤站上10日均線
  這條路徑不要求站上60日均線，用意是抓「深跌後V轉反彈」，現有主規則要求站上60日均線
  會讓這類反彈錯過最兇猛的初升段(常常反彈10~25%後60日均線才追上來)。
  V_DEV_TH 選定過程：掃描-3%~-10%，全樣本Calmar在-7%最高(143.25)且是唯一「訊號集合
  是-5%版本子集合、分年代Calmar沒有輸過-5%版本任一段」的門檻，判定-5%多抓到的訊號
  裡有7成是虧損單，故採用更嚴格的-7%。單獨看這條路徑本身：22筆中13勝9敗(勝率59%)，
  9筆虧損有5筆集中在1997-98亞洲金融風暴、2008金融海嘯等系統性危機期間，代表這條路徑
  在系統性危機時特別容易失敗，屬於「低頻率、高賠率」的訊號，不建議單獨重壓。
  已驗證此路徑與其他進場路徑共用同一個「僅在空手時才進場」判斷，不會與其他交易重疊。

資料來源：台指現貨加權指數(^TWII)逐日OHLC 當代理（yfinance），非台指期貨本尊，回測結果
僅供研究參考。
"""

import argparse
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
from twii_prices import load_twii

# ─── 設定 ───────────────────────────────────────────────

RESULTS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tide_results.csv")

# 資料來源：twii=加權指數(預設，原始定案版)；txf_day=台指期近月日盤；txf_full=台指期近月日夜盤
# 期貨版需先跑 fetch_taifex_tx.py。策略訊號只看收盤價，日盤/日夜盤只差在MAE(高低點)。
SOURCES = {
    "twii": ("台指現貨(^TWII)代理", ""),
    "txf_day": ("台指期近月(日盤，比例後調)", "_txf_day"),
    "txf_full": ("台指期近月(日夜盤，比例後調)", "_txf_full"),
}

BACKTEST_START = "1997-07-02"
# yfinance的end參數不含當天，這裡固定取「今天+1天」，讓每次重跑都自動抓到最新資料，
# 不用手動改日期（之前這裡跟export_chart_data.py各自寫死不同日期，兩邊資料範圍會對不齊）。
BACKTEST_END = (date.today() + timedelta(days=1)).isoformat()

MA_SHORT = 10
MA_LONG = 60
EXIT_PCT = 2.0          # 多空出場都用：從極值回落/反彈這個百分比
SHORT_SLOPE_TH = -0.6   # 空方進場門檻：MA60過去10日變化率須低於此值
LONG_SLOPE_TH = -1.5    # 多方進場門檻：MA10過去5日變化率須不低於此值（排除極端破底）
V_DEV_TH = -7.0         # 多方「V轉」路徑：MA10相對MA60的乖離%須低於此值（深跌格局）
BB_PERIOD = 20          # 布林通道週期
BB_STD = 2              # 布林通道標準差倍數
BBW_PERCENTILE_TH = 80.0  # 空方進場門檻：通道寬度相對近一年百分位須 <= 此值
LOSS_STREAK_TH = 3      # 連續虧損暫停：達到這個連續虧損筆數就觸發暫停
PAUSE_DAYS = 30          # 連續虧損暫停：觸發後暫停交易的天數
BBU_NEAR_TH = 0.95       # 多方鎖利：收盤價在通道內的相對位置(pctB)須曾經 >= 此值才算貼近上緣
BBU_FLAT_DAYS = 2        # 多方鎖利：布林上緣連續這麼多天沒創新高，視為動能停滯
BBU_FLAT_TOLERANCE_PCT = 0.05  # 多方鎖利：容忍BBU日對日微幅上升(<=此%)仍算「沒創新高」


# ─── Step 1: 資料與指標 ─────────────────────────────────────

def load_raw_prices(source="twii"):
    """只載入 Date/Open/High/Low/Close（不含指標）。"""
    if source == "twii":
        return load_twii(BACKTEST_START, BACKTEST_END)
    from txf_prices import load_txf  # 期貨資料只有研究比較用到，推播不需要
    return load_txf("day" if source == "txf_day" else "full")


def load_price_data(source="twii"):
    return add_indicators(load_raw_prices(source))


def add_indicators(df):
    """計算策略用的全部指標（拆出來讓情境模擬可以在歷史後面接假設的K棒重算）。"""
    df = df.copy()
    df["MA_short"] = df["Close"].rolling(MA_SHORT).mean()
    df["MA_long"] = df["Close"].rolling(MA_LONG).mean()
    df["MA60_slope10_pct"] = (df["MA_long"] - df["MA_long"].shift(10)) / df["MA_long"].shift(10) * 100
    df["MA10_slope5_pct"] = (df["MA_short"] - df["MA_short"].shift(5)) / df["MA_short"].shift(5) * 100
    df["dev_ma10_ma60_pct"] = (df["MA_short"] - df["MA_long"]) / df["MA_long"] * 100

    bb_mid = df["Close"].rolling(BB_PERIOD).mean()
    bb_std = df["Close"].rolling(BB_PERIOD).std()
    df["BBU"] = bb_mid + BB_STD * bb_std
    bbl = bb_mid - BB_STD * bb_std
    bbw_pct = (df["BBU"] - bbl) / bb_mid * 100
    # 通道寬度相對「自己過去一年」的百分位排名，用來判斷現在是不是已經寬到極致（而非
    # 用絕對寬度數字，因為指數點位橫跨1997~2026漲了好幾倍，絕對寬度不能跨年代比較）
    df["BBW_percentile_1y"] = bbw_pct.rolling(252, min_periods=60).apply(
        lambda x: (x < x.iloc[-1]).sum() / len(x) * 100, raw=False
    )
    # 收盤價在通道內的相對位置：0=貼下軌，1=貼上軌，供多方鎖利機制判斷是否貼近上緣
    df["pctB_close"] = (df["Close"] - bbl) / (df["BBU"] - bbl)
    return df


# ─── Step 2: 單一部位互斥引擎（多方不濾網，空方套斜率+布林寬度濾網） ─────
#
# 「幻影單」機制（2026-09-25新增）：布林濾網擋掉的空單訊號，如果直接跳過讓帳戶恢復
# 空手，隔天附近常會有另一個訊號（延續同一段走勢的多單或空單）馬上遞補進場——本質上
# 是同一段行情的殘影，卻被算成獨立的兩筆交易。改成「假裝真的進場，照樣用出場規則算到
# 出場為止，但不寫進trades清單」，讓這段期間繼續佔住部位、擋掉遞補訊號。全樣本回測驗證
# 過這個機制後，各年代Calmar都小幅提升、無一變差（全樣本196.25→201.17等），故採用。

def simulate_combined(df, return_state=False):
    """單一部位互斥引擎。return_state=True 時另外回傳資料結束當下的部位狀態（情境表、每日推播用）。

    逐日迴圈直接讀 numpy 陣列（不用 df.iloc），情境表每個假設價位都要重跑全歷史，速度差很多。
    """
    dates = list(df["Date"])
    H, L, C = (df[k].to_numpy(dtype=float) for k in ["High", "Low", "Close"])
    ma_s, ma_l = df["MA_short"].to_numpy(), df["MA_long"].to_numpy()
    s60, s10 = df["MA60_slope10_pct"].to_numpy(), df["MA10_slope5_pct"].to_numpy()
    dev, bbw_rank = df["dev_ma10_ma60_pct"].to_numpy(), df["BBW_percentile_1y"].to_numpy()
    bbu, pctb = df["BBU"].to_numpy(), df["pctB_close"].to_numpy()
    nan = np.isnan

    trades = []
    state = None              # None / 'long' / 'short'
    entry_idx = entry_price = extreme_close = None   # extreme_close：多單=持倉最高收盤，空單=持倉最低收盤
    entry_type = None         # 'normal' / 'v_reversal' / None(空方不分類)
    worst_mae = None          # 持倉期間日內高低點估算的最大不利波動%（槓桿壓力測試用）
    is_phantom = False        # 被布林濾網擋掉、只用來佔位的幻影空單，出場時不記錄
    consecutive_losses = 0    # 交易序列(不分多空)連續虧損筆數
    pause_until_date = None   # 連續虧損暫停到這一天（不含）
    ever_touched_upper = False  # 這筆多單持倉期間是否曾貼近布林上緣
    long_locked_leg = False     # 這筆多單已鎖利入帳，剩下只是佔位等自然出場

    def record(i, net_pct):
        """記一筆交易；i=None 代表資料結束時仍未平倉。"""
        last = len(C) - 1 if i is None else i
        row = {
            "side": state, "entry_type": entry_type,
            "entry_date": dates[entry_idx].date(), "exit_date": None if i is None else dates[i].date(),
            "days_held": (dates[last] - dates[entry_idx]).days,
            "entry_price": round(entry_price, 1), "exit_price": None if i is None else round(C[i], 1),
            "net_pct": net_pct, "worst_mae_pct": round(worst_mae, 2),
        }
        if i is None:
            sign = 1 if state == "long" else -1
            row["open_pnl_pct"] = round((C[last] - entry_price) / entry_price * 100 * sign, 2)
        trades.append(row)

    def count_result(i, net_pct):
        """更新連續虧損計數；滿 LOSS_STREAK_TH 筆就從出場日起暫停 PAUSE_DAYS 天。"""
        nonlocal consecutive_losses, pause_until_date
        consecutive_losses = consecutive_losses + 1 if net_pct <= 0 else 0
        if consecutive_losses >= LOSS_STREAK_TH:
            pause_until_date = dates[i] + pd.Timedelta(days=PAUSE_DAYS)
            consecutive_losses = 0

    for i in range(1, len(C)):
        if nan(ma_s[i]) or nan(ma_l[i]) or nan(ma_s[i - 1]) or nan(s10[i - 1]):
            continue
        c, pc = C[i], C[i - 1]

        if state is None:
            if pause_until_date is not None and dates[i] < pause_until_date:
                continue  # 連續虧損暫停期間：任何訊號都跳過，帳戶維持空手
            normal_long = (c > ma_l[i] and pc < ma_s[i - 1] and c > ma_s[i]
                           and not nan(s10[i]) and s10[i] >= LONG_SLOPE_TH)
            v_reversal = (s10[i - 1] < 0 and s10[i] >= 0 and not nan(dev[i]) and dev[i] <= V_DEV_TH
                          and c > ma_s[i])
            short_signal = (c < ma_l[i] and pc > ma_s[i - 1] and c < ma_s[i]
                            and not nan(s60[i]) and s60[i] < SHORT_SLOPE_TH)
            if normal_long or v_reversal:
                state, entry_idx, entry_price, extreme_close = "long", i, c, c
                entry_type = "normal" if normal_long else "v_reversal"
                worst_mae = max(0.0, (c - L[i]) / c * 100)  # 進場當天自己的盤中低點也算進MAE
                ever_touched_upper = not nan(pctb[i]) and pctb[i] >= BBU_NEAR_TH
                long_locked_leg = False
            elif short_signal:
                # 布林寬度濾網沒過 → 幻影空單：照出場規則佔住部位、擋掉遞補訊號，但不記錄
                state, entry_idx, entry_price, extreme_close = "short", i, c, c
                entry_type = None
                worst_mae = max(0.0, (H[i] - c) / c * 100)
                is_phantom = not (nan(bbw_rank[i]) or bbw_rank[i] <= BBW_PERCENTILE_TH)

        elif state == "long":
            extreme_close = max(extreme_close, c)
            worst_mae = max(worst_mae, (extreme_close - L[i]) / extreme_close * 100)
            dd = (extreme_close - c) / extreme_close * 100
            if not nan(pctb[i]) and pctb[i] >= BBU_NEAR_TH:
                ever_touched_upper = True

            if not long_locked_leg and ever_touched_upper and dd < EXIT_PCT and not nan(bbu[i]):
                cur_profit_pct = (c - entry_price) / entry_price * 100
                bbu_flat = all(
                    i - k - 1 >= 0 and not nan(bbu[i - k]) and not nan(bbu[i - k - 1])
                    and bbu[i - k] <= bbu[i - k - 1] * (1 + BBU_FLAT_TOLERANCE_PCT / 100)
                    for k in range(BBU_FLAT_DAYS))
                if bbu_flat and cur_profit_pct > 0:
                    # 貼近過上緣、動能停滯：鎖利入帳，但部位不釋放，繼續追蹤到自然出場
                    record(i, round(cur_profit_pct, 2))
                    consecutive_losses = 0
                    long_locked_leg = True

            if dd >= EXIT_PCT:
                if not long_locked_leg:
                    net_pct = round((c - entry_price) / entry_price * 100, 2)
                    record(i, net_pct)
                    count_result(i, net_pct)
                state, long_locked_leg = None, False

        else:  # short
            extreme_close = min(extreme_close, c)
            worst_mae = max(worst_mae, (H[i] - extreme_close) / extreme_close * 100)
            if (c - extreme_close) / extreme_close * 100 >= EXIT_PCT:
                if not is_phantom:
                    net_pct = round((entry_price - c) / entry_price * 100, 2)
                    record(i, net_pct)
                    count_result(i, net_pct)
                state, is_phantom = None, False

    # 資料結束時仍持有的部位（幻影單不算；已鎖利入帳的多單那段損益已記錄，不重複）
    if state is not None and not is_phantom and not (state == "long" and long_locked_leg):
        record(None, None)

    if return_state:
        held = state is not None
        state_info = {
            "state": state, "is_phantom": is_phantom, "long_locked_leg": long_locked_leg,
            "entry_date": dates[entry_idx].date() if held else None,
            "entry_price": entry_price if held else None,
            "entry_type": entry_type if held else None,
            "extreme_close": extreme_close if held else None,
            "ever_touched_upper": ever_touched_upper if state == "long" else None,
            "consecutive_losses": consecutive_losses, "pause_until_date": pause_until_date,
        }
        return pd.DataFrame(trades), state_info
    return pd.DataFrame(trades)


# ─── Step 3: 報告 ─────────────────────────────────────────

def compound_stats(trades_df):
    trades_df = trades_df[trades_df["net_pct"].notna()]  # 未平倉部位不計入績效
    if trades_df.empty:
        return None
    r = trades_df["net_pct"].values / 100.0
    equity = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(equity)
    dd = (equity - running_max) / running_max
    max_dd = dd.min() * 100
    wins = r > 0
    total_return = (equity[-1] - 1) * 100
    calmar = total_return / abs(max_dd) if max_dd != 0 else float("nan")
    return {
        "n": len(trades_df), "n_long": (trades_df["side"] == "long").sum(),
        "n_short": (trades_df["side"] == "short").sum(), "win_rate": wins.mean() * 100,
        "total_return": total_return, "equity_multiple": equity[-1], "max_dd": max_dd, "calmar": calmar,
    }


def print_report(trades_df, source="twii"):
    print("=" * 70)
    print(f"  潮汐策略最終定案版回測（多方+空方，{SOURCES[source][0]}）")
    print("=" * 70)

    # 1999起：台指期1998/07才上市，暖機後的第一個共同比較區間
    for era_name, start in [("全樣本", "1997-01-01"), ("1999起", "1999-01-01"), ("2010起", "2010-01-01"),
                             ("2015起", "2015-01-01"), ("2020起", "2020-01-01"), ("2022起", "2022-01-01")]:
        sub = trades_df[trades_df["entry_date"] >= pd.Timestamp(start).date()]
        s = compound_stats(sub)
        if s is None:
            print(f"\n{era_name}: 無交易")
            continue
        print(f"\n{era_name}")
        print(f"  筆數={s['n']}（多{s['n_long']}/空{s['n_short']}）  勝率={s['win_rate']:.1f}%")
        print(f"  複利總報酬={s['total_return']:+.1f}%  本金變為{s['equity_multiple']:.2f}倍")
        print(f"  最大回撤={s['max_dd']:.1f}%  Calmar比={s['calmar']:.2f}")


def save_results(trades_df, source="twii"):
    path = RESULTS_CSV.replace(".csv", f"{SOURCES[source][1]}.csv")
    trades_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n結果已儲存至: {path}")


# ─── 主程式 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=list(SOURCES), default="twii")
    source = parser.parse_args().source

    print(f"[Step 1] 載入逐日資料：{SOURCES[source][0]}...")
    df = load_price_data(source)
    print(f"  取得 {len(df)} 個交易日 ({df['Date'].min().date()} ~ {df['Date'].max().date()})")

    print("\n[Step 2] 模擬多空互斥進出場...")
    trades_df = simulate_combined(df)

    print("\n[Step 3] 輸出報告...")
    print_report(trades_df, source)
    save_results(trades_df, source)


if __name__ == "__main__":
    main()
