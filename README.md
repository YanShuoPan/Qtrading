# Stocks Autobot (LINE Messaging API push)

每天台北時間 08:00，自動：
1. 從 Google Drive 同步 `data/`（SQLite/CSV）
2. 下載台股價量（yfinance `.TW`）
3. 跑簡單選股（MA50、20 日動能、量能門檻）
4. 以 **LINE Developers Messaging API** 的 **push** 傳到你的 LINE

## 一次性設定

### 1) LINE Developers
- 建立 Provider 與 **Messaging API channel**
- 取得 **Channel access token（長效）**
- 取得你的 **userId**（把 Bot 加為好友後可在「Basic settings」查看）

### 2) Google Drive（Service Account）
- 建立 GCP 專案、啟用 **Google Drive API**
- 建立 **Service Account** 並下載 JSON 金鑰
- 在 Google Drive 建資料夾 `stocks-autobot-data`，**分享給該 Service Account email**（編輯者）

### 3) GitHub Secrets
到 repo -> Settings -> Secrets and variables -> Actions：

- `LINE_CHANNEL_ACCESS_TOKEN`：你的 Channel access token
- `LINE_USER_ID`：接收訊息的 userId
- `GDRIVE_SERVICE_ACCOUNT`：把 Service Account JSON 檔完整內容貼進來

## 修改代碼清單
- 預設代碼在 `main.py` 的 `CODES`，或在 Actions 設定環境變數 `TWSE_CODES="2330,2317,...`

## 手動測試
在 GitHub Actions 頁面按 **Run workflow**，觀察是否成功推送訊息與在 Drive 建立/更新 `taiex.sqlite`。

## 資料夾結構
```
.
├─ data/               # Actions 會用 rclone 與 Google Drive 同步
├─ main.py
├─ requirements.txt
└─ .github/workflows/daily.yml
```

## 後續擴充
- 換資料源（TWSE/FinMind）
- 多人推送：在 workflow 設多個 `LINE_USER_ID_*` 後於 `main.py` 迴圈呼叫
- 改成 multicast/broadcast（需多 userId 或全部好友）
