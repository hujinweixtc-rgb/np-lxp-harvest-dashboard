#!/usr/bin/env bash
# 把 NP / LXP 素材看板部署到 Cloud Run（静态页 + 实时刷新 API）。
#
# 前置：
#   1. gcloud 已登录（hujinweixtc@gmail.com）
#   2. Secret Manager 中已有两个 token：
#        np-lxp-harvest-dms-token-np
#        np-lxp-harvest-dms-token-lxp
#      创建方式见 scripts/setup_secrets.sh
#
# 用法：
#   bash deploy.sh
set -euo pipefail

# 本机代理会打断 gcloud 的 GCS 上传
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-advance-rush-406115}"
REGION="${GCP_REGION:-asia-southeast1}"
SERVICE="${SERVICE_NAME:-np-lxp-harvest-dashboard}"
PY="${PYTHON_BIN:-C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe}"
# 刷新结果持久化（否则实例回收后 /tmp 清空、退回镜像快照）
GCS_BUCKET="${DASH_GCS_BUCKET:-advance-rush-406115-dashboard-reports}"
GCS_PREFIX="${DASH_GCS_PREFIX:-np-lxp-harvest/data}"

echo "==> 1/3 打包 DMS 原始缓存 -> raw.tar.gz"
"$PY" scripts/pack_raw.py

echo "==> 2/3 构建并部署 Cloud Run 服务 ${SERVICE}"
# max-instances=1：刷新结果只写单个实例的 /tmp，多实例会导致数据不一致。
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 2 \
  --memory 2Gi \
  --concurrency 40 \
  --min-instances 0 \
  --max-instances 1 \
  --no-cpu-throttling \
  --timeout 3600 \
  --set-env-vars "DASH_GCS_BUCKET=${GCS_BUCKET},DASH_GCS_PREFIX=${GCS_PREFIX}" \
  --set-secrets "DMS_TOKEN_NP=np-lxp-harvest-dms-token-np:latest,DMS_TOKEN_LXP=np-lxp-harvest-dms-token-lxp:latest"

echo "==> 3/3 完成"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)'
