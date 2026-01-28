# 破底翻（C型）事件偵測器

## 簡介

這是一個量化交易策略的事件偵測器，用於識別股票價格的「破底翻」型態：
- **盤整期（Consolidation）**: 價格在一定範圍內波動
- **假跌破（Breakdown）**: 價格短暫跌破盤整區間下緣
- **收回箱底（Reclaim）**: 價格快速收回盤整區間，確認破底翻型態

## 策略邏輯

### Step 1: 計算 ATR (Average True Range)
- **公式**: `TR = max(High - Low, |High - Close_prev|, |Low - Close_prev|)`
- **ATR14**: 14 日 True Range 的移動平均
- **用途**: 衡量價格波動度，用於設定跌破閾值

### Step 2: 偵測多日盤整
- **盤整判斷條件**（使用 20 日 rolling window）:
  1. `box_range_pct = (box_high - box_low) / Close < 8%`
  2. `ATR14 / Close < 2.5%`
- **避免 look-ahead**: 使用 rolling window 確保只用過去資料

### Step 3: 偵測假跌破（Breakdown）
- **跌破條件**:
  - 必須在盤整期間
  - `Low < box_low_ref - 0.5 * ATR14`
- **避免 look-ahead**: `box_low_ref` 使用前一日的 `box_low`

### Step 4: 偵測收回箱底（Reclaim）
- **收回條件**:
  - 在 breakdown 後 1~2 天內
  - `Close > box_low_ref_at_breakdown`
- **標記首次收回**: 只記錄首次收回事件

## 檔案結構

```
Qtrading/
├── modules/
│   └── breakout_detector.py          # 核心偵測模組
├── test_breakout_c_pattern.py        # 批次掃描所有股票
├── view_c_pattern_detail.py          # 單支股票詳細檢視
├── test_output/
│   └── c_pattern_events_*.csv        # 輸出結果
└── C_PATTERN_README.md                # 本文件
```

## 使用方法

### 1. 批次掃描所有股票

```bash
python test_breakout_c_pattern.py
```

**功能**:
- 從 SQLite 資料庫載入所有股票的歷史資料
- 對每支股票執行破底翻偵測
- 輸出事件清單到 CSV 檔案

**輸出**:
- 檔案位置: `test_output/c_pattern_events_YYYYMMDD_HHMMSS.csv`
- 欄位說明:
  - `code`: 股票代碼
  - `breakdown_date`: 跌破日期
  - `reclaim_date`: 收回日期
  - `reclaim_lag`: 收回延遲天數（1 或 2）
  - `close_at_reclaim`: 收回日收盤價
  - `box_low_ref`: 箱底參考價
  - `reclaim_pct`: 收回幅度百分比

### 2. 單支股票詳細檢視

```bash
python view_c_pattern_detail.py <股票代碼>
```

**範例**:
```bash
python view_c_pattern_detail.py 3034
```

**功能**:
- 顯示該股票所有 breakdown 和 reclaim 事件
- 顯示事件前後 5 天的詳細技術指標
- 包含：ATR、box_high、box_low、盤整狀態等

### 3. 在程式中使用

```python
from modules.database import load_recent_prices
from modules.breakout_detector import detect_c_pattern, summarize_c_pattern_events

# 載入資料
hist = load_recent_prices(days=120)
stock_df = hist[hist['code'] == '2330'].copy()

# 執行偵測
result_df = detect_c_pattern(stock_df)

# 彙整事件
events = summarize_c_pattern_events(result_df)
print(events)
```

## 參數調整

可以在呼叫 `detect_c_pattern()` 時調整參數：

```python
result_df = detect_c_pattern(
    df,
    atr_period=14,                      # ATR 週期（預設 14）
    consolidation_window=20,             # 盤整判斷視窗（預設 20）
    consolidation_range_pct=0.08,       # 盤整區間上限（預設 8%）
    consolidation_atr_pct=0.025,        # ATR 佔比上限（預設 2.5%）
    breakdown_k_atr=0.5,                # 跌破閾值 ATR 倍數（預設 0.5）
    reclaim_max_lag=2                   # 收回檢查天數（預設 2）
)
```

## 測試結果

在 40 支台股上測試（資料期間：2025-10-01 ~ 2026-01-23）:

- **總事件數**: 3 個
- **涵蓋股票**: 3 支（3034, 2886, 2002）
- **收回延遲**: 全部為 1 天收回
- **收回幅度**: 1.8% ~ 5.0%

### 範例事件（股票 3034）

| 日期 | 事件 | 收盤價 | 最低價 | 箱底參考 | 說明 |
|------|------|--------|--------|----------|------|
| 2026-01-05 | BREAKDOWN | 363.0 | 360.0 | 367.0 | 跌破箱底 |
| 2026-01-06 | RECLAIM | 378.0 | 365.5 | 360.0 | 收回箱底 +5% |

## 注意事項

### 1. 資料需求
- 至少需要 40 天的歷史資料（20天盤整 + 14天ATR + 緩衝）
- 資料來源：SQLite 資料庫 `taiex.sqlite`
- 確保執行前已更新股價資料

### 2. Look-ahead Bias 防範
- 盤整判斷使用 rolling window（只看過去）
- 跌破判斷使用前一日的 box_low
- reclaim 偵測雖然需要未來資料，但邏輯符合時序性

### 3. 效能考量
- 批次掃描 40 支股票約需 0.5 秒
- 適合每日執行一次
- 建議資料更新後再執行掃描

## 進階應用

### 1. 整合到主策略
可以將破底翻事件作為選股條件之一，與現有的動能策略結合：

```python
from modules.breakout_detector import detect_c_pattern, summarize_c_pattern_events

# 在 pick_stocks 之前先篩選有破底翻事件的股票
def enhanced_pick_stocks(prices):
    # 先執行破底翻偵測
    c_pattern_stocks = []
    for code in prices['code'].unique():
        stock_df = prices[prices['code'] == code]
        result_df = detect_c_pattern(stock_df)
        events = summarize_c_pattern_events(result_df)
        if not events.empty:
            c_pattern_stocks.append(code)

    # 在破底翻股票中選股
    filtered_prices = prices[prices['code'].isin(c_pattern_stocks)]
    return pick_stocks(filtered_prices)
```

### 2. 設定篩選條件
例如只選擇收回幅度 > 3% 的事件：

```python
events = summarize_c_pattern_events(result_df)
strong_events = events[events['reclaim_pct'] > 3.0]
```

### 3. 回測驗證
建議使用歷史資料進行回測，驗證破底翻型態的實際效果。

## 技術限制

1. **參數敏感性**: 盤整判斷的閾值（8%, 2.5%）需根據市場狀況調整
2. **樣本數少**: 當前測試期間短，事件數量較少
3. **未包含交易邏輯**: 本模組只做事件標記，不產生買賣建議

## 後續改進方向

- [ ] 增加更多盤整型態識別（如 W底、頭肩底）
- [ ] 支援自適應參數（根據市場波動度動態調整）
- [ ] 整合成交量分析（破底翻時的量能變化）
- [ ] 建立回測框架，驗證策略效果
- [ ] 視覺化：繪製 K 線圖標註破底翻事件

## 授權與貢獻

本模組為 Qtrading 專案的一部分，遵循專案授權協議。
