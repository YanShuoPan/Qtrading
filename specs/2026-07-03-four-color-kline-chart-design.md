# 四色指標互動 K 線圖 — 設計文件

日期：2026-07-03
狀態：已與使用者確認定案

## 背景與目標

目前網頁上的股票卡片點擊後開啟 Yahoo Finance 技術分析頁，無法呈現自訂的「四色指標」。
本設計以 ECharts 自建互動 K 線圖頁，K 棒依四色指標上色，取代 Yahoo 連結。

## 已確認的決策

| 決策 | 結果 |
|------|------|
| 指標公式 | Close vs MA20（均價）× Volume vs MA20（均量）2×2 矩陣 |
| 週期 N | 均價、均量皆 20 日 |
| 呈現方式 | K 棒本體直接塗四色 |
| 涵蓋範圍 | 全部 1,224 支（taiex.sqlite prices 表內全部股票） |
| 圖表函式庫 | ECharts 5（CDN 載入，無建置流程） |
| 入口 | html_generator 的股票卡片連結改為 chart.html?code={code} |

## 四色判定邏輯

```
ma20  = MA(close, 20)
vma20 = MA(volume, 20)

close > ma20 且 volume > vma20  → 紅 red    帶量翻紅（偏買進）
close < ma20 且 volume > vma20  → 綠 green  帶量翻黑（偏賣出）
close > ma20 且 volume ≤ vma20  → 黃 yellow 偏強、量未確認
close < ma20 且 volume ≤ vma20  → 藍 blue   偏弱、量未確認
close == ma20                   → 併入「> ma20」處理（紅/黃）
MA 暖身期（前 19 天）            → 灰 gray   無訊號
```

顏色代碼：紅 `#E74C3C`、綠 `#27AE60`、黃 `#F1C40F`、藍 `#3498DB`、灰 `#95A5A6`。

## 資料流

```
每日 CI (main.py)
  └─ taiex.sqlite (prices 表)
       └─ modules/chart_data_generator.py（新模組）
            ├─ 每支股票取近 140 個交易日 OHLCV（20 天 MA 暖身 + 約 120 根顯示）
            ├─ 計算 ma20、vma20、逐日四色
            └─ 輸出 docs/chart_data/{code}.json × 全部股票
  └─ peaceiris 部署到 gh-pages（keep_files 同名覆蓋）

瀏覽器
  └─ 股票卡片 → chart.html?code=2330
       └─ fetch chart_data/2330.json → ECharts 渲染
```

## JSON 格式（每支一檔，約 10KB）

```json
{
  "code": "2330",
  "name": "台積電",
  "updated": "2026-07-03",
  "days": [
    ["2026-01-05", 585.0, 592.0, 583.0, 590.0, 32450, 578.3, 28100, "red"]
  ]
}
```

欄位順序：`[date, open, high, low, close, volume(張), ma20, vma20, color]`；
ma20/vma20 暖身期為 null。陣列格式為壓縮檔案大小。

## 前端 chart.html

- 注意：`docs/` 在 main 分支被 gitignore（CI 產物目錄），故 chart.html 源檔放在
  `static/chart.html`（git 追蹤），由 main.py 產生圖表資料時一併複製到 `docs/chart.html`
- 單一靜態頁，ECharts 5 由 jsdelivr CDN 載入
- 讀 `?code=` 參數 fetch 對應 JSON
- 主圖：四色 K 棒（per-item itemStyle，漲跌同色）+ MA20 灰色虛線
- 副圖：成交量柱（同步四色）；dataZoom 滑桿 + 觸控縮放
- tooltip：開高低收、量、均量、顏色訊號中文說明（如「帶量翻紅」）
- 頁首：代碼/名稱、四色圖例說明、Yahoo 技術分析備用連結
- 手機可用

## 既有程式修改

1. `modules/html_generator.py`：6 處 Yahoo 連結改為 `chart.html?code={code}`
2. `main.py`：流程尾端新增「產生圖表資料」步驟，失敗 log warning 不中斷
3. `.github/workflows/daily.yml`：
   - 兩處 `git fetch origin gh-pages` 加 `--depth 1`（抑制歷史增長造成的變慢）
   - 確認 7 天清理腳本不誤刪 chart_data/（該腳本只掃根目錄 *.html，不動資料夾）

## 錯誤處理

- JSON 不存在（新上市、DB 無資料）→ chart.html 顯示「暫無圖表資料」+ Yahoo 備用連結
- 個股資料 < 40 天 → 照畫，MA 不足部分灰色
- 單股產生失敗 → log warning、跳過、繼續（永不中斷 pipeline 原則）
- 迴圈內不用 logger.info，結束後彙整（`完成: N 支 / 失敗: M 支`）

## 測試

- `tests/test_chart_data.py`（pytest）：
  - 四色邊界條件（close 恰等於 ma20、volume 恰等於 vma20）
  - MA 暖身期灰色
  - 資料不足股票的行為
  - JSON 輸出格式與欄位順序

## 部署影響評估（已確認可接受）

- 全部 JSON 約 12MB，CI 產生時間約 10 秒內，對整體 pipeline 無感
- gh-pages git 歷史每日增長約 1-2MB（差異壓縮後），以 `--depth 1` 抑制 fetch 變慢
- GitHub Pages 大小/流量限制均遠未觸及；使用者每次看圖僅載入單支 ~10KB JSON
