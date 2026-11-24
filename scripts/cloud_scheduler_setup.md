# 用 Google Cloud Scheduler 準時觸發 GitHub Actions

## 為什麼要這樣做

GitHub Actions 的 `schedule`（cron）是 best-effort、**沒有 SLA**。本專案實測（2026-09-29 ~ 2026-11-23）：

| Workflow | cron 設定 | 排程觸發次數 | 延遲中位數 | 最長延遲 | 1 小時內觸發 |
|---|---|---|---|---|---|
| daily-picks | 05:33 UTC（台北 13:33） | 40 | 6.65 hr | 10.84 hr | **0 / 40** |
| tide-alert | 06:30 UTC（台北 14:30） | 37 | 7.96 hr | 12.09 hr | **0 / 37** |

而且延遲持續惡化：10 月初約 4.5~6 hr，11 月下旬已達 8~12 hr。
2026-11-23 那次延遲到**台北 11/24 00:23** 才觸發，跨過午夜導致當日資料備援抓錯日期、選股掛零、流程失敗。

延遲發生在「GitHub 建立 run」這一段（`created_at == run_started_at`，job 本身只跑 13 分鐘），
不是 runner 排隊也不是額度問題，**調整 cron 時間無法解決**（台股 13:30 收盤，05:33 UTC 已是最早可用時間）。

解法：改用外部排程器打 GitHub REST API 的 `workflow_dispatch`，觸發是**秒級**的。
`schedule` 保留作為「Cloud Scheduler 掛掉時的備援」，workflow 內的 `guard` job 會擋掉重複執行。

---

## 一、建立 GitHub PAT

GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token

| 欄位 | 設定 |
|---|---|
| Token name | `cloud-scheduler-qtrading` |
| Expiration | 最長 1 年（到期要換，記在行事曆） |
| Repository access | Only select repositories → `YanShuoPan/Qtrading` |
| Permissions | Repository permissions → **Actions: Read and write**（只需要這一個） |

產生後複製 `github_pat_...`（只會顯示一次）。

### 把 token 放進 .env

專案根目錄的 `.env`（已被 `.gitignore` 忽略，不會進版控）：

```ini
GITHUB_PAT=github_pat_你的token
```

本專案所有腳本都會自動從 `.env` 讀取，token 不必出現在指令列或 shell history 裡。

### 驗證 token

```bash
bash scripts/github_dispatch.sh --check     # 只讀取，不會觸發任何 run
```

回 `✅ HTTP 200` 並列出兩個 workflow 就是通的。
401 = token 無效／過期，403 = 權限不足，404 = repo 存取範圍沒包含本 repo 或 Actions 權限沒勾。

寫入權限只能靠實際觸發驗證（**會真的跑一次完整流程、會推播 LINE**）：

```bash
bash scripts/github_dispatch.sh daily.yml      # 回 ✅ HTTP 204 即成功
bash scripts/github_dispatch.sh tide_alert.yml
```

---

## 二、GCP 準備

1. 建立或選定一個 GCP 專案
2. 啟用 Cloud Scheduler API：
   ```bash
   gcloud services enable cloudscheduler.googleapis.com
   ```
3. 需要綁定帳單帳戶，但**每個帳單帳戶每月前 3 個 job 免費**，第 4 個起 US$0.10/job/月。
   本專案只用 2 個 job → 實際費用 **$0**。

---

## 三、建立排程 job

### 方法 A：用本專案的腳本（建立或更新都可重複執行）

```bash
bash scripts/create_cloud_scheduler_jobs.sh      # 自動從 .env 讀 GITHUB_PAT / GCP_PROJECT
```

`.env` 可設定的項目：`GITHUB_PAT`（必填）、`GCP_PROJECT`、`GCP_LOCATION`（預設 `asia-east1`）。
也可以用環境變數覆寫：`GITHUB_PAT`、`GCP_PROJECT`、`GCP_LOCATION`、`GITHUB_REPO`、`GITHUB_REF`、`ENV_FILE`。

### 方法 B：手動下 gcloud 指令

```bash
gcloud scheduler jobs create http qtrading-daily-picks \
  --location=asia-east1 \
  --schedule="30 14 * * 1-5" \
  --time-zone="Asia/Taipei" \
  --uri="https://api.github.com/repos/YanShuoPan/Qtrading/actions/workflows/daily.yml/dispatches" \
  --http-method=POST \
  --headers="Accept=application/vnd.github+json,Authorization=Bearer github_pat_xxx,X-GitHub-Api-Version=2022-11-28,Content-Type=application/json" \
  --message-body='{"ref":"main"}' \
  --attempt-deadline=30s \
  --max-retry-attempts=3
```

tide-alert 同樣一條，換 job 名稱、workflow 檔名與時間：

```bash
gcloud scheduler jobs create http qtrading-tide-alert \
  --location=asia-east1 \
  --schedule="0 15 * * 1-5" \
  --time-zone="Asia/Taipei" \
  --uri="https://api.github.com/repos/YanShuoPan/Qtrading/actions/workflows/tide_alert.yml/dispatches" \
  --http-method=POST \
  --headers="Accept=application/vnd.github+json,Authorization=Bearer github_pat_xxx,X-GitHub-Api-Version=2022-11-28,Content-Type=application/json" \
  --message-body='{"ref":"main"}' \
  --attempt-deadline=30s \
  --max-retry-attempts=3
```

### 方法 C：Console（沒裝 gcloud 時）

Cloud Scheduler → 建立工作：
- 頻率 `30 14 * * 1-5`、時區 **Asia/Taipei**
- 目標類型 **HTTP**、URL 填上面的 dispatches 網址、方法 **POST**
- HTTP 標頭逐一加入 `Accept` / `Authorization` / `X-GitHub-Api-Version` / `Content-Type`
- 內文填 `{"ref":"main"}`

---

## 四、為什麼是 14:30 / 15:00

台股 13:30 收盤，證交所與 Yahoo 約 **14:00 之後**才有完整收盤資料
（主流程每天都要靠 TWSE/TPEx 官方 API 補 500~750 支 yfinance 漏抓的股票）。
**不要照搬原本的 13:33**，太早打會補不到當日資料。

Cloud Scheduler 原生支援 `--time-zone`，直接寫台北時間即可，不必換算 UTC。

---

## 五、驗證

```bash
# 立刻手動觸發一次
gcloud scheduler jobs run qtrading-daily-picks --location=asia-east1

# 看 GitHub 這邊有沒有立刻建立 run（event 應為 workflow_dispatch）
gh run list --workflow=daily.yml --limit 3

# 看 Cloud Scheduler 的執行紀錄（確認回應是 204）
gcloud scheduler jobs describe qtrading-daily-picks --location=asia-east1
gcloud logging read 'resource.type="cloud_scheduler_job"' --limit=10 --freshness=1d
```

隔天確認：`gh run list --workflow=daily.yml --limit 5 --json event,createdAt`
應該看到 `workflow_dispatch` 的 run 準時出現在台北 14:30 左右。

---

## 六、維護注意事項

- **PAT 到期**：fine-grained token 最長 1 年。到期後 Cloud Scheduler 會收到 401，
  但 workflow 的 `schedule` 備援仍會（延遲地）執行，所以不會完全停擺。
  更新 token：`gcloud scheduler jobs update http qtrading-daily-picks --location=asia-east1 --update-headers="Authorization=Bearer <新token>"`
- **PAT 是明文存在 job 設定裡**：任何有該 GCP 專案存取權的人都看得到。
  若需要更嚴謹，可改成 Cloud Scheduler → Pub/Sub → Cloud Function，token 放 Secret Manager。
- **重複執行保護**：兩個 workflow 都有 `guard` job，
  只要今天（台北）已經有成功的 run，延遲送達的 `schedule` 事件就會跳過，不會重複推播 LINE。
  手動或 Cloud Scheduler 的 `workflow_dispatch` 不受此限制，一律執行。
- **要完全停用 GitHub 自己的 cron**：把兩個 workflow 的 `schedule:` 整段註解掉即可
  （不建議，留著當備援比較保險）。
