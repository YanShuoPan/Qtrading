#!/usr/bin/env bash
#
# 建立／更新 Google Cloud Scheduler job，準時用 workflow_dispatch 觸發 GitHub Actions。
# GitHub 的 schedule 事件實測延遲 4.5~12 小時（見 scripts/cloud_scheduler_setup.md），
# 改由 Cloud Scheduler 觸發，workflow 內的 schedule 只當備援。
#
# 用法：
#   GITHUB_PAT=github_pat_xxx bash scripts/create_cloud_scheduler_jobs.sh
#
# 可覆寫的環境變數：
#   GCP_PROJECT   GCP 專案（預設讀 gcloud config）
#   GCP_LOCATION  Scheduler 地區（預設 asia-east1）
#   GITHUB_REPO   owner/repo（預設 YanShuoPan/Qtrading）
#   GITHUB_REF    觸發的分支（預設 main）
#
set -euo pipefail

: "${GITHUB_PAT:?請先設定 GITHUB_PAT（fine-grained token，權限 Actions: Read and write）}"

GCP_LOCATION="${GCP_LOCATION:-asia-east1}"
GITHUB_REPO="${GITHUB_REPO:-YanShuoPan/Qtrading}"
GITHUB_REF="${GITHUB_REF:-main}"
GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"

if [ -z "${GCP_PROJECT}" ] || [ "${GCP_PROJECT}" = "(unset)" ]; then
  echo "❌ 找不到 GCP 專案，請設定 GCP_PROJECT 或先執行 gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi

HEADERS="Accept=application/vnd.github+json,Authorization=Bearer ${GITHUB_PAT},X-GitHub-Api-Version=2022-11-28,Content-Type=application/json"

echo "專案: ${GCP_PROJECT} / 地區: ${GCP_LOCATION} / repo: ${GITHUB_REPO}@${GITHUB_REF}"
echo

# $1=job 名稱  $2=workflow 檔名  $3=cron（台北時間）
create_or_update_job() {
  local job_name="$1" workflow_file="$2" schedule="$3"
  local uri="https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${workflow_file}/dispatches"
  local action=create

  if gcloud scheduler jobs describe "${job_name}" \
       --location="${GCP_LOCATION}" --project="${GCP_PROJECT}" >/dev/null 2>&1; then
    action=update
  fi

  echo "▶ ${action} ${job_name}  (${schedule} Asia/Taipei → ${workflow_file})"
  gcloud scheduler jobs "${action}" http "${job_name}" \
    --location="${GCP_LOCATION}" \
    --project="${GCP_PROJECT}" \
    --schedule="${schedule}" \
    --time-zone="Asia/Taipei" \
    --uri="${uri}" \
    --http-method=POST \
    --headers="${HEADERS}" \
    --message-body="{\"ref\":\"${GITHUB_REF}\"}" \
    --attempt-deadline=30s \
    --max-retry-attempts=3
}

# 台股 13:30 收盤，證交所／Yahoo 約 14:00 後才有完整收盤資料，所以排 14:00 之後
create_or_update_job qtrading-daily-picks daily.yml      "30 14 * * 1-5"
create_or_update_job qtrading-tide-alert  tide_alert.yml "0 15 * * 1-5"

echo
echo "✅ 完成。立刻測試一次："
echo "   gcloud scheduler jobs run qtrading-daily-picks --location=${GCP_LOCATION}"
echo "   gh run list --workflow=daily.yml --limit 3"
