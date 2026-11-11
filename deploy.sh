#!/usr/bin/env bash
# 把 NP / LXP / FR 收割素材看板部署到 Cloud Run（静态页 + 实时刷新 API）。
#
# 前置：
#   1. gcloud 已登录（hujinweixtc@gmail.com）
#   2. Secret Manager 中已有三个 DMS token 与关键词模型 key：
#        np-lxp-harvest-dms-token-np
#        np-lxp-harvest-dms-token-lxp
#        np-lxp-harvest-dms-token-fr
#        np-lxp-harvest-zhipu-key
#      创建方式见 scripts/setup_secrets.sh
#
# 用法：
#   bash deploy.sh
set -euo pipefail

# 本机代理会打断 gcloud 的 GCS 上传；国内网络下 oauth2.googleapis.com 又必须走代理。
# 默认清掉代理；设 KEEP_PROXY=1 可保留（网络环境导致 token 刷新超时时使用）。
if [ "${KEEP_PROXY:-0}" != "1" ]; then
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY || true
fi

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
# raw 没变化时可用 SKIP_PACK=1 复用现有包，省去一次全量压缩（也避开 Windows 下文件占用）。
if [ "${SKIP_PACK:-0}" = "1" ] && [ -f raw.tar.gz ]; then
  echo "    跳过打包：复用现有 raw.tar.gz"
else
  "$PY" scripts/pack_raw.py
fi

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
  --memory 4Gi \
  --concurrency 40 \
  --min-instances 0 \
  --max-instances 1 \
  --no-cpu-throttling \
  --timeout 3600 \
  --set-env-vars "DASH_GCS_BUCKET=${GCS_BUCKET},DASH_GCS_PREFIX=${GCS_PREFIX}" \
  --set-secrets "DMS_TOKEN_NP=np-lxp-harvest-dms-token-np:latest,DMS_TOKEN_LXP=np-lxp-harvest-dms-token-lxp:latest,DMS_TOKEN_FR=np-lxp-harvest-dms-token-fr:latest,ZHIPU_API_KEY=np-lxp-harvest-zhipu-key:latest"

echo "==> 3/3 完成"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)'
