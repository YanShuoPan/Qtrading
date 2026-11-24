#!/usr/bin/env bash
#
# 用 .env 裡的 GITHUB_PAT 驗證 token 或觸發 workflow_dispatch。
# token 永遠只存在記憶體裡，不會被印出來、也不會進 shell history。
#
# 用法：
#   bash scripts/github_dispatch.sh --check            # 只驗證 token，不觸發任何 run
#   bash scripts/github_dispatch.sh daily.yml          # 觸發 daily-picks
#   bash scripts/github_dispatch.sh tide_alert.yml     # 觸發 tide-alert
#
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
GITHUB_REPO="${GITHUB_REPO:-YanShuoPan/Qtrading}"
GITHUB_REF="${GITHUB_REF:-main}"
API="https://api.github.com"

# 只挑出需要的 key，不 source 整個 .env（避免執行到其他設定的副作用）
read_env() {
  local key="$1"
  [ -f "${ENV_FILE}" ] || return 0
  sed -n "s/^[[:space:]]*${key}=//p" "${ENV_FILE}" \
    | tail -1 \
    | sed -e 's/^["'\'']//' -e 's/["'\'']$//' -e 's/[[:space:]]*$//'
}

TOKEN="${GITHUB_PAT:-$(read_env GITHUB_PAT)}"

if [ -z "${TOKEN}" ]; then
  echo "❌ 找不到 GITHUB_PAT。請在 ${ENV_FILE} 裡填入：" >&2
  echo "   GITHUB_PAT=github_pat_..." >&2
  exit 1
fi

case "${TOKEN}" in
  github_pat_*|ghp_*) ;;
  *) echo "⚠️  GITHUB_PAT 開頭不是 github_pat_ 或 ghp_，請確認有沒有貼錯或多了引號" >&2 ;;
esac

api_call() {  # $1=method $2=path [$3=body] -> 回傳 HTTP code，body 寫到 $BODY_FILE
  local method="$1" path="$2" body="${3:-}"
  local args=(-s -o "${BODY_FILE}" -w "%{http_code}" -X "${method}"
    -H "Accept: application/vnd.github+json"
    -H "Authorization: Bearer ${TOKEN}"
    -H "X-GitHub-Api-Version: 2022-11-28")
  [ -n "${body}" ] && args+=(-H "Content-Type: application/json" -d "${body}")
  curl "${args[@]}" "${API}${path}"
}

BODY_FILE="$(mktemp)"
trap 'rm -f "${BODY_FILE}"' EXIT

TARGET="${1:---check}"

if [ "${TARGET}" = "--check" ]; then
  echo "▶ 驗證 token 對 ${GITHUB_REPO} 的 Actions 讀取權限（不會觸發任何 run）"
  code=$(api_call GET "/repos/${GITHUB_REPO}/actions/workflows")
  case "${code}" in
    200)
      echo "✅ HTTP 200 — token 有效，看得到以下 workflow："
      jq -r '.workflows[] | "   - \(.name)  [\(.path)]  \(.state)"' "${BODY_FILE}" 2>/dev/null \
        || grep -o '"path":"[^"]*"' "${BODY_FILE}" | sed 's/^/   /'
      echo
      echo "ℹ️  寫入權限（dispatch）只能靠實際觸發驗證："
      echo "   bash scripts/github_dispatch.sh daily.yml"
      ;;
    401) echo "❌ HTTP 401 — token 無效或已過期/被撤銷" >&2; exit 1 ;;
    403) echo "❌ HTTP 403 — token 權限不足（需要 Repository permissions → Actions）" >&2; exit 1 ;;
    404) echo "❌ HTTP 404 — repo 存取範圍沒包含 ${GITHUB_REPO}，或 Actions 權限沒勾" >&2; exit 1 ;;
    *)   echo "❌ HTTP ${code}" >&2; head -c 400 "${BODY_FILE}" >&2; exit 1 ;;
  esac
  exit 0
fi

echo "▶ 觸發 ${TARGET}（ref=${GITHUB_REF}）"
code=$(api_call POST "/repos/${GITHUB_REPO}/actions/workflows/${TARGET}/dispatches" "{\"ref\":\"${GITHUB_REF}\"}")
case "${code}" in
  204)
    echo "✅ HTTP 204 — 已送出觸發要求"
    echo "   gh run list --workflow=${TARGET} --limit 3"
    ;;
  401) echo "❌ HTTP 401 — token 無效或已過期" >&2; exit 1 ;;
  403) echo "❌ HTTP 403 — token 沒有 Actions: Read and write" >&2; exit 1 ;;
  404) echo "❌ HTTP 404 — workflow 檔名錯誤、分支不存在，或權限不足" >&2; exit 1 ;;
  422) echo "❌ HTTP 422 — ref 或 inputs 有問題：" >&2; head -c 400 "${BODY_FILE}" >&2; exit 1 ;;
  *)   echo "❌ HTTP ${code}" >&2; head -c 400 "${BODY_FILE}" >&2; exit 1 ;;
esac
