# 四色指標互動 K 線圖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 ECharts 自建互動 K 線圖頁（K 棒依四色指標上色），取代網頁上的 Yahoo Finance 連結。

**Architecture:** 每日 pipeline 新增一步：從 taiex.sqlite 撈全部股票近 140 交易日 OHLCV，Python 端計算 MA20 均價/均量與逐日四色，輸出 `docs/chart_data/{code}.json`；靜態頁 `static/chart.html`（CI 時複製到 docs/）用 ECharts 讀 `?code=` 渲染。html_generator 的 6 處 Yahoo 連結改指向 chart.html。

**Tech Stack:** Python 3.11 + pandas + sqlite3（後端資料產生）、ECharts 5 CDN（前端）、pytest（測試）。

**Spec:** `specs/2026-07-03-four-color-kline-chart-design.md`

**注意：** `docs/` 在 main 分支被 gitignore，靜態源檔一律放 `static/`，執行期才複製到 docs/。

---

## File Structure

| 檔案 | 動作 | 職責 |
|------|------|------|
| `modules/chart_data_generator.py` | Create | 四色計算 + JSON 輸出 + 複製 chart.html |
| `tests/test_chart_data.py` | Create | 四色邊界條件與 JSON 輸出測試 |
| `static/chart.html` | Create | ECharts 互動圖頁（唯一前端檔案） |
| `main.py` | Modify（步驟 6.7 之後） | 新增步驟 6.75 產生圖表資料 |
| `modules/html_generator.py` | Modify（6 處） | Yahoo 連結 → chart.html?code= |
| `.github/workflows/daily.yml` | Modify（1 處） | gh-pages fetch 加 --depth 1 |

---

### Task 1: 四色判定核心 `compute_four_color`

**Files:**
- Create: `modules/chart_data_generator.py`
- Test: `tests/test_chart_data.py`

- [ ] **Step 1: Write the failing tests**

建立 `tests/test_chart_data.py`：

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chart_data.py -v --tb=short`
Expected: 全部 FAIL，錯誤為 `ModuleNotFoundError: No module named 'modules.chart_data_generator'`

- [ ] **Step 3: Write minimal implementation**

建立 `modules/chart_data_generator.py`：

```python
"""
圖表資料產生模組 - 為互動 K 線圖產生每支股票的 JSON（含四色指標）

四色定義（N=20）：
  close >= ma20 且 volume >  vma20 → red    帶量翻紅
  close <  ma20 且 volume >  vma20 → green  帶量翻黑
  close >= ma20 且 volume <= vma20 → yellow 偏強、量未確認
  close <  ma20 且 volume <= vma20 → blue   偏弱、量未確認
  MA 暖身期                         → gray   無訊號
"""
import numpy as np
import pandas as pd

from .logger import get_logger

logger = get_logger(__name__)

MA_PERIOD = 20


def compute_four_color(df: pd.DataFrame, n: int = MA_PERIOD) -> pd.DataFrame:
    """計算 N 日均價/均量與四色指標

    Args:
        df: 需含 close、volume 欄位，依日期由舊到新排序
        n: 均價/均量週期

    Returns:
        pd.DataFrame: 原欄位 + ma20 / vma20 / color 的複本
    """
    out = df.copy()
    out["ma20"] = out["close"].rolling(n, min_periods=n).mean()
    out["vma20"] = out["volume"].rolling(n, min_periods=n).mean()

    strong = out["close"] >= out["ma20"]
    heavy = out["volume"] > out["vma20"]
    warmup = out["ma20"].isna() | out["vma20"].isna()

    out["color"] = np.select(
        [warmup, strong & heavy, ~strong & heavy, strong],
        ["gray", "red", "green", "yellow"],
        default="blue",
    )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_chart_data.py -v --tb=short`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add modules/chart_data_generator.py tests/test_chart_data.py
git commit -m "feat: 新增四色指標計算模組 compute_four_color"
```

---

### Task 2: JSON 輸出 `generate_chart_data`

**Files:**
- Modify: `modules/chart_data_generator.py`（追加函數）
- Test: `tests/test_chart_data.py`（追加測試）

- [ ] **Step 1: Write the failing tests**

在 `tests/test_chart_data.py` 頂部 import 區加入：

```python
import json
import os
import sqlite3
```

檔案尾端追加：

```python
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
```

（`test_generate_chart_data_copies_chart_html` 依賴 Task 3 的 `static/chart.html`；
Task 3 完成前允許它 FAIL，Task 3 完成後必須 PASS。）

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chart_data.py -v --tb=short`
Expected: 新增 2 個測試 FAIL（`ImportError: cannot import name 'generate_chart_data'`），原 7 個 PASS

- [ ] **Step 3: Write implementation**

在 `modules/chart_data_generator.py` 頂部 import 區改為：

```python
import json
import os
import shutil
import sqlite3

import numpy as np
import pandas as pd

from .config import DB_PATH
from .logger import get_logger
from .stock_codes import get_stock_name

logger = get_logger(__name__)

MA_PERIOD = 20
DAYS_TO_EXPORT = 140  # 20 天 MA 暖身 + 約 120 根顯示
```

檔案尾端追加：

```python
def generate_chart_data(output_dir: str = "docs", db_path: str = None) -> int:
    """為資料庫中全部股票產生互動圖 JSON，並複製 chart.html 到 output_dir

    單股失敗時跳過並繼續（永不中斷 pipeline）。

    Returns:
        int: 成功產生的股票數
    """
    db_path = db_path or DB_PATH
    chart_dir = os.path.join(output_dir, "chart_data")
    os.makedirs(chart_dir, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        prices = pd.read_sql_query(
            "SELECT code, date, open, high, low, close, volume "
            "FROM prices ORDER BY code, date",
            conn,
        )

    ok, fail = 0, 0
    for code, g in prices.groupby("code"):
        try:
            g = g.tail(DAYS_TO_EXPORT).reset_index(drop=True)
            g["volume"] = (g["volume"] // 1000).astype(int)  # 股 → 張
            g = compute_four_color(g)
            days = [
                [
                    r.date, r.open, r.high, r.low, r.close, int(r.volume),
                    None if pd.isna(r.ma20) else round(float(r.ma20), 2),
                    None if pd.isna(r.vma20) else int(round(float(r.vma20))),
                    r.color,
                ]
                for r in g.itertuples()
            ]
            payload = {
                "code": code,
                "name": get_stock_name(code),
                "updated": g["date"].iloc[-1],
                "days": days,
            }
            with open(os.path.join(chart_dir, f"{code}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            ok += 1
        except Exception as e:
            logger.debug(f"{code} 圖表資料產生失敗: {e}")
            fail += 1

    src = os.path.join(os.path.dirname(__file__), "..", "static", "chart.html")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(output_dir, "chart.html"))
    else:
        logger.warning("⚠️ static/chart.html 不存在，略過複製")

    logger.info(f"✅ 圖表資料完成: {ok} 支成功, {fail} 支失敗")
    return ok
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_chart_data.py -v --tb=short`
Expected: `test_generate_chart_data_writes_json` PASS；
`test_generate_chart_data_copies_chart_html` FAIL（static/chart.html 尚未建立，Task 3 解決）；其餘 PASS

- [ ] **Step 5: Commit**

```bash
git add modules/chart_data_generator.py tests/test_chart_data.py
git commit -m "feat: 新增 generate_chart_data 輸出全股票圖表 JSON"
```

---

### Task 3: 前端頁面 `static/chart.html`

**Files:**
- Create: `static/chart.html`

- [ ] **Step 1: 建立完整頁面**

建立 `static/chart.html`（完整內容如下）：

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>四色 K 線圖</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Microsoft JhengHei', sans-serif; background: #f5f6fa; }
  .header { background: white; padding: 12px 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
            display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .title { font-size: 1.2em; font-weight: bold; color: #1e293b; }
  .updated { color: #94a3b8; font-size: .85em; }
  .yahoo-link { margin-left: auto; font-size: .85em; color: #2563eb; text-decoration: none; }
  .legend { display: flex; gap: 10px; padding: 8px 16px; flex-wrap: wrap; font-size: .82em; color: #475569; }
  .legend span::before { content: "■ "; }
  .lg-red::before    { color: #E74C3C; }
  .lg-green::before  { color: #27AE60; }
  .lg-yellow::before { color: #F1C40F; }
  .lg-blue::before   { color: #3498DB; }
  .lg-gray::before   { color: #95A5A6; }
  #chart { width: 100%; height: calc(100vh - 110px); min-height: 420px; }
  .error { text-align: center; padding: 60px 20px; color: #64748b; }
  .error a { color: #2563eb; }
</style>
</head>
<body>
<div class="header">
  <span class="title" id="title">載入中…</span>
  <span class="updated" id="updated"></span>
  <a class="yahoo-link" id="yahoo" target="_blank">Yahoo 技術分析 ↗</a>
</div>
<div class="legend">
  <span class="lg-red">帶量翻紅（偏買進）</span>
  <span class="lg-green">帶量翻黑（偏賣出）</span>
  <span class="lg-yellow">偏強、量未確認</span>
  <span class="lg-blue">偏弱、量未確認</span>
  <span class="lg-gray">均線暖身期</span>
</div>
<div id="chart"></div>
<script>
const COLORS = { red: '#E74C3C', green: '#27AE60', yellow: '#F1C40F',
                 blue: '#3498DB', gray: '#95A5A6' };
const SIGNALS = { red: '帶量翻紅（偏買進）', green: '帶量翻黑（偏賣出）',
                  yellow: '偏強、量未確認', blue: '偏弱、量未確認',
                  gray: '均線暖身期' };

const code = new URLSearchParams(location.search).get('code');
const yahooUrl = 'https://tw.stock.yahoo.com/quote/' + code + '.TW/technical-analysis';
document.getElementById('yahoo').href = yahooUrl;

function showError(msg) {
  document.getElementById('title').textContent = code || '未指定股票';
  document.getElementById('chart').innerHTML =
    '<div class="error"><p>' + msg + '</p><p style="margin-top:12px;">' +
    '<a href="' + yahooUrl + '" target="_blank">改用 Yahoo 技術分析 ↗</a></p></div>';
}

if (!code) {
  showError('網址缺少 ?code= 參數');
} else {
  fetch('chart_data/' + code + '.json')
    .then(r => { if (!r.ok) throw new Error('not found'); return r.json(); })
    .then(render)
    .catch(() => showError('暫無此股票的圖表資料'));
}

function render(data) {
  document.getElementById('title').textContent = data.code + ' ' + data.name;
  document.getElementById('updated').textContent = '更新至 ' + data.updated;
  document.title = data.code + ' ' + data.name + ' - 四色 K 線圖';

  const dates = [], kbars = [], vols = [], ma20 = [];
  for (const d of data.days) {
    // d = [date, open, high, low, close, volume(張), ma20, vma20, color]
    const c = COLORS[d[8]] || COLORS.gray;
    dates.push(d[0]);
    kbars.push({ value: [d[1], d[4], d[3], d[2]],  // ECharts: [open, close, low, high]
                 itemStyle: { color: c, color0: c, borderColor: c, borderColor0: c },
                 signal: d[8], vma20: d[7] });
    vols.push({ value: d[5], itemStyle: { color: c } });
    ma20.push(d[6]);
  }

  const chart = echarts.init(document.getElementById('chart'));
  chart.setOption({
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: function (params) {
        const i = params[0].dataIndex;
        const d = data.days[i];
        const lines = [
          '<b>' + d[0] + '</b>',
          '開 ' + d[1] + '　高 ' + d[2],
          '低 ' + d[3] + '　收 ' + d[4],
          '量 ' + d[5].toLocaleString() + ' 張' +
            (d[7] ? '（均量 ' + d[7].toLocaleString() + '）' : ''),
          d[6] ? 'MA20 ' + d[6] : '',
          '<b style="color:' + (COLORS[d[8]] || '#888') + '">● ' +
            (SIGNALS[d[8]] || '') + '</b>',
        ];
        return lines.filter(Boolean).join('<br>');
      },
    },
    grid: [
      { left: 55, right: 20, top: 20, height: '58%' },
      { left: 55, right: 20, top: '72%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0,
        axisLabel: { show: false }, axisPointer: { show: true } },
      { type: 'category', data: dates, gridIndex: 1 },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#eee' } } },
      { gridIndex: 1, axisLabel: { formatter: v => (v >= 10000 ? (v / 1000) + 'k' : v) },
        splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 55, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], top: '92%', start: 55, end: 100 },
    ],
    series: [
      { name: 'K線', type: 'candlestick', data: kbars,
        xAxisIndex: 0, yAxisIndex: 0 },
      { name: 'MA20', type: 'line', data: ma20, xAxisIndex: 0, yAxisIndex: 0,
        showSymbol: false, lineStyle: { width: 1.5, type: 'dashed', color: '#7f8c8d' } },
      { name: '成交量', type: 'bar', data: vols, xAxisIndex: 1, yAxisIndex: 1 },
    ],
  });
  window.addEventListener('resize', () => chart.resize());
}
</script>
</body>
</html>
```

- [ ] **Step 2: Run tests（Task 2 的複製測試現在應通過）**

Run: `pytest tests/test_chart_data.py -v --tb=short`
Expected: 9 passed（含 `test_generate_chart_data_copies_chart_html`）

- [ ] **Step 3: 本地實際渲染驗證**

```bash
python -c "from modules.chart_data_generator import generate_chart_data; generate_chart_data()"
python -m http.server 8000 --directory docs
```

瀏覽器開 `http://localhost:8000/chart.html?code=2330` 檢查：
- K 棒有四色、MA20 虛線、成交量柱同色
- tooltip 顯示開高低收/量/訊號中文
- dataZoom 縮放正常
- `http://localhost:8000/chart.html?code=9999` 顯示「暫無此股票的圖表資料」+ Yahoo 備援連結

- [ ] **Step 4: Commit**

```bash
git add static/chart.html
git commit -m "feat: 新增 ECharts 四色 K 線互動圖頁 static/chart.html"
```

---

### Task 4: main.py 整合（步驟 6.75）

**Files:**
- Modify: `main.py`（步驟 6.7 區塊之後、步驟 7 之前，約 476 行）

- [ ] **Step 1: 加入步驟 6.75**

在 `main.py` 步驟 6.7 的 `except` 區塊結束後、`# ===== 步驟 7: 發送 LINE 訊息 =====` 之前插入：

```python
        # ===== 步驟 6.75: 產生互動圖表資料（四色 K 線）=====
        logger.info("\n📌 步驟 6.75: 產生互動圖表資料（四色 K 線）")
        try:
            from modules.chart_data_generator import generate_chart_data
            generate_chart_data(output_dir="docs")
        except Exception as e:
            logger.warning(f"⚠️ 圖表資料產生失敗（不影響主流程）: {e}")
```

- [ ] **Step 2: 驗證語法與整體測試**

```bash
python -m py_compile main.py
pytest tests/ -v --tb=short
```

Expected: py_compile 無輸出；既有測試全部 PASS

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main.py 新增步驟 6.75 產生四色圖表資料"
```

---

### Task 5: html_generator 連結替換（6 處）

**Files:**
- Modify: `modules/html_generator.py:126, 430, 489, 559, 723, 790`

- [ ] **Step 1: 替換 onclick 型（4 處：126、430、489、559 行）**

將

```
onclick="window.open('https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis', '_blank')"
```

全部替換為

```
onclick="window.open('chart.html?code={code}', '_blank')"
```

（559 行那處後面接著 `style=...`，只動 onclick 部分。）

- [ ] **Step 2: 替換 href 型（2 處：723、790 行）**

將

```
<a href="https://tw.stock.yahoo.com/quote/{code}.TW/technical-analysis"
```

全部替換為

```
<a href="chart.html?code={code}"
```

（相對路徑可行：所有日報/熱門股 HTML 與 chart.html 同在 gh-pages 根目錄。）

- [ ] **Step 3: 確認替換完整**

```bash
grep -n "tw.stock.yahoo.com" modules/html_generator.py
```

Expected: 無輸出（0 處殘留）

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add modules/html_generator.py
git commit -m "feat: 股票卡片連結改為自建四色 K 線圖頁"
```

---

### Task 6: daily.yml 調整

**Files:**
- Modify: `.github/workflows/daily.yml:194`

- [ ] **Step 1: 歷史 HTML 拉取改 shallow fetch**

第 194 行：

```yaml
          git fetch origin gh-pages:gh-pages 2>/dev/null || {
```

改為

```yaml
          git fetch --depth 1 origin gh-pages:gh-pages 2>/dev/null || {
```

（僅改這一處——此步驟只讀檔案。第 306 行的 fetch 之後會 commit+push，保守起見不動。）

- [ ] **Step 2: 確認清理腳本不會誤刪 chart_data**

檢查 daily.yml 340 行附近的清理邏輯：只掃根目錄 `*.html` 且排除 `index.html`/`*_hot.html`，
不會碰 `chart_data/` 資料夾。但 `chart.html` 會被當成日期 HTML 嗎？
檢視該 Python 片段的檔名過濾條件——它用日期格式解析檔名，`chart.html` 解析失敗會被跳過即安全；
若該腳本對解析失敗的檔名會刪除，需將 `chart.html` 加入排除清單。以實際程式碼為準，必要時修改。

- [ ] **Step 3: YAML 語法驗證**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/daily.yml', encoding='utf-8'))"
```

Expected: 無輸出（語法正確）

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/daily.yml
git commit -m "chore: gh-pages 歷史拉取改 shallow fetch 抑制變慢"
```

---

### Task 7: 端到端驗證

- [ ] **Step 1: 全量產生**

```bash
python -c "from modules.chart_data_generator import generate_chart_data; import time; t=time.time(); n=generate_chart_data(); print(f'{n} 支, {time.time()-t:.1f} 秒')"
```

Expected: 約 1224 支成功、時間 < 60 秒、`docs/chart_data/` 約 12MB

- [ ] **Step 2: 抽查多支股票渲染**

`python -m http.server 8000 --directory docs` 後抽查：
- `chart.html?code=2330`（上市大型股）
- 一支上櫃股（從 docs/chart_data/ 任選 6 開頭代碼）
- 一支低價冷門股（確認量柱與 tooltip 正常）

- [ ] **Step 3: 跑完整測試**

Run: `pytest tests/ -v --tb=short`
Expected: 全部 PASS

- [ ] **Step 4: 最終 commit（如有殘餘變更）**

```bash
git status
git add -A -- ':!docs'
git commit -m "feat: 四色 K 線互動圖完成"
```

---

## Self-Review 紀錄

- Spec 覆蓋：四色邏輯（Task 1）、JSON 輸出（Task 2）、chart.html（Task 3）、main.py（Task 4）、連結替換（Task 5）、daily.yml（Task 6）、錯誤處理（Task 2 skip + Task 3 fallback 頁）、測試（Task 1/2）——全數對應。
- 型別一致：`generate_chart_data(output_dir, db_path)` 於 Task 2 定義、Task 4/7 呼叫一致；JSON 欄位順序 9 欄在 Task 2 與 Task 3 前端註解一致。
- 已知妥協：volume 以整張輸出（股 ÷1000）；Yahoo 備援連結一律 .TW（沿用既有行為，上櫃股連過去 Yahoo 會自動轉向）。
