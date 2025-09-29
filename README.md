# 台股推薦機器人 (Stocks Autobot)

![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![LINE](https://img.shields.io/badge/LINE-00C300?style=for-the-badge&logo=line&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

每天台北時間 **08:00** 自動執行，提供台股技術分析推薦，透過 LINE 推播文字訊息和 K 線圖表。

⭐ **最新特色**：智能週末檢測，股市休市時自動跳過訊息推送，支援 OAuth 2.0 認證與詳細除錯日誌。

## 🎯 核心功能

### 📊 智能選股系統
- **技術指標分析**：20日移動平均線 (MA20) 斜率計算
- **多重過濾條件**：
  - 連續5日開盤價與收盤價均高於MA20
  - MA20斜率 < 1（避免過熱股票）
  - 波動率 < 3%（降低風險）
  - 與MA20距離控制（動態調整）

### 🏷️ 雙組分類推薦
- **💪 好像蠻強的**：MA20斜率 0.5-1（強勢上升趨勢）
- **👀 有機會噴 觀察一下**：MA20斜率 < 0.5（潛力標的）

### 📈 視覺化圖表
- **K線圖生成**：2×3 網格佈局，每組最多6支股票
- **技術指標疊加**：MA20移動平均線
- **90日歷史資料**：保留3個月完整技術分析基礎
- **跨平台中文字體**：支援 Windows/Linux 環境中文顯示
- **圖片自動上傳**：Telegraph/Catbox 多重備援，無需API key

### 📱 LINE 整合
- **文字推薦訊息**：包含股票代碼和中文名稱
- **圖表推送**：高清K線圖直接傳送到LINE
- **智能週末檢測**：股市休市日（週六/日）自動跳過訊息
- **無推薦時通知**：市場條件不符時的友善提醒

### 🐛 除錯與監控
- **DEBUG_MODE**：詳細執行日誌與錯誤追蹤
- **Google Drive 狀態監控**：上傳下載進度詳細記錄
- **GitHub Actions 文件保存**：自動收集除錯日誌與圖片

## 🚀 自動化流程

```mermaid
graph TD
    A[GitHub Actions 觸發<br/>每日 08:00] --> B[OAuth 2.0 認證<br/>Google Drive API]
    B --> C[從 Google Drive 下載<br/>stocks-autobot-data/data/taiex.sqlite]
    C --> D[檢查本地資料庫<br/>保留90天歷史資料]
    D --> E[下載最新台股數據<br/>yfinance API - 300支股票]
    E --> F[技術分析篩選<br/>MA20 斜率演算法]
    F --> G[週末檢測<br/>股市休市時跳過]
    G --> H{是否為週末?}
    H -->|週末| I[記錄休市日誌<br/>跳過 LINE 推播]
    H -->|平日| J[股票分組分類]
    J --> K[生成 K線圖表<br/>中文字體支援]
    K --> L[LINE 推播訊息+圖片]
    L --> M[上傳更新後資料庫<br/>到 Google Drive]
```

## 🔧 設定指南

### 1. LINE Developers 設定
1. 至 [LINE Developers](https://developers.line.biz/) 建立 Provider
2. 建立 **Messaging API channel**
3. 取得 **Channel access token**（長效）
4. 將機器人加為好友，取得 **User ID**

### 2. Google Drive OAuth 2.0 設定（推薦）
1. 建立 GCP 專案，啟用 **Google Drive API**
2. 建立 **OAuth 2.0 憑證** 並下載 JSON 檔案
3. 建立 Google Drive 資料夾（例如：`stocks-autobot-data`）
4. **取得資料夾 ID**：
   - 開啟 Google Drive 資料夾
   - 從網址列複製資料夾 ID（如：`1Oyn-Zuiswh-mUL7G4dKwjLoZfwUk9e_f`）
   - 設定為 GitHub Secret: `GOOGLE_DRIVE_FOLDER_ID`
5. 程式會自動在指定資料夾下建立 `data` 子資料夾存放 `taiex.sqlite`

### 3. Service Account 備援設定（可選）
如果 OAuth 2.0 失效，可設定 Service Account 作為備援：
1. 建立 **Service Account** 並下載 JSON 金鑰
2. 將資料夾分享給 Service Account email（編輯者權限）
3. 設定為 GitHub Secret: `GDRIVE_SERVICE_ACCOUNT`

💡 **認證優先順序**：OAuth 2.0 → Service Account → 跳過雲端同步

### 4. GitHub Secrets 設定
在 Repository → Settings → Secrets and variables → Actions 新增：

| Secret/Variable Name | 說明 | 類型 | 必需 |
|---------------------|------|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API 的 Channel access token | Secret | ✅ |
| `LINE_USER_ID` | 接收推播的使用者 ID | Secret | ✅ |
| `OAUTH` | OAuth 2.0 認證 JSON 完整內容 | Secret | 🔶 推薦 |
| `GOOGLE_DRIVE_FOLDER_ID` | Google Drive 資料夾 ID | Secret | 🔶 推薦 |
| `GDRIVE_SERVICE_ACCOUNT` | Service Account JSON（備援認證） | Secret | 🔷 可選 |
| `GDRIVE_FOLDER_ID` | 舊版資料夾 ID（相容性） | Secret | 🔷 可選 |
| `DEBUG_MODE` | 啟用詳細除錯日誌 (`true`/`false`) | Variable | 🔷 可選 |

### 5. 環境變數自訂（可選）
在 `.github/workflows/daily.yml` 中可設定：
- `TWSE_CODES`：自訂股票代碼清單（預設300支台股）
- `TOP_K`：選股數量上限（預設300）
- `DEBUG_MODE`：除錯模式，收集詳細日誌和錯誤資訊

## 📊 支援股票清單

目前支援 **300支台股** 包括：
- **電子股**：台積電(2330)、鴻海(2317)、聯發科(2454)、廣達(2382)...
- **金融股**：富邦金(2881)、國泰金(2882)、兆豐金(2886)、中信金(2891)...
- **傳產股**：台塑(1301)、中鋼(2002)、台化(1326)、統一(1216)...
- **航運股**：長榮(2603)、陽明(2609)、萬海(2615)...

完整清單請參考 `main.py` 中的 `STOCK_NAMES` 字典，涵蓋台股市值前300大公司。

## 🏃‍♂️ 快速開始

1. **Fork 此專案**到你的 GitHub 帳號
2. **設定 Secrets**（參考上方設定指南）
3. **手動測試**：GitHub Actions → 選擇 `daily-picks` → Run workflow
4. **檢查 LINE**：確認收到推薦訊息和圖表
5. **等待每日自動執行**：每天 08:00 會自動運行

## 📁 專案結構

```
stocks-autobot/
├── main.py                    # 主要執行程式
├── test_local_oauth.py        # OAuth 2.0 本地測試版本
├── requirements.txt           # Python 套件依賴
├── data/                      # 資料庫檔案（與 Google Drive 同步）
│   └── taiex.sqlite          # 股價歷史資料
├── .github/
│   └── workflows/
│       └── daily.yml         # GitHub Actions 自動化流程
└── README.md                 # 專案說明
```

## 🔬 技術架構

- **資料來源**：Yahoo Finance API (yfinance)
- **資料庫**：SQLite（本地快取，避免重複下載）
- **圖表生成**：matplotlib + 自製 K線圖函數
- **圖床服務**：Telegraph、Catbox（無需API key）
- **訊息推播**：LINE Messaging API
- **雲端同步**：Google Drive API + Service Account
- **自動化**：GitHub Actions
- **認證方式**：OAuth 2.0 優先，Service Account 備援

## 📈 演算法說明

### 篩選條件
1. **趨勢檢查**：連續5日開盤價與收盤價均高於MA20
2. **斜率控制**：MA20斜率 < 1（避免過熱）
3. **波動率限制**：5日收盤價標準差 < 3%
4. **距離控制**：與MA20距離在合理範圍內

### 分組邏輯
- **好像蠻強的組**：斜率 ∈ [0.5, 1)，代表穩健上升趨勢
- **有機會噴 觀察一下組**：斜率 < 0.5，代表潛力標的

### 優化機制
當某組股票 > 6支時：
1. 優先排除5日最低收盤價股票
2. 選擇與MA20距離最近的6支股票

## 🛠️ 本地開發

```bash
# 複製專案
git clone https://github.com/your-username/stocks-autobot.git
cd stocks-autobot

# 安裝依賴
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 檔案填入必要資訊

# 本地測試（含 OAuth 2.0 Google Drive 功能）
python test_local_oauth.py

# 雲端版本測試（完整功能）
python main.py
```

## 📝 更新日誌

### v3.0.0 (2024-12-30)
- 🚀 **擴展至300支台股**：市值前300大公司完整覆蓋
- 🔐 **OAuth 2.0 認證**：取代 Service Account 成為主要認證方式
- 📴 **智能週末檢測**：股市休市日自動跳過 LINE 訊息推送
- 🐛 **DEBUG_MODE**：詳細除錯日誌與 GitHub Actions 文件收集
- 🔍 **Google Drive 監控**：上傳下載狀態詳細記錄
- 🎨 **跨平台中文字體**：Windows/Linux 環境完美支援中文顯示
- 📅 **90天資料保留**：確保3個月技術分析圖表完整性

### v2.1.0 (2024-12-29)
- 🔐 整合 Google Drive Service Account API 直接存取
- ⚡ 移除 rclone 依賴，改用原生 Google Drive API
- 📁 自動建立 `stocks-autobot-data/data/` 資料夾結構
- 🔄 智能資料同步：僅在資料更新時上傳到 Google Drive
- 📋 簡化 GitHub Actions workflow 設定

### v2.0.0 (2024-12-29)
- ✨ 新增雙組分類推薦系統
- 📊 K線圖表自動生成和推送
- 🎯 升級為100支台股支援（現已擴展至300支）
- 🔍 導入 MA20 斜率技術分析
- 🖼️ 多重圖床備援機制

### v1.0.0
- 🚀 基礎選股推薦功能
- 📱 LINE 推播整合
- ☁️ Google Drive 同步
- ⚡ GitHub Actions 自動化

## 🤝 貢獻指南

歡迎提交 Issue 和 Pull Request！

1. Fork 專案
2. 建立功能分支 (`git checkout -b feature/new-feature`)
3. 提交更改 (`git commit -am 'Add new feature'`)
4. 推送分支 (`git push origin feature/new-feature`)
5. 建立 Pull Request

## 📄 授權

MIT License - 詳見 [LICENSE](LICENSE) 檔案

## ⚠️ 免責聲明

本專案僅供學習和研究使用，不構成任何投資建議。投資有風險，請謹慎評估。

---

Made with ❤️ for Taiwan Stock Market