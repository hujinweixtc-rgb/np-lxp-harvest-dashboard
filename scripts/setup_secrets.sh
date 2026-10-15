#!/usr/bin/env bash
# 在 Secret Manager 中创建 / 更新看板所需的两个 DMS token。
#
# 凭据来源：本地 config/dms_tokens.json（已 gitignore），或显式传入。
#
# 用法：
#   bash scripts/setup_secrets.sh                 # 从 config/dms_tokens.json 读取
#   NP_TOKEN=xxx LXP_TOKEN=yyy bash scripts/setup_secrets.sh
#
# ⚠️ 旧 token 曾提交到公开仓库，务必在 DMS 后台重新生成后再执行本脚本。
set -euo pipefail

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-advance-rush-406115}"
SECRET_NP="${SECRET_NP:-np-lxp-harvest-dms-token-np}"
SECRET_LXP="${SECRET_LXP:-np-lxp-harvest-dms-token-lxp}"
CONFIG="$ROOT/config/dms_tokens.json"
PY="${PYTHON_BIN:-C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe}"

if [[ -z "${NP_TOKEN:-}" || -z "${LXP_TOKEN:-}" ]]; then
  if [[ ! -f "$CONFIG" ]]; then
    echo "找不到 $CONFIG，请设置 NP_TOKEN / LXP_TOKEN 环境变量" >&2
    exit 1
  fi
  # Windows 版 Python 需要原生路径；Git Bash 下用 cygpath 转换
  CONFIG_PY="$(cygpath -w "$CONFIG" 2>/dev/null || printf '%s' "$CONFIG")"
  read_token() {
    "$PY" -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))[sys.argv[2]])" "$CONFIG_PY" "$1"
  }
  NP_TOKEN="${NP_TOKEN:-$(read_token NP)}"
  LXP_TOKEN="${LXP_TOKEN:-$(read_token LXP)}"
fi

upsert() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=-
    echo "  已新增版本：$name"
  else
    printf '%s' "$value" | gcloud secrets create "$name" --project "$PROJECT" \
      --replication-policy=automatic --data-file=-
    echo "  已创建：$name"
  fi
}

echo "==> 写入 Secret Manager（project=$PROJECT）"
upsert "$SECRET_NP" "$NP_TOKEN"
upsert "$SECRET_LXP" "$LXP_TOKEN"

echo "==> 授权 Cloud Run 默认服务账号读取这两个 secret"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for name in "$SECRET_NP" "$SECRET_LXP"; do
  gcloud secrets add-iam-policy-binding "$name" --project "$PROJECT" \
    --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" >/dev/null
  echo "  $name -> $SA"
done

echo "==> 完成（token 前 6 位校验：NP=${NP_TOKEN:0:6}… / LXP=${LXP_TOKEN:0:6}…）"
